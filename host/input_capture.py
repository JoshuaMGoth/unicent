"""
Cross-platform input capture for UniCent host.

Reads mouse and keyboard events from the local system.
- Linux:   evdev (/dev/input/event*)
- macOS:   Quartz CGEventTap
- Windows: ctypes user32 hooks (SetWindowsHookEx)

Supports exclusive grab (when sending events to remote) and
passthrough (when controlling local machine).
"""

import os
import sys
import struct
import select
import threading
import logging
import platform
from typing import Callable, List, Optional, Set

log = logging.getLogger(__name__)

_SYSTEM = platform.system()

# ────────────────────────────────────────────────────────────
# Event types / constants (platform-neutral, evdev-compatible)
# ────────────────────────────────────────────────────────────
EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03

REL_X = 0x00
REL_Y = 0x01
REL_WHEEL = 0x08
REL_HWHEEL = 0x06
REL_WHEEL_HI_RES = 0x0B
REL_HWHEEL_HI_RES = 0x0C

KEY_RELEASE = 0
KEY_PRESS = 1
KEY_REPEAT = 2

# evdev event struct (64-bit Linux)
EVENT_FORMAT = 'llHHi'
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)


# ────────────────────────────────────────────────────────────
# Linux evdev helpers
# ────────────────────────────────────────────────────────────

if _SYSTEM == 'Linux':
    import fcntl
    EVIOCGRAB = 0x40044590

    def find_input_devices() -> dict:
        """Find keyboard and mouse input devices on Linux."""
        devices = {'keyboards': [], 'mice': [], 'all': []}
        input_dir = '/dev/input'
        if not os.path.exists(input_dir):
            log.error(f"{input_dir} does not exist")
            return devices
        for entry in sorted(os.listdir(input_dir)):
            if not entry.startswith('event'):
                continue
            path = os.path.join(input_dir, entry)
            try:
                caps = _get_device_capabilities(path)
                if caps is None:
                    continue
                device_info = {
                    'path': path,
                    'name': _get_device_name(path),
                    'caps': caps,
                }
                has_keys = EV_KEY in caps
                has_rel = EV_REL in caps
                if has_rel and has_keys:
                    devices['mice'].append(device_info)
                    devices['all'].append(device_info)
                elif has_keys and not has_rel:
                    key_caps = caps.get(EV_KEY, set())
                    if any(k >= 1 and k <= 83 for k in key_caps):
                        devices['keyboards'].append(device_info)
                        devices['all'].append(device_info)
            except (PermissionError, OSError):
                continue
        log.info(f"Found {len(devices['keyboards'])} keyboards, {len(devices['mice'])} mice")
        for d in devices['keyboards']:
            log.info(f"  Keyboard: {d['name']} ({d['path']})")
        for d in devices['mice']:
            log.info(f"  Mouse: {d['name']} ({d['path']})")
        return devices

    def _get_device_name(path: str) -> str:
        try:
            import ctypes
            name_buf = ctypes.create_string_buffer(256)
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            try:
                EVIOCGNAME = 0x80004506 | (256 << 16)
                fcntl.ioctl(fd, EVIOCGNAME, name_buf)
                return name_buf.value.decode('utf-8', errors='replace').strip()
            finally:
                os.close(fd)
        except Exception:
            return os.path.basename(path)

    def _get_device_capabilities(path: str):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            try:
                caps = {}
                ev_bits = bytearray(64)
                EVIOCGBIT_0 = 0x80404520
                fcntl.ioctl(fd, EVIOCGBIT_0, ev_bits)
                for ev_type in range(min(32, len(ev_bits) * 8)):
                    byte_idx = ev_type // 8
                    bit_idx = ev_type % 8
                    if byte_idx < len(ev_bits) and (ev_bits[byte_idx] >> bit_idx) & 1:
                        code_bits = bytearray(128)
                        EVIOCGBIT_TYPE = (2 << 30) | (128 << 16) | (ord('E') << 8) | (0x20 + ev_type)
                        try:
                            fcntl.ioctl(fd, EVIOCGBIT_TYPE, code_bits)
                            codes = set()
                            for code in range(min(1024, len(code_bits) * 8)):
                                bi = code // 8
                                bii = code % 8
                                if bi < len(code_bits) and (code_bits[bi] >> bii) & 1:
                                    codes.add(code)
                            caps[ev_type] = codes
                        except OSError:
                            caps[ev_type] = set()
                return caps
            finally:
                os.close(fd)
        except (PermissionError, OSError):
            return None

