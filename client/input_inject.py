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
            from Quartz import (
                CGEventCreateMouseEvent,
                CGEventCreateKeyboardEvent,
                CGEventCreateScrollWheelEvent2,
                CGEventPost,
                CGEventSetIntegerValueField,
                CGEventSetFlags,
                CGDisplayBounds,
                CGMainDisplayID,
                CGWarpMouseCursorPosition,
                CGAssociateMouseAndMouseCursorPosition,
                CGEventSourceCreate,
                kCGEventSourceStateHIDSystemState,
                kCGHIDEventTap,
            )
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
        self._update_screen_bounds()
        self._init_cursor_position()

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

    def move_mouse_relative(self, dx: int, dy: int):
        Q = self._Q
        new_x = max(self._min_x, min(self._cursor_x + dx, self._max_x - 1))
        new_y = max(self._min_y, min(self._cursor_y + dy, self._max_y - 1))
        self._cursor_x = new_x
        self._cursor_y = new_y
        point = Q.CGPointMake(new_x, new_y)

        # On some macOS setups, posted relative move events are delivered but
        # don't visibly move the cursor. A direct warp guarantees movement.
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
        event = Q.CGEventCreateMouseEvent(self._source, et, point, 0)
        if event:
            Q.CGEventSetIntegerValueField(event, Q.kCGMouseEventDeltaX, dx)
            Q.CGEventSetIntegerValueField(event, Q.kCGMouseEventDeltaY, dy)
            Q.CGEventPost(Q.kCGHIDEventTap, event)

    def move_mouse_absolute(self, x: int, y: int):
        Q = self._Q
        self._cursor_x = float(x)
        self._cursor_y = float(y)
        point = Q.CGPointMake(x, y)
        Q.CGWarpMouseCursorPosition(point)
        Q.CGAssociateMouseAndMouseCursorPosition(True)
        event = Q.CGEventCreateMouseEvent(self._source, Q.kCGEventMouseMoved, point, 0)
        if event:
            Q.CGEventPost(Q.kCGHIDEventTap, event)

    def warp_cursor(self, x: int, y: int):
        Q = self._Q
        self._cursor_x = float(x)
        self._cursor_y = float(y)
        point = Q.CGPointMake(x, y)
        Q.CGWarpMouseCursorPosition(point)
        Q.CGAssociateMouseAndMouseCursorPosition(True)

    def mouse_button(self, linux_button: int, state: int):
        Q = self._Q
        mac_button = self._LINUX_BTN_TO_MACOS.get(linux_button, -1)
        if mac_button < 0:
            return
        point = Q.CGPointMake(self._cursor_x, self._cursor_y)
        if mac_button == 0:
            et = Q.kCGEventLeftMouseDown if state else Q.kCGEventLeftMouseUp
        elif mac_button == 1:
            et = Q.kCGEventRightMouseDown if state else Q.kCGEventRightMouseUp
        else:
            et = Q.kCGEventOtherMouseDown if state else Q.kCGEventOtherMouseUp
        event = Q.CGEventCreateMouseEvent(self._source, et, point, mac_button)
        if event:
            if mac_button > 1:
                Q.CGEventSetIntegerValueField(event, Q.kCGMouseEventButtonNumber, mac_button)
            Q.CGEventPost(Q.kCGHIDEventTap, event)
        if state:
            self._buttons_pressed.add(mac_button)
        else:
            self._buttons_pressed.discard(mac_button)

    def scroll(self, dx: int, dy: int):
        Q = self._Q
        event = Q.CGEventCreateScrollWheelEvent2(
            self._source, Q.kCGScrollEventUnitPixel, 2, dy * 3, dx * 3)
        if event:
            Q.CGEventPost(Q.kCGHIDEventTap, event)

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
            Q.CGEventPost(Q.kCGHIDEventTap, event)

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
            Q.CGEventPost(Q.kCGHIDEventTap, event)

    def reset_modifiers(self):
        Q = self._Q
        for lkc in self._MODIFIER_KEYCODES:
            mkc = self._LINUX_TO_MACOS.get(lkc, -1)
            if mkc >= 0:
                event = Q.CGEventCreateKeyboardEvent(self._source, mkc, False)
                if event:
                    Q.CGEventPost(Q.kCGHIDEventTap, event)
        self._modifier_flags = 0
        self._buttons_pressed.clear()

    def release_all(self):
        self.reset_modifiers()

    @property
    def cursor_position(self):
        return (int(self._cursor_x), int(self._cursor_y))


