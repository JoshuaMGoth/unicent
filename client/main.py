#!/usr/bin/env python3
"""
UniCent Client — macOS entry point.

Connects to a UniCent host and receives mouse/keyboard events,
injecting them into macOS via Quartz (CoreGraphics).

Usage:
    python3 -m client.main [--host HOST_IP] [--port PORT] [--no-tls]

The client will auto-discover hosts on the network if no --host is specified.
"""

import sys
import os
import argparse
import logging
import signal
import time
import threading
import socket

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.discovery import DiscoveryBeacon, DiscoveryListener
from client.connection import HostConnection
from client.screen_manager import get_macos_screens, get_clipboard_content, set_clipboard_content

try:
    from client.tray import ClientTray, RUMPS_AVAILABLE as TRAY_AVAILABLE
except ImportError:
    TRAY_AVAILABLE = False

log = logging.getLogger('unicent.client')


class UniCentClient:
    """Main client application controller for macOS."""

    def __init__(self, host_addr=None, host_port=27183,
                 use_tls=True, cert_dir='certs'):
        self.host_addr = host_addr
        self.host_port = host_port
        self.use_tls = use_tls
        self.cert_dir = cert_dir
        self._running = False
        self._is_active = False  # Whether this client is being controlled

        # Components
        self.connection: HostConnection = None  # type: ignore
        self.injector = None  # InputInjector (lazy init)
        self.beacon: DiscoveryBeacon = None  # type: ignore
        self.listener: DiscoveryListener = None  # type: ignore

        # Track state
        self._screens = []
        self._clipboard = ''
        self._use_tray = True  # Use tray/menu bar icon by default

    def run(self):
        """Main entry point."""
        self._running = True
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # If tray is available and enabled, use it
        if self._use_tray and TRAY_AVAILABLE:
            tray = ClientTray(self)
            tray.run()  # This blocks on macOS main thread
            return

        # Otherwise run in terminal mode
        self._run_terminal_mode()

    def _start_background(self):
        """Start all client logic (called from tray wrapper, runs in bg thread)."""
        self._running = True
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._init_components()
        self._connect_to_host()

        # Background main loop (clipboard monitoring)
        try:
            last_clipboard_check = 0
            while self._running:
                time.sleep(0.5)
                now = time.time()
                if now - last_clipboard_check > 2.0:
                    last_clipboard_check = now
                    self._check_clipboard()
        except Exception:
            pass

    def _run_terminal_mode(self):
        """Run in terminal mode (no tray icon)."""

        self._print_banner()

        self._init_components()
        self._connect_to_host()

        print(f"\n{'='*60}")
        print(f"  UniCent CLIENT running")
        print(f"  Connecting to host: {self.host_addr}:{self.host_port}")
        print(f"{'='*60}\n")

        # 8. Main loop (clipboard monitoring, etc.)
        try:
            last_clipboard_check = 0
            while self._running:
                time.sleep(0.5)
                now = time.time()
                if now - last_clipboard_check > 2.0:
                    last_clipboard_check = now
                    self._check_clipboard()
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    def _init_components(self):
        """Initialize all client components (input injector, screens, discovery)."""

        # 1. Check accessibility permissions
        print("  Checking accessibility permissions...")
        try:
            from client.input_inject import (
                InputInjector, check_accessibility_permissions,
                request_accessibility_permissions,
            )
            if not check_accessibility_permissions():
                request_accessibility_permissions()
                print("\n  Please grant permissions and restart.")
                print("  (You can continue, but input injection may not work)\n")
        except Exception as e:
            log.warning(f"Could not check permissions: {e}")

        # 2. Initialize input injector
        print("  Initializing input injector...")
        try:
            from client.input_inject import InputInjector
            self.injector = InputInjector()
            print("  Input injector ready")
        except Exception as e:
            print(f"  [WARNING] Input injector failed: {e}")
            print("  Will attempt to use fallback methods")

        # 3. Detect screens
        print("  Detecting screens...")
        self._screens = get_macos_screens()
        for i, s in enumerate(self._screens):
            print(f"    Monitor {i+1}: {s['width']}x{s['height']} "
                  f"(scale: {s.get('scale', 1)}x) - {s.get('name', 'unknown')}")

        # 4. Get clipboard
        self._clipboard = get_clipboard_content()

        # 5. Start discovery
        self.beacon = DiscoveryBeacon(
            service_port=0,
            hostname=socket.gethostname(),
            role='client',
            extra={'screens': len(self._screens)},
        )
        self.beacon.start()

    def _connect_to_host(self):
        """Find host and establish connection."""

        # 6. Find host if not specified
        if not self.host_addr:
            print("\n  Searching for host on network...")
            self.host_addr = self._discover_host()
            if not self.host_addr:
                print("  [ERROR] No host found on network!")
                print("  Use --host <IP> to specify the host address.")
                self._shutdown()
                return

        # 7. Set up connection
        ca_file = os.path.join(self.cert_dir, 'ca.crt') if self.use_tls else None
        cert_file = os.path.join(self.cert_dir, 'client.crt') if self.use_tls else None

        if self.use_tls and ca_file and not os.path.exists(ca_file):
            print(f"\n  [WARNING] TLS certificates not found in {self.cert_dir}/")
            print("  Continuing without encryption...\n")
            ca_file = None
            cert_file = None

        self.connection = HostConnection(
            host_addr=self.host_addr,
            host_port=self.host_port,
            ca_file=ca_file,
            cert_file=cert_file,
            hostname=socket.gethostname(),
        )
        self.connection.set_screens(self._screens)
        self.connection.set_clipboard(self._clipboard)

        # Set up callbacks
        self.connection.on_connected = self._on_connected
        self.connection.on_disconnected = self._on_disconnected
        self.connection.on_mouse_move = self._on_mouse_move
        self.connection.on_mouse_move_abs = self._on_mouse_move_abs
        self.connection.on_mouse_button = self._on_mouse_button
        self.connection.on_mouse_scroll = self._on_mouse_scroll
        self.connection.on_key_event = self._on_key_event
        self.connection.on_switch_active = self._on_switch_active
        self.connection.on_cursor_warp = self._on_cursor_warp
        self.connection.on_clipboard = self._on_clipboard

        # Start connection
        self.connection.start()

    def _print_banner(self):
        print()
        print("  ╔══════════════════════════════════════╗")
        print("  ║        UniCent CLIENT v1.0          ║")
        print("  ║          macOS Input Receiver         ║")
        print("  ╚══════════════════════════════════════╝")
        print()

    def _discover_host(self, timeout: float = 10.0) -> str:
        """Try to auto-discover a host on the network."""
        found_event = threading.Event()
        host_info = {}

        def on_host_found(info):
            if info.get('role') == 'host':
                host_info.update(info)
                found_event.set()

        listener = DiscoveryListener(
            on_discovered=on_host_found,
            filter_role='host',
        )
        listener.start()

        print(f"    Waiting up to {timeout}s for host broadcast...")
        found = found_event.wait(timeout=timeout)
        listener.stop()

        if found:
            addr = host_info.get('ip', '')
            port = host_info.get('port', 27183)
            hostname = host_info.get('hostname', addr)
            print(f"    Found host: {hostname} at {addr}:{port}")
            self.host_port = port
            return addr

        return ''

    # --- Connection callbacks ---

    def _on_connected(self):
        """Called when connected to the host."""
        print("\n  [+] Connected to host!")
        print("      Waiting for input control...\n")

    def _on_disconnected(self):
        """Called when disconnected from the host."""
        self._is_active = False
        if self.injector:
            self.injector.release_all()
        print("\n  [-] Disconnected from host")
        print("      Attempting to reconnect...\n")

    def _on_mouse_move(self, dx: int, dy: int):
        """Handle relative mouse movement from host."""
        if self.injector and self._is_active:
            self.injector.move_mouse_relative(dx, dy)

    def _on_mouse_move_abs(self, x: int, y: int):
        """Handle absolute mouse movement from host."""
        if self.injector and self._is_active:
            self.injector.move_mouse_absolute(x, y)

    def _on_mouse_button(self, button: int, state: int):
        """Handle mouse button from host."""
        if self.injector and self._is_active:
            self.injector.mouse_button(button, state)

    def _on_mouse_scroll(self, dx: int, dy: int):
        """Handle scroll from host."""
        if self.injector and self._is_active:
            self.injector.scroll(dx, dy)

    def _on_key_event(self, keycode: int, state: int):
        """Handle keyboard event from host."""
        if self.injector and self._is_active:
            self.injector.key_event(keycode, state)

    def _on_switch_active(self, target: str, cursor_x: int, cursor_y: int):
        """Handle switch-active notification from host."""
        if target and target != '':
            self._is_active = True
            print(f"  [>] Now receiving input (cursor at {cursor_x}, {cursor_y})")
        else:
            self._is_active = False
            if self.injector:
                self.injector.release_all()
            print("  [<] Input control released")

    def _on_cursor_warp(self, x: int, y: int):
        """Handle cursor warp from host."""
        if self.injector:
            self.injector.warp_cursor(x, y)
            log.debug(f"Cursor warped to ({x}, {y})")

    def _on_clipboard(self, content: str):
        """Handle clipboard data from host."""
        if content and content != self._clipboard:
            self._clipboard = content
            set_clipboard_content(content)
            log.info(f"Clipboard updated: {len(content)} chars")

    def _check_clipboard(self):
        """Check if local clipboard has changed and sync to host."""
        try:
            current = get_clipboard_content()
            if current and current != self._clipboard:
                self._clipboard = current
                if self.connection and self.connection.connected:
                    self.connection.send_clipboard(current)
                    log.debug("Clipboard synced to host")
        except Exception:
            pass

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print("\n  Shutting down...")
        self._running = False

    def _shutdown(self):
        """Clean shutdown."""
        print("  Stopping connection...")
        if self.connection:
            self.connection.stop()
        print("  Stopping discovery...")
        if self.beacon:
            self.beacon.stop()
        if self.listener:
            self.listener.stop()
        if self.injector:
            self.injector.release_all()
        print("  Goodbye!\n")


def main():
    parser = argparse.ArgumentParser(
        description='UniCent Client - Receive mouse & keyboard over network',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        '--host', type=str, default=None,
        help='Host IP address (auto-discover if not specified)',
    )
    parser.add_argument(
        '-p', '--port', type=int, default=27183,
        help='Host port (default: 27183)',
    )
    parser.add_argument(
        '--no-tls', action='store_true',
        help='Disable TLS encryption',
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
        help='Disable menu bar icon (terminal-only mode)',
    )

    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S',
    )

    client = UniCentClient(
        host_addr=args.host,
        host_port=args.port,
        use_tls=not args.no_tls,
        cert_dir=args.certs,
    )
    if args.no_tray:
        client._use_tray = False
    client.run()


if __name__ == '__main__':
    main()
