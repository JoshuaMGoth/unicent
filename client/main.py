"""
UniCent Client — cross-platform.

Connects to a UniCent host and injects received mouse/keyboard events
into the local system.

Usage:
    python -m client.main --host <HOST_IP> [--port PORT]
                          [--no-tls] [--no-tray] [-v]
"""

import argparse
import logging
import os
import platform
import signal
import socket
import sys
import threading
import time
from typing import Optional

from client.connection import HostConnection
from client.input_inject import InputInjector, check_accessibility_permissions
from client.screen_manager import get_client_screens, get_clipboard_content, set_clipboard_content
from client.config import get_host_ip, set_host_ip

log = logging.getLogger(__name__)

_SYSTEM = platform.system()


class UniCentClient:
    """
    Main client controller.

    1.  Detects local screens.
    2.  Connects to the host via TCP.
    3.  Receives input events and injects them locally.
    4.  Handles clipboard sync, cursor warp, active/inactive states.
    """

    def __init__(self, host_addr: str = '', host_port: int = 27183,
                 use_tls: bool = True, use_tray: bool = True,
                 cert_file: str = '', ca_file: str = '',
                 verbose: bool = False):
        # If no host provided, try to use stored config
        if not host_addr:
            stored_ip = get_host_ip()
            if stored_ip:
                host_addr = stored_ip
                log.info(f"Using stored host IP from config: {stored_ip}")
        
        self.host_addr = host_addr
        self.host_port = host_port
        self.use_tls = use_tls
        self.use_tray = use_tray
        self.verbose = verbose

        # TLS
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.cert_file = cert_file or os.path.join(base_dir, 'certs', 'client.crt')
        self.ca_file = ca_file or os.path.join(base_dir, 'certs', 'ca.crt')
        if not use_tls:
            self.cert_file = self.ca_file = ''

        # Components
        self.connection: Optional[HostConnection] = None
        self.injector = None
        self.discovery_listener = None

        # State
        self._running = False
        self._active = False
        self._hostname = socket.gethostname()
        self._screens: list = []
        self._lock = threading.Lock()

    # ──── Lifecycle ────────────────────────────────────────

    def run(self):
        """Main entry-point. Blocks until quit."""
        self._running = True
        self._print_banner()

        # 1. Check permissions (macOS accessibility, etc.)
        if not check_accessibility_permissions():
            print("  ⚠  Accessibility permissions not granted.")
            print("     On macOS: System Settings → Privacy → Accessibility")
            print("     On Linux: ensure xdotool is installed")
            print()

        # 2. Detect screens
        self._screens = get_client_screens()
        self._print_screens()

        # 3. Create injector
        self.injector = InputInjector()
        log.info(f"Input injector ready ({_SYSTEM})")

        # 4. Optionally start with tray
        if self.use_tray:
            try:
                from client.tray import ClientTray, TRAY_AVAILABLE
                if TRAY_AVAILABLE:
                    tray = ClientTray(self)
                    tray.run()  # May block on macOS (rumps)
                    return
            except ImportError:
                log.warning("Tray library not available")
            except Exception as e:
                log.warning(f"Tray icon disabled: {e}")

        # 5. No tray – run in terminal mode
        self._run_terminal_mode()

    def _run_terminal_mode(self):
        """Run without tray icon — terminal-only."""
        self._start_background()
        try:
            while self._running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n  Interrupted.")
        finally:
            self._shutdown()

    def _start_background(self):
        """Start connection, discovery, and injector in the background."""
        # Get clipboard for handshake
        clipboard = ''
        try:
            clipboard = get_clipboard_content()
        except Exception:
            pass

        # Start connection
        self.connection = HostConnection(
            host_addr=self.host_addr,
            host_port=self.host_port,
            cert_file=self.cert_file if self.use_tls else '',
            ca_file=self.ca_file if self.use_tls else '',
            hostname=self._hostname,
        )
        self.connection.set_screens(self._screens)
        self.connection.set_clipboard(clipboard)

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
        self.connection.on_wake_screen = self._on_wake_screen

        self.connection.start()

        # Auto-discovery (listen for hosts if no address given)
        if not self.host_addr:
            try:
                from shared.discovery import DiscoveryListener
                self.discovery_listener = DiscoveryListener(
                    on_discovered=self._on_host_discovered,
                    filter_role='host',
                )
                self.discovery_listener.start()
                print("  Listening for hosts via auto-discovery...")
            except Exception as e:
                log.warning(f"Discovery disabled: {e}")

        print("  Connecting to host...")
        print()

    def _shutdown(self):
        self._running = False
        print("\n  Shutting down...")
        if self.connection:
            self.connection.stop()
        if self.discovery_listener:
            self.discovery_listener.stop()
        print("  Goodbye.")

    # ──── Connection callbacks ─────────────────────────────

    def _on_connected(self):
        log.info("Connected to host")
        # Save the host IP for future auto-reconnection
        if self.host_addr:
            set_host_ip(self.host_addr)
        print(f"\n  ● Connected to {self.host_addr}:{self.host_port}")

    def _on_disconnected(self):
        self._active = False
        log.info("Disconnected from host")
        print("\n  ○ Disconnected from host")

    # ──── Input event callbacks ────────────────────────────

    def _on_mouse_move(self, dx: int, dy: int):
        if self._active and self.injector:
            self.injector.move_mouse_relative(dx, dy)

    def _on_mouse_move_abs(self, x: int, y: int):
        if self._active and self.injector:
            self.injector.move_mouse_absolute(x, y)

    def _on_mouse_button(self, button: int, state: int):
        if self._active and self.injector:
            self.injector.mouse_button(button, state)

    def _on_mouse_scroll(self, dx: int, dy: int):
        if self._active and self.injector:
            self.injector.scroll(dx, dy)

    def _on_key_event(self, keycode: int, state: int):
        if self._active and self.injector:
            self.injector.key_event(keycode, state)

    def _on_switch_active(self, target: str, x: int, y: int):
        """Host is switching control to/from us."""
        if target and target != '':
            self._active = True
            log.info(f"Now active — receiving input (cursor at {x},{y})")
            print(f"\n  ⚡ Active — receiving input (cursor at {x},{y})")
            if self.injector:
                self.injector.move_mouse_absolute(x, y)
        else:
            # Becoming inactive — send our clipboard to the host
            self._send_clipboard_to_host()
            self._active = False
            log.info("Now inactive")
            print("\n  ● Inactive — host has control")

    def _on_cursor_warp(self, x: int, y: int):
        if self.injector:
            self.injector.move_mouse_absolute(x, y)
            log.debug(f"Cursor warped to ({x}, {y})")

    def _on_clipboard(self, content: str):
        if content:
            try:
                set_clipboard_content(content)
                log.info(f"Clipboard received ({len(content)} chars)")
            except Exception as e:
                log.warning(f"Failed to set clipboard: {e}")

    def _on_wake_screen(self):
        """Wake the display from sleep/lock by simulating input."""
        log.info("Wake-screen signal received")
        print("\n  \u26a1 Wake signal received — waking display")
        if self.injector:
            try:
                # Simulate a tiny mouse move to wake the display
                self.injector.move_mouse_relative(1, 0)
                import time
                time.sleep(0.05)
                self.injector.move_mouse_relative(-1, 0)
            except Exception as e:
                log.warning(f"Wake mouse-move failed: {e}")
            try:
                # Press and release Shift to further wake the screen
                # Shift (keycode 42 Linux) is harmless and wakes displays
                self.injector.key_event(42, 1)  # press
                import time
                time.sleep(0.05)
                self.injector.key_event(42, 0)  # release
            except Exception as e:
                log.warning(f"Wake key-event failed: {e}")
        # Mark ourselves as active so keyboard input flows
        self._active = True

    def _send_clipboard_to_host(self):
        """Read local clipboard and send it to the host."""
        try:
            clip = get_clipboard_content()
            if clip and self.connection:
                self.connection.send_clipboard(clip)
                log.info(f"Clipboard sent to host ({len(clip)} chars)")
                print(f"  ✦ Clipboard sent to host ({len(clip)} chars)")
        except Exception as e:
            log.warning(f"Clipboard send failed: {e}")

    # ──── Discovery ────────────────────────────────────────

    def _on_host_discovered(self, info: dict):
        """Called when a host is found via discovery."""
        host_ip = info.get('ip', '')
        host_port = info.get('port', 27183)
        hostname = info.get('hostname', host_ip)
        log.info(f"Discovered host: {hostname} at {host_ip}:{host_port}")
        print(f"\n  Discovered host: {hostname} ({host_ip}:{host_port})")
        if not self.host_addr:
            self.host_addr = host_ip
            self.host_port = host_port
            if self.connection:
                self.connection.host_addr = host_ip
                self.connection.host_port = host_port

    # ──── Display helpers ──────────────────────────────────

    def _print_banner(self):
        print()
        print("  ╔══════════════════════════════════════╗")
        print("  ║          UniCent Client              ║")
        print("  ╚══════════════════════════════════════╝")
        print()
        tls_str = 'TLS' if self.use_tls else 'NO TLS'
        print(f"  Hostname : {self._hostname}")
        host_display = self.host_addr or '(auto-discover)'
        print(f"  Host     : {host_display}:{self.host_port} ({tls_str})")
        print(f"  Platform : {_SYSTEM} ({platform.machine()})")
        print()

    def _print_screens(self):
        print("  Screens:")
        for s in self._screens:
            print(f"    {s.get('name', '?')}: {s['width']}x{s['height']}"
                  f" @ +{s.get('x', 0)}+{s.get('y', 0)}"
                  f" (scale {s.get('scale', 1.0)}x)")
        print()


# ────────────────────────────────────────────────────────────
#  CLI entry-point
# ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='UniCent Client')
    parser.add_argument('--host', default='', help='Host IP address / hostname')
    parser.add_argument('--port', type=int, default=27183, help='Host TCP port (default 27183)')
    parser.add_argument('--no-tls', action='store_true', help='Disable TLS encryption')
    parser.add_argument('--no-tray', action='store_true', help='Disable system tray / menu bar icon')
    parser.add_argument('--cert', default='', help='Client TLS certificate file')
    parser.add_argument('--ca', default='', help='CA certificate file')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose logging')
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S',
    )

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    client = UniCentClient(
        host_addr=args.host,
        host_port=args.port,
        use_tls=not args.no_tls,
        use_tray=not args.no_tray,
        cert_file=args.cert,
        ca_file=args.ca,
        verbose=args.verbose,
    )
    client.run()


if __name__ == '__main__':
    main()
