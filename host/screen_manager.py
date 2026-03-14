"""
Virtual screen layout manager for the host — cross-platform.

Manages the spatial arrangement of all screens (host + clients)
in a unified virtual desktop. Handles edge detection for seamless
cursor transitions between machines.

Screen detection:
- Linux:   xrandr, /sys/class/drm, fbset
- macOS:   Quartz CGDisplayBounds
- Windows: ctypes user32 EnumDisplayMonitors
"""

import logging
import platform
import subprocess
from typing import List, Optional, Tuple
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

_SYSTEM = platform.system()


@dataclass
class Screen:
    """Represents a single physical monitor."""
    width: int
    height: int
    x: int = 0
    y: int = 0
    scale: float = 1.0
    name: str = ''

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def to_dict(self) -> dict:
        return {'width': self.width, 'height': self.height,
                'x': self.x, 'y': self.y, 'scale': self.scale, 'name': self.name}

    @staticmethod
    def from_dict(d: dict) -> 'Screen':
        return Screen(width=d['width'], height=d['height'],
                      x=d.get('x', 0), y=d.get('y', 0),
                      scale=d.get('scale', 1.0), name=d.get('name', ''))


@dataclass
class MachineScreens:
    """All screens belonging to a single machine."""
    machine_id: str
    screens: List[Screen] = field(default_factory=list)
    offset_x: int = 0
    offset_y: int = 0

    @property
    def total_width(self) -> int:
        if not self.screens:
            return 0
        return max(s.right for s in self.screens) - min(s.x for s in self.screens)

    @property
    def total_height(self) -> int:
        if not self.screens:
            return 0
        return max(s.bottom for s in self.screens) - min(s.y for s in self.screens)

    @property
    def left(self) -> int:
        return self.offset_x

    @property
    def right(self) -> int:
        return self.offset_x + self.total_width

    @property
    def top(self) -> int:
        return self.offset_y

    @property
    def bottom(self) -> int:
        return self.offset_y + self.total_height

    def contains_global(self, gx: int, gy: int) -> bool:
        lx = gx - self.offset_x
        ly = gy - self.offset_y
        return any(s.contains(lx, ly) for s in self.screens)

    def global_to_local(self, gx: int, gy: int) -> Tuple[int, int]:
        return gx - self.offset_x, gy - self.offset_y

    def local_to_global(self, lx: int, ly: int) -> Tuple[int, int]:
        return lx + self.offset_x, ly + self.offset_y


