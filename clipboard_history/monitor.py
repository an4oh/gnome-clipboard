"""Watches the system clipboard and records every new text or PNG image."""
import sys

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gio, GLib  # noqa: E402

from .storage import content_hash  # noqa: E402


class ClipboardMonitor:
    def __init__(self, clipboard, storage, on_new=None):
        self.clipboard = clipboard
        self.storage = storage
        self.on_new = on_new
        self._self_written = None
        clipboard.connect("changed", self._on_changed)

    def mark_self_written(self, h):
        """Skip the next clipboard event carrying this hash (we wrote it ourselves)."""
        self._self_written = h

    def _is_self_written(self, h):
        if self._self_written is not None and h == self._self_written:
            self._self_written = None
            return True
        return False

    def _on_changed(self, clipboard):
        # Content owned by this very process is something we set while pasting:
        # reading it back would only re-add what is already stored.
        if clipboard.is_local():
            return
        # On X11 the formats of foreign content are often still empty when
        # "changed" fires, so do not inspect them: ask for text first (the
        # backend negotiates text targets with the owner directly), then
        # fall back to PNG.
        clipboard.read_text_async(None, self._on_text)

    def _on_text(self, clipboard, result):
        try:
            text = clipboard.read_text_finish(result)
        except GLib.Error:
            # Expected: empty clipboard, no owner, or non-text content.
            text = None
        if not text:
            # read_texture_async would pick an unsupported mime (e.g.
            # image/x-xpixmap): request PNG explicitly instead.
            clipboard.read_async(["image/png"], GLib.PRIORITY_DEFAULT, None, self._on_image_stream)
            return
        if self._is_self_written(content_hash(text.encode("utf-8"))):
            return
        self.storage.add_text(text)
        self._notify()

    def _on_image_stream(self, clipboard, result):
        try:
            stream, _mime = clipboard.read_finish(result)
        except GLib.Error:
            # Expected: no image on the clipboard (empty, owner gone, not supported).
            return
        if stream is None:
            return
        sink = Gio.MemoryOutputStream.new_resizable()
        flags = Gio.OutputStreamSpliceFlags.CLOSE_SOURCE | Gio.OutputStreamSpliceFlags.CLOSE_TARGET
        sink.splice_async(stream, flags, GLib.PRIORITY_DEFAULT, None, self._on_image_read)

    def _on_image_read(self, sink, result):
        try:
            sink.splice_finish(result)
        except GLib.Error as e:
            print(f"clipboard-history: reading image failed: {e.message}", file=sys.stderr)
            return
        png = sink.steal_as_bytes().get_data()
        if not png or self._is_self_written(content_hash(png)):
            return
        self.storage.add_image(png)
        self._notify()

    def _notify(self):
        if self.on_new:
            self.on_new()
