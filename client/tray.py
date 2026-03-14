"""
Client system tray / menu bar icon for macOS.

Provides a menu bar status item with right-click menu
for UniCent client controls.

Uses rumps for native macOS menu bar integration.
Falls back to a simple approach if rumps is not available.
"""

import os
import sys
import threading
import logging
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from client.main import UniCentClient

log = logging.getLogger(__name__)

try:
    import rumps
    RUMPS_AVAILABLE = True
except ImportError:
    RUMPS_AVAILABLE = False
    log.warning("rumps not installed — menu bar icon disabled")


def _get_icon_path(size: int = 64) -> Optional[str]:
    """Get path to client icon."""
    asset_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'assets',
    )
    icon_path = os.path.join(asset_dir, f'icon-client-{size}.png')
    if os.path.exists(icon_path):
        return icon_path
    for s in (64, 128, 48, 32, 256):
        p = os.path.join(asset_dir, f'icon-client-{s}.png')
        if os.path.exists(p):
            return p
    return None


class ClientMenuBarApp(rumps.App if RUMPS_AVAILABLE else object):
    """macOS menu bar application for UniCent client."""

    def __init__(self, client: 'UniCentClient'):
        self._client = client
        self._connected = False
        self._active = False

        icon_path = _get_icon_path(32)

        if RUMPS_AVAILABLE:
            super().__init__(
                name='UniCent',
                title=None,
                icon=icon_path,
                template=True,  # Makes icon adapt to dark/light mode
            )
            self._build_menu()

    def _build_menu(self):
        """Build the menu bar menu."""
        self.menu.clear()

        # Status
        if self._connected:
            if self._active:
                status = '● Receiving input'
            else:
                status = '● Connected to host'
        else:
            status = '○ Disconnected'

        self.menu = [
            rumps.MenuItem(status, callback=None),
            None,  # separator
        ]

        # Host info
        host_addr = getattr(self._client, 'host_addr', None)
        if host_addr:
            host_port = getattr(self._client, 'host_port', 27183)
            self.menu.append(
                rumps.MenuItem(f'Host: {host_addr}:{host_port}', callback=None)
            )
            self.menu.append(None)  # separator

        # Reconnect
        if not self._connected and host_addr:
            reconnect_item = rumps.MenuItem('Reconnect', callback=self._on_reconnect)
            self.menu.append(reconnect_item)
            self.menu.append(None)

        # Quit
        quit_item = rumps.MenuItem('Quit UniCent', callback=self._on_quit)
        self.menu.append(quit_item)

    def update_status(self, connected: bool, active: bool = False):
        """Update the connection/active status."""
        self._connected = connected
        self._active = active
        self._build_menu()

        # Update icon title to show status
        if active:
            self.title = '⚡'
        elif connected:
            self.title = None  # Just show icon
        else:
            self.title = '✕'

    def _on_reconnect(self, sender=None):
        """Force reconnect."""
        conn = getattr(self._client, 'connection', None)
        if conn:
            conn.stop()
            time.sleep(0.5)
            conn.start()

    def _on_quit(self, sender=None):
        """Quit the application."""
        self._client._running = False
        rumps.quit_application()


class ClientTray:
    """Wrapper that manages the macOS menu bar app.

    Since rumps needs to run on the main thread, this class
    provides methods to start the client logic in background threads
    and run the menu bar app on the main thread.
    """

    def __init__(self, client: 'UniCentClient'):
        self.client = client
        self.app: Optional[ClientMenuBarApp] = None

    def run(self):
        """Run the menu bar app on the main thread.

        The client's network/input logic runs in background threads
        (which UniCentClient already does via HostConnection.start()).
        This method blocks until the app quits.
        """
        if not RUMPS_AVAILABLE:
            log.warning("rumps not available, running without menu bar icon")
            # Fall back to the original terminal-based loop
            self.client.run()
            return

        self.app = ClientMenuBarApp(self.client)

        # Patch the client's callbacks to update tray status
        original_on_connected = self.client._on_connected
        original_on_disconnected = self.client._on_disconnected
        original_on_switch_active = self.client._on_switch_active

        def on_connected_wrapper():
            original_on_connected()
            if self.app:
                self.app.update_status(connected=True, active=False)

        def on_disconnected_wrapper():
            original_on_disconnected()
            if self.app:
                self.app.update_status(connected=False, active=False)

        def on_switch_active_wrapper(target, x, y):
            original_on_switch_active(target, x, y)
            is_active = bool(target)
            if self.app:
                self.app.update_status(connected=True, active=is_active)

        # Start client logic in background (without blocking main loop)
        def start_client_bg():
            self.client._start_background()

        bg_thread = threading.Thread(target=start_client_bg, daemon=True)
        bg_thread.start()

        # Give the client a moment to initialize before patching callbacks
        time.sleep(0.5)
        if self.client.connection:
            self.client.connection.on_connected = on_connected_wrapper
            self.client.connection.on_disconnected = on_disconnected_wrapper
            self.client.connection.on_switch_active = on_switch_active_wrapper

        # Run the menu bar app (blocks on main thread)
        self.app.run()

    def stop(self):
        """Stop the menu bar app."""
        if self.app and RUMPS_AVAILABLE:
            rumps.quit_application()
