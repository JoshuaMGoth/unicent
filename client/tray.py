"""
Client system tray / menu bar icon — cross-platform.

Uses rumps on macOS (native menu bar), pystray on Linux/Windows.
Icon: Purple rounded-rectangle with white 'U'.

Includes About, Check for Updates, and Report a Bug.
"""

import os
import sys
import platform
import threading
import logging
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from client.main import UniCentClient

from shared.version import __version__, __app_name__

log = logging.getLogger(__name__)

_SYSTEM = platform.system()

TRAY_AVAILABLE = False
_USE_RUMPS = False

if _SYSTEM == 'Darwin':
    try:
        import rumps
        TRAY_AVAILABLE = True
        _USE_RUMPS = True
    except ImportError:
        pass

if not TRAY_AVAILABLE:
    try:
        import pystray
        from pystray import MenuItem, Menu
        from PIL import Image
        TRAY_AVAILABLE = True
    except ImportError:
        log.warning("No tray library available — tray icon disabled")


def _get_u_icon_path(size: int = 64) -> Optional[str]:
    """Get path to 'U' icon file."""
    asset_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'assets',
    )
    icon_path = os.path.join(asset_dir, f'icon-u-{size}.png')
    if os.path.exists(icon_path):
        return icon_path
    for s in (64, 128, 48, 32, 256):
        p = os.path.join(asset_dir, f'icon-u-{s}.png')
        if os.path.exists(p):
            return p
    return None


def _load_u_icon(size: int = 64):
    """Load the 'U' icon as PIL Image (for pystray)."""
    from PIL import Image as PILImage, ImageDraw, ImageFont
    asset_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'assets',
    )
    icon_path = os.path.join(asset_dir, f'icon-u-{size}.png')
    if os.path.exists(icon_path):
        return PILImage.open(icon_path)
    for s in (64, 128, 48, 32, 256):
        p = os.path.join(asset_dir, f'icon-u-{s}.png')
        if os.path.exists(p):
            return PILImage.open(p).resize((size, size), PILImage.LANCZOS)
    # Generate
    img = PILImage.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = max(1, size // 16)
    radius = size // 4
    draw.rounded_rectangle([margin, margin, size - margin - 1,
                            size - margin - 1],
                           radius=radius, fill=(75, 0, 130, 255))
    font_size = int(size * 0.65)
    font = ImageFont.load_default()
    for fp in ["/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "/System/Library/Fonts/Helvetica.ttc",
               "C:/Windows/Fonts/arialbd.ttf"]:
        try:
            font = ImageFont.truetype(fp, font_size)
            break
        except Exception:
            continue
    bbox = draw.textbbox((0, 0), "U", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]),
              "U", fill=(255, 255, 255, 255), font=font)
    return img


# ─── Dialog launchers (shared by all backends) ───────────────

def _show_about():
    try:
        from shared.dialogs import show_about_dialog
        show_about_dialog()
    except Exception as e:
        log.warning(f"Could not show About dialog: {e}")


def _show_updates():
    try:
        from shared.dialogs import show_update_dialog
        show_update_dialog()
    except Exception as e:
        log.warning(f"Could not show Update dialog: {e}")


def _show_bug_report():
    try:
        from shared.dialogs import show_bug_report_dialog
        show_bug_report_dialog()
    except Exception as e:
        log.warning(f"Could not show Bug Report dialog: {e}")


# ─── macOS: rumps-based menu bar app ───────────────────────────

if _USE_RUMPS:
    class ClientMenuBarApp(rumps.App):
        """macOS menu bar application for UniCent client."""

        def __init__(self, client: 'UniCentClient'):
            self._client = client
            self._connected = False
            self._active = False
            icon_path = _get_u_icon_path(32)
            super().__init__(
                name='UniCent',
                title=None,
                icon=icon_path,
                template=True,
            )
            self._build_menu()

        def _build_menu(self):
            self.menu.clear()
            if self._connected:
                status = '● Receiving input' if self._active \
                    else '● Connected to host'
            else:
                status = '○ Disconnected'
            self.menu = [rumps.MenuItem(status, callback=None), None]
            host_addr = getattr(self._client, 'host_addr', None)
            if host_addr:
                host_port = getattr(self._client, 'host_port', 27183)
                self.menu.append(rumps.MenuItem(
                    f'Host: {host_addr}:{host_port}', callback=None))
                self.menu.append(None)
            if not self._connected and host_addr:
                self.menu.append(rumps.MenuItem(
                    'Reconnect', callback=self._on_reconnect))
                self.menu.append(None)

            # Tools
            self.menu.append(None)
            self.menu.append(rumps.MenuItem(
                'Check for Updates...', callback=self._on_updates))
            self.menu.append(rumps.MenuItem(
                'Report a Bug...', callback=self._on_bug_report))
            self.menu.append(None)
            self.menu.append(rumps.MenuItem(
                f'About {__app_name__} v{__version__}',
                callback=self._on_about))
            self.menu.append(None)
            self.menu.append(rumps.MenuItem(
                'Quit UniCent', callback=self._on_quit))

        def update_status(self, connected: bool, active: bool = False):
            self._connected = connected
            self._active = active
            self._build_menu()
            if active:
                self.title = '⚡'
            elif connected:
                self.title = None
            else:
                self.title = '✕'

        def _on_reconnect(self, sender=None):
            conn = getattr(self._client, 'connection', None)
            if conn:
                conn.stop()
                time.sleep(0.5)
                conn.start()

        def _on_about(self, sender=None):
            _show_about()

        def _on_updates(self, sender=None):
            _show_updates()

        def _on_bug_report(self, sender=None):
            _show_bug_report()

        def _on_quit(self, sender=None):
            self._client._running = False
            rumps.quit_application()