class ScreenLayout:
    """Manages the virtual screen layout across all machines."""

    def __init__(self, client_side: str = 'right'):
        self.machines: List[MachineScreens] = []
        self._cursor_x: int = 0
        self._cursor_y: int = 0
        self._active_machine: str = 'host'
        self._edge_margin: int = 1
        self.client_side: str = client_side

    def set_host_screens(self, screens: List[dict]):
        host_screens = [Screen.from_dict(s) for s in screens]
        self.machines = [m for m in self.machines if m.machine_id != 'host']
        ms = MachineScreens(machine_id='host', screens=host_screens)
        self.machines.insert(0, ms)
        self._recalculate_layout()
        self.init_cursor_at_host()
        log.info(f"Host screens set: {len(host_screens)} monitor(s)")

    def add_client_screens(self, client_id: str, screens: List[dict]):
        client_screens = [Screen.from_dict(s) for s in screens]
        self.machines = [m for m in self.machines if m.machine_id != client_id]
        ms = MachineScreens(machine_id=client_id, screens=client_screens)
        self.machines.append(ms)
        self._recalculate_layout()
        log.info(f"Client '{client_id}' screens set: {len(client_screens)} monitor(s)")

    def remove_client(self, client_id: str):
        self.machines = [m for m in self.machines if m.machine_id != client_id]
        self._recalculate_layout()
        if self._active_machine == client_id:
            self._active_machine = 'host'

    def _recalculate_layout(self):
        old_active_offset_x = 0
        old_active_offset_y = 0
        for m in self.machines:
            if m.machine_id == self._active_machine:
                old_active_offset_x = m.offset_x
                old_active_offset_y = m.offset_y
                break

        max_height = max((m.total_height for m in self.machines), default=0)

        if self.client_side == 'left':
            host = [m for m in self.machines if m.machine_id == 'host']
            clients = [m for m in self.machines if m.machine_id != 'host']
            ordered = list(reversed(clients)) + host
        else:
            ordered = list(self.machines)

        x_offset = 0
        for machine in ordered:
            machine.offset_x = x_offset
            machine.offset_y = (max_height - machine.total_height) // 2
            x_offset += machine.total_width

        for m in ordered:
            if m.machine_id == self._active_machine:
                delta_x = m.offset_x - old_active_offset_x
                delta_y = m.offset_y - old_active_offset_y
                if delta_x != 0 or delta_y != 0:
                    self._cursor_x += delta_x
                    self._cursor_y += delta_y
                    log.info(f"Cursor adjusted by ({delta_x},{delta_y}) "
                             f"to ({self._cursor_x},{self._cursor_y})")
                break

        layout_desc = ', '.join(
            f"{m.machine_id}({m.total_width}x{m.total_height}@{m.offset_x})"
            for m in ordered)
        log.info(f"Layout: {layout_desc}")

    def get_layout_info(self) -> list:
        return [
            {'machine_id': m.machine_id, 'offset_x': m.offset_x,
             'offset_y': m.offset_y, 'total_width': m.total_width,
             'total_height': m.total_height,
             'screens': [s.to_dict() for s in m.screens]}
            for m in self.machines
        ]

    @property
    def active_machine(self) -> str:
        return self._active_machine

    @property
    def cursor_position(self) -> Tuple[int, int]:
        return self._cursor_x, self._cursor_y

    def init_cursor_at_host(self, local_x: int = None, local_y: int = None):
        for m in self.machines:
            if m.machine_id == 'host':
                if local_x is not None and local_y is not None:
                    self._cursor_x = m.offset_x + local_x
                    self._cursor_y = m.offset_y + local_y
                else:
                    self._cursor_x = m.offset_x + m.total_width // 2
                    self._cursor_y = m.offset_y + m.total_height // 2
                self._active_machine = 'host'
                log.info(f"Cursor initialized at ({self._cursor_x}, {self._cursor_y}) on host")
                return

    def move_cursor(self, dx: int, dy: int) -> Optional[str]:
        new_x = self._cursor_x + dx
        new_y = self._cursor_y + dy
        total_width = sum(m.total_width for m in self.machines)
        max_height = max((m.total_height for m in self.machines), default=0)
        new_x = max(0, min(new_x, total_width - 1))
        new_y = max(0, min(new_y, max_height - 1))
        self._cursor_x = new_x
        self._cursor_y = new_y
        for machine in self.machines:
            if machine.left <= new_x < machine.right:
                if machine.machine_id != self._active_machine:
                    old = self._active_machine
                    self._active_machine = machine.machine_id
                    log.info(f"Cursor crossed: {old} -> {machine.machine_id}")
                    return machine.machine_id
                break
        return None

    def get_local_cursor(self, machine_id: Optional[str] = None) -> Tuple[int, int]:
        if machine_id is None:
            machine_id = self._active_machine
        for machine in self.machines:
            if machine.machine_id == machine_id:
                return machine.global_to_local(self._cursor_x, self._cursor_y)
        return 0, 0

    def set_cursor_for_machine(self, machine_id: str, edge: str = 'left',
                                position: int = -1):
        for machine in self.machines:
            if machine.machine_id != machine_id:
                continue
            if edge == 'left':
                self._cursor_x = machine.left
            elif edge == 'right':
                self._cursor_x = machine.right - 1
            elif edge == 'center':
                self._cursor_x = machine.left + machine.total_width // 2
            if position >= 0:
                self._cursor_y = machine.offset_y + position
            else:
                self._cursor_y = machine.offset_y + machine.total_height // 2
            self._active_machine = machine_id
            return

    def switch_to_next(self) -> str:
        if not self.machines:
            return self._active_machine
        current_idx = next(
            (i for i, m in enumerate(self.machines)
             if m.machine_id == self._active_machine), 0)
        next_idx = (current_idx + 1) % len(self.machines)
        target = self.machines[next_idx].machine_id
        self.set_cursor_for_machine(target, edge='center')
        return target

    def switch_to_index(self, index: int) -> Optional[str]:
        if 0 <= index < len(self.machines):
            target = self.machines[index].machine_id
            self.set_cursor_for_machine(target, edge='center')
            return target
        return None

    def get_machine_list(self) -> List[Tuple[int, str, bool]]:
        return [
            (i, m.machine_id, m.machine_id == self._active_machine)
            for i, m in enumerate(self.machines)
        ]


# ────────────────────────────────────────────────────────────
# Platform-specific screen detection
# ────────────────────────────────────────────────────────────

def get_host_screen_info() -> List[dict]:
    """Get screen information for the host machine (any OS)."""
    if _SYSTEM == 'Linux':
        return _get_screens_linux()
    elif _SYSTEM == 'Darwin':
        return _get_screens_macos()
    elif _SYSTEM == 'Windows':
        return _get_screens_windows()
    log.warning("Unknown OS, defaulting to 1920x1080")
    return [{'width': 1920, 'height': 1080, 'x': 0, 'y': 0, 'scale': 1.0, 'name': 'default'}]