elif _SYSTEM == 'Darwin':
    def find_input_devices() -> dict:
        """On macOS, we use CGEventTap — no /dev/input enumeration needed."""
        return {'keyboards': [{'path': 'CGEventTap', 'name': 'System HID'}],
                'mice': [{'path': 'CGEventTap', 'name': 'System HID'}],
                'all': [{'path': 'CGEventTap', 'name': 'System HID'}]}

elif _SYSTEM == 'Windows':
    def find_input_devices() -> dict:
        """On Windows we use low-level hooks — no enumeration needed."""
        return {'keyboards': [{'path': 'WinHook', 'name': 'System HID'}],
                'mice': [{'path': 'WinHook', 'name': 'System HID'}],
                'all': [{'path': 'WinHook', 'name': 'System HID'}]}
else:
    def find_input_devices() -> dict:
        return {'keyboards': [], 'mice': [], 'all': []}


# ────────────────────────────────────────────────────────────
# Linux evdev InputCapture
# ────────────────────────────────────────────────────────────

class _LinuxInputCapture:
    """Captures input events via Linux evdev."""

    def __init__(self):
        self._fds: dict = {}
        self._grabbed: Set[int] = set()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.on_mouse_move: Optional[Callable] = None
        self.on_mouse_button: Optional[Callable] = None
        self.on_mouse_scroll: Optional[Callable] = None
        self.on_key_event: Optional[Callable] = None
        self.on_syn: Optional[Callable] = None
        self._rel_x = 0
        self._rel_y = 0
        self._scroll_x = 0
        self._scroll_y = 0

    def open_devices(self, device_paths: List[str]) -> int:
        opened = 0
        for path in device_paths:
            try:
                f = open(path, 'rb')
                fd = f.fileno()
                import fcntl as _fcntl
                flags = _fcntl.fcntl(fd, _fcntl.F_GETFL)
                _fcntl.fcntl(fd, _fcntl.F_SETFL, flags | os.O_NONBLOCK)
                self._fds[fd] = {'path': path, 'file': f}
                opened += 1
                log.info(f"Opened input device: {path}")
            except (PermissionError, OSError) as e:
                log.error(f"Cannot open {path}: {e}")
        return opened

    def grab(self):
        with self._lock:
            for fd, info in self._fds.items():
                if fd not in self._grabbed:
                    try:
                        fcntl.ioctl(fd, EVIOCGRAB, 1)
                        self._grabbed.add(fd)
                        log.debug(f"Grabbed {info['path']}")
                    except OSError as e:
                        log.error(f"Cannot grab {info['path']}: {e}")

    def ungrab(self):
        with self._lock:
            for fd in list(self._grabbed):
                try:
                    fcntl.ioctl(fd, EVIOCGRAB, 0)
                    self._grabbed.discard(fd)
                except OSError:
                    self._grabbed.discard(fd)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        log.info("Input capture started (Linux evdev)")

    def stop(self):
        self._running = False
        self.ungrab()
        if self._thread:
            self._thread.join(timeout=3)
        for fd, info in self._fds.items():
            try:
                info['file'].close()
            except Exception:
                pass
        self._fds.clear()
        log.info("Input capture stopped")

    def _read_loop(self):
        import time as _time
        while self._running:
            if not self._fds:
                _time.sleep(0.1)
                continue
            try:
                readable, _, _ = select.select(list(self._fds.keys()), [], [], 0.1)
            except (ValueError, OSError):
                continue
            for fd in readable:
                self._read_device(fd)

    def _read_device(self, fd: int):
        try:
            while True:
                data = os.read(fd, EVENT_SIZE * 64)
                if not data:
                    break
                offset = 0
                while offset + EVENT_SIZE <= len(data):
                    ev_sec, ev_usec, ev_type, ev_code, ev_value = struct.unpack_from(
                        EVENT_FORMAT, data, offset)
                    offset += EVENT_SIZE
                    self._handle_event(ev_type, ev_code, ev_value)
        except BlockingIOError:
            pass
        except OSError as e:
            if e.errno == 19:
                log.warning(f"Device removed: {self._fds.get(fd, {}).get('path', fd)}")
                self._grabbed.discard(fd)
                info = self._fds.pop(fd, None)
                if info:
                    try:
                        info['file'].close()
                    except Exception:
                        pass

    def _handle_event(self, ev_type: int, ev_code: int, ev_value: int):
        if ev_type == EV_REL:
            if ev_code == REL_X:
                self._rel_x += ev_value
            elif ev_code == REL_Y:
                self._rel_y += ev_value
            elif ev_code in (REL_WHEEL, REL_WHEEL_HI_RES):
                self._scroll_y += ev_value
            elif ev_code in (REL_HWHEEL, REL_HWHEEL_HI_RES):
                self._scroll_x += ev_value
        elif ev_type == EV_KEY:
            if 0x110 <= ev_code <= 0x117:
                if self.on_mouse_button:
                    self.on_mouse_button(ev_code, ev_value)
            else:
                if self.on_key_event:
                    self.on_key_event(ev_code, ev_value)
        elif ev_type == EV_SYN:
            if (self._rel_x or self._rel_y) and self.on_mouse_move:
                self.on_mouse_move(self._rel_x, self._rel_y)
            if (self._scroll_x or self._scroll_y) and self.on_mouse_scroll:
                self.on_mouse_scroll(self._scroll_x, self._scroll_y)
            self._rel_x = self._rel_y = self._scroll_x = self._scroll_y = 0
            if self.on_syn:
                self.on_syn()


