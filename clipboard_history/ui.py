"""Popup window: search, list of cards, pin/delete, paste on click or Enter."""
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk, Pango  # noqa: E402

from . import paste  # noqa: E402

try:
    gi.require_version("GdkX11", "4.0")
    from gi.repository import GdkX11  # noqa: E402
except (ValueError, ImportError):  # not an X11-capable GTK build
    GdkX11 = None

WIDTH, HEIGHT = 360, 480
THUMB_W, THUMB_H = 320, 120
PASTE_DELAY_MS = 80
APP_ICON = "org.an4oh.ClipboardHistory"
# Fallback in case the surface "mapped" notification never arrives.
PLACE_FALLBACK_MS = 150
# Mutter places a newly mapped window on its own schedule and may override an
# early move (or drop a move to the position the window had when hidden), so
# the position is checked and re-applied until it holds, before revealing.
PLACE_CHECK_MS = 15
PLACE_MAX_CHECKS = 20
PLACE_STABLE_CHECKS = 2
# Mutter's move-grab (dragging the header) steals focus from the popup: on
# focus loss wait a bit and check the real mouse button state before hiding.
HIDE_CHECK_MS = 60
# A press on the header this recent before the focus loss starts a drag.
DRAG_PRESS_WINDOW_S = 1.0

CSS = b"""
.clip-card { padding: 8px; margin: 4px 6px; }
.clip-time { font-size: smaller; opacity: 0.7; }
.clip-title { font-weight: bold; }
"""


def relative_time(ts, now=None):
    delta = int((now if now is not None else time.time()) - ts)
    if delta < 60:
        return "adesso"
    if delta < 3600:
        return f"{delta // 60} min fa"
    if delta < 86400:
        return f"{delta // 3600} h fa"
    days = delta // 86400
    if days == 1:
        return "ieri"
    if days < 7:
        return f"{days} giorni fa"
    return time.strftime("%d/%m/%Y", time.localtime(ts))


