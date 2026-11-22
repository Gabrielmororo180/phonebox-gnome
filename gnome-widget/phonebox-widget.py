#!/usr/bin/env python3
"""PhoneBox panel as a desktop widget on Linux (made for GNOME, works on most X11 desktops).

Shows the panel the agent already serves at http://127.0.0.1:8765/panel/ in a borderless window with a slim
handle on top: drag it to move, use the pin to keep the widget above other windows or not, and drag the
bottom-right corner to resize. Size, position and pin are remembered. The widget stays on every workspace and
out of the taskbar and Alt+Tab; starting it again while it runs brings it to the front.

GNOME on Wayland lets no app place itself or stay below other windows, so the widget runs through XWayland
(GDK_BACKEND=x11); the panel itself does not care.

With --dropdown it is the panel of the PhoneBox GNOME Shell extension (gnome-shell-extension/ in this repository): it starts
hidden, has no handle, and the extension shows it under its top bar indicator (actions "show(x, y)" and "hide" on
D-Bus, which every Gtk.Application exports; "navigate(url)" starts it hidden and points it at the agent).

Keys: F5 reload, Ctrl+Q quit, Esc hides the dropdown.
"""
import argparse
import json
import os
import signal
import sys

# Forced, not a default: terminals and editors often export GDK_BACKEND=wayland, and under Wayland move() is ignored,
# get_position() reads 0,0 and keep-below does nothing. --wayland opts out.
os.environ["GDK_BACKEND"] = "wayland" if "--wayland" in sys.argv[1:] else "x11"

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2  # noqa: E402

APP_ID = "io.github.gabrielmororo180.PhoneBoxGnome"
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "phonebox-widget")
STATE_FILE = os.path.join(CONFIG_DIR, "state.json")
RETRY_SECONDS = 5
TABS_POLL_MS = 700

# The panel is an ES module; importing main.js again returns the same live instance, so its pages, current page and
# goPage() can be used from here without changing the panel.
JS_PAGES = """const m = await import('./main.js');
return JSON.stringify({ pages: m.pages.map((p) => [p.icon || '', p.title || '']), cur: m.curPage });"""
JS_GO = """const m = await import('./main.js');
m.goPage(i, Math.abs(i - m.curPage) > 1);"""

CSS = b"""
.pb-handle { background: #15171c; color: #8b93a3; }
.pb-handle label { font-size: 11px; font-weight: 600; letter-spacing: 1px; }
.pb-handle button { min-height: 0; min-width: 0; padding: 2px 6px; border: none; box-shadow: none;
                    background: none; color: #8b93a3; }
.pb-handle button:hover { background: #2a2e37; color: #e6e9ef; }
.pb-handle button:checked { color: #6aa9ff; }
.pb-tabs { background: #15171c; border-bottom: 1px solid #23262e; }
.pb-tabs button { min-height: 0; min-width: 0; padding: 3px 10px; margin: 0 1px 3px 1px; border: none;
                  border-radius: 6px; box-shadow: none; background: none; color: #8b93a3; font-size: 12px; }
.pb-tabs button:hover { background: #23262e; color: #e6e9ef; }
.pb-tabs button.active { background: #2b3445; color: #e6e9ef; }
.pb-grip { background: linear-gradient(135deg, transparent 50%, rgba(139,147,163,0.55) 50%); }
"""


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, STATE_FILE)
    except OSError as e:
        print(f"phonebox-widget: could not save the position: {e}", file=sys.stderr)


