"""
Cross-platform input injection for UniCent client.

Injects mouse moves, clicks, scrolls, and keyboard events.
- macOS:   Quartz (CoreGraphics) CGEvent APIs
- Linux:   xdotool + python-xlib or uinput
- Windows: ctypes SendInput (user32)

All platforms receive Linux evdev key/button codes over the wire
and translate them to the local platform representation.
"""

import logging
import platform
import subprocess
import time
from typing import Optional

log = logging.getLogger(__name__)

_SYSTEM = platform.system()


# ────────────────────────────────────────────────────────────
# macOS Quartz Injector
# ────────────────────────────────────────────────────────────

class _MacOSInjector:
    """Injects input events into macOS using Quartz/CoreGraphics."""

    def __init__(self):
        try:
            import Quartz
            self._Q = Quartz
        except ImportError:
            raise RuntimeError("pyobjc-framework-Quartz required: pip3 install pyobjc-framework-Quartz")

        from shared.keymap import (
            LINUX_TO_MACOS, LINUX_BTN_TO_MACOS,
            LINUX_MOD_TO_MACOS_FLAG,
            KEY_LEFTSHIFT, KEY_RIGHTSHIFT,
            KEY_LEFTCTRL, KEY_RIGHTCTRL,
            KEY_LEFTALT, KEY_RIGHTALT,
            KEY_LEFTMETA, KEY_RIGHTMETA,
        )
        self._LINUX_TO_MACOS = LINUX_TO_MACOS
        self._LINUX_BTN_TO_MACOS = LINUX_BTN_TO_MACOS
        self._LINUX_MOD_TO_MACOS_FLAG = LINUX_MOD_TO_MACOS_FLAG
        self._MODIFIER_KEYCODES = {
            KEY_LEFTSHIFT, KEY_RIGHTSHIFT,
            KEY_LEFTCTRL, KEY_RIGHTCTRL,
            KEY_LEFTALT, KEY_RIGHTALT,
            KEY_LEFTMETA, KEY_RIGHTMETA,
        }

        self._source = Quartz.CGEventSourceCreate(
            Quartz.kCGEventSourceStateHIDSystemState)
        self._cursor_x: float = 0.0
        self._cursor_y: float = 0.0
        self._modifier_flags: int = 0
        self._buttons_pressed: set = set()
        self._last_click_time: dict = {}
        self._click_count: dict = {}
        self._double_click_interval = 0.5
        self._event_tap = None
        self._tap_runloop_source = None
        self._setup_event_tap()
        self._update_screen_bounds()
        self._init_cursor_position()

    def _create_mouse_event(self, event_type: int, point, button: int):
        """Create a mouse event using a NULL source.

        Using None (NULL) as the source on macOS 26+ avoids hardware-origin
        checks that can cause the window server to drop events with a
        HID-system-state source when Accessibility trust is evaluated.
        """
        Q = self._Q
        return Q.CGEventCreateMouseEvent(None, event_type, point, button)

    def _setup_event_tap(self):
        """Create a CGEventTap to keep this process registered with macOS.

        Tries intercepting tap first (best click support), falls back to
        listen-only if Accessibility is not granted.  Either way, all event
        posting uses kCGSessionEventTap which does not require Accessibility.
        """
        Q = self._Q
        mask = (
            (1 << Q.kCGEventLeftMouseDown) |
            (1 << Q.kCGEventLeftMouseUp) |
            (1 << Q.kCGEventRightMouseDown) |
            (1 << Q.kCGEventRightMouseUp) |
            (1 << Q.kCGEventMouseMoved) |
            (1 << Q.kCGEventLeftMouseDragged) |
            (1 << Q.kCGEventRightMouseDragged) |
            (1 << Q.kCGEventScrollWheel) |
            (1 << Q.kCGEventKeyDown) |
            (1 << Q.kCGEventKeyUp) |
            (1 << Q.kCGEventFlagsChanged)
        )
        try:
            # Try intercepting tap first (requires Accessibility)
            self._event_tap = Q.CGEventTapCreate(
                Q.kCGSessionEventTap,
                Q.kCGHeadInsertEventTap,
                Q.kCGEventTapOptionDefault,
                mask,
                self._tap_callback,
                None,
            )
            if self._event_tap:
                log.info("Intercepting event tap created (Accessibility granted)")
            else:
                # Fall back to listen-only tap (no Accessibility needed)
                self._event_tap = Q.CGEventTapCreate(
                    Q.kCGSessionEventTap,
                    Q.kCGHeadInsertEventTap,
                    Q.kCGEventTapOptionListenOnly,
                    mask,
                    self._tap_callback,
                    None,
                )
                if self._event_tap:
                    log.info("Listen-only event tap created (no Accessibility)")
                else:
                    log.warning("CGEventTapCreate returned None for both modes")

            if self._event_tap:
                self._tap_runloop_source = Q.CFMachPortCreateRunLoopSource(
                    None, self._event_tap, 0)
                import threading
                def _run_tap():
                    Q.CFRunLoopAddSource(
                        Q.CFRunLoopGetCurrent(),
                        self._tap_runloop_source,
                        Q.kCFRunLoopCommonModes)
                    Q.CGEventTapEnable(self._event_tap, True)
                    Q.CFRunLoopRun()
                t = threading.Thread(target=_run_tap, daemon=True)
                t.start()
        except Exception as e:
            log.warning(f"Could not create event tap: {e}")

    def _tap_callback(self, proxy, event_type, event, refcon):
        """Tap callback — pass events through and re-enable if macOS disables."""
        if event_type in (0xFFFFFFFE, 0xFFFFFFFF) and self._event_tap:
            log.warning("Event tap was disabled by macOS — re-enabling")
            self._Q.CGEventTapEnable(self._event_tap, True)
        return event

    def _post_event(self, event):
        """Post an event at the session level."""
        if not event:
            return
        Q = self._Q
        Q.CGEventPost(Q.kCGSessionEventTap, event)

    def _post_click_event(self, event):
        """Post a click event at the session level.

        Using kCGSessionEventTap instead of kCGHIDEventTap avoids the
        Accessibility permission requirement that causes clicks to be
        silently dropped on macOS when the process is not trusted.
        """
        if not event:
            return
        Q = self._Q
        Q.CGEventPost(Q.kCGSessionEventTap, event)

    def _update_screen_bounds(self):
        Q = self._Q
        main_display = Q.CGMainDisplayID()
        bounds = Q.CGDisplayBounds(main_display)
        self._min_x = bounds.origin.x
        self._min_y = bounds.origin.y
        self._max_x = bounds.origin.x + bounds.size.width
        self._max_y = bounds.origin.y + bounds.size.height
        try:
            (err, display_ids, count) = Q.CGGetActiveDisplayList(16, None, None)
            if err == 0 and display_ids:
                for did in display_ids:
                    b = Q.CGDisplayBounds(did)
                    self._min_x = min(self._min_x, b.origin.x)
                    self._min_y = min(self._min_y, b.origin.y)
                    self._max_x = max(self._max_x, b.origin.x + b.size.width)
                    self._max_y = max(self._max_y, b.origin.y + b.size.height)
        except Exception:
            pass
        log.info(f"Screen bounds: ({self._min_x},{self._min_y}) to ({self._max_x},{self._max_y})")

    def _init_cursor_position(self):
        try:
            Q = self._Q
            event = Q.CGEventCreate(None)
            if event:
                loc = Q.CGEventGetLocation(event)
                self._cursor_x = loc.x
                self._cursor_y = loc.y
        except Exception:
            self._cursor_x = self._max_x / 2
            self._cursor_y = self._max_y / 2

    def _sync_cursor_from_system(self):
        """Refresh cached cursor position from macOS global cursor state."""
        Q = self._Q
        try:
            event = Q.CGEventCreate(None)
            if event:
                loc = Q.CGEventGetLocation(event)
                self._cursor_x = loc.x
                self._cursor_y = loc.y
        except Exception:
            pass

    def _warp_and_notify(self, point, dx: int = 0, dy: int = 0):
        """Move cursor via warp, then immediately post a synthetic move event.

        CGWarpMouseCursorPosition moves the visible cursor but suppresses
        the next *hardware* mouse-moved event.  Posting our own synthetic
        move event right after the warp re-syncs AppKit's hit-testing,
        because the suppression only affects hardware events, not synthetic
        ones.  This is the technique Barrier / Synergy use.
        """
        Q = self._Q
        Q.CGWarpMouseCursorPosition(point)
        Q.CGAssociateMouseAndMouseCursorPosition(True)

        if 0 in self._buttons_pressed:
            et = Q.kCGEventLeftMouseDragged
        elif 1 in self._buttons_pressed:
            et = Q.kCGEventRightMouseDragged
        elif self._buttons_pressed:
            et = Q.kCGEventOtherMouseDragged
        else:
            et = Q.kCGEventMouseMoved

        event = self._create_mouse_event(et, point, 0)
        if event:
            Q.CGEventSetIntegerValueField(event, Q.kCGMouseEventDeltaX, dx)
            Q.CGEventSetIntegerValueField(event, Q.kCGMouseEventDeltaY, dy)
            self._post_event(event)

    def move_mouse_relative(self, dx: int, dy: int):
        Q = self._Q
        new_x = max(self._min_x, min(self._cursor_x + dx, self._max_x - 1))
        new_y = max(self._min_y, min(self._cursor_y + dy, self._max_y - 1))
        self._cursor_x = new_x
        self._cursor_y = new_y
        self._warp_and_notify(Q.CGPointMake(new_x, new_y), dx, dy)

    def move_mouse_absolute(self, x: int, y: int):
        Q = self._Q
        self._cursor_x = float(x)
        self._cursor_y = float(y)
        self._warp_and_notify(Q.CGPointMake(x, y), 0, 0)

    def warp_cursor(self, x: int, y: int):
        Q = self._Q
        self._cursor_x = float(x)
        self._cursor_y = float(y)
        self._warp_and_notify(Q.CGPointMake(x, y), 0, 0)

    def mouse_button(self, linux_button: int, state: int):
        Q = self._Q
        mac_button = self._LINUX_BTN_TO_MACOS.get(linux_button, -1)
        if mac_button < 0:
            return
        pressed = state in (1, 2)

        point = Q.CGPointMake(self._cursor_x, self._cursor_y)

        if mac_button == 0:
            et = Q.kCGEventLeftMouseDown if pressed else Q.kCGEventLeftMouseUp
            event = self._create_mouse_event(et, point, 0)
        elif mac_button == 1:
            et = Q.kCGEventRightMouseDown if pressed else Q.kCGEventRightMouseUp
            event = self._create_mouse_event(et, point, 1)
        else:
            et = Q.kCGEventOtherMouseDown if pressed else Q.kCGEventOtherMouseUp
            event = self._create_mouse_event(et, point, mac_button)

        if event:
            # Keep click events minimal and explicit for macOS reliability.
            Q.CGEventSetIntegerValueField(event, Q.kCGMouseEventButtonNumber, mac_button)
            click_state_field = getattr(Q, 'kCGMouseEventClickState', None)
            if click_state_field is not None:
                Q.CGEventSetIntegerValueField(event, click_state_field, 1)
            Q.CGEventSetFlags(event, self._modifier_flags)
            self._post_click_event(event)
        log.debug(
            "macOS mouse_button injected linux=%s mac=%s state=%s at=(%s,%s)",
            linux_button, mac_button, state, int(self._cursor_x), int(self._cursor_y)
        )
        if pressed:
            self._buttons_pressed.add(mac_button)
        else:
            self._buttons_pressed.discard(mac_button)

    def scroll(self, dx: int, dy: int):
        Q = self._Q
        # CGEventCreateScrollWheelEvent2 with wheelCount=2 triggers a PyObjC
        # binding error on some macOS versions ('Need 4 arguments, got 5').
        # Use two separate single-axis events instead.
        if dy:
            event = Q.CGEventCreateScrollWheelEvent2(
                self._source, Q.kCGScrollEventUnitPixel, 1, dy * 3)
            if event:
                self._post_event(event)
        if dx:
            event = Q.CGEventCreateScrollWheelEvent2(
                self._source, Q.kCGScrollEventUnitPixel, 1, dx * 3)
            if event:
                Q.CGEventSetIntegerValueField(
                    event, Q.kCGScrollWheelEventDeltaAxis2, dx * 3)
                Q.CGEventSetIntegerValueField(
                    event, Q.kCGScrollWheelEventDeltaAxis1, 0)
                self._post_event(event)

    def key_event(self, linux_keycode: int, state: int):
        Q = self._Q
        if linux_keycode in self._MODIFIER_KEYCODES:
            self._handle_modifier(linux_keycode, state)
            return
        mac_keycode = self._LINUX_TO_MACOS.get(linux_keycode, -1)
        if mac_keycode < 0:
            return
        key_down = state in (1, 2)
        event = Q.CGEventCreateKeyboardEvent(self._source, mac_keycode, key_down)
        if event:
            Q.CGEventSetFlags(event, self._modifier_flags)
            self._post_event(event)

    def _handle_modifier(self, linux_keycode: int, state: int):
        Q = self._Q
        mac_flag = self._LINUX_MOD_TO_MACOS_FLAG.get(linux_keycode, 0)
        mac_keycode = self._LINUX_TO_MACOS.get(linux_keycode, -1)
        if not mac_flag or mac_keycode < 0:
            return
        if state == 1:
            self._modifier_flags |= mac_flag
        elif state == 0:
            self._modifier_flags &= ~mac_flag
        event = Q.CGEventCreateKeyboardEvent(self._source, mac_keycode, state == 1)
        if event:
            Q.CGEventSetFlags(event, self._modifier_flags)
            self._post_event(event)

    def reset_modifiers(self):
        Q = self._Q
        for lkc in self._MODIFIER_KEYCODES:
            mkc = self._LINUX_TO_MACOS.get(lkc, -1)
            if mkc >= 0:
                event = Q.CGEventCreateKeyboardEvent(self._source, mkc, False)
                if event:
                    self._post_event(event)
        self._modifier_flags = 0
        self._buttons_pressed.clear()

    def release_all(self):
        self.reset_modifiers()

    @property
    def cursor_position(self):
        return (int(self._cursor_x), int(self._cursor_y))


