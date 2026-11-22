# PhoneBox desktop widget (GNOME)

Shows the PhoneBox panel on the Linux desktop, without a phone. The agent already serves the panel at
<http://127.0.0.1:8765/panel/> (the layout editor's live preview); this opens it in a borderless window with a slim
handle, on every workspace and out of the taskbar and Alt+Tab.

Made for GNOME; it also works on most other X11 desktops. To have it in the GNOME top bar instead of as a
window, use the [top bar extension](../gnome-shell-extension).

## Install

You need a running PhoneBox agent, plus GTK 3 and WebKitGTK 4.1 for Python:

```sh
sudo apt install python3-gi gir1.2-webkit2-4.1   # Debian/Ubuntu
./install.sh                                      # ~/.local/bin/phonebox-widget, app menu entry, start at login
phonebox-widget &
```

`./install.sh --uninstall` removes it. Without installing: `python3 phonebox-widget.py`.

## Use

- **GitHub:** click a pull request in the GitHub widget to open it in your browser (the dropdown hides itself).
- **Pages:** click a tab under the handle to switch pages (the mouse wheel scrolls the tabs). The active tab
  follows the panel when it changes page by itself.
- **Move:** drag the handle on top. **Resize:** drag the bottom-right corner.
- **Pin** (on the handle): pinned keeps the widget above other windows (the default); unpinned makes it a normal
  window that other windows can cover; click it to bring it back to the front.
- Starting it again (app menu, `phonebox-widget`) brings the running widget to the front instead of opening another.
- Size, position and pin are remembered in `~/.config/phonebox-widget/state.json`.
- **F5** reloads, **Ctrl+Q** quits.
- If the agent is not running yet, the widget waits and retries every 5 seconds.

| Option | |
|---|---|
| `--width 420 --height 760` | size in pixels |
| `--x 20 --y 60` | position |
| `--above` | start pinned above other windows |
| `--below` | unpinned means below all windows, like a desktop widget. On GNOME with desktop icons (DING) this hides it completely |
| `--decorated` | normal title bar instead of the handle |
| `--url …` | another panel address, e.g. an agent on another computer |
| `--no-tabs` | hide the page tabs |
| `--dropdown` | the panel of the [top bar extension](../gnome-shell-extension): starts hidden, no handle |
| `--show-at X Y` | with `--dropdown`: show it at once, at X, Y |
| `--debug` | right-click menu and web inspector |
| `--wayland` | native Wayland window (no position or keep-below) |

## Notes

- **Wayland:** GNOME lets no Wayland app place itself or stay below other windows, so the widget runs through
  XWayland (it sets `GDK_BACKEND=x11` itself, overriding the environment). `--wayland` runs it as a native Wayland
  window instead, which then behaves like a normal window.
- **Layout:** pages are designed for a phone screen. In the settings page, a portrait page sized for the widget
  works best; the panel uses the portrait or landscape layout to match the window.
- **Phone-only features** such as waking the screen, dictation and the volume keys do nothing here. Widget data,
  controls and actions come from the agent and work as on the phone.
