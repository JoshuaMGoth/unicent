"""
Host system tray icon — cross-platform.

Provides a right-click menu on the system tray icon with all
UniCent controls, settings, about info, update checking, and
bug reporting.

When running as root on Linux (the typical case, since input capture
needs root), the actual pystray icon runs in a **subprocess** under
the regular user, because the D-Bus session bus rejects connections
from UID 0.  Communication happens via JSON lines over stdin/stdout
pipes.

On non-root or non-Linux systems, pystray runs directly in-process.

Icon: Purple rounded-rectangle with white 'U'.

Requires: pystray + Pillow
"""

import os
import sys
import json
import platform
import subprocess
import threading
import logging
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from host.main import UniCentHost

from shared.version import __version__, __app_name__

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


# ── Icon generation ───────────────────────────────────────────

def _load_u_icon(size: int = 64):
    """Load the 'U' icon from assets, fall back to generated."""
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


# ══════════════════════════════════════════════════════════════
# HostTray — main entry point
# ══════════════════════════════════════════════════════════════

class HostTray:
    """System tray icon for the UniCent host.

    Supports two execution modes:

    *  **direct** — pystray runs in-process (non-root, or non-Linux).
    *  **subprocess** — pystray runs in a child process that drops
       privileges to the regular user (root on Linux).
    """

    def __init__(self, host: 'UniCentHost'):
        self.host = host
        # Direct-mode handles
        self._icon: Optional['pystray.Icon'] = None
        self._tray_thread: Optional[threading.Thread] = None
        # Subprocess-mode handles
        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        # Shared
        self._update_info: Optional[dict] = None
        self._mode: str = 'none'  # 'direct' | 'subprocess' | 'none'

    # ── public API ────────────────────────────────────────

    def start(self):
        if not TRAY_AVAILABLE:
            log.warning("System tray not available")
            return

        if _SYSTEM == 'Linux' and os.geteuid() == 0:
            self._start_subprocess()
        else:
            self._start_direct()

        # Background update check
        self._check_updates_async()

    def stop(self):
        if self._mode == 'subprocess':
            self._stop_subprocess()
        elif self._mode == 'direct':
            self._stop_direct()

    def update_menu(self):
        if self._mode == 'subprocess':
            self._send_state_to_worker()
        elif self._mode == 'direct' and self._icon:
            self._icon.menu = self._build_menu()
            try:
                self._icon.update_menu()
            except Exception:
                pass

    def update_tooltip(self, text: str):
        if self._mode == 'direct' and self._icon:
            self._icon.title = text

    # ══════════════════════════════════════════════════════
    # SUBPROCESS MODE  (root on Linux)
    # ══════════════════════════════════════════════════════

    def _start_subprocess(self):
        """Spawn the tray icon in a child process running as the
        regular user so it can connect to the D-Bus session bus."""
        import pwd

        sudo_user = os.environ.get('SUDO_USER', '')
        if not sudo_user:
            log.warning("SUDO_USER not set — tray icon disabled "
                        "(cannot determine regular user)")
            return

        try:
            pw = pwd.getpwnam(sudo_user)
        except KeyError:
            log.warning(f"User {sudo_user!r} not found — tray disabled")
            return

        project_root = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))

        env = os.environ.copy()
        # Guarantee the child sees the right environment
        env.setdefault('HOME', pw.pw_dir)
        env.setdefault('XDG_RUNTIME_DIR', f'/run/user/{pw.pw_uid}')
        env.setdefault('DBUS_SESSION_BUS_ADDRESS',
                       f'unix:path=/run/user/{pw.pw_uid}/bus')

        try:
            self._proc = subprocess.Popen(
                [sys.executable, '-m', 'host.tray_worker'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                user=pw.pw_uid,
                group=pw.pw_gid,
                cwd=project_root,
                env=env,
            )
        except Exception as e:
            log.warning(f"Failed to spawn tray subprocess: {e}")
            return

        self._mode = 'subprocess'
        log.info(f"Tray subprocess started  pid={self._proc.pid}  "
                 f"user={sudo_user}")

        # Send initial state
        self._send_cmd('init', state=self._get_state())

        # Start reader for actions coming back from the worker
        self._reader_thread = threading.Thread(
            target=self._read_worker_actions, daemon=True)
        self._reader_thread.start()

    def _stop_subprocess(self):
        if self._proc and self._proc.poll() is None:
            self._send_cmd('stop')
            try:
                self._proc.wait(timeout=3)
            except Exception:
                self._proc.kill()
        self._proc = None

    def _send_cmd(self, cmd: str, **kw):
        """Send a JSON command to the worker's stdin."""
        if not self._proc or self._proc.poll() is not None:
            return
        try:
            line = json.dumps({"cmd": cmd, **kw}) + "\n"
            self._proc.stdin.write(line.encode())
            self._proc.stdin.flush()
        except Exception as e:
            log.debug(f"Tray worker send error: {e}")

    def _send_state_to_worker(self):
        self._send_cmd('update', state=self._get_state())

    def _get_state(self) -> dict:
        """Serialize current host state for the worker."""
        active = getattr(self.host, 'layout', None)
        active_machine = active.active_machine if active else 'host'
        controlling = ('HOST (local)' if active_machine == 'host'
                       else active_machine)

        server = getattr(self.host, 'server', None)
        clients = server.get_client_list() if server else []
        # Ensure JSON-safe (drop non-serializable fields)
        safe_clients = []
        for c in clients:
            safe_clients.append({
                'client_id': c.get('client_id', ''),
                'hostname': c.get('hostname', ''),
                'address': c.get('address', ''),
            })

        return {
            'controlling': controlling,
            'clients': safe_clients,
            'side': getattr(self.host, 'client_side', 'right'),
            'update_info': self._update_info,
        }

    def _read_worker_actions(self):
        """Read JSON action lines from the worker's stdout."""
        try:
            while self._proc and self._proc.poll() is None:
                raw = self._proc.stdout.readline()
                if not raw:
                    break
                line = raw.decode().strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._dispatch_action(msg)
        except Exception as e:
            log.debug(f"Tray worker reader exited: {e}")

    def _dispatch_action(self, msg: dict):
        """Route an action received from the tray worker."""
        action = msg.get('action', '')
        if action == 'ready':
            log.debug("Tray worker ready")
        elif action == 'switch':
            self.host._hotkey_switch_to(msg.get('index', 0))
        elif action == 'switch_next':
            self.host._hotkey_switch_next()
        elif action == 'toggle_side':
            self._toggle_side()
        elif action == 'sync_clipboard':
            self.host._hotkey_clipboard_sync()
        elif action == 'refresh_layout':
            self._refresh_layout()
        elif action == 'show_about':
            self._show_about()
        elif action == 'show_settings':
            self._show_settings()
        elif action == 'show_updates':
            self._show_updates()
        elif action == 'show_bug_report':
            self._show_bug_report()
        elif action == 'quit':
            self._on_quit()
        elif action == 'error':
            log.warning(f"Tray worker error: {msg.get('message')}")

    # ══════════════════════════════════════════════════════
    # DIRECT MODE  (non-root / non-Linux)
    # ══════════════════════════════════════════════════════

    def _start_direct(self):
        # D-Bus / DISPLAY fixups for rare non-root Linux case
        if _SYSTEM == 'Linux' and os.geteuid() == 0:
            sudo_user = os.environ.get('SUDO_USER', '')
            if sudo_user and not os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
                try:
                    result = subprocess.run(
                        ['su', '-', sudo_user, '-c',
                         'echo $DBUS_SESSION_BUS_ADDRESS'],
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
            title=f'{__app_name__} Host v{__version__}',
            menu=self._build_menu(),
        )
        self._tray_thread = threading.Thread(
            target=self._run_icon, daemon=True)
        self._tray_thread.start()
        self._mode = 'direct'
        log.info("System tray icon started (direct mode)")

    def _run_icon(self):
        try:
            self._icon.run()
        except Exception as e:
            log.warning(f"Tray icon error: {e}")
            self._icon = None

    def _stop_direct(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

    def _build_menu(self):
        """Build the pystray menu (direct mode only)."""
        active = getattr(self.host, 'layout', None)
        active_machine = active.active_machine if active else 'host'
        controlling = ('HOST (local)' if active_machine == 'host'
                       else active_machine)

        items = []

        # ── Status ──
        items.append(MenuItem(
            f'Controlling: {controlling}', action=None, enabled=False))
        items.append(Menu.SEPARATOR)

        # ── Switch options ──
        items.append(MenuItem(
            'Switch to Host (local)      Ctrl+Alt+1',
            lambda: self.host._hotkey_switch_to(0)))

        server = getattr(self.host, 'server', None)
        clients = server.get_client_list() if server else []
        for i, client in enumerate(clients):
            client_name = client.get(
                'hostname', client.get('client_id', f'Client {i+1}'))
            label = f'Switch to {client_name}      Ctrl+Alt+{i+2}'
            idx = i + 1
            items.append(MenuItem(
                label,
                lambda _item=None, _idx=idx:
                    self.host._hotkey_switch_to(_idx)))

        if not clients:
            items.append(MenuItem(
                'No clients connected', action=None, enabled=False))

        items.append(MenuItem(
            'Switch to Next      Ctrl+Alt+S',
            lambda: self.host._hotkey_switch_next()))
        items.append(Menu.SEPARATOR)

        # ── Side placement ──
        current_side = getattr(self.host, 'client_side', 'right')
        other_side = 'left' if current_side == 'right' else 'right'
        items.append(MenuItem(
            f'Clients on: {current_side.upper()} side',
            action=None, enabled=False))
        items.append(MenuItem(
            f'Move clients to {other_side} side',
            lambda: self._toggle_side()))
        items.append(Menu.SEPARATOR)

        # ── Clipboard ──
        items.append(MenuItem(
            'Sync Clipboard      Ctrl+Alt+C',
            lambda: self.host._hotkey_clipboard_sync()))

        # ── Refresh Layout ──
        items.append(MenuItem(
            'Refresh Layout      Ctrl+Alt+R',
            lambda: self._refresh_layout()))
        items.append(Menu.SEPARATOR)

        # ── Client info ──
        if clients:
            items.append(MenuItem(
                f'Connected Clients ({len(clients)})',
                Menu(*[
                    MenuItem(
                        f'{c.get("hostname", c["client_id"])}'
                        f' — {c.get("address", "")}',
                        action=None, enabled=False,
                    ) for c in clients
                ]),
            ))
            items.append(Menu.SEPARATOR)

        # ── Tools submenu ──
        tools_items = [
            MenuItem('Settings...', lambda: self._show_settings()),
            MenuItem('Check for Updates...', lambda: self._show_updates()),
            MenuItem('Report a Bug...', lambda: self._show_bug_report()),
        ]
        items.append(MenuItem('Tools', Menu(*tools_items)))

        # ── Update notification ──
        if self._update_info:
            items.append(MenuItem(
                f'Update available: v{self._update_info["latest"]}',
                lambda: self._show_updates()))

        items.append(Menu.SEPARATOR)

        # ── About ──
        items.append(MenuItem(
            f'About {__app_name__} v{__version__}',
            lambda: self._show_about()))

        items.append(Menu.SEPARATOR)

        # ── Quit ──
        items.append(MenuItem('Quit      Ctrl+Alt+Q', self._on_quit))

        return Menu(*items)

    # ══════════════════════════════════════════════════════
    # SHARED CALLBACKS  (used by both modes)
    # ══════════════════════════════════════════════════════

    def _on_quit(self):
        self.host._hotkey_quit()
        self.stop()

    def _refresh_layout(self):
        try:
            self.host.refresh_layout()
            print("\n  Layout refreshed from tray")
        except Exception as e:
            log.warning(f"Could not refresh layout: {e}")

    def _toggle_side(self):
        current = getattr(self.host, 'client_side', 'right')
        new_side = 'left' if current == 'right' else 'right'
        self.host.client_side = new_side
        self.host.layout.client_side = new_side
        self.host.layout._recalculate_layout()
        print(f"\n  Clients moved to {new_side.upper()} side")
        self.host._print_layout()
        self.update_menu()

    def _show_about(self):
        try:
            from shared.dialogs import show_about_dialog
            show_about_dialog()
        except Exception as e:
            log.warning(f"Could not show About dialog: {e}")

    def _show_settings(self):
        try:
            from shared.dialogs import show_settings_dialog
            show_settings_dialog(host=self.host)
        except Exception as e:
            log.warning(f"Could not show Settings dialog: {e}")

    def _show_updates(self):
        try:
            from shared.dialogs import show_update_dialog
            show_update_dialog(update_info=self._update_info)
        except Exception as e:
            log.warning(f"Could not show Update dialog: {e}")

    def _show_bug_report(self):
        try:
            from shared.dialogs import show_bug_report_dialog
            show_bug_report_dialog()
        except Exception as e:
            log.warning(f"Could not show Bug Report dialog: {e}")

    def _check_updates_async(self):
        """Check for updates in background on startup."""
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