# ────────────────────────────────────────────────────────────
# Linux Input Injector (python-xlib XTest preferred, xdotool fallback)
# ────────────────────────────────────────────────────────────

class _LinuxInjector:
    """Injects input events on Linux.

    Primary:  python-xlib XTest extension — single persistent X11 connection,
              zero subprocess overhead, correct double-click / right-click /
              modifier tracking.
    Fallback: xdotool subprocess (one process per event — higher latency,
              no double-click, kept for compatibility only).
    """

    # evdev button code → X11 button number
    _BTN_TO_X11 = {
        272: 1,   # BTN_LEFT
        273: 3,   # BTN_RIGHT
        274: 2,   # BTN_MIDDLE
        275: 8,   # BTN_SIDE  (back)
        276: 9,   # BTN_EXTRA (forward)
    }

    # evdev modifier key codes (shift, ctrl, alt, meta — both sides)
    _MODIFIER_EVDEV = {42, 54, 29, 97, 56, 100, 125, 126}

    def __init__(self):
        self._cursor_x: int = 0
        self._cursor_y: int = 0
        self._buttons_pressed: set = set()
        self._modifier_state: set = set()
        self._display = None
        self._X = None
        self._xtest = None

        # ── Try python-xlib XTest first ──────────────────────────────────
        try:
            from Xlib import display as _xdisplay, X as _X
            from Xlib.ext import xtest as _xtest
            _d = _xdisplay.Display()
            # Confirm XTest extension is present
            if _d.query_extension('XTEST') is None:
                raise RuntimeError("XTEST extension not available")
            self._display = _d
            self._X = _X
            self._xtest = _xtest
            log.info("Linux injector: using python-xlib XTest (zero subprocess latency)")
        except Exception as e:
            log.warning(
                f"python-xlib XTest unavailable ({e}) — falling back to xdotool. "
                "Install python-xlib for best performance: pip install python-xlib"
            )
            self._display = None

        # ── xdotool fallback bookkeeping ─────────────────────────────────
        if not self._display:
            self._has_xdotool = self._check_tool('xdotool')
            self._has_ydotool = self._check_tool('ydotool')
            self._EVDEV_TO_XKEYSYM = self._build_evdev_to_xkeysym()
            if not self._has_xdotool and not self._has_ydotool:
                log.warning("Neither python-xlib nor xdotool available — injection limited")

        self._init_cursor_position()

    def _check_tool(self, name):
        try:
            subprocess.run([name, '--version'], capture_output=True, timeout=2)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _build_evdev_to_xkeysym(self):
        """Map evdev key codes to X11 keysym names for xdotool fallback."""
        return {
            1: 'Escape', 2: '1', 3: '2', 4: '3', 5: '4', 6: '5',
            7: '6', 8: '7', 9: '8', 10: '9', 11: '0',
            12: 'minus', 13: 'equal', 14: 'BackSpace', 15: 'Tab',
            16: 'q', 17: 'w', 18: 'e', 19: 'r', 20: 't',
            21: 'y', 22: 'u', 23: 'i', 24: 'o', 25: 'p',
            26: 'bracketleft', 27: 'bracketright', 28: 'Return',
            29: 'Control_L', 30: 'a', 31: 's', 32: 'd', 33: 'f',
            34: 'g', 35: 'h', 36: 'j', 37: 'k', 38: 'l',
            39: 'semicolon', 40: 'apostrophe', 41: 'grave',
            42: 'Shift_L', 43: 'backslash',
            44: 'z', 45: 'x', 46: 'c', 47: 'v', 48: 'b',
            49: 'n', 50: 'm', 51: 'comma', 52: 'period', 53: 'slash',
            54: 'Shift_R', 56: 'Alt_L', 57: 'space', 58: 'Caps_Lock',
            59: 'F1', 60: 'F2', 61: 'F3', 62: 'F4', 63: 'F5',
            64: 'F6', 65: 'F7', 66: 'F8', 67: 'F9', 68: 'F10',
            87: 'F11', 88: 'F12',
            97: 'Control_R', 100: 'Alt_R',
            102: 'Home', 103: 'Up', 104: 'Prior', 105: 'Left',
            106: 'Right', 107: 'End', 108: 'Down', 109: 'Next',
            110: 'Insert', 111: 'Delete',
            125: 'Super_L', 126: 'Super_R',
        }

    def _init_cursor_position(self):
        # python-xlib path: read the current pointer position from the X server
        if self._display:
            try:
                data = self._display.screen().root.query_pointer()
                self._cursor_x = data.root_x
                self._cursor_y = data.root_y
                return
            except Exception:
                pass
        # xdotool fallback
        if getattr(self, '_has_xdotool', False):
            try:
                import re
                result = subprocess.run(
                    ['xdotool', 'getmouselocation'],
                    capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    match = re.search(r'x:(\d+)\s+y:(\d+)', result.stdout)
                    if match:
                        self._cursor_x = int(match.group(1))
                        self._cursor_y = int(match.group(2))
                        return
            except Exception:
                pass
        self._cursor_x = 960
        self._cursor_y = 540

    # ── python-xlib XTest helpers ─────────────────────────────────────────

    def _xtest_motion(self, x: int, y: int):
        """Warp cursor to absolute (x, y) via XTest with a single flush."""
        X = self._X
        self._xtest.fake_input(
            self._display, X.MotionNotify, False, X.CurrentTime, X.NONE, x, y)
        self._display.flush()

    def _xtest_button(self, x11_btn: int, pressed: bool):
        """Press or release an X11 mouse button via XTest."""
        X = self._X
        evt = X.ButtonPress if pressed else X.ButtonRelease
        self._xtest.fake_input(self._display, evt, x11_btn, X.CurrentTime)
        self._display.flush()

    def _xtest_key(self, x11_keycode: int, pressed: bool):
        """Press or release an X11 key via XTest."""
        X = self._X
        evt = X.KeyPress if pressed else X.KeyRelease
        self._xtest.fake_input(self._display, evt, x11_keycode, X.CurrentTime)
        self._display.flush()

    # ── Public injection API ──────────────────────────────────────────────

    def move_mouse_relative(self, dx: int, dy: int):
        self._cursor_x += dx
        self._cursor_y += dy
        if self._display:
            self._xtest_motion(self._cursor_x, self._cursor_y)
        elif getattr(self, '_has_xdotool', False):
            try:
                subprocess.Popen(
                    ['xdotool', 'mousemove', '--', str(self._cursor_x), str(self._cursor_y)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def move_mouse_absolute(self, x: int, y: int):
        self._cursor_x = x
        self._cursor_y = y
        if self._display:
            self._xtest_motion(x, y)
        elif getattr(self, '_has_xdotool', False):
            try:
                subprocess.Popen(
                    ['xdotool', 'mousemove', str(x), str(y)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def warp_cursor(self, x: int, y: int):
        self.move_mouse_absolute(x, y)

    def mouse_button(self, linux_button: int, state: int):
        pressed = bool(state)
        if self._display:
            x11_btn = self._BTN_TO_X11.get(linux_button)
            if x11_btn is not None:
                self._xtest_button(x11_btn, pressed)
        elif getattr(self, '_has_xdotool', False):
            # xdotool button map: left=1, middle=2, right=3, back=8, fwd=9
            btn_map = {272: 1, 273: 3, 274: 2, 275: 8, 276: 9}
            xbtn = btn_map.get(linux_button)
            if xbtn is not None:
                action = 'mousedown' if pressed else 'mouseup'
                try:
                    subprocess.Popen(
                        ['xdotool', action, str(xbtn)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
        if pressed:
            self._buttons_pressed.add(linux_button)
        else:
            self._buttons_pressed.discard(linux_button)

    def scroll(self, dx: int, dy: int):
        # X11 scroll buttons: 4=up, 5=down, 6=left, 7=right
        if dy > 0:
            btn = 4
        elif dy < 0:
            btn = 5
        elif dx > 0:
            btn = 7
        elif dx < 0:
            btn = 6
        else:
            return
        clicks = max(1, min(abs(dy or dx), 10))
        if self._display:
            X = self._X
            for _ in range(clicks):
                self._xtest.fake_input(self._display, X.ButtonPress, btn, X.CurrentTime)
                self._xtest.fake_input(self._display, X.ButtonRelease, btn, X.CurrentTime)
            self._display.flush()
        elif getattr(self, '_has_xdotool', False):
            try:
                subprocess.Popen(
                    ['xdotool', 'click', str(btn)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def key_event(self, linux_keycode: int, state: int):
        pressed = state in (1, 2)
        if self._display:
            # On Linux, X11 keycode = evdev keycode + 8 (universal offset)
            x11_keycode = linux_keycode + 8
            self._xtest_key(x11_keycode, pressed)
        elif getattr(self, '_has_xdotool', False):
            keysym = self._EVDEV_TO_XKEYSYM.get(linux_keycode)
            if keysym:
                action = 'keydown' if pressed else 'keyup'
                try:
                    subprocess.Popen(
                        ['xdotool', action, keysym],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass

    def reset_modifiers(self):
        if self._display:
            # Release all modifier keys: Shift, Ctrl, Alt, Meta (both sides)
            for evdev_kc in self._MODIFIER_EVDEV:
                x11_kc = evdev_kc + 8
                self._xtest_key(x11_kc, False)
        elif getattr(self, '_has_xdotool', False):
            for keysym in ['Shift_L', 'Shift_R', 'Control_L', 'Control_R',
                           'Alt_L', 'Alt_R', 'Super_L', 'Super_R']:
                try:
                    subprocess.Popen(
                        ['xdotool', 'keyup', keysym],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
        self._modifier_state.clear()
        self._buttons_pressed.clear()

    def release_all(self):
        self.reset_modifiers()

    @property
    def cursor_position(self):
        return (self._cursor_x, self._cursor_y)


# ────────────────────────────────────────────────────────────
# Windows Input Injector (ctypes SendInput)
# ────────────────────────────────────────────────────────────

class _WindowsInjector:
    """Injects input events on Windows using ctypes SendInput."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self._ctypes = ctypes
        self._user32 = ctypes.windll.user32
        self._cursor_x: int = 0
        self._cursor_y: int = 0
        self._buttons_pressed: set = set()
        self._modifier_flags: int = 0

        # Get screen dimensions
        self._screen_w = self._user32.GetSystemMetrics(0)
        self._screen_h = self._user32.GetSystemMetrics(1)

        # Build evdev → Windows VK map
        self._EVDEV_TO_VK = {
            1: 0x1B, 2: 0x31, 3: 0x32, 4: 0x33, 5: 0x34,
            6: 0x35, 7: 0x36, 8: 0x37, 9: 0x38, 10: 0x39, 11: 0x30,
            12: 0xBD, 13: 0xBB, 14: 0x08, 15: 0x09,
            16: 0x51, 17: 0x57, 18: 0x45, 19: 0x52, 20: 0x54,
            21: 0x59, 22: 0x55, 23: 0x49, 24: 0x4F, 25: 0x50,
            26: 0xDB, 27: 0xDD, 28: 0x0D,
            29: 0xA2, 30: 0x41, 31: 0x53, 32: 0x44, 33: 0x46,
            34: 0x47, 35: 0x48, 36: 0x4A, 37: 0x4B, 38: 0x4C,
            39: 0xBA, 40: 0xDE, 41: 0xC0,
            42: 0xA0, 43: 0xDC,
            44: 0x5A, 45: 0x58, 46: 0x43, 47: 0x56, 48: 0x42,
            49: 0x4E, 50: 0x4D, 51: 0xBC, 52: 0xBE, 53: 0xBF,
            54: 0xA1, 56: 0xA4, 57: 0x20, 58: 0x14,
            59: 0x70, 60: 0x71, 61: 0x72, 62: 0x73, 63: 0x74,
            64: 0x75, 65: 0x76, 66: 0x77, 67: 0x78, 68: 0x79,
            87: 0x7A, 88: 0x7B,
            97: 0xA3, 100: 0xA5,
            102: 0x24, 103: 0x26, 104: 0x21, 105: 0x25,
            106: 0x27, 107: 0x23, 108: 0x28, 109: 0x22,
            110: 0x2D, 111: 0x2E,
            125: 0x5B, 126: 0x5C,
        }

        # Init cursor pos
        pt = wintypes.POINT()
        self._user32.GetCursorPos(ctypes.byref(pt))
        self._cursor_x = pt.x
        self._cursor_y = pt.y

    def move_mouse_relative(self, dx: int, dy: int):
        self._cursor_x += dx
        self._cursor_y += dy
        self._cursor_x = max(0, min(self._cursor_x, self._screen_w - 1))
        self._cursor_y = max(0, min(self._cursor_y, self._screen_h - 1))
        self._user32.SetCursorPos(self._cursor_x, self._cursor_y)

    def move_mouse_absolute(self, x: int, y: int):
        self._cursor_x = x
        self._cursor_y = y
        self._user32.SetCursorPos(x, y)

    def warp_cursor(self, x: int, y: int):
        self.move_mouse_absolute(x, y)

    def mouse_button(self, linux_button: int, state: int):
        import ctypes

        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004
        MOUSEEVENTF_RIGHTDOWN = 0x0008
        MOUSEEVENTF_RIGHTUP = 0x0010
        MOUSEEVENTF_MIDDLEDOWN = 0x0020
        MOUSEEVENTF_MIDDLEUP = 0x0040

        flag_map = {
            272: (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
            273: (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
            274: (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
        }
        flags = flag_map.get(linux_button)
        if not flags:
            return
        flag = flags[0] if state else flags[1]
        self._user32.mouse_event(flag, 0, 0, 0, 0)
        if state:
            self._buttons_pressed.add(linux_button)
        else:
            self._buttons_pressed.discard(linux_button)

    def scroll(self, dx: int, dy: int):
        MOUSEEVENTF_WHEEL = 0x0800
        MOUSEEVENTF_HWHEEL = 0x01000
        WHEEL_DELTA = 120
        if dy:
            self._user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, dy * WHEEL_DELTA, 0)
        if dx:
            self._user32.mouse_event(MOUSEEVENTF_HWHEEL, 0, 0, dx * WHEEL_DELTA, 0)

    def key_event(self, linux_keycode: int, state: int):
        import ctypes

        KEYEVENTF_KEYUP = 0x0002
        vk = self._EVDEV_TO_VK.get(linux_keycode)
        if vk is None:
            return
        flags = 0 if state in (1, 2) else KEYEVENTF_KEYUP
        self._user32.keybd_event(vk, 0, flags, 0)

    def reset_modifiers(self):
        KEYEVENTF_KEYUP = 0x0002
        for vk in [0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C]:
            self._user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        self._buttons_pressed.clear()

    def release_all(self):
        self.reset_modifiers()

    @property
    def cursor_position(self):
        return (self._cursor_x, self._cursor_y)


# ────────────────────────────────────────────────────────────
# Permission checks
# ────────────────────────────────────────────────────────────

def check_accessibility_permissions() -> bool:
    """Check if the app has the required permissions for input injection."""
    if _SYSTEM == 'Darwin':
        try:
            import Quartz
            if hasattr(Quartz, 'AXIsProcessTrusted'):
                return bool(Quartz.AXIsProcessTrusted())
            # Fallback for older bindings.
            from Quartz import CGEventCreateKeyboardEvent, CGEventSourceCreate, kCGEventSourceStateHIDSystemState
            source = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
            event = CGEventCreateKeyboardEvent(source, 0, False)
            return event is not None
        except Exception:
            return False
    elif _SYSTEM == 'Linux':
        try:
            subprocess.run(['xdotool', '--version'], capture_output=True, timeout=2)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    elif _SYSTEM == 'Windows':
        return True  # No special permissions needed
    return False


def request_accessibility_permissions():
    """Prompt user to grant required permissions — GUI dialog on macOS."""
    if _SYSTEM == 'Darwin':
        try:
            import Quartz
            opts_key = getattr(Quartz, 'kAXTrustedCheckOptionPrompt', None)
            check_fn = getattr(Quartz, 'AXIsProcessTrustedWithOptions', None)
            if opts_key is not None and check_fn is not None:
                check_fn({opts_key: True})
        except Exception:
            pass
        _show_macos_accessibility_dialog()
    elif _SYSTEM == 'Linux':
        print("\n  ⚠  xdotool is required for input injection on Linux.")
        print("  Install it:")
        print("    Arch:   sudo pacman -S xdotool")
        print("    Debian: sudo apt install xdotool")
        print()
    elif _SYSTEM == 'Windows':
        print("  No special permissions needed on Windows.")


def _show_macos_accessibility_dialog():
    """Show a friendly macOS dialog explaining how to grant Accessibility."""
    try:
        import rumps
        response = rumps.alert(
            title='UniCent needs Accessibility Permission',
            message=(
                'UniCent needs Accessibility access to control your '
                'mouse and keyboard.\n\n'
                '1. Click "Open Settings" below\n'
                '2. Click the + button\n'
                '3. Navigate to Applications → Xcode → Contents → '
                'Developer → Library → Frameworks → Python3.framework '
                '→ Versions → 3.9 → Resources → Python.app\n'
                '   (or search for "Python")\n'
                '4. Toggle it ON\n'
                '5. Restart UniCent'
            ),
            ok='Open Settings',
            cancel='Later',
        )
        if response == 1:  # OK/Open Settings clicked
            subprocess.run(
                ['open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'],
                check=False,
            )
        return
    except Exception:
        pass
    # Fallback: try tkinter
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        result = messagebox.askokcancel(
            'UniCent — Accessibility Permission Required',
            'UniCent needs Accessibility access to control your '
            'mouse and keyboard.\n\n'
            '1. Click OK to open System Settings\n'
            '2. Click the + button\n'
            '3. Add "Python" (or the Python.app from your framework)\n'
            '4. Toggle it ON, then restart UniCent',
        )
        root.destroy()
        if result:
            subprocess.run(
                ['open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'],
                check=False,
            )
        return
    except Exception:
        pass
    # Final fallback: terminal
    print("\n  ⚠  Accessibility permissions required!")
    print("  System Settings → Privacy & Security → Accessibility")
    print("  Add Python and toggle it ON, then restart UniCent.")
    subprocess.run(
        ['open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'],
        check=False,
    )


# ────────────────────────────────────────────────────────────
# Factory
# ────────────────────────────────────────────────────────────

def InputInjector():
    """Factory: returns the platform-appropriate InputInjector instance."""
    if _SYSTEM == 'Darwin':
        return _MacOSInjector()
    elif _SYSTEM == 'Linux':
        return _LinuxInjector()
    elif _SYSTEM == 'Windows':
        return _WindowsInjector()
    else:
        raise RuntimeError(f"Unsupported platform: {_SYSTEM}")