# ────────────────────────────────────────────────────────────
# Linux Input Injector (xdotool + python-xlib / xdg)
# ────────────────────────────────────────────────────────────

class _LinuxInjector:
    """Injects input events on Linux using xdotool (X11/XWayland)."""

    def __init__(self):
        self._cursor_x: int = 0
        self._cursor_y: int = 0
        self._buttons_pressed: set = set()
        self._modifier_state: set = set()
        self._has_xdotool = self._check_tool('xdotool')
        self._has_ydotool = self._check_tool('ydotool')

        from shared.keymap import LINUX_TO_MACOS, LINUX_BTN_TO_MACOS
        # evdev key code → X11 keysym name mapping for xdotool
        self._EVDEV_TO_XKEYSYM = self._build_evdev_to_xkeysym()

        if not self._has_xdotool and not self._has_ydotool:
            log.warning("Neither xdotool nor ydotool found — input injection limited")

        self._init_cursor_position()

    def _check_tool(self, name):
        try:
            subprocess.run([name, '--version'], capture_output=True, timeout=2)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _build_evdev_to_xkeysym(self):
        """Map evdev key codes to X11 keysym names for xdotool."""
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
        if self._has_xdotool:
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

    def move_mouse_relative(self, dx: int, dy: int):
        self._cursor_x += dx
        self._cursor_y += dy
        if self._has_xdotool:
            try:
                subprocess.Popen(
                    ['xdotool', 'mousemove', '--', str(self._cursor_x), str(self._cursor_y)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def move_mouse_absolute(self, x: int, y: int):
        self._cursor_x = x
        self._cursor_y = y
        if self._has_xdotool:
            try:
                subprocess.Popen(
                    ['xdotool', 'mousemove', str(x), str(y)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def warp_cursor(self, x: int, y: int):
        self.move_mouse_absolute(x, y)

    def mouse_button(self, linux_button: int, state: int):
        btn_map = {272: 1, 273: 3, 274: 2, 275: 4, 276: 5}
        xbtn = btn_map.get(linux_button)
        if not xbtn:
            return
        if self._has_xdotool:
            action = 'mousedown' if state else 'mouseup'
            try:
                subprocess.Popen(
                    ['xdotool', action, str(xbtn)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
        if state:
            self._buttons_pressed.add(linux_button)
        else:
            self._buttons_pressed.discard(linux_button)

    def scroll(self, dx: int, dy: int):
        if self._has_xdotool:
            # xdotool click 4=scroll up, 5=scroll down, 6=left, 7=right
            if dy > 0:
                btn = '4'
            elif dy < 0:
                btn = '5'
            elif dx > 0:
                btn = '7'
            elif dx < 0:
                btn = '6'
            else:
                return
            try:
                subprocess.Popen(
                    ['xdotool', 'click', btn],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def key_event(self, linux_keycode: int, state: int):
        keysym = self._EVDEV_TO_XKEYSYM.get(linux_keycode)
        if not keysym:
            return
        if self._has_xdotool:
            action = 'keydown' if state in (1, 2) else 'keyup'
            try:
                subprocess.Popen(
                    ['xdotool', action, keysym],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def reset_modifiers(self):
        for keysym in ['Shift_L', 'Shift_R', 'Control_L', 'Control_R',
                       'Alt_L', 'Alt_R', 'Super_L', 'Super_R']:
            if self._has_xdotool:
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
