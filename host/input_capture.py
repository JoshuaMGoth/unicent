"""
Linux input capture using evdev.

Reads mouse and keyboard events from /dev/input/event* devices.
Supports exclusive grab (when sending events to remote) and
passthrough (when controlling local machine).

Works in minimal environments (Arch installer) without X11/Wayland.
"""

import os
import struct
import select
import threading
import logging
from typing import Callable, List, Optional, Set

log = logging.getLogger(__name__)

# evdev event struct format: time_sec(long), time_usec(long), type(ushort), code(ushort), value(int)
# On 64-bit: struct input_event { struct timeval { long, long }; __u16 type; __u16 code; __s32 value; }
EVENT_FORMAT = 'llHHi'
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)

# Event types
EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03

# Relative axes
REL_X = 0x00
REL_Y = 0x01
REL_WHEEL = 0x08
REL_HWHEEL = 0x06
REL_WHEEL_HI_RES = 0x0B
REL_HWHEEL_HI_RES = 0x0C

# Key/button states
KEY_RELEASE = 0
KEY_PRESS = 1
KEY_REPEAT = 2

# EVIOCGRAB ioctl number
import fcntl
EVIOCGRAB = 0x40044590


def find_input_devices() -> dict:
    """Find keyboard and mouse input devices.

    Returns dict with keys 'keyboards' and 'mice', each containing
    a list of device paths.
    """
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

            # Classify device
            has_keys = EV_KEY in caps
            has_rel = EV_REL in caps

            if has_rel and has_keys:
                # Has relative axes and buttons -> likely a mouse
                devices['mice'].append(device_info)
                devices['all'].append(device_info)
            elif has_keys and not has_rel:
                # Has keys but no relative axes -> likely a keyboard
                # Check if it has actual letter keys (not just media keys)
                key_caps = caps.get(EV_KEY, set())
                if any(k >= 1 and k <= 83 for k in key_caps):
                    devices['keyboards'].append(device_info)
                    devices['all'].append(device_info)

        except (PermissionError, OSError) as e:
            log.debug(f"Cannot access {path}: {e}")
            continue

    log.info(f"Found {len(devices['keyboards'])} keyboards, {len(devices['mice'])} mice")
    for d in devices['keyboards']:
        log.info(f"  Keyboard: {d['name']} ({d['path']})")
    for d in devices['mice']:
        log.info(f"  Mouse: {d['name']} ({d['path']})")

    return devices


def _get_device_name(path: str) -> str:
    """Get the human-readable name of an input device."""
    try:
        # EVIOCGNAME ioctl
        import ctypes
        name_buf = ctypes.create_string_buffer(256)
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            # EVIOCGNAME(len) = _IOC(_IOC_READ, 'E', 0x06, len)
            EVIOCGNAME = 0x80004506 | (256 << 16)
            fcntl.ioctl(fd, EVIOCGNAME, name_buf)
            return name_buf.value.decode('utf-8', errors='replace').strip()
        finally:
            os.close(fd)
    except Exception:
        return os.path.basename(path)