class PopupWindow(Gtk.Window):
    def __init__(self, app, storage, monitor):
        super().__init__(application=app, title="Appunti")
        self.storage = storage
        self.monitor = monitor
        self.clipboard = Gdk.Display.get_default().get_clipboard()
        self.target_window = None
        self._was_active = False
        self._pending_pointer = None
        self._placing = False
        self._show_gen = 0  # invalidates placement timers of earlier shows
        self._hide_pending = False
        self._dragging = False
        self._header_press_at = None
        self._focus_lost_at = 0.0

        Gtk.Window.set_default_icon_name(APP_ICON)
        self.set_icon_name(APP_ICON)

        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(WIDTH, HEIGHT)

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        root.set_margin_top(8)
        root.set_margin_bottom(8)
        root.set_margin_start(8)
        root.set_margin_end(8)
        self.set_child(root)

        header = Gtk.Box(spacing=6)
        title = Gtk.Label(label="Appunti", xalign=0, hexpand=True)
        title.add_css_class("clip-title")
        clear_btn = Gtk.Button(label="Cancella tutto")
        clear_btn.connect("clicked", self._on_clear_all)
        header.append(title)
        header.append(clear_btn)
        # Dragging the header moves the window (GTK4 has no title bar here).
        handle = Gtk.WindowHandle(child=header)
        press = Gtk.GestureClick()
        press.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        press.connect("pressed", self._on_header_pressed)
        handle.add_controller(press)
        self._handle = handle
        root.append(handle)

        self.search = Gtk.SearchEntry(placeholder_text="Cerca")
        self.search.connect("search-changed", lambda *_: self.refresh())
        root.append(self.search)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.set_activate_on_single_click(True)
        self.listbox.connect("row-activated", self._on_row_activated)
        self.listbox.set_placeholder(Gtk.Label(label="Nessun elemento", margin_top=24))
        self.scroller = Gtk.ScrolledWindow(vexpand=True)
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_child(self.listbox)
        root.append(self.scroller)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        self.connect("notify::is-active", self._on_active_changed)
        self.connect("close-request", self._on_close_request)

        # Realize once up front: the X11 surface (and its xid) then exists
        # before the first present(), which makes the first show faster and
        # lets us watch for the map to place the window before revealing it.
        self.set_opacity(0.0)
        self.connect("realize", self._on_realize)
        self.realize()

    # --- show / hide -------------------------------------------------------

    def toggle(self):
        if self.get_visible():
            self.hide_popup()
        else:
            self.show_popup()

    def show_popup(self):
        self.target_window = paste.get_active_window()
        pointer = paste.get_mouse_location()
        self.search.set_text("")
        self.refresh()
        self._was_active = False
        self._reset_drag_state()
        self._reset_header_gestures()
        # Show it fully transparent, move it once mapped, then reveal it: the
        # user never sees it at Mutter's position nor the zoom-in animation.
        self.set_opacity(0.0)
        self._pending_pointer = pointer
        self._placing = True
        self._show_gen += 1
        self.present()
        self.search.grab_focus()
        GLib.timeout_add(PLACE_FALLBACK_MS, self._place_and_focus)

    def hide_popup(self):
        self._was_active = False
        self._reset_drag_state()
        self._placing = False
        self._pending_pointer = None
        self._show_gen += 1
        self.set_opacity(0.0)
        self.set_visible(False)

    def _on_realize(self, *_):
        surface = self.get_surface()
        if surface is not None:
            surface.connect("notify::mapped", self._on_surface_mapped)

    def _on_surface_mapped(self, surface, _pspec):
        if surface.get_mapped() and self._placing:
            GLib.idle_add(self._place_and_focus)

    def _xid(self):
        surface = self.get_surface()
        if GdkX11 is None or surface is None or not isinstance(surface, GdkX11.X11Surface):
            return None
        return surface.get_xid()

    def _place_and_focus(self):
        """GTK4 cannot move windows: place it with xdotool once it is mapped,
        then make it visible. Runs once per show (mapped signal or fallback)."""
        if not self._placing or not self.get_visible():
            return False
        self._placing = False
        pointer, self._pending_pointer = self._pending_pointer, None
        xid = self._xid()
        if xid is None or not pointer:
            self._reveal(xid)
            return False
        target = self._clamp_to_monitor(*pointer)
        paste.move_window(xid, *target, sync=True)
        state = {"checks": 0, "stable": 0}
        GLib.timeout_add(PLACE_CHECK_MS, self._check_placement, xid, target, state, self._show_gen)
        return False

    def _check_placement(self, xid, target, state, gen):
        if gen != self._show_gen or not self.get_visible():
            return False
        state["checks"] += 1
        if paste.get_window_position(xid) == target:
            state["stable"] += 1
        else:
            state["stable"] = 0
            paste.move_window(xid, *target, sync=True)
        if state["stable"] >= PLACE_STABLE_CHECKS or state["checks"] >= PLACE_MAX_CHECKS:
            self._reveal(xid)
            return False
        return True

    def _reveal(self, xid):
        self.set_opacity(1.0)
        # GTK may keep is-active from the previous show (no focus-out after the
        # unmap), so no notify fires on this show: seed it from the real state.
        if self.is_active():
            self._was_active = True
        # Mutter may refuse focus to a window shown from a background daemon;
        # an explicit activation via _NET_ACTIVE_WINDOW is honoured.
        if xid is not None and not self.is_active():
            paste.activate_window(xid)

    def _clamp_to_monitor(self, x, y):
        display = Gdk.Display.get_default()
        monitors = display.get_monitors()
        for i in range(monitors.get_n_items()):
            g = monitors.get_item(i).get_geometry()
            if g.x <= x < g.x + g.width and g.y <= y < g.y + g.height:
                x = max(g.x, min(x, g.x + g.width - WIDTH))
                y = max(g.y, min(y, g.y + g.height - HEIGHT))
                break
        return x, y

    def _reset_drag_state(self):
        self._hide_pending = False
        self._dragging = False
        self._header_press_at = None

    def _reset_header_gestures(self):
        # The button release of a move-grab goes to Mutter, not to us: the
        # header gestures stay "pressed" and would ignore the next press.
        controllers = self._handle.observe_controllers()
        for i in range(controllers.get_n_items()):
            controllers.get_item(i).reset()

    def _on_header_pressed(self, *_):
        self._header_press_at = time.monotonic()

    def _on_active_changed(self, *_):
        if self.is_active():
            self._was_active = True
        elif self._was_active and self.get_visible() and not self._hide_pending:
            self._hide_pending = True
            self._focus_lost_at = time.monotonic()
            GLib.timeout_add(HIDE_CHECK_MS, self._maybe_hide, self._show_gen)

    def _button1_pressed(self):
        # GTK's own pointer state goes stale after Mutter's move-grab (the
        # release is never delivered to us), so ask the X server directly.
        pressed = paste.button1_pressed()
        if pressed is not None:
            return pressed
        surface = self.get_surface()
        seat = Gdk.Display.get_default().get_default_seat()
        device = seat.get_pointer() if seat is not None else None
        if surface is None or device is None:
            return False
        mask = surface.get_device_position(device)[-1]
        return bool(mask & Gdk.ModifierType.BUTTON1_MASK)

    def _maybe_hide(self, gen):
        """Hide after a focus loss, unless it is a header drag (move-grab)."""
        if gen != self._show_gen or not self.get_visible() or self.is_active():
            if self._dragging:
                self._reset_header_gestures()
            self._reset_drag_state()
            return False
        if self._button1_pressed():
            pressed_at = self._header_press_at
            if self._dragging or (
                pressed_at is not None
                and 0 <= self._focus_lost_at - pressed_at < DRAG_PRESS_WINDOW_S
            ):
                self._dragging = True
                return True  # keep polling until the button is released
        elif self._dragging:
            # Drag finished: the popup stays where it was dropped, refocus it.
            self._reset_drag_state()
            self._reset_header_gestures()
            xid = self._xid()
            if xid is not None:
                paste.activate_window(xid)
            return False
        self.hide_popup()
        return False

    def _on_close_request(self, *_):
        self.hide_popup()
        return True  # keep the window alive for the next toggle

    # --- list --------------------------------------------------------------

    def refresh(self):
        self.listbox.remove_all()
        for item in self.storage.list(self.search.get_text()):
            self.listbox.append(self._make_row(item))
        first = self.listbox.get_row_at_index(0)
        if first:
            self.listbox.select_row(first)

    def _make_row(self, item):
        row = Gtk.ListBoxRow()
        row.item_id = item.id

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class("card")
        card.add_css_class("clip-card")

        if item.kind == "image":
            card.append(self._thumbnail(item.image_path))
        else:
            label = Gtk.Label(label=item.text, xalign=0, wrap=True, lines=3)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_max_width_chars(40)
            label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            card.append(label)

        footer = Gtk.Box(spacing=4)
        when = Gtk.Label(label=relative_time(item.last_used_at), xalign=0, hexpand=True)
        when.add_css_class("clip-time")
        footer.append(when)

        pin_btn = Gtk.ToggleButton(icon_name="view-pin-symbolic", active=item.pinned)
        pin_btn.set_tooltip_text("Rimuovi dai fissati" if item.pinned else "Fissa")
        pin_btn.add_css_class("flat")
        pin_btn.set_focus_on_click(False)
        pin_btn.connect("toggled", self._on_pin_toggled, item.id)
        footer.append(pin_btn)

        del_btn = Gtk.Button(icon_name="edit-delete-symbolic", tooltip_text="Cancella")
        del_btn.add_css_class("flat")
        del_btn.set_focus_on_click(False)
        del_btn.connect("clicked", self._on_delete, item.id)
        footer.append(del_btn)

        card.append(footer)
        row.set_child(card)
        return row

    @staticmethod
    def _thumbnail(path):
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, THUMB_W, THUMB_H, True)
            picture = Gtk.Picture.new_for_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
            picture.set_can_shrink(False)
            picture.set_halign(Gtk.Align.START)
            return picture
        except GLib.Error as e:
            print(f"clipboard-history: cannot load {path}: {e.message}", file=sys.stderr)
            return Gtk.Label(label="[immagine non disponibile]", xalign=0)

    # --- actions -----------------------------------------------------------

    def _on_pin_toggled(self, button, item_id):
        self.storage.pin(item_id, button.get_active())
        GLib.idle_add(self._refresh_keep_search)

    def _on_delete(self, _button, item_id):
        self.storage.delete(item_id)
        GLib.idle_add(self._refresh_keep_search)

    def _refresh_keep_search(self):
        self.refresh()
        return False

    def _on_clear_all(self, _button):
        self.storage.clear_unpinned()
        self.refresh()

    def _on_row_activated(self, _listbox, row):
        self.paste_item(row.item_id)

    def _move_selection(self, step):
        current = self.listbox.get_selected_row()
        index = current.get_index() + step if current else 0
        row = self.listbox.get_row_at_index(max(0, index))
        if row:
            self.listbox.select_row(row)
            # Scroll it into view without taking focus away from the search entry.
            adj = self.scroller.get_vadjustment()
            ok, bounds = row.compute_bounds(self.listbox)
            if ok:
                top = bounds.get_y()
                bottom = top + bounds.get_height()
                if top < adj.get_value():
                    adj.set_value(top)
                elif bottom > adj.get_value() + adj.get_page_size():
                    adj.set_value(bottom - adj.get_page_size())

    def _on_key(self, _ctrl, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.hide_popup()
            return True
        if keyval == Gdk.KEY_Down:
            self._move_selection(1)
            return True
        if keyval == Gdk.KEY_Up:
            self._move_selection(-1)
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            row = self.listbox.get_selected_row()
            if row:
                self.paste_item(row.item_id)
            return True
        return False

    def paste_item(self, item_id):
        item = self.storage.get(item_id)
        if item is None:
            self.refresh()
            return
        if item.kind == "image":
            try:
                texture = Gdk.Texture.new_from_filename(item.image_path)
            except GLib.Error as e:
                print(f"clipboard-history: cannot load {item.image_path}: {e.message}", file=sys.stderr)
                return
            value = GObject.Value(Gdk.Texture, texture)
        else:
            value = GObject.Value(GObject.TYPE_STRING, item.text)
        self.monitor.mark_self_written(item.hash)
        self.clipboard.set(value)
        self.storage.touch(item.id)
        target = self.target_window
        self.hide_popup()
        # Let the popup unmap before giving focus back and sending Ctrl+V.
        GLib.timeout_add(PASTE_DELAY_MS, self._send_paste, target)

    @staticmethod
    def _send_paste(target):
        paste.send_paste(target)
        return False
