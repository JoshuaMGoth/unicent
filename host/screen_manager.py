"""
Virtual screen layout manager for the host.

Manages the spatial arrangement of all screens (host + clients)
in a unified virtual desktop. Handles edge detection for seamless
cursor transitions between machines.
"""

import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class Screen:
    """Represents a single physical monitor."""
    width: int
    height: int
    x: int = 0           # Position in virtual space
    y: int = 0
    scale: float = 1.0   # HiDPI scale factor
    name: str = ''       # e.g., "Built-in Retina Display"

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def to_dict(self) -> dict:
        return {
            'width': self.width,
            'height': self.height,
            'x': self.x,
            'y': self.y,
            'scale': self.scale,
            'name': self.name,
        }

    @staticmethod
    def from_dict(d: dict) -> 'Screen':
        return Screen(
            width=d['width'],
            height=d['height'],
            x=d.get('x', 0),
            y=d.get('y', 0),
            scale=d.get('scale', 1.0),
            name=d.get('name', ''),
        )


@dataclass
class MachineScreens:
    """All screens belonging to a single machine."""
    machine_id: str       # 'host' or client hostname
    screens: List[Screen] = field(default_factory=list)
    offset_x: int = 0     # Offset in the virtual layout
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
        """Check if a global virtual coordinate is within this machine's area."""
        lx = gx - self.offset_x
        ly = gy - self.offset_y
        return any(s.contains(lx, ly) for s in self.screens)

    def global_to_local(self, gx: int, gy: int) -> Tuple[int, int]:
        """Convert global virtual coords to local coords for this machine."""
        return gx - self.offset_x, gy - self.offset_y

    def local_to_global(self, lx: int, ly: int) -> Tuple[int, int]:
        """Convert local coords to global virtual coords."""
        return lx + self.offset_x, ly + self.offset_y


