"""
UniCent Host — cross-platform.

Captures local mouse/keyboard input and forwards it over the network
to connected clients. Manages the virtual screen layout and handles
edge-based cursor transitions.

Usage:
    python -m host.main [--port PORT] [--client-side left|right]
                        [--no-tls] [--no-tray] [-v]
"""

import argparse
import logging
import os
import platform
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Optional

from host.server import HostServer
from host.input_capture import InputCapture, find_input_devices, HotkeyDetector
from host.screen_manager import ScreenLayout, get_host_screen_info
from shared.keymap import (
    CTRL_KEYS, ALT_KEYS, KEY_S, KEY_C, KEY_R, KEY_W,
    KEY_1, KEY_2, KEY_3, KEY_4, KEY_5, KEY_6, KEY_7, KEY_8, KEY_9,
)

log = logging.getLogger(__name__)

_SYSTEM = platform.system()


# ────────────────────────────────────────────────────────────
#  Cross-platform cursor read / warp
# ────────────────────────────────────────────────────────────


def _read_cursor_position():
    """Read current cursor position → (x, y) or None."""
    if _SYSTEM == 'Linux':
        try:
            result = subprocess.run(
                ['xdotool', 'getmouselocation', '--shell'],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                vals = {}
                for line in result.stdout.strip().split('\n'):
                    if '=' in line:
                        k, v = line.split('=', 1)
                        vals[k] = int(v)
                return vals.get('X', 0), vals.get('Y', 0)
        except Exception:
            pass
    elif _SYSTEM == 'Darwin':
        try:
            from Quartz import CGEventCreate, CGEventGetLocation
            event = CGEventCreate(None)
            loc = CGEventGetLocation(event)
            return int(loc.x), int(loc.y)
        except Exception:
            pass
    elif _SYSTEM == 'Windows':
        try:
            import ctypes
            from ctypes import wintypes
            pt = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return pt.x, pt.y
        except Exception:
            pass
    return None


def _warp_cursor(x: int, y: int):
    """Warp the local cursor to (x, y)."""
    if _SYSTEM == 'Linux':
        try:
            subprocess.run(['xdotool', 'mousemove', '--', str(x), str(y)],
                           capture_output=True, timeout=2)
        except Exception:
            pass
    elif _SYSTEM == 'Darwin':
        try:
            from Quartz import CGWarpMouseCursorPosition, CGPointMake
            CGWarpMouseCursorPosition(CGPointMake(x, y))
        except Exception:
            pass
    elif _SYSTEM == 'Windows':
        try:
            import ctypes
            ctypes.windll.user32.SetCursorPos(x, y)
        except Exception:
            pass


# ────────────────────────────────────────────────────────────
#  UniCentHost
# ────────────────────────────────────────────────────────────

class UniCentHost:
    """
    Main host controller.

    1.  Detects local screens.
    2.  Starts TCP server & discovery beacon.
    3.  Opens input devices and starts capture loop.
    4.  Routes events: local → layout → server → client.
    5.  Handles hotkeys for switching, clipboard sync, quit.
    """

    def __init__(self, port: int = 27183, client_side: str = 'right',
                 use_tls: bool = True, use_tray: bool = True,
                 cert_file: str = '', key_file: str = '', ca_file: str = '',
                 verbose: bool = False):
        self.port = port
        self.client_side = client_side
        self.use_tls = use_tls
        self.use_tray = use_tray
        self.verbose = verbose

        # TLS
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.cert_file = cert_file or os.path.join(base_dir, 'certs', 'host.crt')
        self.key_file = key_file or os.path.join(base_dir, 'certs', 'host.key')
        self.ca_file = ca_file or os.path.join(base_dir, 'certs', 'ca.crt')
        if not use_tls:
            self.cert_file = self.key_file = self.ca_file = ''

        # Components
        self.server: Optional[HostServer] = None
        self.capture = None
        self.layout = ScreenLayout(client_side=client_side)
        self.hotkey = HotkeyDetector()
        self.tray = None
        self.beacon = None

        # State
        self._running = False
        self._controlling_remote = False
        self._last_cursor_sync = 0.0
        self._host_hostname = socket.gethostname()
        self._pending_clipboard: str = ''  # clipboard received from client
        self._last_switch_time: float = 0.0
        self._current_remote: str = ''
        self._host_return_intent: int = 0
        self._host_return_threshold: int = 120

        # Cooldown: ignore edge crossings for this long after returning to host
        self._last_host_return: float = 0.0

    # ──── Lifecycle ────────────────────────────────────────

    def run(self):
        """Main entry-point.  Blocks until quit."""
        self._running = True
        self._print_banner()

        # 1. Detect screens
        screens = get_host_screen_info()
        self.layout.set_host_screens(screens)
        self._print_screens(screens)

        # Sync initial cursor position
        pos = _read_cursor_position()
        if pos:
            self.layout.init_cursor_at_host(pos[0], pos[1])
            log.info(f"Initial cursor position: {pos}")

        # 2. Start server
        self.server = HostServer(
            port=self.port,
            cert_file=self.cert_file,
            key_file=self.key_file,
            ca_file=self.ca_file,
        )
        self.server.set_host_info(
            self._host_hostname, screens, self.layout.get_layout_info())
        self.server.on_client_connected = self._on_client_connected
        self.server.on_client_disconnected = self._on_client_disconnected
        self.server.on_client_screens = self._on_client_screens
        self.server.on_clipboard_received = self._on_clipboard_received
        self.server.start()

        # 3. Start discovery beacon
        try:
            from shared.discovery import DiscoveryBeacon
            self.beacon = DiscoveryBeacon(
                service_port=self.port,
                hostname=self._host_hostname,
                role='host',
            )
            self.beacon.start()
        except Exception as e:
            log.warning(f"Discovery beacon disabled: {e}")

        # 4. Open input devices and start capture
        self.capture = InputCapture()
        devices = find_input_devices()
        all_devs = [d['path'] for d in devices.get('all', [])]
        if all_devs:
            opened = self.capture.open_devices(all_devs)
            log.info(f"Opened {opened}/{len(all_devs)} input devices")
        else:
            log.warning("No input devices found (CGEventTap / hooks may still work)")
            self.capture.open_devices([])

        self.capture.on_mouse_move = self._on_mouse_move
        self.capture.on_mouse_button = self._on_mouse_button
        self.capture.on_mouse_scroll = self._on_mouse_scroll
        self.capture.on_key_event = self._on_key_event
        self.capture.start()

        # 5. Register hotkeys
        self._register_hotkeys()

        # 6. Start tray icon (optional)
        if self.use_tray:
            try:
                from host.tray import HostTray, TRAY_AVAILABLE
                if TRAY_AVAILABLE:
                    self.tray = HostTray(self)
                    self.tray.start()
            except Exception as e:
                log.warning(f"Tray icon disabled: {e}")

        self._print_status()

        # 7. Main loop — keep alive
        try:
            while self._running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n  Interrupted.")
        finally:
            self._shutdown()

    def _shutdown(self):
        self._running = False
        print("\n  Shutting down...")
        if self.capture:
            self.capture.ungrab()
            self.capture.stop()
        if self.server:
            self.server.stop()
        if self.beacon:
            self.beacon.stop()
        if self.tray:
            self.tray.stop()
        print("  Goodbye.")

    # ──── Input event callbacks ────────────────────────────

    def _on_mouse_move(self, dx: int, dy: int):
        if not self._controlling_remote:
            # Local mode — track cursor via deltas and detect edge crossing.
            # Brief cooldown after returning from remote prevents re-triggering
            # while the physical cursor is still near the screen edge.
            self.layout.move_cursor(dx, dy)
            if time.time() - self._last_host_return > 0.2:
                new_machine = self.layout.active_machine
                if new_machine != 'host':
                    log.info(f"Edge crossing → {new_machine}")
                    self._switch_to_machine(new_machine)
        else:
            # Remote mode → forward to active client via layout
            old_x = self.layout._cursor_x
            new_machine = self.layout.move_cursor(dx, dy)
            if new_machine == 'host':
                elapsed = time.time() - self._last_switch_time
                log.debug(f"[BOUNCE] cursor→host dx={dx} old_x={old_x} new_x={self.layout._cursor_x} elapsed={elapsed:.3f}s")
                # Require sustained intent at the return edge to switch back.
                self._host_return_intent += 1
                self.layout._active_machine = self._current_remote
                for m in self.layout.machines:
                    if m.machine_id == self._current_remote:
                        self.layout._cursor_x = max(m.left, min(self.layout._cursor_x, m.right - 1))
                        break
                self.server.forward_mouse_move(dx, dy)

                if elapsed >= 0.5 and self._host_return_intent >= self._host_return_threshold:
                    log.info(
                        f"[SWITCH] Returning to host "
                        f"(elapsed={elapsed:.3f}s, intent={self._host_return_intent})"
                    )
                    self._host_return_intent = 0
                    self._switch_to_host()
            else:
                self._host_return_intent = 0
                self.server.forward_mouse_move(dx, dy)

    def _on_mouse_button(self, button: int, state: int):
        log.info("HOST mouse_button button=%s state=%s controlling_remote=%s", button, state, self._controlling_remote)
        # Safety handoff: if layout already points at a client but the
        # mode has not switched yet, promote on click-down so the click
        # is delivered to the intended remote machine.
        if not self._controlling_remote and state == 1:
            target = self.layout.active_machine
            if target != 'host' and target in self.server.clients:
                log.info("Promoting click handoff → %s", target)
                self._switch_to_machine(target)
        if self._controlling_remote:
            self.server.forward_mouse_button(button, state)

    def _on_mouse_scroll(self, dx: int, dy: int):
        if self._controlling_remote:
            self.server.forward_mouse_scroll(dx, dy)

    def _on_key_event(self, keycode: int, state: int):
        # Always process hotkeys regardless of mode
        if self.hotkey.process_key(keycode, state):
            return  # Hotkey consumed the event
        if self._controlling_remote:
            self.server.forward_key_event(keycode, state)

    # ──── Machine switching ────────────────────────────────

    def _switch_to_machine(self, machine_id: str):
        """Switch control to a client machine."""
        if machine_id == 'host':
            self._switch_to_host()
            return

        if machine_id not in self.server.clients:
            return

        # Auto-sync: send host clipboard to the client we're switching to
        try:
            from client.screen_manager import get_clipboard_content
            clip = get_clipboard_content()
            if clip:
                self.server.send_clipboard(clip)
                log.debug(f"Clipboard sent to {machine_id} ({len(clip)} chars)")
        except Exception as e:
            log.debug(f"Clipboard auto-sync failed: {e}")

        self._controlling_remote = True
        self._current_remote = machine_id
        self._last_switch_time = time.time()
        self._host_return_intent = 0
        self.server.set_active_client(machine_id)
        self.capture.grab()

        # Place cursor at center of the client screen to prevent
        # immediate bounce-back from being too close to the boundary.
        for m in self.layout.machines:
            if m.machine_id == machine_id:
                self.layout._cursor_x = m.left + m.total_width // 2
                # Keep the y position from the physical cursor
                self.layout._cursor_y = max(m.top, min(self.layout._cursor_y, m.bottom - 1))
                break

        lx, ly = self.layout.get_local_cursor(machine_id)
        self.server.send_switch_active(machine_id, lx, ly)
        self.server.send_cursor_warp(machine_id, lx, ly)

        print(f"\n  >> Controlling: {machine_id} (cursor at {lx},{ly})")
        if self.tray:
            self.tray.update_tooltip(f'UniCent — {machine_id}')
            self.tray.update_menu()

    def _switch_to_host(self):
        """Return control to the local host machine."""
        if self._controlling_remote:
            old = self.layout.active_machine
            if old != 'host' and old in self.server.clients:
                self.server.send_switch_inactive(old)

        self._controlling_remote = False
        self.capture.ungrab()
        self.server.set_active_client(None)
        self.layout._active_machine = 'host'
        self._last_host_return = time.time()

        # Push the virtual cursor away from the boundary so the next small
        # delta doesn't immediately re-trigger an edge crossing.
        for m in self.layout.machines:
            if m.machine_id == 'host':
                inset = 300
                if self.client_side == 'left':
                    self.layout._cursor_x = max(self.layout._cursor_x, m.left + inset)
                else:
                    self.layout._cursor_x = min(self.layout._cursor_x, m.right - 1 - inset)
                break

        # Apply any pending clipboard that wasn't set yet
        if self._pending_clipboard:
            try:
                from client.screen_manager import set_clipboard_content
                set_clipboard_content(self._pending_clipboard)
                log.info(f"Host clipboard set from pending ({len(self._pending_clipboard)} chars)")
            except Exception as e:
                log.warning(f"Pending clipboard apply failed: {e}")
            self._pending_clipboard = ''

        lx, ly = self.layout.get_local_cursor('host')
        _warp_cursor(lx, ly)

        print(f"\n  >> Controlling: HOST (local) (cursor at {lx},{ly})")
        if self.tray:
            self.tray.update_tooltip('UniCent Host — local')
            self.tray.update_menu()

    # ──── Hotkey handlers ──────────────────────────────────

    def _register_hotkeys(self):
        """Register Ctrl+Alt+<key> hotkeys."""
        self.hotkey.register(
            'switch_next', [CTRL_KEYS, ALT_KEYS], KEY_S,
            self._hotkey_switch_next)
        self.hotkey.register(
            'clipboard', [CTRL_KEYS, ALT_KEYS], KEY_C,
            self._hotkey_clipboard_sync)
        self.hotkey.register(
            'refresh', [CTRL_KEYS, ALT_KEYS], KEY_R,
            self._hotkey_refresh_layout)

        # Ctrl+Alt+1..9 → switch to machine index
        for i, key in enumerate([KEY_1, KEY_2, KEY_3, KEY_4, KEY_5,
                                  KEY_6, KEY_7, KEY_8, KEY_9]):
            idx = i
            self.hotkey.register(
                f'switch_{i}', [CTRL_KEYS, ALT_KEYS], key,
                lambda _idx=idx: self._hotkey_switch_to(_idx))

        # Ctrl+Alt+W → wake & activate current/last client
        self.hotkey.register(
            'wake_client', [CTRL_KEYS, ALT_KEYS], KEY_W,
            self._hotkey_wake_client)

    def _hotkey_switch_next(self):
        target = self.layout.switch_to_next()
        if target == 'host':
            self._switch_to_host()
        else:
            self._switch_to_machine(target)
        print(f"\n  [Hotkey] Switched to next → {target}")

    def _hotkey_switch_to(self, index: int):
        target = self.layout.switch_to_index(index)
        if target:
            if target == 'host':
                self._switch_to_host()
            else:
                self._switch_to_machine(target)
            print(f"\n  [Hotkey] Switched to #{index} → {target}")

    def _hotkey_clipboard_sync(self):
        """Bidirectional clipboard sync: host↔clients."""
        try:
            from client.screen_manager import get_clipboard_content, set_clipboard_content
            # 1. Send host clipboard → all clients
            host_clip = get_clipboard_content()
            if host_clip:
                self.server.send_clipboard(host_clip)
                print(f"\n  [Hotkey] Host clipboard → clients ({len(host_clip)} chars)")
            # 2. Apply any pending client clipboard → host
            if self._pending_clipboard:
                set_clipboard_content(self._pending_clipboard)
                print(f"  [Hotkey] Client clipboard → host ({len(self._pending_clipboard)} chars)")
                self._pending_clipboard = ''
            elif not host_clip:
                print("\n  [Hotkey] Clipboard empty")
        except Exception as e:
            log.warning(f"Clipboard sync failed: {e}")

    def _hotkey_refresh_layout(self):
        """Re-detect host screens, re-read cursor position, recalculate layout."""
        self.refresh_layout()
        print("\n  [Hotkey] Layout refreshed")

    def _hotkey_wake_client(self):
        """Wake & activate the current or first connected client."""
        clients = self.server.get_client_list() if self.server else []
        if not clients:
            print("\n  [Hotkey] No clients to wake")
            return
        # Prefer the currently active client, else the first connected
        active = self.layout.active_machine if self.layout else None
        target_id = None
        if active and active != 'host':
            target_id = active
        else:
            target_id = clients[0]['client_id']
        self.wake_client(target_id)

    def wake_client(self, client_id: str):
        """Send wake signal to a client, then switch control to it."""
        if not self.server or client_id not in self.server.clients:
            print(f"\n  [Wake] Client {client_id} not connected")
            return
        self.server.send_wake_screen(client_id)
        # Also switch to that client so keyboard input goes to it
        self._hotkey_switch_to_by_id(client_id)
        print(f"\n  [Wake] Sent wake to {client_id}")
        if self.tray:
            self.tray.update_menu()

    def _hotkey_switch_to_by_id(self, client_id: str):
        """Switch to a machine by client_id rather than index."""
        if not self.layout:
            return
        for i, m in enumerate(self.layout.machines):
            if m.machine_id == client_id:
                self._hotkey_switch_to(i)
                return
        # Fallback: just try switching by name
        self._switch_to_machine(client_id)

    def refresh_layout(self):
        """Re-detect screens and resync cursor with the physical position.

        Call this when a client connects/disconnects or whenever the
        edge boundaries feel wrong.
        """
        # 1. Re-detect host screens
        screens = get_host_screen_info()
        self.layout.set_host_screens(screens)

        # 2. Re-add all current clients (their screens haven't changed)
        for cid, client in self.server.clients.items():
            if client.screens:
                self.layout.add_client_screens(cid, client.screens)

        # 3. Resync cursor to the physical position
        self._resync_cursor()

        # 4. Update server with new layout
        self.server.set_host_info(
            self._host_hostname,
            [s.to_dict() for s in self.layout.machines[0].screens],
            self.layout.get_layout_info(),
        )

        log.info("Layout refreshed")
        self._print_layout()
        if self.tray:
            self.tray.update_menu()

    def _resync_cursor(self):
        """Re-read the physical cursor position and update the layout.

        Only meaningful when we're controlling the host (local), as
        we can read the hardware cursor position.
        """
        if self._controlling_remote:
            return  # Can't read remote cursor position
        pos = _read_cursor_position()
        if pos:
            self.layout.init_cursor_at_host(pos[0], pos[1])
            log.info(f"Cursor resynced to physical position: {pos}")

    def _hotkey_quit(self):
        print("\n  [Hotkey] Quitting...")
        self._running = False

    # ──── Server callbacks ─────────────────────────────────

    def _on_client_connected(self, client_id: str, screens: list):
        log.info(f"Client connected: {client_id}")
        self.layout.add_client_screens(client_id, screens)

        # Resync cursor with physical position so edge detection is accurate
        self._resync_cursor()

        # Update server with new layout
        self.server.set_host_info(
            self._host_hostname,
            [s.to_dict() for s in self.layout.machines[0].screens],
            self.layout.get_layout_info(),
        )
        print(f"\n  ✦ Client connected: {client_id}")
        self._print_layout()

        # Force-connect behavior: when a client joins, immediately switch
        # control to that client so users can recover from edge-detection
        # issues after reboot without manual hotkeys.
        try:
            self._switch_to_machine(client_id)
        except Exception as e:
            log.warning(f"Auto switch-to-client failed: {e}")

        if self.tray:
            self.tray.update_menu()

    def _on_client_disconnected(self, client_id: str):
        log.info(f"Client disconnected: {client_id}")
        was_controlling = (self.layout.active_machine == client_id)
        self.layout.remove_client(client_id)
        if was_controlling:
            self._switch_to_host()

        # Resync cursor with physical position after layout change
        self._resync_cursor()

        print(f"\n  ✦ Client disconnected: {client_id}")
        self._print_layout()
        if self.tray:
            self.tray.update_menu()

    def _on_client_screens(self, client_id: str, screens: list):
        self.layout.add_client_screens(client_id, screens)
        self._print_layout()

    def _on_clipboard_received(self, client_id: str, content: str):
        if content:
            self._pending_clipboard = content
            log.info(f"Clipboard received from {client_id} ({len(content)} chars)")
            # Apply to host clipboard immediately (even if we're remote,
            # this ensures the clipboard is set by the time the user
            # switches back to host).
            try:
                from client.screen_manager import set_clipboard_content
                set_clipboard_content(content)
                log.info(f"Host clipboard updated from {client_id}")
                self._pending_clipboard = ''  # already applied
            except Exception as e:
                log.warning(f"Failed to set host clipboard: {e}")
                # Will be retried in _switch_to_host via _pending_clipboard

    # ──── Display helpers ──────────────────────────────────

    def _print_banner(self):
        print()
        print("  ╔══════════════════════════════════════╗")
        print("  ║          UniCent Host                ║")
        print("  ╚══════════════════════════════════════╝")
        print()
        tls_str = 'TLS' if self.use_tls else 'NO TLS'
        print(f"  Hostname : {self._host_hostname}")
        print(f"  Port     : {self.port} ({tls_str})")
        print(f"  Clients  : {self.client_side} side")
        print(f"  Platform : {_SYSTEM} ({platform.machine()})")
        print()

    def _print_screens(self, screens):
        print("  Screens:")
        for s in screens:
            print(f"    {s.get('name', '?')}: {s['width']}x{s['height']}"
                  f" @ +{s.get('x', 0)}+{s.get('y', 0)}"
                  f" (scale {s.get('scale', 1.0)}x)")
        print()

    def _print_layout(self):
        print("  Layout:")
        for idx, machine_id, active in self.layout.get_machine_list():
            flag = ' ◄' if active else ''
            ms = next((m for m in self.layout.machines if m.machine_id == machine_id), None)
            if ms:
                print(f"    [{idx}] {machine_id}: {ms.total_width}x{ms.total_height}"
                      f" @ +{ms.offset_x}+{ms.offset_y}{flag}")
        print()

    def _print_status(self):
        print("  Hotkeys:")
        print("    Ctrl+Alt+S       — Switch to next machine")
        print("    Ctrl+Alt+1..9    — Switch to machine #1..#9")
        print("    Ctrl+Alt+C       — Sync clipboard")
        print("    Ctrl+Alt+R       — Refresh layout / resync edges")
        print("    Ctrl+Alt+W       — Wake & activate client")
        print()
        print("  Waiting for clients...")
        print()


# ────────────────────────────────────────────────────────────
#  CLI entry-point
# ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='UniCent Host')
    parser.add_argument('--port', type=int, default=27183, help='TCP port (default 27183)')
    parser.add_argument('--client-side', choices=['left', 'right'], default='right',
                        help='Side where clients appear (default right)')
    parser.add_argument('--no-tls', action='store_true', help='Disable TLS encryption')
    parser.add_argument('--no-tray', action='store_true', help='Disable system tray icon')
    parser.add_argument('--cert', default='', help='TLS certificate file')
    parser.add_argument('--key', default='', help='TLS key file')
    parser.add_argument('--ca', default='', help='CA certificate file')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose logging')
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S',
    )

    # Handle Ctrl+C
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    host = UniCentHost(
        port=args.port,
        client_side=args.client_side,
        use_tls=not args.no_tls,
        use_tray=not args.no_tray,
        cert_file=args.cert,
        key_file=args.key,
        ca_file=args.ca,
        verbose=args.verbose,
    )
    host.run()


if __name__ == '__main__':
    main()