# ────────────────────────────────────────────────────────────
# macOS CGEventTap InputCapture
# ────────────────────────────────────────────────────────────

class _MacOSInputCapture:
    """Captures input events via macOS CGEventTap."""

    # Linux evdev button codes for compatibility
    _BTN_LEFT = 272
    _BTN_RIGHT = 273
    _BTN_MIDDLE = 274

    # macOS virtual key code → evdev key code (reverse of keymap)
    _MACOS_TO_EVDEV = {}

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._tap = None
        self._grabbed = False
        self.on_mouse_move: Optional[Callable] = None
        self.on_mouse_button: Optional[Callable] = None
        self.on_mouse_scroll: Optional[Callable] = None
        self.on_key_event: Optional[Callable] = None
        self.on_syn: Optional[Callable] = None

        # Build reverse keymap
        try:
            from shared.keymap import MACOS_TO_LINUX
            self._MACOS_TO_EVDEV = dict(MACOS_TO_LINUX)
        except Exception:
            pass

    def open_devices(self, device_paths: List[str]) -> int:
        return 1  # CGEventTap handles all devices

    def grab(self):
        self._grabbed = True
        log.debug("Grab enabled (CGEventTap will suppress events)")

    def ungrab(self):
        self._grabbed = False
        log.debug("Grab disabled (CGEventTap passthrough)")

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._tap_loop, daemon=True)
        self._thread.start()
        log.info("Input capture started (macOS CGEventTap)")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        log.info("Input capture stopped")

    def _tap_loop(self):
        try:
            import Quartz
            from Quartz import (
                CGEventTapCreate, CGEventTapEnable,
                kCGSessionEventTap, kCGHeadInsertEventTap,
                kCGEventTapOptionDefault,
                kCGEventMouseMoved, kCGEventLeftMouseDown, kCGEventLeftMouseUp,
                kCGEventRightMouseDown, kCGEventRightMouseUp,
                kCGEventOtherMouseDown, kCGEventOtherMouseUp,
                kCGEventScrollWheel, kCGEventKeyDown, kCGEventKeyUp,
                kCGEventFlagsChanged, kCGEventLeftMouseDragged,
                kCGEventRightMouseDragged, kCGEventOtherMouseDragged,
                CGEventGetIntegerValueField,
                kCGMouseEventDeltaX, kCGMouseEventDeltaY,
                kCGMouseEventButtonNumber,
                kCGScrollWheelEventDeltaAxis1, kCGScrollWheelEventDeltaAxis2,
                kCGKeyboardEventKeycode,
            )
            import AppKit

            mask = (
                (1 << kCGEventMouseMoved) |
                (1 << kCGEventLeftMouseDown) | (1 << kCGEventLeftMouseUp) |
                (1 << kCGEventRightMouseDown) | (1 << kCGEventRightMouseUp) |
                (1 << kCGEventOtherMouseDown) | (1 << kCGEventOtherMouseUp) |
                (1 << kCGEventScrollWheel) |
                (1 << kCGEventKeyDown) | (1 << kCGEventKeyUp) |
                (1 << kCGEventFlagsChanged) |
                (1 << kCGEventLeftMouseDragged) |
                (1 << kCGEventRightMouseDragged) |
                (1 << kCGEventOtherMouseDragged)
            )

            def _callback(proxy, event_type, event, refcon):
                try:
                    suppress = self._handle_cg_event(event_type, event, Quartz)
                    if self._grabbed and suppress:
                        return None  # Suppress the event
                except Exception:
                    pass
                return event

            self._tap = CGEventTapCreate(
                kCGSessionEventTap,
                kCGHeadInsertEventTap,
                kCGEventTapOptionDefault,
                mask,
                _callback,
                None,
            )
            if not self._tap:
                log.error("Failed to create CGEventTap — check Accessibility permissions")
                return

            run_loop_source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
            Quartz.CFRunLoopAddSource(
                Quartz.CFRunLoopGetCurrent(),
                run_loop_source,
                Quartz.kCFRunLoopCommonModes,
            )
            CGEventTapEnable(self._tap, True)

            # Run the loop
            while self._running:
                Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 0.1, False)

        except ImportError:
            log.error("Quartz framework not available for input capture")
        except Exception as e:
            log.error(f"CGEventTap error: {e}", exc_info=True)

    def _handle_cg_event(self, event_type, event, Q):
        """Handle a CGEvent. Returns True if event should be suppressed when grabbed."""
        from Quartz import (
            kCGEventMouseMoved, kCGEventLeftMouseDown, kCGEventLeftMouseUp,
            kCGEventRightMouseDown, kCGEventRightMouseUp,
            kCGEventOtherMouseDown, kCGEventOtherMouseUp,
            kCGEventScrollWheel, kCGEventKeyDown, kCGEventKeyUp,
            kCGEventFlagsChanged,
            kCGEventLeftMouseDragged, kCGEventRightMouseDragged,
            kCGEventOtherMouseDragged,
            CGEventGetIntegerValueField,
            kCGMouseEventDeltaX, kCGMouseEventDeltaY,
            kCGMouseEventButtonNumber,
            kCGScrollWheelEventDeltaAxis1, kCGScrollWheelEventDeltaAxis2,
            kCGKeyboardEventKeycode,
        )

        if event_type in (kCGEventMouseMoved, kCGEventLeftMouseDragged,
                          kCGEventRightMouseDragged, kCGEventOtherMouseDragged):
            dx = CGEventGetIntegerValueField(event, kCGMouseEventDeltaX)
            dy = CGEventGetIntegerValueField(event, kCGMouseEventDeltaY)
            if (dx or dy) and self.on_mouse_move:
                self.on_mouse_move(dx, dy)
            return True

        elif event_type in (kCGEventLeftMouseDown, kCGEventLeftMouseUp):
            state = 1 if event_type == kCGEventLeftMouseDown else 0
            if self.on_mouse_button:
                self.on_mouse_button(self._BTN_LEFT, state)
            return True

        elif event_type in (kCGEventRightMouseDown, kCGEventRightMouseUp):
            state = 1 if event_type == kCGEventRightMouseDown else 0
            if self.on_mouse_button:
                self.on_mouse_button(self._BTN_RIGHT, state)
            return True

        elif event_type in (kCGEventOtherMouseDown, kCGEventOtherMouseUp):
            state = 1 if event_type == kCGEventOtherMouseDown else 0
            mac_btn = CGEventGetIntegerValueField(event, kCGMouseEventButtonNumber)
            evdev_btn = {0: 272, 1: 273, 2: 274, 3: 275, 4: 276}.get(mac_btn, 274)
            if self.on_mouse_button:
                self.on_mouse_button(evdev_btn, state)
            return True

        elif event_type == kCGEventScrollWheel:
            dy = CGEventGetIntegerValueField(event, kCGScrollWheelEventDeltaAxis1)
            dx = CGEventGetIntegerValueField(event, kCGScrollWheelEventDeltaAxis2)
            if (dx or dy) and self.on_mouse_scroll:
                self.on_mouse_scroll(dx, dy)
            return True

        elif event_type in (kCGEventKeyDown, kCGEventKeyUp):
            mac_keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            evdev_keycode = self._MACOS_TO_EVDEV.get(mac_keycode, -1)
            if evdev_keycode >= 0 and self.on_key_event:
                state = 1 if event_type == kCGEventKeyDown else 0
                self.on_key_event(evdev_keycode, state)
            return True

        elif event_type == kCGEventFlagsChanged:
            mac_keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            evdev_keycode = self._MACOS_TO_EVDEV.get(mac_keycode, -1)
            if evdev_keycode >= 0 and self.on_key_event:
                # For flags changed, determine press/release from flags
                # Simplified: treat as press (will get another event on release)
                self.on_key_event(evdev_keycode, 1)
            return True

        return False


