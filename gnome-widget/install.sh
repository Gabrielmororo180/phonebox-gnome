#!/usr/bin/env bash
# Installs the PhoneBox desktop widget for the current user and starts it at login.
#   ./install.sh             install
#   ./install.sh --uninstall remove it again (keeps ~/.config/phonebox-widget)
set -euo pipefail

BIN="$HOME/.local/bin/phonebox-widget"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications/phonebox-widget.desktop"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/phonebox-widget.desktop"

if [[ "${1:-}" == "--uninstall" ]]; then
    pkill -f "$BIN" 2>/dev/null || true
    rm -f "$BIN" "$APPS" "$AUTOSTART"
    echo "PhoneBox widget removed."
    exit 0
fi

if ! python3 -c "import gi; gi.require_version('Gtk','3.0'); gi.require_version('WebKit2','4.1')" 2>/dev/null; then
    echo "Missing GTK 3 / WebKitGTK 4.1 for Python. Install it with:"
    echo "  Debian/Ubuntu: sudo apt install python3-gi gir1.2-webkit2-4.1"
    echo "  Fedora:        sudo dnf install python3-gobject webkit2gtk4.1"
    echo "  Arch:          sudo pacman -S python-gobject webkit2gtk-4.1"
    exit 1
fi

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install -Dm755 "$here/phonebox-widget.py" "$BIN"

desktop="[Desktop Entry]
Type=Application
Name=PhoneBox Widget
Comment=The PhoneBox panel on the desktop
Exec=$BIN
Icon=utilities-system-monitor
Terminal=false
Categories=Utility;
X-GNOME-Autostart-Delay=5"

mkdir -p "$(dirname "$APPS")" "$(dirname "$AUTOSTART")"
printf '%s\n' "$desktop" > "$APPS"
printf '%s\n' "$desktop" > "$AUTOSTART"

echo "Installed. It starts at login; start it now with: phonebox-widget &"