class ScreenLayout:
    """Manages the virtual screen layout across all machines.

    Screens are arranged left-to-right by default:
    [Host Screens] [Client 1 Screens] [Client 2 Screens] ...

    The virtual cursor moves across this unified space. When it
    crosses a machine boundary, control switches to that machine.
    """

    def __init__(self, client_side: str = 'right'):
        self.machines: List[MachineScreens] = []
        self._cursor_x: int = 0
        self._cursor_y: int = 0
        self._active_machine: str = 'host'
        self._edge_margin: int = 1  # pixels from edge to trigger switch
        self.client_side: str = client_side  # 'left' or 'right'

    def set_host_screens(self, screens: List[dict]):
        """Set the host machine's screen configuration."""
        host_screens = [Screen.from_dict(s) for s in screens]
        # Remove existing host entry
        self.machines = [m for m in self.machines if m.machine_id != 'host']
        # Insert host at position 0
        ms = MachineScreens(machine_id='host', screens=host_screens)
        self.machines.insert(0, ms)
        self._recalculate_layout()
        # Initialize cursor at host center
        self.init_cursor_at_host()
        log.info(f"Host screens set: {len(host_screens)} monitor(s)")

    def add_client_screens(self, client_id: str, screens: List[dict]):
        """Add or update a client's screen configuration."""
        client_screens = [Screen.from_dict(s) for s in screens]
        # Remove existing entry for this client
        self.machines = [m for m in self.machines if m.machine_id != client_id]
        ms = MachineScreens(machine_id=client_id, screens=client_screens)
        self.machines.append(ms)
        self._recalculate_layout()
        log.info(f"Client '{client_id}' screens set: {len(client_screens)} monitor(s)")

    def remove_client(self, client_id: str):
        """Remove a client from the layout."""
        self.machines = [m for m in self.machines if m.machine_id != client_id]
        self._recalculate_layout()
        if self._active_machine == client_id:
            self._active_machine = 'host'

    def _recalculate_layout(self):
        """Recalculate the positions of all machines in the virtual space.

        Arranges machines based on client_side setting:
        - 'right' (default): [Host] [Client1] [Client2] ...
        - 'left': ... [Client2] [Client1] [Host]

        Also adjusts the virtual cursor to stay on the active machine
        when the layout shifts (e.g., when a client connects).
        """
        # Save old offset of the active machine so we can adjust cursor
        old_active_offset_x = 0
        old_active_offset_y = 0
        for m in self.machines:
            if m.machine_id == self._active_machine:
                old_active_offset_x = m.offset_x
                old_active_offset_y = m.offset_y
                break

        max_height = max((m.total_height for m in self.machines), default=0)

        if self.client_side == 'left':
            # Place clients to the LEFT of host
            # Order: clients first (reversed), then host
            host = [m for m in self.machines if m.machine_id == 'host']
            clients = [m for m in self.machines if m.machine_id != 'host']
            ordered = list(reversed(clients)) + host
        else:
            # Default: host first, clients after (right side)
            ordered = list(self.machines)

        x_offset = 0
        for machine in ordered:
            machine.offset_x = x_offset
            machine.offset_y = (max_height - machine.total_height) // 2
            x_offset += machine.total_width

        # Adjust virtual cursor to follow the active machine's new position
        for m in ordered:
            if m.machine_id == self._active_machine:
                delta_x = m.offset_x - old_active_offset_x
                delta_y = m.offset_y - old_active_offset_y
                if delta_x != 0 or delta_y != 0:
                    self._cursor_x += delta_x
                    self._cursor_y += delta_y
                    log.info(f"Cursor adjusted by ({delta_x},{delta_y}) "
                             f"to ({self._cursor_x},{self._cursor_y}) "
                             f"— active machine '{self._active_machine}' shifted")
                break

        layout_desc = ', '.join(
            f"{m.machine_id}({m.total_width}x{m.total_height}@{m.offset_x})"
            for m in ordered
        )
        log.info(f"Layout: {layout_desc}")

    def get_layout_info(self) -> list:
        """Get the layout as a serializable list."""
        return [
            {
                'machine_id': m.machine_id,
                'offset_x': m.offset_x,
                'offset_y': m.offset_y,
                'total_width': m.total_width,
                'total_height': m.total_height,
                'screens': [s.to_dict() for s in m.screens],
            }
            for m in self.machines
        ]

    @property
    def active_machine(self) -> str:
        return self._active_machine

    @property
    def cursor_position(self) -> Tuple[int, int]:
        return self._cursor_x, self._cursor_y

    def init_cursor_at_host(self, local_x: int = None, local_y: int = None):
        """Position the virtual cursor within the host's screen area.

        Args:
            local_x: X position in host-local coords (default: center)
            local_y: Y position in host-local coords (default: center)
        """
        for m in self.machines:
            if m.machine_id == 'host':
                if local_x is not None and local_y is not None:
                    self._cursor_x = m.offset_x + local_x
                    self._cursor_y = m.offset_y + local_y
                else:
                    self._cursor_x = m.offset_x + m.total_width // 2
                    self._cursor_y = m.offset_y + m.total_height // 2
                self._active_machine = 'host'
                log.info(f"Cursor initialized at ({self._cursor_x}, {self._cursor_y}) "
                         f"on host (offset {m.offset_x},{m.offset_y})")
                return
        log.warning("No host machine in layout for cursor init")

    def move_cursor(self, dx: int, dy: int) -> Optional[str]:
        """Move the virtual cursor by (dx, dy).

        Returns the machine_id if the cursor crossed into a different machine,
        or None if it stayed within the same machine.
        """
        new_x = self._cursor_x + dx
        new_y = self._cursor_y + dy

        # Clamp to virtual space bounds
        total_width = sum(m.total_width for m in self.machines)
        max_height = max((m.total_height for m in self.machines), default=0)
        new_x = max(0, min(new_x, total_width - 1))
        new_y = max(0, min(new_y, max_height - 1))

        self._cursor_x = new_x
        self._cursor_y = new_y

        # Find which machine the cursor is now in
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
        """Get cursor position in local coordinates for the specified machine."""
        if machine_id is None:
            machine_id = self._active_machine
        for machine in self.machines:
            if machine.machine_id == machine_id:
                return machine.global_to_local(self._cursor_x, self._cursor_y)
        return 0, 0

    def set_cursor_for_machine(self, machine_id: str, edge: str = 'left',
                                position: int = -1):
        """Set cursor to the edge of a machine's screen area.

        Used when switching machines via hotkey.
        """
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
            log.info(f"Cursor warped to {machine_id} ({self._cursor_x}, {self._cursor_y})")
            return

    def switch_to_next(self) -> str:
        """Switch to the next machine in the layout. Returns new machine_id."""
        if not self.machines:
            return self._active_machine

        current_idx = next(
            (i for i, m in enumerate(self.machines)
             if m.machine_id == self._active_machine),
            0
        )
        next_idx = (current_idx + 1) % len(self.machines)
        target = self.machines[next_idx].machine_id
        self.set_cursor_for_machine(target, edge='center')
        return target

    def switch_to_index(self, index: int) -> Optional[str]:
        """Switch to machine at the given index (0-based). Returns machine_id or None."""
        if 0 <= index < len(self.machines):
            target = self.machines[index].machine_id
            self.set_cursor_for_machine(target, edge='center')
            return target
        return None

    def get_machine_list(self) -> List[Tuple[int, str, bool]]:
        """Get list of (index, machine_id, is_active) for the toggle menu."""
        return [
            (i, m.machine_id, m.machine_id == self._active_machine)
            for i, m in enumerate(self.machines)
        ]


