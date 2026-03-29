"""
Client system tray / menu bar icon — cross-platform.

Uses rumps on macOS (native menu bar), pystray on Linux/Windows.
Icon: Purple rounded-rectangle with white 'U'.

Features: status display, host search, manual IP entry,
auto-update checking, about, and bug report.
"""

import os
import sys
import platform
import threading
import logging
import time
import queue
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from client.main import UniCentClient

from shared.version import __version__, __app_name__, __author__, __website__, __repo_url__, __description__

log = logging.getLogger(__name__)

# Cache version info for native dialogs (avoids importing shared.dialogs/tkinter)
_about_author = __author__
_about_website = __website__
_about_repo_url = __repo_url__

_SYSTEM = platform.system()

# ─── macOS: override NSBundle name BEFORE any NSApplication is created ───
# This changes the menu bar app name from "Python" to "UniCent Client".
if _SYSTEM == 'Darwin':
    try:
        from Foundation import NSBundle
        _bundle = NSBundle.mainBundle()
        _info = _bundle.infoDictionary()
        _info['CFBundleName'] = 'UniCent Client'
        _info['CFBundleDisplayName'] = 'UniCent Client'
    except Exception:
        pass
    # Set the application icon so macOS shows our icon everywhere
    try:
        from AppKit import NSApplication, NSImage
        _icon_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'assets',
        )
        for _sz in (128, 64, 256, 48, 32):
            _candidate = os.path.join(_icon_dir, f'icon-u-{_sz}.png')
            if os.path.exists(_candidate):
                _ns_img = NSImage.alloc().initWithContentsOfFile_(_candidate)
                if _ns_img:
                    NSApplication.sharedApplication().setApplicationIconImage_(_ns_img)
                break
    except Exception:
        pass

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


def _show_updates(update_info=None):
    try:
        from shared.dialogs import show_update_dialog
        show_update_dialog(update_info=update_info)
    except Exception as e:
        log.warning(f"Could not show Update dialog: {e}")


def _show_bug_report():
    try:
        from shared.dialogs import show_bug_report_dialog
        show_bug_report_dialog()
    except Exception as e:
        log.warning(f"Could not show Bug Report dialog: {e}")


def _search_for_host(client: 'UniCentClient'):
    """Scan Tailscale peers for a UniCent host and connect."""
    def _do_scan():
        try:
            from shared.discovery import scan_for_host
            log.info("Scanning for hosts...")
            found = scan_for_host()
            if found:
                log.info(f"Found host at {found}")
                client.host_addr = found
                if client.connection:
                    client.connection.host_addr = found
                    if not client.connection.connected:
                        client.connection.stop()
                        time.sleep(0.3)
                        client.connection.start()
            else:
                log.info("No host found on network")
        except Exception as e:
            log.warning(f"Host scan failed: {e}")
    threading.Thread(target=_do_scan, daemon=True).start()


def _set_host_ip(client: 'UniCentClient', ip: str):
    """Manually set the host IP and reconnect."""
    ip = ip.strip()
    if not ip:
        return
    log.info(f"Manually setting host to {ip}")
    from client.config import set_host_ip
    set_host_ip(ip)
    client.host_addr = ip
    if client.connection:
        client.connection.host_addr = ip
        client.connection.stop()
        time.sleep(0.3)
        client.connection.start()


# ─── macOS: rumps-based menu bar app ───────────────────────────

