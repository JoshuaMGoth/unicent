"""
Host system tray icon for Linux (KDE/GNOME/etc).

Provides a right-click menu on the system tray icon with all
UniCent controls. Works alongside Ctrl+Alt keyboard shortcuts.

Requires: pystray, Pillow
"""

import os
import sys
import threading
import logging
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from host.main import UniCentHost

log = logging.getLogger(__name__)

try:
    import pystray
    from pystray import MenuItem, Menu
    from PIL import Image
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False
    log.warning("pystray or Pillow not installed — tray icon disabled")


def _load_icon(size: int = 64) -> 'Image.Image':
    """Load the host icon from assets."""
    asset_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'assets',
    )
    icon_path = os.path.join(asset_dir, f'icon-host-{size}.png')
    if os.path.exists(icon_path):
        return Image.open(icon_path)
    # Try any available size
    for s in (64, 128, 48, 32, 256):
        p = os.path.join(asset_dir, f'icon-host-{s}.png')
        if os.path.exists(p):
            return Image.open(p).resize((size, size), Image.LANCZOS)
    # Generate a fallback icon
    return _generate_fallback_icon(size)


def _generate_fallback_icon(size: int = 64) -> 'Image.Image':
    """Generate a simple fallback icon if no asset exists."""
    from PIL import ImageDraw
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Purple circle with 'H'
    margin = size // 8
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=(128, 90, 213, 255),
    )
    # Draw 'H' text centered
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
                                  size // 2)
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "H", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - tw) / 2, (size - th) / 2 - margin // 2),
        "H",
        fill=(255, 255, 255, 255),
        font=font,
    )
    return img


class HostTray:
    """System tray icon for UniCent host."""

    def __init__(self, host: 'UniCentHost'):
        self.host = host
        self._icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Create and show the tray icon. Must be called from the main thread on some platforms."""
        if not TRAY_AVAILABLE:
            log.warning("System tray not available")
            return

        # When running as root (sudo), we need the user's D-Bus session
        # Preserve these from the calling user's environment
        if os.geteuid() == 0:
            sudo_user = os.environ.get('SUDO_USER', '')
            if sudo_user and not os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
                # Try to get D-Bus address from the user's session
                try:
                    import subprocess
                    result = subprocess.run(
                        ['su', '-', sudo_user, '-c',
                         'echo $DBUS_SESSION_BUS_ADDRESS'],
                        capture_output=True, text=True, timeout=5,
                    )
                    dbus_addr = result.stdout.strip()
                    if dbus_addr:
                        os.environ['DBUS_SESSION_BUS_ADDRESS'] = dbus_addr
                except Exception as e:
                    log.debug(f"Could not get DBUS address: {e}")

            if not os.environ.get('DISPLAY'):
                os.environ['DISPLAY'] = ':0'

        try:
            icon_image = _load_icon(64)
        except Exception as e:
            log.warning(f"Could not load tray icon image: {e}")
            return

        self._icon = pystray.Icon(
            name='unicent-host',
            icon=icon_image,
            title='UniCent Host',
            menu=self._build_menu(),
        )
        # Run in a thread so it doesn't block
        self._thread = threading.Thread(target=self._run_icon, daemon=True)
        self._thread.start()
        log.info("System tray icon started")

    def _run_icon(self):
        """Run the icon, catching errors gracefully."""
        try:
            self._icon.run()
        except Exception as e:
            log.warning(f"Tray icon error (will continue without tray): {e}")
            self._icon = None

    def stop(self):
        """Remove the tray icon."""
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

    def update_menu(self):
        """Refresh the tray menu (e.g. when clients connect/disconnect)."""
        if self._icon:
            self._icon.menu = self._build_menu()
            try:
                self._icon.update_menu()
            except Exception:
                pass

    def update_tooltip(self, text: str):
        """Update the tray icon tooltip."""
        if self._icon:
            self._icon.title = text

    def _build_menu(self) -> 'Menu':
        """Build the right-click context menu."""
        items = []

        # --- Status header ---
        active = getattr(self.host, 'layout', None)
        active_machine = active.active_machine if active else 'host'
        controlling = 'HOST (local)' if active_machine == 'host' else active_machine

        items.append(MenuItem(
            f'Controlling: {controlling}',
            action=None,
            enabled=False,
        ))
        items.append(Menu.SEPARATOR)

        # --- Switch options ---
        items.append(MenuItem(
            'Switch to Host (local)      Ctrl+Alt+1',
            lambda: self.host._hotkey_switch_to(0),
        ))

        # Connected clients
        server = getattr(self.host, 'server', None)
        clients = server.get_client_list() if server else []
        for i, client in enumerate(clients):
            client_name = client.get('hostname', client.get('client_id', f'Client {i+1}'))
            addr = client.get('address', '')
            label = f'Switch to {client_name}      Ctrl+Alt+{i+2}'
            idx = i + 1
            items.append(MenuItem(
                label,
                lambda _item=None, _idx=idx: self.host._hotkey_switch_to(_idx),
            ))

        if not clients:
            items.append(MenuItem(
                'No clients connected',
                action=None,
                enabled=False,
            ))

        items.append(MenuItem(
            'Switch to Next      Ctrl+Alt+S',
            lambda: self.host._hotkey_switch_next(),
        ))

        items.append(Menu.SEPARATOR)

        # --- Side placement ---
        current_side = getattr(self.host, 'client_side', 'right')
        other_side = 'left' if current_side == 'right' else 'right'
        items.append(MenuItem(
            f'Clients on: {current_side.upper()} side',
            action=None,
            enabled=False,
        ))
        items.append(MenuItem(
            f'Move clients to {other_side} side',
            lambda: self._toggle_side(),
        ))

        items.append(Menu.SEPARATOR)

        # --- Actions ---
        items.append(MenuItem(
            'Sync Clipboard      Ctrl+Alt+C',
            lambda: self.host._hotkey_clipboard_sync(),
        ))

        items.append(Menu.SEPARATOR)

        # --- Connected clients info ---
        if clients:
            items.append(MenuItem(
                f'Connected Clients ({len(clients)})',
                Menu(*[
                    MenuItem(
                        f'{c.get("hostname", c["client_id"])} — {c.get("address", "")}',
                        action=None,
                        enabled=False,
                    )
                    for c in clients
                ]),
            ))
            items.append(Menu.SEPARATOR)

        # --- Quit ---
        items.append(MenuItem(
            'Quit      Ctrl+Alt+Q',
            self._on_quit,
        ))

        return Menu(*items)

    def _on_quit(self):
        """Handle quit from tray menu."""
        self.host._hotkey_quit()
        self.stop()

    def _toggle_side(self):
        """Toggle client placement side."""
        current = getattr(self.host, 'client_side', 'right')
        new_side = 'left' if current == 'right' else 'right'
        self.host.client_side = new_side
        self.host.layout.client_side = new_side
        self.host.layout._recalculate_layout()
        print(f"\n  Clients moved to {new_side.upper()} side")
        self.host._print_layout()
        self.update_menu()