def get_host_screen_info() -> List[dict]:
    """Get screen information for the host machine.

    In a minimal Linux environment (no X11/Wayland), we try multiple methods:
    1. Try querying via xrandr (if X is available)
    2. Try reading from /sys/class/drm
    3. Fall back to a default resolution
    """
    screens = []

    # Method 1: Try xrandr
    try:
        import subprocess
        result = subprocess.run(
            ['xrandr', '--query'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            import re
            for line in result.stdout.split('\n'):
                match = re.match(r'.+\s+connected\s+(?:primary\s+)?(\d+)x(\d+)\+(\d+)\+(\d+)', line)
                if match:
                    screens.append({
                        'width': int(match.group(1)),
                        'height': int(match.group(2)),
                        'x': int(match.group(3)),
                        'y': int(match.group(4)),
                        'scale': 1.0,
                        'name': line.split()[0],
                    })
            if screens:
                return screens
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass

    # Method 2: Try /sys/class/drm
    try:
        import glob
        for mode_path in glob.glob('/sys/class/drm/card*-*/modes'):
            with open(mode_path) as f:
                first_mode = f.readline().strip()
                if 'x' in first_mode:
                    w, h = first_mode.split('x')
                    connector = mode_path.split('/')[-2]
                    # Check if this connector is connected
                    status_path = mode_path.replace('/modes', '/status')
                    try:
                        with open(status_path) as sf:
                            if sf.read().strip() != 'connected':
                                continue
                    except FileNotFoundError:
                        pass
                    screens.append({
                        'width': int(w),
                        'height': int(h),
                        'x': len(screens) * int(w),  # Arrange side by side
                        'y': 0,
                        'scale': 1.0,
                        'name': connector,
                    })
        if screens:
            return screens
    except Exception:
        pass

    # Method 3: Try fbset or read framebuffer info
    try:
        import subprocess
        result = subprocess.run(
            ['fbset', '-s'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            import re
            match = re.search(r'geometry\s+(\d+)\s+(\d+)', result.stdout)
            if match:
                return [{
                    'width': int(match.group(1)),
                    'height': int(match.group(2)),
                    'x': 0, 'y': 0,
                    'scale': 1.0,
                    'name': 'framebuffer',
                }]
    except (FileNotFoundError, Exception):
        pass

    # Fallback: assume 1920x1080
    log.warning("Could not detect screen resolution, defaulting to 1920x1080")
    return [{
        'width': 1920,
        'height': 1080,
        'x': 0, 'y': 0,
        'scale': 1.0,
        'name': 'default',
    }]