# ─── Cross-platform: pystray-based tray ───────────────────────

class _PystrayClientTray:
    """pystray-based system tray for Linux/Windows client."""

    def __init__(self, client: 'UniCentClient'):
        self.client = client
        self._icon = None
        self._thread: Optional[threading.Thread] = None
        self._connected = False
        self._active = False

    def start(self):
        try:
            icon_image = _load_u_icon(64)
        except Exception as e:
            log.warning(f"Could not load tray icon: {e}")
            return
        self._icon = pystray.Icon(
            name='unicent-client',
            icon=icon_image,
            title=f'{__app_name__} Client v{__version__}',
            menu=self._build_menu(),
        )
        self._thread = threading.Thread(target=self._run_icon, daemon=True)
        self._thread.start()

    def _run_icon(self):
        try:
            self._icon.run()
        except Exception as e:
            log.warning(f"Tray icon error: {e}")

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

    def update_status(self, connected: bool, active: bool = False):
        self._connected = connected
        self._active = active
        if self._icon:
            self._icon.menu = self._build_menu()
            tooltip = f'{__app_name__} — Receiving input' if active else (
                f'{__app_name__} — Connected' if connected
                else f'{__app_name__} — Disconnected')
            self._icon.title = tooltip
            try:
                self._icon.update_menu()
            except Exception:
                pass

    def _build_menu(self):
        if self._connected:
            status = '● Receiving input' if self._active else '● Connected'
        else:
            status = '○ Disconnected'
        items = [
            MenuItem(status, action=None, enabled=False),
            Menu.SEPARATOR,
        ]
        host_addr = getattr(self.client, 'host_addr', None)
        if host_addr:
            host_port = getattr(self.client, 'host_port', 27183)
            items.append(MenuItem(f'Host: {host_addr}:{host_port}',
                                  action=None, enabled=False))
            items.append(Menu.SEPARATOR)
        if not self._connected and host_addr:
            items.append(MenuItem('Reconnect', lambda: self._reconnect()))
            items.append(Menu.SEPARATOR)

        # Tools
        items.append(MenuItem('Check for Updates...',
                              lambda: _show_updates()))
        items.append(MenuItem('Report a Bug...',
                              lambda: _show_bug_report()))
        items.append(Menu.SEPARATOR)
        items.append(MenuItem(f'About {__app_name__} v{__version__}',
                              lambda: _show_about()))
        items.append(Menu.SEPARATOR)
        items.append(MenuItem('Quit UniCent', lambda: self._quit()))
        return Menu(*items)

    def _reconnect(self):
        conn = getattr(self.client, 'connection', None)
        if conn:
            conn.stop()
            time.sleep(0.5)
            conn.start()

    def _quit(self):
        self.client._running = False
        self.stop()


# ─── Unified wrapper class ────────────────────────────────────

class ClientTray:
    """Wrapper that manages the client tray icon across platforms.

    On macOS uses rumps (runs on main thread).
    On Linux/Windows uses pystray (runs in background thread).
    """

    def __init__(self, client: 'UniCentClient'):
        self.client = client
        self.app = None         # rumps app (macOS)
        self._pystray = None    # pystray tray (Linux/Windows)

    def run(self):
        """Run the tray. On macOS this blocks (rumps main loop)."""
        if _USE_RUMPS:
            self.app = ClientMenuBarApp(self.client)
            # Patch callbacks for status updates
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
                if self.app:
                    self.app.update_status(
                        connected=True, active=bool(target))

            # Start client logic in background
            bg_thread = threading.Thread(
                target=self.client._start_background, daemon=True)
            bg_thread.start()
            time.sleep(0.5)

            # Patch callbacks after connection is set up
            if self.client.connection:
                self.client.connection.on_connected = on_connected_wrapper
                self.client.connection.on_disconnected = \
                    on_disconnected_wrapper
                self.client.connection.on_switch_active = \
                    on_switch_active_wrapper

            # Run rumps on main thread (blocks)
            self.app.run()
        elif TRAY_AVAILABLE:
            # pystray for Linux/Windows — doesn't need main thread
            self._pystray = _PystrayClientTray(self.client)

            original_on_connected = self.client._on_connected
            original_on_disconnected = self.client._on_disconnected
            original_on_switch_active = self.client._on_switch_active

            def on_connected_wrapper():
                original_on_connected()
                if self._pystray:
                    self._pystray.update_status(connected=True)

            def on_disconnected_wrapper():
                original_on_disconnected()
                if self._pystray:
                    self._pystray.update_status(connected=False)

            def on_switch_active_wrapper(target, x, y):
                original_on_switch_active(target, x, y)
                if self._pystray:
                    self._pystray.update_status(
                        connected=True, active=bool(target))

            self._pystray.start()
            self.client._start_background()

            # Patch callbacks after background start
            if self.client.connection:
                self.client.connection.on_connected = on_connected_wrapper
                self.client.connection.on_disconnected = \
                    on_disconnected_wrapper
                self.client.connection.on_switch_active = \
                    on_switch_active_wrapper
        else:
            # No tray available, just run terminal mode
            self.client._run_terminal_mode()

    def stop(self):
        if self._pystray:
            self._pystray.stop()