class Widget(Gtk.ApplicationWindow):
    def __init__(self, app, args):
        super().__init__(application=app, title="PhoneBox")
        self.args = args
        self.state = load_state()
        self.retry_id = 0
        self.save_id = 0
        self.tracking = False  # until the window manager has placed the window, positions read as 0,0
        self.tab_pages = None
        self.tab_buttons = []
        self.tabs_busy = False
        self.dropdown = args.dropdown
        # the dropdown keeps a size of its own; its position is the indicator's
        self.key = (lambda k: "dropdown_" + k) if self.dropdown else (lambda k: k)

        self.set_decorated(args.decorated and not self.dropdown)
        self.set_skip_taskbar_hint(True)  # also keeps it out of Alt+Tab; a UTILITY type hint would, but GNOME then ignores move()
        self.set_skip_pager_hint(True)
        self.stick()  # every workspace

        width = args.width or self.state.get(self.key("width"), 420)
        height = args.height or self.state.get(self.key("height"), 780 if not self.dropdown else 720)
        self.set_default_size(width, height)
        x = args.x if args.x is not None else None if self.dropdown else self.state.get("x")
        y = args.y if args.y is not None else None if self.dropdown else self.state.get("y")
        if x is not None and y is not None:
            self.move(x, y)

        # Unpinned is a normal window, not keep-below: on GNOME the desktop-icons window (DING) shares the bottom layer
        # and covers a keep-below window completely, leaving nothing to click. --below asks for it anyway.
        self.below = args.below
        above = True if args.above or self.dropdown else False if args.below else self.state.get("above", True)

        self.web = WebKit2.WebView()
        settings = self.web.get_settings()
        settings.set_enable_developer_extras(args.debug)
        settings.set_media_playback_requires_user_gesture(False)
        # the panel paints its own background; this avoids a white flash while it loads
        self.web.set_background_color(Gdk.RGBA(0, 0, 0, 1))
        self.web.connect("load-failed", self.on_load_failed)
        self.web.connect("load-changed", self.on_load_changed)
        if not args.debug:
            self.web.connect("context-menu", lambda *_: True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        if not args.decorated and not self.dropdown:
            box.pack_start(self.build_handle(above), False, False, 0)
        if not args.no_tabs:
            box.pack_start(self.build_tabs(), False, False, 0)
        overlay = Gtk.Overlay()
        overlay.add(self.web)
        if not args.decorated:
            overlay.add_overlay(self.build_grip())
        box.pack_start(overlay, True, True, 0)
        self.add(box)
        self.set_above(above)

        self.connect("key-press-event", self.on_key)
        self.connect("configure-event", self.on_configure)
        self.connect("map-event", self.on_map)
        self.connect("destroy", self.on_destroy)

        self.web.load_uri(args.url)
        if not args.no_tabs:
            GLib.timeout_add(TABS_POLL_MS, self.poll_tabs)

    # ---------------------------------------------------------------- page tabs
    def build_tabs(self):
        self.tabs_scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.EXTERNAL,
                                                vscrollbar_policy=Gtk.PolicyType.NEVER, no_show_all=True)
        self.tabs_scroller.get_style_context().add_class("pb-tabs")
        # a mouse wheel scrolls the tabs sideways
        self.tabs_scroller.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.tabs_scroller.connect("scroll-event", self.on_tabs_scroll)
        self.tabs_box = Gtk.Box(spacing=0, margin_start=6, margin_end=6)
        self.tabs_scroller.add(self.tabs_box)
        return self.tabs_scroller

    def on_tabs_scroll(self, _w, event):
        adj = self.tabs_scroller.get_hadjustment()
        ok, dx, dy = event.get_scroll_deltas()
        if not ok:
            dy = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.LEFT: -1}.get(event.direction, 1)
            dx = 0
        adj.set_value(adj.get_value() + (dx + dy) * 40)
        return True

    def poll_tabs(self):
        if not self.tabs_busy and self.web.get_uri() == self.args.url:
            self.tabs_busy = True
            self.web.call_async_javascript_function(JS_PAGES, -1, None, None, None, None, self.on_tabs_state)
        return True  # keeps polling: pages change when the layout is saved, the current page when it rotates

    def on_tabs_state(self, web, result):
        self.tabs_busy = False
        try:
            state = json.loads(web.call_async_javascript_function_finish(result).to_string())
        except Exception:  # panel still booting, or a page without the panel (waiting for the agent)
            return
        pages = [tuple(p) for p in state.get("pages", [])]
        if pages != self.tab_pages:
            self.tab_pages = pages
            self.rebuild_tabs()
        cur = state.get("cur", 0)
        for i, b in enumerate(self.tab_buttons):
            ctx = b.get_style_context()
            if i == cur and not ctx.has_class("active"):
                ctx.add_class("active")
                self.scroll_tab_into_view(b)
            elif i != cur:
                ctx.remove_class("active")

    def rebuild_tabs(self):
        for b in self.tab_buttons:
            b.destroy()
        self.tab_buttons = []
        for i, (icon, title) in enumerate(self.tab_pages):
            b = Gtk.Button(label=f"{icon} {title}".strip() or str(i + 1), relief=Gtk.ReliefStyle.NONE,
                           focus_on_click=False)
            b.connect("clicked", lambda _b, n=i: self.go_page(n))
            self.tabs_box.pack_start(b, False, False, 0)
            self.tab_buttons.append(b)
        self.tabs_box.show_all()
        self.tabs_scroller.set_visible(len(self.tab_buttons) > 1)

    def scroll_tab_into_view(self, button):
        alloc = button.get_allocation()
        adj = self.tabs_scroller.get_hadjustment()
        if alloc.x < adj.get_value():
            adj.set_value(alloc.x)
        elif alloc.x + alloc.width > adj.get_value() + adj.get_page_size():
            adj.set_value(alloc.x + alloc.width - adj.get_page_size())

    def go_page(self, i):
        args = GLib.Variant("a{sv}", {"i": GLib.Variant("i", i)})
        self.web.call_async_javascript_function(JS_GO, -1, args, None, None, None, None)
        for n, b in enumerate(self.tab_buttons):
            (b.get_style_context().add_class if n == i else b.get_style_context().remove_class)("active")

    # ---------------------------------------------------------------- handle: move, pin, reload, close
    def build_handle(self, above):
        handle = Gtk.EventBox()
        handle.get_style_context().add_class("pb-handle")
        handle.connect("button-press-event", self.on_handle_press)
        handle.connect("realize", lambda w: w.get_window().set_cursor(
            Gdk.Cursor.new_from_name(w.get_display(), "grab")))

        row = Gtk.Box(spacing=2, margin_start=10, margin_end=4, margin_top=2, margin_bottom=2)
        title = Gtk.Label(label="PHONEBOX", xalign=0)
        row.pack_start(title, True, True, 0)

        self.pin = Gtk.ToggleButton(active=above, relief=Gtk.ReliefStyle.NONE)
        self.pin.add(Gtk.Image.new_from_icon_name("view-pin-symbolic", Gtk.IconSize.MENU))
        self.pin.connect("toggled", lambda b: self.set_above(b.get_active(), remember=True))
        row.pack_start(self.pin, False, False, 0)

        for icon, tip, action in (("view-refresh-symbolic", "Reload (F5)", lambda *_: self.web.reload()),
                                  ("window-close-symbolic", "Close (Ctrl+Q)", lambda *_: self.destroy())):
            b = Gtk.Button(relief=Gtk.ReliefStyle.NONE, tooltip_text=tip)
            b.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU))
            b.connect("clicked", action)
            row.pack_start(b, False, False, 0)

        handle.add(row)
        return handle

    def build_grip(self):
        grip = Gtk.EventBox(halign=Gtk.Align.END, valign=Gtk.Align.END, tooltip_text="Drag to resize")
        grip.set_size_request(16, 16)
        grip.get_style_context().add_class("pb-grip")
        grip.connect("realize", lambda w: w.get_window().set_cursor(
            Gdk.Cursor.new_from_name(w.get_display(), "se-resize")))
        grip.connect("button-press-event", self.on_grip_press)
        return grip

    def on_handle_press(self, _w, event):
        if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
            return True
        return False

    def on_grip_press(self, _w, event):
        if event.button == 1:
            self.begin_resize_drag(Gdk.WindowEdge.SOUTH_EAST, event.button,
                                   int(event.x_root), int(event.y_root), event.time)
            return True
        return False

    def set_above(self, above, remember=False):
        self.set_keep_above(above)
        self.set_keep_below(self.below and not above)
        if hasattr(self, "pin"):
            self.pin.set_tooltip_text("Always on top (click for a normal window)" if above
                                      else "Normal window (click to keep it always on top)")
        if remember:
            self.state["above"] = above
            save_state(self.state)

    # a second start (app menu, autostart) brings the running widget to the front instead of opening another one
    def bring_to_front(self):
        self.deiconify()
        if self.below and not self.pin.get_active():
            # below windows: lift it for a moment, then let it sink back
            self.set_keep_below(False)
            self.present()
            GLib.timeout_add_seconds(4, lambda: (self.set_keep_below(self.below and not self.pin.get_active()), False)[1])
        else:
            self.present()

    # ---------------------------------------------------------------- loading
    # the agent may start after the widget (login), or restart for an update: keep trying
    def on_load_failed(self, _web, _event, uri, error):
        if error.matches(WebKit2.NetworkError.quark(), WebKit2.NetworkError.CANCELLED):
            return False
        print(f"phonebox-widget: {uri}: {error.message}; retrying in {RETRY_SECONDS} s", file=sys.stderr)
        self.web.load_html(
            "<body style='background:#000;color:#888;font:14px sans-serif;display:grid;place-items:center;"
            "height:100vh;margin:0'>Waiting for the PhoneBox agent…</body>", None)
        if not self.retry_id:
            self.retry_id = GLib.timeout_add_seconds(RETRY_SECONDS, self.retry)
        return True

    def on_load_changed(self, _web, event):
        if event == WebKit2.LoadEvent.FINISHED and self.web.get_uri() == self.args.url and self.retry_id:
            GLib.source_remove(self.retry_id)
            self.retry_id = 0

    def retry(self):
        self.retry_id = 0
        self.web.load_uri(self.args.url)
        return False

    def on_key(self, _win, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        if event.keyval == Gdk.KEY_F5:
            self.web.reload()
            return True
        if ctrl and event.keyval in (Gdk.KEY_q, Gdk.KEY_Q):
            self.destroy()
            return True
        if self.dropdown and event.keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        return False

    # ---------------------------------------------------------------- remembered geometry
    def on_map(self, _win, _event):
        self.tracking = False
        GLib.timeout_add(1000, self.start_tracking)
        return False

    def navigate(self, url):
        if url and url != self.args.url:
            self.args.url = url
            self.tab_pages = None
            self.web.load_uri(url)

    def show_at(self, x, y):
        self.move(x, y)
        self.show_all()
        self.present()

    def start_tracking(self):
        self.tracking = True
        return False

    def on_configure(self, _win, _event):
        if not self.tracking:
            return False
        # debounce: a drag sends many events
        if self.save_id:
            GLib.source_remove(self.save_id)
        self.save_id = GLib.timeout_add(500, self.remember_geometry)
        return False

    def remember_geometry(self):
        self.save_id = 0
        width, height = self.get_size()
        self.state[self.key("width")] = width
        self.state[self.key("height")] = height
        if not self.dropdown:
            self.state["x"], self.state["y"] = self.get_position()
        save_state(self.state)
        return False

    def on_destroy(self, _win):
        if self.save_id:
            GLib.source_remove(self.save_id)
            self.remember_geometry()


class App(Gtk.Application):
    def __init__(self, args):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS
                         if hasattr(Gio.ApplicationFlags, "DEFAULT_FLAGS") else Gio.ApplicationFlags.FLAGS_NONE)
        self.args = args
        self.win = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        css = Gtk.CssProvider()
        css.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        # logout and pkill send SIGTERM: close normally so a pending position is still saved
        for sig in (signal.SIGTERM, signal.SIGINT):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self.close_window)
        # the GNOME Shell extension drives the dropdown with these (org.gtk.Actions on D-Bus)
        show = Gio.SimpleAction.new("show", GLib.VariantType.new("(ii)"))
        show.connect("activate", lambda _a, xy: self.ensure_window().show_at(*xy.unpack()))
        hide = Gio.SimpleAction.new("hide", None)
        hide.connect("activate", lambda *_: self.win and self.win.hide())
        # starts the panel hidden if needed, and points it at the agent the extension uses (its port is a setting)
        navigate = Gio.SimpleAction.new("navigate", GLib.VariantType.new("s"))
        navigate.connect("activate", lambda _a, url: self.ensure_window().navigate(url.get_string()))
        for action in (show, hide, navigate):
            self.add_action(action)

    def close_window(self):
        if self.win:
            self.win.destroy()
        else:
            self.quit()
        return False

    def ensure_window(self):
        if not self.win:
            self.win = Widget(self, self.args)
            # hidden windows still keep the application running
        return self.win

    def do_activate(self):
        if self.win:
            if not self.args.dropdown:
                self.win.bring_to_front()
            return
        win = self.ensure_window()
        if self.args.show_at:
            win.show_at(*self.args.show_at)
        elif not self.args.dropdown:
            win.show_all()


