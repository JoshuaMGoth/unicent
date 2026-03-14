"""
Host system tray icon — cross-platform.

Provides a right-click menu on the system tray icon with all
UniCent controls. Works on Linux (KDE/GNOME/etc), macOS, and Windows.

Icon: Purple rounded-rectangle with white 'U'.

Requires: pystray + Pillow
"""

import os
import sys
import platform
import threading
import logging
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from host.main import UniCentHost

log = logging.getLogger(__name__)

_SYSTEM = platform.system()

TRAY_AVAILABLE = False

try:
    import pystray
    from pystray import MenuItem, Menu
    from PIL import Image
    TRAY_AVAILABLE = True
except ImportError:
    log.warning("pystray/Pillow not installed — tray icon disabled")


def _load_u_icon(size: int = 64):
    """Load the 'U' icon from assets."""
    asset_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'assets',
    )
    icon_path = os.path.join(asset_dir, f'icon-u-{size}.png')
    if os.path.exists(icon_path):
        return Image.open(icon_path)
    for s in (64, 128, 48, 32, 256):
        p = os.path.join(asset_dir, f'icon-u-{s}.png')
        if os.path.exists(p):
            return Image.open(p).resize((size, size), Image.LANCZOS)
    return _generate_u_icon(size)


def _generate_u_icon(size: int = 64):
    """Generate a 'U' icon programmatically."""
    from PIL import ImageDraw, ImageFont
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = max(1, size // 16)
    radius = size // 4
    draw.rounded_rectangle(
        [margin, margin, size - margin - 1, size - margin - 1],
        radius=radius, fill=(75, 0, 130, 255),
    )
    font_size = int(size * 0.65)
    font = None
    for font_path in [
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
    ]:
        try:
            font = ImageFont.truetype(font_path, font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "U", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]),
        "U", fill=(255, 255, 255, 255), font=font,
    )
    return img


class HostTray:
    """System tray icon for UniCent host — cross-platform."""

    def __init__(self, host: 'UniCentHost'):
        self.host = host
        self._icon = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if not TRAY_AVAILABLE:
            log.warning("System tray not available")
            return

        # D-Bus / DISPLAY fixups for Linux running as root
        if _SYSTEM == 'Linux' and os.geteuid() == 0:
            sudo_user = os.environ.get('SUDO_USER', '')
            if sudo_user and not os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
                try:
                    import subprocess
                    result = subprocess.run(
                        ['su', '-', sudo_user, '-c', 'echo $DBUS_SESSION_BUS_ADDRESS'],
                        capture_output=True, text=True, timeout=5,
                    )
                    dbus_addr = result.stdout.strip()
                    if dbus_addr:
                        os.environ['DBUS_SESSION_BUS_ADDRESS'] = dbus_addr
                except Exception:
                    pass
            if not os.environ.get('DISPLAY'):
                os.environ['DISPLAY'] = ':0'

        try:
            icon_image = _load_u_icon(64)
        except Exception as e:
            log.warning(f"Could not load tray icon: {e}")
            return

        self._icon = pystray.Icon(
            name='unicent-host',
            icon=icon_image,
            title='UniCent Host',
            menu=self._build_menu(),
        )
        self._thread = threading.Thread(target=self._run_icon, daemon=True)
        self._thread.start()
        log.info("System tray icon started")

    def _run_icon(self):
        try:
            self._icon.run()
        except Exception as e:
            log.warning(f"Tray icon error: {e}")
            self._icon = None

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

    def update_menu(self):
        if self._icon:
            self._icon.menu = self._build_menu()
            try:
                self._icon.update_menu()
            except Exception:
                pass

    def update_tooltip(self, text: str):
        if self._icon:
            self._icon.title = text

    def _build_menu(self):
        active = getattr(self.host, 'layout', None)
        active_machine = active.active_machine if active else 'host'
        controlling = 'HOST (local)' if active_machine == 'host' else active_machine

        items = []
        items.append(MenuItem(f'Controlling: {controlling}', action=None, enabled=False))
        items.append(Menu.SEPARATOR)

        # Switch options
        items.append(MenuItem('Switch to Host (local)      Ctrl+Alt+1',
                              lambda: self.host._hotkey_switch_to(0)))

        server = getattr(self.host, 'server', None)
        clients = server.get_client_list() if server else []
        for i, client in enumerate(clients):
            client_name = client.get('hostname', client.get('client_id', f'Client {i+1}'))
            label = f'Switch to {client_name}      Ctrl+Alt+{i+2}'
            idx = i + 1
            items.append(MenuItem(label,
                lambda _item=None, _idx=idx: self.host._hotkey_switch_to(_idx)))

        if not clients:
            items.append(MenuItem('No clients connected', action=None, enabled=False))

        items.append(MenuItem('Switch to Next      Ctrl+Alt+S',
                              lambda: self.host._hotkey_switch_next()))
        items.append(Menu.SEPARATOR)

        # Side placement
        current_side = getattr(self.host, 'client_side', 'right')
        other_side = 'left' if current_side == 'right' else 'right'
        items.append(MenuItem(f'Clients on: {current_side.upper()} side',
                              action=None, enabled=False))
        items.append(MenuItem(f'Move clients to {other_side} side',
                              lambda: self._toggle_side()))
        items.append(Menu.SEPARATOR)

        # Actions
        items.append(MenuItem('Sync Clipboard      Ctrl+Alt+C',
                              lambda: self.host._hotkey_clipboard_sync()))
        items.append(Menu.SEPARATOR)

        # Client info
        if clients:
            items.append(MenuItem(
                f'Connected Clients ({len(clients)})',
                Menu(*[
                    MenuItem(
                        f'{c.get("hostname", c["client_id"])} — {c.get("address", "")}',
                        action=None, enabled=False,
                    ) for c in clients
                ]),
            ))
            items.append(Menu.SEPARATOR)

        items.append(MenuItem('Quit      Ctrl+Alt+Q', self._on_quit))
        return Menu(*items)

    def _on_quit(self):
        self.host._hotkey_quit()
        self.stop()

    def _toggle_side(self):
        current = getattr(self.host, 'client_side', 'right')
        new_side = 'left' if current == 'right' else 'right'
        self.host.client_side = new_side
        self.host.layout.client_side = new_side
        self.host.layout._recalculate_layout()
        print(f"\n  Clients moved to {new_side.upper()} side")
        self.host._print_layout()
        self.update_menu()