def _get_device_capabilities(path: str) -> Optional[dict]:
    """Get the capabilities (event types and codes) of an input device."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            caps = {}
            # EVIOCGBIT(ev_type, len) = _IOC(_IOC_READ, 'E', 0x20 + ev_type, len)
            # First get supported event types
            ev_bits = bytearray(64)
            EVIOCGBIT_0 = 0x80404520
            fcntl.ioctl(fd, EVIOCGBIT_0, ev_bits)

            for ev_type in range(min(32, len(ev_bits) * 8)):
                byte_idx = ev_type // 8
                bit_idx = ev_type % 8
                if byte_idx < len(ev_bits) and (ev_bits[byte_idx] >> bit_idx) & 1:
                    # Get codes for this event type
                    code_bits = bytearray(128)
                    EVIOCGBIT_TYPE = 0x80804520 | ((ev_type & 0xFF) << 0)
                    # Recalculate properly
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


class InputCapture:
    """Captures input events from Linux evdev devices.

    Supports:
    - Reading keyboard and mouse events
    - Exclusive grab (prevents events from reaching local system)
    - Callback-based event notification
    """

    def __init__(self):
        self._fds: dict = {}          # fd -> {'path': str, 'file': file}
        self._grabbed: Set[int] = set()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Callbacks
        self.on_mouse_move: Optional[Callable] = None     # (dx, dy)
        self.on_mouse_button: Optional[Callable] = None   # (button, state)
        self.on_mouse_scroll: Optional[Callable] = None   # (dx, dy)
        self.on_key_event: Optional[Callable] = None      # (keycode, state)
        self.on_syn: Optional[Callable] = None            # ()

        # Accumulated relative motion (batched per SYN)
        self._rel_x = 0
        self._rel_y = 0
        self._scroll_x = 0
        self._scroll_y = 0

    def open_devices(self, device_paths: List[str]) -> int:
        """Open the specified input devices. Returns number successfully opened."""
        opened = 0
        for path in device_paths:
            try:
                f = open(path, 'rb')
                fd = f.fileno()
                # Set non-blocking
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
        """Grab all devices exclusively (prevent local processing)."""
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
        """Release exclusive grab on all devices."""
        with self._lock:
            for fd in list(self._grabbed):
                try:
                    fcntl.ioctl(fd, EVIOCGRAB, 0)
                    self._grabbed.discard(fd)
                    info = self._fds.get(fd, {})
                    log.debug(f"Ungrabbed {info.get('path', fd)}")
                except OSError:
                    self._grabbed.discard(fd)

    def start(self):
        """Start reading events in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        log.info("Input capture started")

    def stop(self):
        """Stop reading events and release all devices."""
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
        """Main event reading loop."""
        while self._running:
            if not self._fds:
                import time
                time.sleep(0.1)
                continue

            try:
                readable, _, _ = select.select(
                    list(self._fds.keys()), [], [], 0.1
                )
            except (ValueError, OSError):
                continue

            for fd in readable:
                self._read_device(fd)

    def _read_device(self, fd: int):
        """Read and process events from a single device."""
        try:
            while True:
                data = os.read(fd, EVENT_SIZE * 64)  # Read batch
                if not data:
                    break
                offset = 0
                while offset + EVENT_SIZE <= len(data):
                    ev_sec, ev_usec, ev_type, ev_code, ev_value = struct.unpack_from(
                        EVENT_FORMAT, data, offset
                    )
                    offset += EVENT_SIZE
                    self._handle_event(ev_type, ev_code, ev_value)
        except BlockingIOError:
            pass
        except OSError as e:
            if e.errno == 19:  # ENODEV - device removed
                log.warning(f"Device removed: {self._fds.get(fd, {}).get('path', fd)}")
                self._grabbed.discard(fd)
                info = self._fds.pop(fd, None)
                if info:
                    try:
                        info['file'].close()
                    except Exception:
                        pass

    def _handle_event(self, ev_type: int, ev_code: int, ev_value: int):
        """Process a single input event."""
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
            if ev_code >= 0x110 and ev_code <= 0x117:
                # Mouse button
                if self.on_mouse_button:
                    self.on_mouse_button(ev_code, ev_value)
            else:
                # Keyboard key
                if self.on_key_event:
                    self.on_key_event(ev_code, ev_value)

        elif ev_type == EV_SYN:
            # SYN_REPORT: flush accumulated motion
            if (self._rel_x or self._rel_y) and self.on_mouse_move:
                self.on_mouse_move(self._rel_x, self._rel_y)
            if (self._scroll_x or self._scroll_y) and self.on_mouse_scroll:
                self.on_mouse_scroll(self._scroll_x, self._scroll_y)
            self._rel_x = 0
            self._rel_y = 0
            self._scroll_x = 0
            self._scroll_y = 0
            if self.on_syn:
                self.on_syn()


class HotkeyDetector:
    """Detects keyboard shortcuts from a stream of key events.

    Tracks modifier state and fires callbacks when hotkey combos are detected.
    """

    def __init__(self):
        self._modifiers: Set[int] = set()  # Currently pressed modifier keycodes
        self._callbacks: dict = {}

        # Import key codes
        from shared.keymap import (
            CTRL_KEYS, ALT_KEYS, SHIFT_KEYS, META_KEYS,
            KEY_S, KEY_T, KEY_1, KEY_2, KEY_3, KEY_4, KEY_5,
            KEY_SCROLLLOCK, KEY_C,
        )
        self.CTRL_KEYS = CTRL_KEYS
        self.ALT_KEYS = ALT_KEYS
        self.SHIFT_KEYS = SHIFT_KEYS
        self.META_KEYS = META_KEYS
        self.ALL_MODS = CTRL_KEYS | ALT_KEYS | SHIFT_KEYS | META_KEYS

    def register(self, name: str, modifiers: set, key: int, callback: Callable):
        """Register a hotkey combination.

        Args:
            name: Identifier for this hotkey.
            modifiers: Set of modifier type sets that must be active
                       e.g., {frozenset(CTRL_KEYS), frozenset(ALT_KEYS)}
            key: The non-modifier key code.
            callback: Function to call when hotkey is pressed.
        """
        self._callbacks[name] = {
            'modifiers': modifiers,
            'key': key,
            'callback': callback,
        }

    def process_key(self, keycode: int, state: int) -> bool:
        """Process a key event. Returns True if a hotkey was triggered.

        Args:
            keycode: Linux evdev key code.
            state: 0=release, 1=press, 2=repeat.
        """
        # Track modifier state
        if keycode in self.ALL_MODS:
            if state == KEY_PRESS:
                self._modifiers.add(keycode)
            elif state == KEY_RELEASE:
                self._modifiers.discard(keycode)
            return False

        # Only trigger on key press (not repeat or release)
        if state != KEY_PRESS:
            return False

        # Check each registered hotkey
        for name, info in self._callbacks.items():
            if info['key'] != keycode:
                continue

            # Check all required modifier groups are satisfied
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
        """Reset modifier state."""
        self._modifiers.clear()