if _USE_RUMPS:
    class ClientMenuBarApp(rumps.App):
        """macOS menu bar application for UniCent client."""

        def __init__(self, client: 'UniCentClient'):
            self._client = client
            self._connected = False
            self._active = False
            self._update_info = None
            self._ui_updates: queue.Queue = queue.Queue()
            icon_path = _get_u_icon_path(16) or _get_u_icon_path(32)
            super().__init__(
                name='UniCent',
                title=None,
                icon=icon_path,
                template=False,
            )
            self._build_menu()
            # rumps timers run on the app loop (main thread). Use this
            # to safely apply UI mutations queued by worker threads.
            self._ui_timer = rumps.Timer(self._drain_ui_updates, 0.2)
            self._ui_timer.start()
            self._check_updates_async()

        def _build_menu(self):
            self.menu.clear()
            if self._connected:
                status = '● Receiving input' if self._active \
                    else '● Connected to host'
            else:
                status = '○ Disconnected'

            items = [rumps.MenuItem(status, callback=None), None]

            host_addr = getattr(self._client, 'host_addr', None)
            if host_addr:
                host_port = getattr(self._client, 'host_port', 27183)
                items.append(rumps.MenuItem(
                    f'Host: {host_addr}:{host_port}', callback=None))
                items.append(None)
            if not self._connected and host_addr:
                items.append(rumps.MenuItem(
                    'Reconnect', callback=self._on_reconnect))

            # Host discovery
            items.append(None)
            items.append(rumps.MenuItem(
                'Search for Host...', callback=self._on_search_host))
            items.append(rumps.MenuItem(
                'Set Host IP...', callback=self._on_set_host_ip))

            # Tools
            items.append(None)
            if self._update_info:
                items.append(rumps.MenuItem(
                    f'⬆ Update available: v{self._update_info["latest"]}',
                    callback=self._on_updates))
            items.append(rumps.MenuItem(
                'Check for Updates...', callback=self._on_updates))
            items.append(rumps.MenuItem(
                'Report a Bug...', callback=self._on_bug_report))
            items.append(None)
            items.append(rumps.MenuItem(
                f'About {__app_name__} v{__version__}',
                callback=self._on_about))
            items.append(None)
            items.append(rumps.MenuItem(
                'Quit UniCent', callback=self._on_quit))

            self.menu = items

        def _set_status(self, connected: bool, active: bool = False):
            self._connected = connected
            self._active = active
            self._build_menu()
            if active:
                self.title = '⚡'
            elif connected:
                self.title = None
            else:
                self.title = '✕'

        def update_status(self, connected: bool, active: bool = False):
            if threading.current_thread() is threading.main_thread():
                self._set_status(connected, active)
            else:
                self.enqueue_status(connected, active)

        def enqueue_status(self, connected: bool, active: bool = False):
            self._ui_updates.put(('status', (connected, active)))

        def enqueue_update_info(self, info: Optional[dict]):
            self._ui_updates.put(('update_info', info))

        def _drain_ui_updates(self, _sender=None):
            latest_status = None
            latest_update = None
            pending_update_alert = None
            while True:
                try:
                    kind, payload = self._ui_updates.get_nowait()
                except queue.Empty:
                    break
                if kind == 'status':
                    latest_status = payload
                elif kind == 'update_info':
                    latest_update = payload
                elif kind == 'show_update_alert':
                    pending_update_alert = payload

            if latest_status is not None:
                self._set_status(*latest_status)
            if latest_update is not None:
                self._update_info = latest_update
                self._build_menu()
            if pending_update_alert is not None:
                self._update_info = pending_update_alert
                self._build_menu()
                self._on_updates()

        def _on_reconnect(self, sender=None):
            conn = getattr(self._client, 'connection', None)
            if conn:
                conn.stop()
                time.sleep(0.5)
                conn.start()

        def _on_search_host(self, sender=None):
            _search_for_host(self._client)

        def _on_set_host_ip(self, sender=None):
            response = rumps.Window(
                message='Enter the host IP address:',
                title='Set Host IP',
                default_text=getattr(self._client, 'host_addr', '') or '',
                ok='Connect',
                cancel='Cancel',
            ).run()
            if response.clicked:
                _set_host_ip(self._client, response.text)

        def _on_about(self, sender=None):
            # Use native rumps alert — Tkinter crashes on macOS
            # when rumps owns the main thread.
            rumps.alert(
                title=f'About {__app_name__} v{__version__}',
                message=(
                    f'{__description__}\n\n'
                    f'Version {__version__}\n'
                    f'A {_about_author} Product\n\n'
                    f'{_about_website}\n'
                    f'{_about_repo_url}'
                ),
                ok='Close',
            )

        def _on_updates(self, sender=None):
            if self._update_info:
                resp = rumps.alert(
                    title='Update Available',
                    message=(
                        f'Current: v{self._update_info["current"]}\n'
                        f'Latest:  v{self._update_info["latest"]}\n\n'
                        f'Open the releases page to download?'
                    ),
                    ok='Open Releases',
                    cancel='Cancel',
                )
                if resp == 1:
                    import webbrowser
                    webbrowser.open(self._update_info.get(
                        'url', f'{_about_repo_url}/releases'))
            else:
                # Check inline and report
                def _bg_check():
                    from shared.updater import check_for_update
                    info = check_for_update()
                    if info:
                        self.enqueue_update_info(info)
                        self._ui_updates.put(('show_update_alert', info))
                    else:
                        rumps.notification(
                            'UniCent', '',
                            f'You are running the latest version (v{__version__}).'
                        )
                threading.Thread(target=_bg_check, daemon=True).start()

        def _on_bug_report(self, sender=None):
            import webbrowser
            webbrowser.open(f'{_about_repo_url}/issues')

        def _on_quit(self, sender=None):
            self._client._running = False
            rumps.quit_application()

        def _check_updates_async(self):
            try:
                from shared.updater import check_for_update_async
                def _on_result(info):
                    if info:
                        self.enqueue_update_info(info)
                        log.info(f"Update available: v{info['latest']} "
                                 f"(current: v{info['current']})")
                check_for_update_async(_on_result)
            except Exception as e:
                log.debug(f"Background update check failed: {e}")


