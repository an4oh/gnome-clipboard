# clipboard-history

Windows-style clipboard history (Win+V) for GNOME on X11. A daemon records every
text or image you copy; `Super+V` opens a popup with the latest items. Click or
press Enter to paste into the active window. Items can be pinned, deleted or
searched. The 25 most recent unpinned items are kept; pinned items never expire.

Data lives in `~/.local/share/clipboard-history/`.

## Requirements

- GNOME in an **X11** session (Wayland is not supported, see below)
- Python 3 with PyGObject and GTK 4: `python3-gi`, `gir1.2-gtk-4.0`
- `xdotool`
- `xclip` (optional, lets terminal apps such as Claude Code read copied images)

No pip dependencies. On Ubuntu/Debian:

```sh
sudo apt install python3-gi gir1.2-gtk-4.0 xdotool xclip
```

## Tested on

Only one setup so far:

- Ubuntu 24.04.5 LTS, GNOME Shell 46.0, X11 session
- Python 3.12.3, GTK 4.14.5, PyGObject 3.48.2, xdotool 3.20160805.1

Other distros and versions may work but are untested.

## Install

```sh
./install.sh
```

Installs a systemd user service `clipboard-history.service`, links the command
into `~/.local/bin`, adds the app icon, and binds `Super+V` to the popup (taking
it from the notification tray; `Super+M` still opens that). Idempotent.

`./uninstall.sh` reverts everything except the stored history.

## Tests

```sh
python3 -m pytest tests/ -q
```

## Wayland

On Wayland `xdotool` cannot focus windows or send Ctrl+V, so automatic pasting
does not work. Not handled: X11 is the only supported session.

## License

MIT, see [LICENSE](LICENSE).
