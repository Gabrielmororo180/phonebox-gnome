#!/usr/bin/env bash
# Installs the PhoneBox top bar extension for GNOME Shell, with the desktop widget it opens.
#   ./install.sh              install (then log out and back in)
#   ./install.sh --uninstall  remove the extension (the widget stays; remove it with ../gnome-widget/install.sh --uninstall)
set -euo pipefail

UUID="phonebox-gnome@gabrielmororo180.github.io"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/$UUID"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/phonebox-widget.desktop"

enabled() { gsettings get org.gnome.shell enabled-extensions; }

if [[ "${1:-}" == "--uninstall" ]]; then
    gnome-extensions disable "$UUID" 2>/dev/null || true
    rm -rf "$DEST"
    echo "Extension removed. Log out and back in to clear it from the top bar."
    exit 0
fi

if ! command -v gnome-shell >/dev/null; then
    echo "GNOME Shell not found; on other desktops use the widget alone (../gnome-widget)."
    exit 1
fi
WIDGET_INSTALLER="$here/../gnome-widget/install.sh"
if [[ ! -x "$WIDGET_INSTALLER" ]]; then
    echo "The panel's installer is missing ($WIDGET_INSTALLER)."
    echo "Install from a full clone of https://github.com/Gabrielmororo180/phonebox-gnome."
    exit 1
fi
if ! command -v glib-compile-schemas >/dev/null; then
    echo "glib-compile-schemas not found (Debian/Ubuntu: sudo apt install libglib2.0-bin)."
    exit 1
fi

# the panel the indicator opens
"$WIDGET_INSTALLER"
# the extension starts the widget itself (hidden, as its dropdown); a separate autostart would open a second panel
rm -f "$AUTOSTART"
pkill -f "[p]ython3 $HOME/.local/bin/phonebox-widget" 2>/dev/null || true

mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
cp -r "$here/$UUID" "$DEST"
# the port setting; extensions.gnome.org compiles this itself, a local install has to
glib-compile-schemas "$DEST/schemas"

# GNOME Shell on Wayland only finds new extensions at login, so `gnome-extensions enable` would fail now:
# add it to the enabled list directly and it loads at the next login.
if ! enabled | grep -q "'$UUID'"; then
    current="$(enabled)"
    case "$current" in
        "@as []"|"[]") gsettings set org.gnome.shell enabled-extensions "['$UUID']" ;;
        *) gsettings set org.gnome.shell enabled-extensions "${current%]}, '$UUID']" ;;
    esac
fi
gnome-extensions enable "$UUID" 2>/dev/null || true

echo
echo "Installed. Log out and back in; PhoneBox then appears in the top bar."
echo "Left click opens the panel, right click opens the settings page."
echo "If the agent runs on another port (--port): gnome-extensions prefs $UUID"
