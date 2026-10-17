#!/usr/bin/env bash
# Remove gnome-clipboard for the current user (idempotent). Data in
# ~/.local/share/gnome-clipboard is kept.
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN="$HOME/.local/bin/gnome-clipboard"
UNIT="$HOME/.config/systemd/user/gnome-clipboard.service"
APP_ID="org.an4oh.GnomeClipboard"
DESKTOP="$HOME/.local/share/applications/$APP_ID.desktop"
ICON="$HOME/.local/share/icons/hicolor/scalable/apps/$APP_ID.svg"

MK_SCHEMA="org.gnome.settings-daemon.plugins.media-keys"
KB_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom-gnome-clipboard/"
KB_SCHEMA="$MK_SCHEMA.custom-keybinding:$KB_PATH"

gv_list() {
    python3 - "$@" <<'PY'
import ast, sys
current, action, item = sys.argv[1], sys.argv[2], sys.argv[3]
current = current.strip()
if current.startswith("@as"):
    current = current[3:].strip()
values = ast.literal_eval(current) if current else []
if action == "add" and item not in values:
    values.append(item)
elif action == "remove":
    values = [v for v in values if v != item]
print("[" + ", ".join(repr(v) for v in values) + "]")
PY
}

echo "-> stopping service"
systemctl --user disable --now gnome-clipboard.service 2>/dev/null || true
rm -f "$UNIT"
systemctl --user daemon-reload
systemctl --user reset-failed gnome-clipboard.service 2>/dev/null || true

echo "-> removing $BIN"
if [ -L "$BIN" ] && [ "$(readlink -f "$BIN")" = "$ROOT/bin/gnome-clipboard" ]; then
    rm -f "$BIN"
elif [ -e "$BIN" ]; then
    echo "   $BIN is not our symlink, left untouched" >&2
fi

echo "-> removing desktop entry and icon"
rm -f "$DESKTOP" "$ICON"
if command -v update-desktop-database >/dev/null; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

echo "-> restoring keybindings"
customs="$(gsettings get "$MK_SCHEMA" custom-keybindings)"
gsettings set "$MK_SCHEMA" custom-keybindings "$(gv_list "$customs" remove "$KB_PATH")"
for key in name command binding; do
    gsettings reset "$KB_SCHEMA" "$key"
done
tray="$(gsettings get org.gnome.shell.keybindings toggle-message-tray)"
gsettings set org.gnome.shell.keybindings toggle-message-tray "$(gv_list "$tray" add '<Super>v')"

echo "done (history kept in ~/.local/share/gnome-clipboard)"
