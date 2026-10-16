#!/usr/bin/env bash
# Install clipboard-history for the current user (idempotent).
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN_DIR="$HOME/.local/bin"
BIN="$BIN_DIR/clipboard-history"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/clipboard-history.service"
APP_ID="org.an4oh.ClipboardHistory"
APPS_DIR="$HOME/.local/share/applications"
ICON_ROOT="$HOME/.local/share/icons/hicolor"
ICON_DIR="$ICON_ROOT/scalable/apps"

MK_SCHEMA="org.gnome.settings-daemon.plugins.media-keys"
KB_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom-clipboard-history/"
KB_SCHEMA="$MK_SCHEMA.custom-keybinding:$KB_PATH"

for cmd in python3 xdotool systemctl gsettings; do
    command -v "$cmd" >/dev/null || { echo "missing dependency: $cmd" >&2; exit 1; }
done
command -v xclip >/dev/null || echo "note: xclip not found; terminal apps may not read images from the clipboard (sudo apt install xclip)" >&2
python3 -c "import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk" \
    || { echo "missing PyGObject/GTK4 (python3-gi, gir1.2-gtk-4.0)" >&2; exit 1; }

# Print a GVariant string array with `item` added (add) or removed (remove).
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

echo "-> linking $BIN"
mkdir -p "$BIN_DIR"
chmod +x "$ROOT/bin/clipboard-history"
ln -sfn "$ROOT/bin/clipboard-history" "$BIN"

echo "-> installing desktop entry and icon"
mkdir -p "$APPS_DIR" "$ICON_DIR"
install -m 644 "$ROOT/data/$APP_ID.desktop" "$APPS_DIR/$APP_ID.desktop"
install -m 644 "$ROOT/data/$APP_ID.svg" "$ICON_DIR/$APP_ID.svg"
if command -v update-desktop-database >/dev/null; then
    update-desktop-database "$APPS_DIR" || true
fi
if command -v gtk-update-icon-cache >/dev/null; then
    gtk-update-icon-cache -q -t "$ICON_ROOT" || true
fi

echo "-> writing $UNIT"
mkdir -p "$UNIT_DIR"
cat > "$UNIT" <<UNIT
[Unit]
Description=Clipboard history daemon (Super+V popup)
After=graphical-session.target
PartOf=graphical-session.target

[Service]
ExecStart=%h/.local/bin/clipboard-history daemon
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
UNIT

# The service needs the X display; GNOME exports it at login, but make sure the
# current manager has it when installing from a terminal.
vars=()
[ -n "${DISPLAY:-}" ] && vars+=(DISPLAY)
[ -n "${XAUTHORITY:-}" ] && vars+=(XAUTHORITY)
if [ ${#vars[@]} -gt 0 ]; then
    systemctl --user import-environment "${vars[@]}"
fi

systemctl --user daemon-reload
systemctl --user enable clipboard-history.service
systemctl --user restart clipboard-history.service

echo "-> configuring Super+V"
tray="$(gsettings get org.gnome.shell.keybindings toggle-message-tray)"
gsettings set org.gnome.shell.keybindings toggle-message-tray "$(gv_list "$tray" remove '<Super>v')"

customs="$(gsettings get "$MK_SCHEMA" custom-keybindings)"
gsettings set "$MK_SCHEMA" custom-keybindings "$(gv_list "$customs" add "$KB_PATH")"
gsettings set "$KB_SCHEMA" name "Clipboard history"
gsettings set "$KB_SCHEMA" command "$BIN toggle"
gsettings set "$KB_SCHEMA" binding "<Super>v"

echo "done: press Super+V to open the clipboard history"