# ─── Cross-platform: pystray-based tray ───────────────────────

class _PystrayClientTray:
    """pystray-based system tray for Linux/Windows client."""

    def __init__(self, client: 'UniCentClient'):
        self.client = client
        self._icon = None
        self._thread: Optional[threading.Thread] = None
        self._connected = False
        self._active = False
        self._update_info: Optional[dict] = None

    def start(self):
        try:
            icon_image = _load_u_icon(128)
        except Exception as e:
            log.warning(f"Could not load tray icon: {e}")
            return
        self._icon = pystray.Icon(
            name='unicent-client',
            icon=icon_image,
            title=__app_name__,
            menu=self._build_menu(),
        )
        self._thread = threading.Thread(target=self._run_icon, daemon=True)
        self._thread.start()
        self._check_updates_async()

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
        self.update_menu()

    def update_menu(self):
        if self._icon:
            self._icon.menu = self._build_menu()
            self._icon.title = __app_name__
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

        # Host discovery
        items.append(MenuItem('Search for Host...',
                              lambda: _search_for_host(self.client)))
        items.append(MenuItem('Set Host IP...',
                              lambda: self._prompt_host_ip()))
        items.append(Menu.SEPARATOR)

        # Tools
        if self._update_info:
            items.append(MenuItem(
                f'⬆ Update available: v{self._update_info["latest"]}',
                lambda: _show_updates(self._update_info)))
        items.append(MenuItem('Check for Updates...',
                              lambda: _show_updates(self._update_info)))
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

    def _prompt_host_ip(self):
        """Prompt user for host IP using a simple dialog."""
        try:
            from shared.dialogs import show_input_dialog
            ip = show_input_dialog(
                title='Set Host IP',
                prompt='Enter the host IP address:',
                default=getattr(self.client, 'host_addr', '') or '',
            )
            if ip:
                _set_host_ip(self.client, ip)
        except Exception:
            # Fallback: use stdin if no GUI dialog available
            log.info("Enter host IP in the terminal")

    def _quit(self):
        self.client._running = False
        self.stop()

    def _check_updates_async(self):
        try:
            from shared.updater import check_for_update_async
            def _on_result(info):
                if info:
                    self._update_info = info
                    log.info(f"Update available: v{info['latest']} "
                             f"(current: v{info['current']})")
                    self.update_menu()
            check_for_update_async(_on_result)
        except Exception as e:
            log.debug(f"Background update check failed: {e}")


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
                    self.app.enqueue_status(connected=True, active=False)

            def on_disconnected_wrapper():
                original_on_disconnected()
                if self.app:
                    self.app.enqueue_status(connected=False, active=False)

            def on_switch_active_wrapper(target, x, y):
                original_on_switch_active(target, x, y)
                if self.app:
                    self.app.enqueue_status(
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
