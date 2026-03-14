#!/usr/bin/env python3
"""
UniCent Host — Main entry point.

Runs on Arch Linux (including installer environment).
Captures input from local keyboard/mouse and forwards to connected
macOS clients based on virtual screen layout.

Usage:
    sudo python3 -m host.main [--port PORT] [--no-tls] [--no-grab]

Hotkeys:
    Ctrl+Alt+S  or ScrollLock : Switch to next computer
    Ctrl+Alt+1                : Switch to host (local)
    Ctrl+Alt+2                : Switch to client 1
    Ctrl+Alt+3                : Switch to client 2
    Ctrl+Alt+T                : Show toggle menu
    Ctrl+Alt+C                : Sync clipboard
    Ctrl+Alt+Q                : Quit
"""

import sys
import os
import argparse
import logging
import signal
import time
import threading
import socket
import subprocess
import re

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.discovery import DiscoveryBeacon, DiscoveryListener
from shared.keymap import (
    CTRL_KEYS, ALT_KEYS, KEY_S, KEY_T, KEY_1, KEY_2, KEY_3,
    KEY_4, KEY_5, KEY_SCROLLLOCK, KEY_C,
)
from host.input_capture import InputCapture, HotkeyDetector, find_input_devices
from host.screen_manager import ScreenLayout, get_host_screen_info
from host.server import HostServer

try:
    from host.tray import HostTray, TRAY_AVAILABLE
except ImportError:
    TRAY_AVAILABLE = False

log = logging.getLogger('unicent.host')