def main():
    p = argparse.ArgumentParser(description="Show the PhoneBox panel as a desktop widget.")
    p.add_argument("--url", default="http://127.0.0.1:8765/panel/", help="panel address (default: %(default)s)")
    p.add_argument("--width", type=int, help="width in pixels (default: last size, else 420)")
    p.add_argument("--height", type=int, help="height in pixels (default: last size, else 780)")
    p.add_argument("--x", type=int, help="left edge in pixels (default: last position)")
    p.add_argument("--y", type=int, help="top edge in pixels (default: last position)")
    p.add_argument("--above", action="store_true", help="start pinned above other windows")
    p.add_argument("--below", action="store_true",
                   help="unpinned means below all windows, like a desktop widget (hidden by desktop icons on GNOME)")
    p.add_argument("--decorated", action="store_true", help="a normal title bar instead of the slim handle")
    p.add_argument("--dropdown", action="store_true",
                   help="the GNOME Shell extension's panel: starts hidden, no handle, shown under the indicator")
    p.add_argument("--show-at", type=int, nargs=2, metavar=("X", "Y"), help="show the dropdown at once, at X, Y")
    p.add_argument("--no-tabs", action="store_true", help="hide the page tabs")
    p.add_argument("--debug", action="store_true", help="enable the right-click menu and the web inspector")
    p.add_argument("--wayland", action="store_true", help="run as a native Wayland window (no position or keep-below)")
    args = p.parse_args()

    # options are this process's own; a second start only brings the running widget to the front
    sys.exit(App(args).run([sys.argv[0]]))


if __name__ == "__main__":
    main()