def _get_screens_linux() -> List[dict]:
    screens = []
    # Method 1: xrandr
    try:
        import re
        result = subprocess.run(['xrandr', '--query'],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                match = re.match(r'.+\s+connected\s+(?:primary\s+)?(\d+)x(\d+)\+(\d+)\+(\d+)', line)
                if match:
                    screens.append({
                        'width': int(match.group(1)), 'height': int(match.group(2)),
                        'x': int(match.group(3)), 'y': int(match.group(4)),
                        'scale': 1.0, 'name': line.split()[0],
                    })
            if screens:
                return screens
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Method 2: /sys/class/drm
    try:
        import glob
        for mode_path in glob.glob('/sys/class/drm/card*-*/modes'):
            with open(mode_path) as f:
                first_mode = f.readline().strip()
                if 'x' in first_mode:
                    w, h = first_mode.split('x')
                    connector = mode_path.split('/')[-2]
                    status_path = mode_path.replace('/modes', '/status')
                    try:
                        with open(status_path) as sf:
                            if sf.read().strip() != 'connected':
                                continue
                    except FileNotFoundError:
                        pass
                    screens.append({
                        'width': int(w), 'height': int(h),
                        'x': len(screens) * int(w), 'y': 0,
                        'scale': 1.0, 'name': connector,
                    })
        if screens:
            return screens
    except Exception:
        pass

    # Method 3: fbset
    try:
        import re
        result = subprocess.run(['fbset', '-s'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            match = re.search(r'geometry\s+(\d+)\s+(\d+)', result.stdout)
            if match:
                return [{'width': int(match.group(1)), 'height': int(match.group(2)),
                         'x': 0, 'y': 0, 'scale': 1.0, 'name': 'framebuffer'}]
    except (FileNotFoundError, Exception):
        pass

    log.warning("Could not detect screen resolution, defaulting to 1920x1080")
    return [{'width': 1920, 'height': 1080, 'x': 0, 'y': 0, 'scale': 1.0, 'name': 'default'}]


def _get_screens_macos() -> List[dict]:
    screens = []
    try:
        from Quartz import CGGetActiveDisplayList, CGDisplayBounds, CGMainDisplayID
        try:
            from AppKit import NSScreen
        except ImportError:
            NSScreen = None
        (err, display_ids, count) = CGGetActiveDisplayList(16, None, None)
        if err == 0 and display_ids:
            ns_screens = NSScreen.screens() if NSScreen else []
            for i, did in enumerate(display_ids):
                bounds = CGDisplayBounds(did)
                scale = 1.0
                if ns_screens:
                    for ns in ns_screens:
                        frame = ns.frame()
                        if (abs(frame.origin.x - bounds.origin.x) < 1 and
                                abs(frame.origin.y - bounds.origin.y) < 1):
                            scale = ns.backingScaleFactor()
                            break
                name = f"Display {i + 1}"
                if ns_screens and i < len(ns_screens):
                    try:
                        name = ns_screens[i].localizedName()
                    except Exception:
                        pass
                screens.append({
                    'width': int(bounds.size.width), 'height': int(bounds.size.height),
                    'x': int(bounds.origin.x), 'y': int(bounds.origin.y),
                    'scale': float(scale), 'name': name,
                })
        if screens:
            return screens
    except ImportError:
        pass
    # Fallback: system_profiler
    try:
        import json
        result = subprocess.run(['system_profiler', 'SPDisplaysDataType', '-json'],
                                capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            x_offset = 0
            for gpu in data.get('SPDisplaysDataType', []):
                for display in gpu.get('spdisplays_ndrvs', []):
                    resolution = display.get('_spdisplays_resolution', '')
                    if ' x ' in resolution:
                        parts = resolution.split(' x ')
                        try:
                            w = int(parts[0].strip())
                            h_part = parts[1].split('@')[0].split('(')[0].strip()
                            h = int(h_part)
                            scale = 1.0
                            if 'Retina' in display.get('spdisplays_display_type', ''):
                                scale = 2.0
                                w //= 2
                                h //= 2
                            name = display.get('_name', f'Display {len(screens) + 1}')
                            screens.append({
                                'width': w, 'height': h, 'x': x_offset, 'y': 0,
                                'scale': scale, 'name': name,
                            })
                            x_offset += w
                        except (ValueError, IndexError):
                            continue
            if screens:
                return screens
    except Exception:
        pass
    return [{'width': 1920, 'height': 1080, 'x': 0, 'y': 0, 'scale': 1.0, 'name': 'default'}]


def _get_screens_windows() -> List[dict]:
    screens = []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        MONITORS = []

        def _monitor_enum_proc(hMonitor, hdcMonitor, lprcMonitor, dwData):
            class MONITORINFOEX(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD),
                    ("szDevice", ctypes.c_wchar * 32),
                ]

            mi = MONITORINFOEX()
            mi.cbSize = ctypes.sizeof(MONITORINFOEX)
            user32.GetMonitorInfoW(hMonitor, ctypes.byref(mi))
            MONITORS.append({
                'width': mi.rcMonitor.right - mi.rcMonitor.left,
                'height': mi.rcMonitor.bottom - mi.rcMonitor.top,
                'x': mi.rcMonitor.left,
                'y': mi.rcMonitor.top,
                'scale': 1.0,
                'name': mi.szDevice,
            })
            return 1

        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
            ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_monitor_enum_proc), 0)
        screens = MONITORS

        # Try to get DPI scaling
        try:
            for s in screens:
                # GetDpiForSystem requires Windows 10 1607+
                dpi = user32.GetDpiForSystem()
                s['scale'] = dpi / 96.0
        except Exception:
            pass

        if screens:
            return screens
    except Exception:
        pass

    return [{'width': 1920, 'height': 1080, 'x': 0, 'y': 0, 'scale': 1.0, 'name': 'default'}]
