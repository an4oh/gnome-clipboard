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
MOVE_DELAY_MS = 30

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
        root.append(header)

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
        self.present()
        self.search.grab_focus()
        GLib.timeout_add(MOVE_DELAY_MS, self._place_and_focus, pointer)

    def hide_popup(self):
        self._was_active = False
        self.set_visible(False)

    def _xid(self):
        surface = self.get_surface()
        if GdkX11 is None or surface is None or not isinstance(surface, GdkX11.X11Surface):
            return None
        return surface.get_xid()

    def _place_and_focus(self, pointer):
        """GTK4 cannot move windows: place it with xdotool after it is mapped."""
        if not self.get_visible():
            return False
        xid = self._xid()
        if xid is None:
            return False
        if pointer:
            x, y = self._clamp_to_monitor(*pointer)
            paste.move_window(xid, x, y)
        # Mutter may refuse focus to a window shown from a background daemon;
        # an explicit activation via _NET_ACTIVE_WINDOW is honoured.
        if not self.is_active():
            paste.activate_window(xid)
        return False

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

    def _on_active_changed(self, *_):
        if self.is_active():
            self._was_active = True
        elif self._was_active and self.get_visible():
            self.hide_popup()

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