# ────────────────────────────────────────────────────────────
# Windows low-level hooks InputCapture
# ────────────────────────────────────────────────────────────

class _WindowsInputCapture:
    """Captures input via Windows low-level hooks."""

    _BTN_LEFT = 272
    _BTN_RIGHT = 273
    _BTN_MIDDLE = 274

    # Windows VK → evdev keycode mapping
    _VK_TO_EVDEV = {}

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._grabbed = False
        self._hooks = []
        self.on_mouse_move: Optional[Callable] = None
        self.on_mouse_button: Optional[Callable] = None
        self.on_mouse_scroll: Optional[Callable] = None
        self.on_key_event: Optional[Callable] = None
        self.on_syn: Optional[Callable] = None
        self._last_x = 0
        self._last_y = 0

        # Build VK → evdev mapping
        self._build_vk_map()

    def _build_vk_map(self):
        """Map Windows virtual-key codes to Linux evdev codes."""
        self._VK_TO_EVDEV = {
            0x1B: 1,    # VK_ESCAPE -> KEY_ESC
            0x31: 2, 0x32: 3, 0x33: 4, 0x34: 5, 0x35: 6,  # 1-5
            0x36: 7, 0x37: 8, 0x38: 9, 0x39: 10, 0x30: 11, # 6-0
            0xBD: 12, 0xBB: 13, 0x08: 14,  # -, =, Backspace
            0x09: 15,   # Tab
            0x51: 16, 0x57: 17, 0x45: 18, 0x52: 19, 0x54: 20,
            0x59: 21, 0x55: 22, 0x49: 23, 0x4F: 24, 0x50: 25,
            0xDB: 26, 0xDD: 27, 0x0D: 28,  # [, ], Enter
            0xA2: 29,   # VK_LCONTROL
            0x41: 30, 0x53: 31, 0x44: 32, 0x46: 33, 0x47: 34,
            0x48: 35, 0x4A: 36, 0x4B: 37, 0x4C: 38,
            0xBA: 39, 0xDE: 40, 0xC0: 41,  # ;, ', `
            0xA0: 42,   # VK_LSHIFT
            0xDC: 43,   # backslash
            0x5A: 44, 0x58: 45, 0x43: 46, 0x56: 47, 0x42: 48,
            0x4E: 49, 0x4D: 50, 0xBC: 51, 0xBE: 52, 0xBF: 53,
            0xA1: 54,   # VK_RSHIFT
            0x6A: 55,   # numpad *
            0xA4: 56,   # VK_LMENU (Alt)
            0x20: 57,   # Space
            0x14: 58,   # Caps Lock
            0x70: 59, 0x71: 60, 0x72: 61, 0x73: 62, 0x74: 63,
            0x75: 64, 0x76: 65, 0x77: 66, 0x78: 67, 0x79: 68,
            0x7A: 87, 0x7B: 88,  # F1-F12
            0xA3: 97,   # VK_RCONTROL
            0xA5: 100,  # VK_RMENU (RAlt)
            0x24: 102,  # Home
            0x26: 103,  # Up
            0x21: 104,  # PageUp
            0x25: 105,  # Left
            0x27: 106,  # Right
            0x23: 107,  # End
            0x28: 108,  # Down
            0x22: 109,  # PageDown
            0x2D: 110,  # Insert
            0x2E: 111,  # Delete
            0x5B: 125,  # VK_LWIN
            0x5C: 126,  # VK_RWIN
        }

    def open_devices(self, device_paths: List[str]) -> int:
        return 1

    def grab(self):
        self._grabbed = True
        log.debug("Grab enabled (hooks will suppress events)")

    def ungrab(self):
        self._grabbed = False
        log.debug("Grab disabled")

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._hook_loop, daemon=True)
        self._thread.start()
        log.info("Input capture started (Windows hooks)")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        log.info("Input capture stopped")

    def _hook_loop(self):
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32

            WH_MOUSE_LL = 14
            WH_KEYBOARD_LL = 13

            # Mouse hook callback type
            HOOKPROC = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_int,
                                        wintypes.WPARAM, wintypes.LPARAM)

            WM_MOUSEMOVE = 0x0200
            WM_LBUTTONDOWN = 0x0201
            WM_LBUTTONUP = 0x0202
            WM_RBUTTONDOWN = 0x0204
            WM_RBUTTONUP = 0x0205
            WM_MBUTTONDOWN = 0x0207
            WM_MBUTTONUP = 0x0208
            WM_MOUSEWHEEL = 0x020A
            WM_MOUSEHWHEEL = 0x020E
            WM_KEYDOWN = 0x0100
            WM_KEYUP = 0x0101
            WM_SYSKEYDOWN = 0x0104
            WM_SYSKEYUP = 0x0105

            class MSLLHOOKSTRUCT(ctypes.Structure):
                _fields_ = [
                    ("pt", wintypes.POINT),
                    ("mouseData", wintypes.DWORD),
                    ("flags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
                ]

            class KBDLLHOOKSTRUCT(ctypes.Structure):
                _fields_ = [
                    ("vkCode", wintypes.DWORD),
                    ("scanCode", wintypes.DWORD),
                    ("flags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
                ]

            # Initialize last position
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            self._last_x = pt.x
            self._last_y = pt.y

            @HOOKPROC
            def mouse_proc(nCode, wParam, lParam):
                if nCode >= 0:
                    ms = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                    suppress = self._handle_mouse(wParam, ms)
                    if self._grabbed and suppress:
                        return 1
                return user32.CallNextHookEx(None, nCode, wParam, lParam)

            @HOOKPROC
            def kb_proc(nCode, wParam, lParam):
                if nCode >= 0:
                    kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    suppress = self._handle_keyboard(wParam, kb)
                    if self._grabbed and suppress:
                        return 1
                return user32.CallNextHookEx(None, nCode, wParam, lParam)

            mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_proc, None, 0)
            kb_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, kb_proc, None, 0)

            msg = wintypes.MSG()
            while self._running:
                if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    import time
                    time.sleep(0.001)

            if mouse_hook:
                user32.UnhookWindowsHookEx(mouse_hook)
            if kb_hook:
                user32.UnhookWindowsHookEx(kb_hook)

        except Exception as e:
            log.error(f"Windows hook error: {e}", exc_info=True)

    def _handle_mouse(self, wParam, ms) -> bool:
        WM_MOUSEMOVE = 0x0200
        WM_LBUTTONDOWN = 0x0201
        WM_LBUTTONUP = 0x0202
        WM_RBUTTONDOWN = 0x0204
        WM_RBUTTONUP = 0x0205
        WM_MBUTTONDOWN = 0x0207
        WM_MBUTTONUP = 0x0208
        WM_MOUSEWHEEL = 0x020A
        WM_MOUSEHWHEEL = 0x020E

        if wParam == WM_MOUSEMOVE:
            dx = ms.pt.x - self._last_x
            dy = ms.pt.y - self._last_y
            self._last_x = ms.pt.x
            self._last_y = ms.pt.y
            if (dx or dy) and self.on_mouse_move:
                self.on_mouse_move(dx, dy)
            return True
        elif wParam == WM_LBUTTONDOWN:
            if self.on_mouse_button:
                self.on_mouse_button(self._BTN_LEFT, 1)
            return True
        elif wParam == WM_LBUTTONUP:
            if self.on_mouse_button:
                self.on_mouse_button(self._BTN_LEFT, 0)
            return True
        elif wParam == WM_RBUTTONDOWN:
            if self.on_mouse_button:
                self.on_mouse_button(self._BTN_RIGHT, 1)
            return True
        elif wParam == WM_RBUTTONUP:
            if self.on_mouse_button:
                self.on_mouse_button(self._BTN_RIGHT, 0)
            return True
        elif wParam == WM_MBUTTONDOWN:
            if self.on_mouse_button:
                self.on_mouse_button(self._BTN_MIDDLE, 1)
            return True
        elif wParam == WM_MBUTTONUP:
            if self.on_mouse_button:
                self.on_mouse_button(self._BTN_MIDDLE, 0)
            return True
        elif wParam == WM_MOUSEWHEEL:
            wheel_delta = (ms.mouseData >> 16) & 0xFFFF
            if wheel_delta > 32767:
                wheel_delta -= 65536
            dy = 1 if wheel_delta > 0 else -1
            if self.on_mouse_scroll:
                self.on_mouse_scroll(0, dy)
            return True
        elif wParam == WM_MOUSEHWHEEL:
            wheel_delta = (ms.mouseData >> 16) & 0xFFFF
            if wheel_delta > 32767:
                wheel_delta -= 65536
            dx = 1 if wheel_delta > 0 else -1
            if self.on_mouse_scroll:
                self.on_mouse_scroll(dx, 0)
            return True
        return False

    def _handle_keyboard(self, wParam, kb) -> bool:
        WM_KEYDOWN = 0x0100
        WM_KEYUP = 0x0101
        WM_SYSKEYDOWN = 0x0104
        WM_SYSKEYUP = 0x0105

        vk = kb.vkCode
        evdev_code = self._VK_TO_EVDEV.get(vk, -1)
        if evdev_code < 0:
            return False
        if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            state = 1
        elif wParam in (WM_KEYUP, WM_SYSKEYUP):
            state = 0
        else:
            return False
        if self.on_key_event:
            self.on_key_event(evdev_code, state)
        return True


