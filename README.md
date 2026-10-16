# clipboard-history

Windows-style clipboard history (Win+V) for GNOME on X11. A daemon records every
text or image you copy; `Super+V` opens a popup near the pointer with the latest
items. Click or press Enter to paste into the active window. You can pin, delete
or search items, and clear all unpinned ones. The 25 most recent unpinned items
are kept; pinned items never expire.

Data is stored in `~/.local/share/clipboard-history/` (`history.db` and `images/`).

## Requirements

- Ubuntu/GNOME in an **X11** session
- `python3-gi`, `gir1.2-gtk-4.0`, `xdotool` (no pip dependencies)
- `xclip` (optional, needed by terminal apps such as Claude Code to read images from the clipboard)

## Install

```sh
./install.sh
```

Links `bin/clipboard-history` into `~/.local/bin`, installs and starts the user
service `clipboard-history.service`, and moves `Super+V` from the notification
tray (`Super+M` stays) to a custom shortcut "Clipboard history". The script is
idempotent.

Manual use: `clipboard-history daemon` (default) or `clipboard-history toggle`.

## Uninstall

```sh
./uninstall.sh
```

Stops and removes the service, the link and the shortcut, and gives `Super+V`
back to the notification tray. Clipboard history on disk is kept.

## Tests

```sh
python3 -m pytest tests/ -q
```

## Wayland limitation

On Wayland automatic pasting does not work: `xdotool` cannot activate windows or
send Ctrl+V, and the popup cannot be positioned. This is not handled; X11 is the
only supported session.

## License

MIT, see [LICENSE](LICENSE).
