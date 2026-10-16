"""Single-instance GTK application.

The first instance is the daemon: it owns the clipboard monitor and a hidden
popup window. Running `clipboard-history toggle` starts a second instance that
forwards its command line to the daemon over D-Bus and exits.
"""
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from .monitor import ClipboardMonitor  # noqa: E402
from .storage import Storage, default_data_dir  # noqa: E402
from .ui import PopupWindow  # noqa: E402

APP_ID = "org.an4oh.ClipboardHistory"
COMMANDS = ("daemon", "toggle")
USAGE = "usage: clipboard-history [daemon|toggle]"


class ClipboardHistoryApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.storage = None
        self.monitor = None
        self.window = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        data_dir = default_data_dir()
        self.storage = Storage(data_dir / "history.db", data_dir / "images")
        clipboard = Gdk.Display.get_default().get_clipboard()
        self.monitor = ClipboardMonitor(clipboard, self.storage, on_new=self._on_new_item)
        self.window = PopupWindow(self, self.storage, self.monitor)
        # Keep running with no visible window.
        self.hold()

    def do_shutdown(self):
        if self.storage:
            self.storage.close()
        Gtk.Application.do_shutdown(self)

    def do_command_line(self, command_line):
        args = command_line.get_arguments()[1:]
        cmd = args[0] if args else "daemon"
        if cmd not in COMMANDS:
            command_line.printerr_literal(USAGE + "\n")
            return 2
        if cmd == "toggle":
            self.window.toggle()
        # "daemon" on an already running primary is a no-op.
        return 0

    def _on_new_item(self):
        if self.window and self.window.get_visible():
            self.window.refresh()


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if len(argv) > 2 or (len(argv) == 2 and argv[1] not in COMMANDS):
        print(USAGE, file=sys.stderr)
        return 2
    # GTK uses the program name as WM_CLASS on X11: match the .desktop file's
    # StartupWMClass so GNOME Shell shows the app icon and name.
    GLib.set_prgname(APP_ID)
    app = ClipboardHistoryApp()
    if len(argv) == 2 and argv[1] == "toggle":
        app.register(None)
        if not app.get_is_remote():
            print("clipboard-history: daemon not running (systemctl --user start clipboard-history)", file=sys.stderr)
            return 1
    return app.run(argv)