# ────────────────────────────────────────────────────────────
# HotkeyDetector (platform-neutral)
# ────────────────────────────────────────────────────────────

class HotkeyDetector:
    """Detects keyboard shortcuts from a stream of key events."""

    def __init__(self):
        self._modifiers: Set[int] = set()
        self._callbacks: dict = {}
        from shared.keymap import CTRL_KEYS, ALT_KEYS, SHIFT_KEYS, META_KEYS
        self.CTRL_KEYS = CTRL_KEYS
        self.ALT_KEYS = ALT_KEYS
        self.SHIFT_KEYS = SHIFT_KEYS
        self.META_KEYS = META_KEYS
        self.ALL_MODS = CTRL_KEYS | ALT_KEYS | SHIFT_KEYS | META_KEYS

    def register(self, name: str, modifiers: set, key: int, callback: Callable):
        self._callbacks[name] = {
            'modifiers': modifiers,
            'key': key,
            'callback': callback,
        }

    def process_key(self, keycode: int, state: int) -> bool:
        if keycode in self.ALL_MODS:
            if state == KEY_PRESS:
                self._modifiers.add(keycode)
            elif state == KEY_RELEASE:
                self._modifiers.discard(keycode)
            return False
        if state != KEY_PRESS:
            return False
        for name, info in self._callbacks.items():
            if info['key'] != keycode:
                continue
            all_satisfied = True
            for mod_set in info['modifiers']:
                if not (self._modifiers & mod_set):
                    all_satisfied = False
                    break
            if all_satisfied:
                try:
                    info['callback']()
                except Exception as e:
                    log.error(f"Hotkey callback error ({name}): {e}")
                return True
        return False

    def reset(self):
        self._modifiers.clear()


# ────────────────────────────────────────────────────────────
# Factory: select the right implementation
# ────────────────────────────────────────────────────────────

def InputCapture():
    """Factory: returns the platform-appropriate InputCapture instance."""
    if _SYSTEM == 'Linux':
        return _LinuxInputCapture()
    elif _SYSTEM == 'Darwin':
        return _MacOSInputCapture()
    elif _SYSTEM == 'Windows':
        return _WindowsInputCapture()
    else:
        raise RuntimeError(f"Unsupported platform: {_SYSTEM}")