class UniCentHost:
    """Main host application controller."""

    def __init__(self, port: int = 27183, use_tls: bool = True,
                 allow_grab: bool = True, cert_dir: str = 'certs',
                 client_side: str = 'right'):
        self.port = port
        self.use_tls = use_tls
        self.allow_grab = allow_grab
        self.cert_dir = cert_dir
        self.client_side = client_side
        self._running = False
        self._controlling_remote = False
        self._show_menu = False

        # Components
        self.layout = ScreenLayout(client_side=client_side)
        self.input_capture = InputCapture()
        self.hotkey_detector = HotkeyDetector()
        self.server: HostServer = None  # type: ignore
        self.beacon: DiscoveryBeacon = None  # type: ignore
        self.listener: DiscoveryListener = None  # type: ignore
        self.tray = None  # System tray icon

        # Clipboard
        self._clipboard = ''

    def run(self):
        """Main entry point."""
        self._running = True
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._print_banner()

        # 1. Detect screens
        log.info("Detecting host screens...")
        host_screens = get_host_screen_info()
        self.layout.set_host_screens(host_screens)
        for i, s in enumerate(host_screens):
            print(f"  Monitor {i+1}: {s['width']}x{s['height']} ({s.get('name', 'unknown')})")

        # Sync virtual cursor with real cursor position
        pos = self._read_host_cursor()
        if pos:
            self.layout.init_cursor_at_host(pos[0], pos[1])
            log.info(f"Synced virtual cursor to real position ({pos[0]}, {pos[1]})")
        else:
            log.info("Could not read cursor — using host center")

        # 2. Find input devices
        log.info("Finding input devices...")
        devices = find_input_devices()
        if not devices['keyboards'] and not devices['mice']:
            print("\n[ERROR] No input devices found!")
            print("Make sure you're running as root (sudo).")
            print("Check that /dev/input/event* devices exist.")
            sys.exit(1)

        all_paths = [d['path'] for d in devices['all']]
        opened = self.input_capture.open_devices(all_paths)
        if opened == 0:
            print("\n[ERROR] Could not open any input devices!")
            print("Make sure you're running as root (sudo).")
            sys.exit(1)
        print(f"  Opened {opened} input device(s)")

        # 3. Set up input callbacks
        self._setup_input_handlers()

        # 4. Set up hotkeys
        self._setup_hotkeys()

        # 5. Start network server
        cert_file = os.path.join(self.cert_dir, 'server.crt') if self.use_tls else None
        key_file = os.path.join(self.cert_dir, 'server.key') if self.use_tls else None
        ca_file = os.path.join(self.cert_dir, 'ca.crt') if self.use_tls else None

        if self.use_tls and cert_file and not os.path.exists(cert_file):
            print(f"\n[WARNING] TLS certificates not found in {self.cert_dir}/")
            print("Run ./generate_certs.sh first, or use --no-tls")
            print("Continuing without encryption...\n")
            cert_file = None
            key_file = None
            ca_file = None

        self.server = HostServer(
            port=self.port,
            cert_file=cert_file,
            key_file=key_file,
            ca_file=ca_file,
        )
        self.server.set_host_info(
            socket.gethostname(),
            host_screens,
            self.layout.get_layout_info(),
        )
        self.server.on_client_connected = self._on_client_connected
        self.server.on_client_disconnected = self._on_client_disconnected
        self.server.on_client_screens = self._on_client_screens
        self.server.on_clipboard_received = self._on_clipboard_received
        self.server.start()

        # 6. Start discovery
        self.beacon = DiscoveryBeacon(
            service_port=self.port,
            hostname=socket.gethostname(),
            role='host',
        )
        self.beacon.start()

        self.listener = DiscoveryListener(
            on_discovered=self._on_peer_discovered,
            filter_role='client',
        )
        self.listener.start()

        # 7. Start input capture
        self.input_capture.start()

        # 8. Start system tray icon
        if TRAY_AVAILABLE:
            try:
                self.tray = HostTray(self)
                self.tray.start()
                print("  System tray icon started")
            except Exception as e:
                log.warning(f"Could not start tray icon: {e}")
                self.tray = None

        print(f"\n{'='*60}")
        print(f"  UniCent HOST running on port {self.port}")
        if self.tray:
            print(f"  Right-click the tray icon for controls")
        print(f"  Waiting for client connections...")
        print(f"{'='*60}")
        print()
        self._print_hotkeys()

        # 9. Main loop
        try:
            while self._running:
                if self._show_menu:
                    self._display_menu()
                    self._show_menu = False
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    def _print_banner(self):
        print()
        print("  ╔══════════════════════════════════════╗")
        print("  ║          UniCent HOST v1.0           ║")
        print("  ║   Cross-platform Mouse & Keyboard    ║")
        print("  ╚══════════════════════════════════════╝")
        print()

    def _print_hotkeys(self):
        print("  Hotkeys:")
        print("    Ctrl+Alt+S / ScrollLock  →  Switch to next computer")
        print("    Ctrl+Alt+1               →  Switch to host (local)")
        print("    Ctrl+Alt+2               →  Switch to client 1")
        print("    Ctrl+Alt+3               →  Switch to client 2")
        print("    Ctrl+Alt+T               →  Show computer list")
        print("    Ctrl+Alt+C               →  Sync clipboard")
        print("    Ctrl+Alt+Q               →  Quit")
        print()

    def _setup_input_handlers(self):
        """Connect input event callbacks."""
        self.input_capture.on_mouse_move = self._on_mouse_move
        self.input_capture.on_mouse_button = self._on_mouse_button
        self.input_capture.on_mouse_scroll = self._on_mouse_scroll
        self.input_capture.on_key_event = self._on_key_event

    def _setup_hotkeys(self):
        """Register keyboard shortcuts."""
        ctrl_alt = {frozenset(CTRL_KEYS), frozenset(ALT_KEYS)}

        # Ctrl+Alt+S: Switch to next
        self.hotkey_detector.register(
            'switch_next', ctrl_alt, KEY_S, self._hotkey_switch_next
        )
        # ScrollLock: Switch to next
        self.hotkey_detector.register(
            'scrolllock', set(), KEY_SCROLLLOCK, self._hotkey_switch_next
        )
        # Ctrl+Alt+1: Switch to host
        self.hotkey_detector.register(
            'switch_1', ctrl_alt, KEY_1,
            lambda: self._hotkey_switch_to(0)
        )
        # Ctrl+Alt+2: Switch to client 1
        self.hotkey_detector.register(
            'switch_2', ctrl_alt, KEY_2,
            lambda: self._hotkey_switch_to(1)
        )
        # Ctrl+Alt+3: Switch to client 2
        self.hotkey_detector.register(
            'switch_3', ctrl_alt, KEY_3,
            lambda: self._hotkey_switch_to(2)
        )
        # Ctrl+Alt+4: Switch to client 3
        self.hotkey_detector.register(
            'switch_4', ctrl_alt, KEY_4,
            lambda: self._hotkey_switch_to(3)
        )
        # Ctrl+Alt+T: Toggle menu
        self.hotkey_detector.register(
            'toggle_menu', ctrl_alt, KEY_T, self._hotkey_toggle_menu
        )
        # Ctrl+Alt+C: Clipboard sync
        self.hotkey_detector.register(
            'clipboard', ctrl_alt, KEY_C, self._hotkey_clipboard_sync
        )
        # Ctrl+Alt+Q: Quit (use KEY_Q = 16)
        self.hotkey_detector.register(
            'quit', ctrl_alt, 16, self._hotkey_quit  # KEY_Q = 16
        )

    # --- Input event handlers ---

    def _on_key_event(self, keycode: int, state: int):
        """Handle keyboard event from evdev."""
        # Always check hotkeys first (even when controlling remote)
        if self.hotkey_detector.process_key(keycode, state):
            return  # Hotkey consumed the event

        # Forward to remote if controlling a client
        if self._controlling_remote and self.server:
            self.server.forward_key_event(keycode, state)

    def _on_mouse_move(self, dx: int, dy: int):
        """Handle mouse move from evdev."""
        if self._controlling_remote:
            # Update virtual cursor and check for edge crossing
            new_machine = self.layout.move_cursor(dx, dy)
            if new_machine:
                self._switch_to_machine(new_machine)
            else:
                # Forward movement to client
                if self.server:
                    self.server.forward_mouse_move(dx, dy)
        else:
            # Update virtual cursor for edge detection
            new_machine = self.layout.move_cursor(dx, dy)
            if new_machine and new_machine != 'host':
                self._switch_to_machine(new_machine)

    def _on_mouse_button(self, button: int, state: int):
        """Handle mouse button from evdev."""
        if self._controlling_remote and self.server:
            self.server.forward_mouse_button(button, state)

    def _on_mouse_scroll(self, dx: int, dy: int):
        """Handle scroll from evdev."""
        if self._controlling_remote and self.server:
            self.server.forward_mouse_scroll(dx, dy)

    # --- Machine switching ---

    def _switch_to_machine(self, machine_id: str):
        """Switch input control to a specific machine."""
        old_active = self.layout.active_machine

        if machine_id == 'host':
            # Switching to local
            self._controlling_remote = False
            if self.allow_grab:
                self.input_capture.ungrab()

            # Warp the real cursor to match virtual cursor position
            local_x, local_y = self.layout.get_local_cursor('host')
            self._warp_host_cursor(local_x, local_y)

            # Re-sync virtual cursor from real cursor (after warp)
            time.sleep(0.02)  # Brief delay for warp to take effect
            pos = self._read_host_cursor()
            if pos:
                self.layout.init_cursor_at_host(pos[0], pos[1])

            # Notify old client it's no longer active
            if old_active != 'host' and self.server:
                self.server.send_switch_inactive(old_active)
            self.server.set_active_client(None)
            print(f"\n  → Controlling: HOST (local)")
            if self.tray:
                self.tray.update_menu()
                self.tray.update_tooltip('UniCent — Controlling: HOST')
        else:
            # Switching to remote client
            if machine_id not in self.server.clients:
                print(f"\n  [!] Client '{machine_id}' not connected")
                return

            # Notify old client if it was a different remote
            if old_active != 'host' and old_active != machine_id and self.server:
                self.server.send_switch_inactive(old_active)

            self._controlling_remote = True
            if self.allow_grab:
                self.input_capture.grab()

            # Get cursor position in client's local coordinates
            local_x, local_y = self.layout.get_local_cursor(machine_id)
            self.server.set_active_client(machine_id)
            self.server.send_switch_active(machine_id, local_x, local_y)
            self.server.send_cursor_warp(machine_id, local_x, local_y)
            print(f"\n  → Controlling: {machine_id} (remote)")
            if self.tray:
                self.tray.update_menu()
                self.tray.update_tooltip(f'UniCent — Controlling: {machine_id}')

    # --- Hotkey handlers ---

    def _hotkey_switch_next(self):
        """Switch to next computer in layout."""
        target = self.layout.switch_to_next()
        self._switch_to_machine(target)

    def _hotkey_switch_to(self, index: int):
        """Switch to computer at specific index."""
        target = self.layout.switch_to_index(index)
        if target:
            self._switch_to_machine(target)
        else:
            print(f"\n  [!] No computer at position {index + 1}")

    def _hotkey_toggle_menu(self):
        """Show the toggle menu."""
        self._show_menu = True

    def _hotkey_clipboard_sync(self):
        """Synchronize clipboard."""
        if self.server:
            self.server.send_clipboard(self._clipboard)
            print("\n  [clipboard] Synced to all clients")

    def _hotkey_quit(self):
        """Quit the application."""
        print("\n  Quitting...")
        self._running = False

    # --- Menu ---

    def _display_menu(self):
        """Display the computer selection menu in the terminal."""
        machines = self.layout.get_machine_list()
        clients = self.server.get_client_list() if self.server else []

        print(f"\n  ┌──────────────────────────────────────┐")
        print(f"  │       Computer Selection Menu         │")
        print(f"  ├──────────────────────────────────────┤")

        for idx, machine_id, is_active in machines:
            marker = " ◄━" if is_active else ""
            shortcut = f"Ctrl+Alt+{idx+1}"

            if machine_id == 'host':
                name = f"HOST ({socket.gethostname()})"
            else:
                client_info = next(
                    (c for c in clients if c['client_id'] == machine_id),
                    None
                )
                if client_info:
                    name = f"{machine_id} ({client_info['address']})"
                else:
                    name = machine_id

            print(f"  │  [{idx+1}] {name:<28}{marker:>4} │")

        print(f"  ├──────────────────────────────────────┤")
        print(f"  │  Press Ctrl+Alt+<number> to switch   │")
        print(f"  └──────────────────────────────────────┘\n")

    # --- Server callbacks ---

    def _on_client_connected(self, client_id: str, screens: list):
        """Called when a new client connects."""
        self.layout.add_client_screens(client_id, screens)
        # Update server with new layout
        host_screen_dicts = (
            [s.to_dict() for s in self.layout.machines[0].screens]
            if self.layout.machines else []
        )
        self.server.set_host_info(
            socket.gethostname(),
            host_screen_dicts,
            self.layout.get_layout_info(),
        )
        print(f"\n  [+] Client connected: {client_id}")
        print(f"      Screens: {len(screens)}")
        for i, s in enumerate(screens):
            print(f"      Monitor {i+1}: {s['width']}x{s['height']}")
        print()
        self._print_layout()
        # Update tray menu
        if self.tray:
            self.tray.update_menu()
            self.tray.update_tooltip(f'UniCent — {client_id} connected')

    def _on_client_disconnected(self, client_id: str):
        """Called when a client disconnects."""
        self.layout.remove_client(client_id)
        if self._controlling_remote and self.layout.active_machine == 'host':
            self._controlling_remote = False
            if self.allow_grab:
                self.input_capture.ungrab()
        print(f"\n  [-] Client disconnected: {client_id}\n")
        # Update tray menu
        if self.tray:
            self.tray.update_menu()
            self.tray.update_tooltip('UniCent Host — No clients')

    def _on_client_screens(self, client_id: str, screens: list):
        """Called when a client updates its screen info."""
        self.layout.add_client_screens(client_id, screens)
        log.info(f"Updated screens for {client_id}")

    def _on_clipboard_received(self, client_id: str, content: str):
        """Called when clipboard data is received from a client."""
        self._clipboard = content
        log.info(f"Clipboard received from {client_id}: {len(content)} chars")

    def _on_peer_discovered(self, info: dict):
        """Called when a new peer is discovered on the network."""
        log.info(f"Discovered peer: {info.get('hostname')} at {info.get('ip')}")

    def _print_layout(self):
        """Print the current virtual screen layout."""
        print("  Current layout:")
        for m in self.layout.machines:
            active = " ◄" if m.machine_id == self.layout.active_machine else ""
            print(f"    [{m.machine_id}] {m.total_width}x{m.total_height} "
                  f"@ ({m.offset_x},{m.offset_y}){active}")
        cx, cy = self.layout.cursor_position
        print(f"  Cursor: ({cx},{cy}) on '{self.layout.active_machine}'")
        print()

    # --- Host cursor helpers ---

    def _read_host_cursor(self):
        """Try to read the current cursor position from the compositor.

        Returns (x, y) tuple or None if unable to read.
        Uses xdotool (works via XWayland on KDE Plasma Wayland).
        """
        try:
            result = subprocess.run(
                ['xdotool', 'getmouselocation'],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                match = re.search(r'x:(\d+)\s+y:(\d+)', result.stdout)
                if match:
                    return int(match.group(1)), int(match.group(2))
        except Exception:
            pass
        return None

    def _warp_host_cursor(self, x: int, y: int):
        """Warp the host cursor to position (x, y) in host-local coordinates.

        Uses xdotool for cursor warping (works via XWayland on KDE Wayland).
        """
        try:
            result = subprocess.run(
                ['xdotool', 'mousemove', str(x), str(y)],
                capture_output=True, timeout=2
            )
            if result.returncode == 0:
                log.debug(f"Cursor warped to ({x}, {y})")
                return
        except Exception:
            pass
        log.debug(f"Could not warp cursor to ({x}, {y})")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print("\n  Shutting down...")
        self._running = False

    def _shutdown(self):
        """Clean shutdown of all components."""
        print("  Stopping tray icon...")
        if self.tray:
            self.tray.stop()
        print("  Stopping input capture...")
        self.input_capture.stop()
        print("  Stopping server...")
        if self.server:
            self.server.stop()
        print("  Stopping discovery...")
        if self.beacon:
            self.beacon.stop()
        if self.listener:
            self.listener.stop()
        print("  Goodbye!\n")


def main():
    parser = argparse.ArgumentParser(
        description='UniCent Host - Share mouse & keyboard over network',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        '-p', '--port', type=int, default=27183,
        help='Server port (default: 27183)',
    )
    parser.add_argument(
        '--no-tls', action='store_true',
        help='Disable TLS encryption',
    )
    parser.add_argument(
        '--no-grab', action='store_true',
        help='Disable exclusive device grab (for debugging)',
    )
    parser.add_argument(
        '--certs', default='certs',
        help='Directory containing TLS certificates (default: certs)',
    )
    parser.add_argument(
        '-v', '--verbose', action='store_true',
        help='Enable debug logging',
    )
    parser.add_argument(
        '--no-tray', action='store_true',
        help='Disable system tray icon (terminal-only mode)',
    )
    parser.add_argument(
        '--client-side', choices=['left', 'right'], default='right',
        help='Which side of host screen to place clients (default: right)',
    )

    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S',
    )

    # Check root
    if os.geteuid() != 0:
        print("\n  [WARNING] Not running as root!")
        print("  Input device access requires root privileges.")
        print("  Run with: sudo python3 -m host.main\n")

    host = UniCentHost(
        port=args.port,
        use_tls=not args.no_tls,
        allow_grab=not args.no_grab,
        cert_dir=args.certs,
        client_side=args.client_side,
    )
    if args.no_tray:
        # Disable tray globally
        global TRAY_AVAILABLE
        TRAY_AVAILABLE = False
    host.run()


if __name__ == '__main__':
    main()
