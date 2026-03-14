#!/usr/bin/env python3
"""
Tray icon subprocess for UniCent Host.

Runs as the regular (non-root) user so it can access the D-Bus session bus
for AppIndicator/StatusNotifierItem tray icons on Wayland/KDE.

Communication protocol (JSON lines over stdin/stdout):

  Parent -> Child (stdin):
    {"cmd": "init",   "state": {...}}
    {"cmd": "update", "state": {...}}
    {"cmd": "stop"}

  Child -> Parent (stdout):
    {"action": "ready"}
    {"action": "switch",         "index": N}
    {"action": "switch_next"}
    {"action": "toggle_side"}
    {"action": "sync_clipboard"}
    {"action": "show_about"}
    {"action": "show_settings"}
    {"action": "show_updates"}
    {"action": "show_bug_report"}
    {"action": "quit"}
    {"action": "error",          "message": "..."}
"""

import sys
import os
import json
import threading

# Add project root to path so shared.* imports work
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def main():
    import pystray
    from pystray import MenuItem, Menu
    from PIL import Image, ImageDraw, ImageFont
    from shared.version import __version__, __app_name__

    _icon_ref = [None]
    _state = [{}]

    # ── helpers ────────────────────────────────────────────

    def _send(action: str, **kw):
        """Send a JSON line to the parent process (stdout)."""
        try:
            sys.stdout.write(json.dumps({"action": action, **kw}) + "\n")
            sys.stdout.flush()
        except Exception:
            pass

    def _load_icon(size: int = 64):
        asset_dir = os.path.join(_project_root, "assets")
        for s in (size, 64, 128, 48, 32, 256):
            p = os.path.join(asset_dir, f"icon-u-{s}.png")
            if os.path.exists(p):
                img = Image.open(p)
                if s != size:
                    img = img.resize((size, size), Image.LANCZOS)
                return img
        return _generate_icon(size)

    def _generate_icon(size: int = 64):
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        margin = max(1, size // 16)
        radius = size // 4
        draw.rounded_rectangle(
            [margin, margin, size - margin - 1, size - margin - 1],
            radius=radius,
            fill=(75, 0, 130, 255),
        )
        font_size = int(size * 0.65)
        font = None
        for fp in (
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "C:/Windows/Fonts/arialbd.ttf",
        ):
            try:
                font = ImageFont.truetype(fp, font_size)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), "U", font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]),
            "U",
            fill=(255, 255, 255, 255),
            font=font,
        )
        return img

    # ── menu builder ──────────────────────────────────────

    def _build_menu():
        s = _state[0]
        items = []

        # Status
        controlling = s.get("controlling", "HOST (local)")
        items.append(
            MenuItem(f"Controlling: {controlling}", action=None, enabled=False)
        )
        items.append(Menu.SEPARATOR)

        # Switch — host
        items.append(
            MenuItem(
                "Switch to Host (local)      Ctrl+Alt+1",
                lambda: _send("switch", index=0),
            )
        )

        # Switch — clients
        clients = s.get("clients", [])
        for i, c in enumerate(clients):
            name = c.get("hostname", c.get("client_id", f"Client {i + 1}"))
            idx = i + 1
            items.append(
                MenuItem(
                    f"Switch to {name}      Ctrl+Alt+{idx + 1}",
                    lambda _i=None, _idx=idx: _send("switch", index=_idx),
                )
            )
        if not clients:
            items.append(
                MenuItem("No clients connected", action=None, enabled=False)
            )

        items.append(
            MenuItem(
                "Switch to Next      Ctrl+Alt+S",
                lambda: _send("switch_next"),
            )
        )
        items.append(Menu.SEPARATOR)

        # Side placement
        side = s.get("side", "right")
        other = "left" if side == "right" else "right"
        items.append(
            MenuItem(
                f"Clients on: {side.upper()} side", action=None, enabled=False
            )
        )
        items.append(
            MenuItem(
                f"Move clients to {other} side",
                lambda: _send("toggle_side"),
            )
        )
        items.append(Menu.SEPARATOR)

        # Clipboard
        items.append(
            MenuItem(
                "Sync Clipboard      Ctrl+Alt+C",
                lambda: _send("sync_clipboard"),
            )
        )

        # Refresh Layout
        items.append(
            MenuItem(
                "Refresh Layout      Ctrl+Alt+R",
                lambda: _send("refresh_layout"),
            )
        )

        # Wake shortcut
        items.append(
            MenuItem(
                "Wake Active Client      Ctrl+Alt+W",
                lambda: _send("wake_active"),
            )
        )
        items.append(Menu.SEPARATOR)

        # Client info submenu
        if clients:
            client_items = []
            for c in clients:
                cname = c.get('hostname', c.get('client_id', '?'))
                cid = c.get('client_id', '')
                client_items.append(
                    MenuItem(
                        f'{cname} \u2014 {c.get("address", "")}',
                        action=None,
                        enabled=False,
                    )
                )
                client_items.append(
                    MenuItem(
                        f'  Wake & Activate {cname}',
                        lambda _cid=cid: _send('wake_client', client_id=_cid),
                    )
                )
            items.append(
                MenuItem(
                    f"Connected Clients ({len(clients)})",
                    Menu(*client_items),
                )
            )
            items.append(Menu.SEPARATOR)

        # Tools submenu
        tools = [
            MenuItem("Settings...", lambda: _send("show_settings")),
            MenuItem("Check for Updates...", lambda: _send("show_updates")),
            MenuItem("Report a Bug...", lambda: _send("show_bug_report")),
        ]
        items.append(MenuItem("Tools", Menu(*tools)))

        # Update notification
        update_info = s.get("update_info")
        if update_info:
            items.append(
                MenuItem(
                    f'Update available: v{update_info["latest"]}',
                    lambda: _send("show_updates"),
                )
            )

        items.append(Menu.SEPARATOR)

        # About
        items.append(
            MenuItem(
                f"About {__app_name__} v{__version__}",
                lambda: _send("show_about"),
            )
        )
        items.append(Menu.SEPARATOR)

        # Quit
        items.append(
            MenuItem("Quit      Ctrl+Alt+Q", lambda: _send("quit"))
        )

        return Menu(*items)

    # ── stdin reader (background thread) ──────────────────

    def _stdin_reader():
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                cmd = msg.get("cmd")
                if cmd == "update":
                    _state[0] = msg.get("state", {})
                    if _icon_ref[0]:
                        _icon_ref[0].menu = _build_menu()
                        try:
                            _icon_ref[0].update_menu()
                        except Exception:
                            pass
                elif cmd == "stop":
                    if _icon_ref[0]:
                        _icon_ref[0].stop()
                    break
        except Exception:
            pass
        # stdin closed or stop received → exit
        if _icon_ref[0]:
            try:
                _icon_ref[0].stop()
            except Exception:
                pass

    # ── main entry point ──────────────────────────────────

    # Block on first line = initial state
    try:
        first_line = sys.stdin.readline().strip()
        if first_line:
            msg = json.loads(first_line)
            if msg.get("cmd") == "init":
                _state[0] = msg.get("state", {})
            else:
                _state[0] = msg  # fallback: raw state dict
    except Exception:
        pass

    # Create icon
    try:
        img = _load_icon(64)
    except Exception:
        img = Image.new("RGBA", (64, 64), (75, 0, 130, 255))

    icon = pystray.Icon(
        name="unicent-host",
        icon=img,
        title=f"{__app_name__} Host v{__version__}",
        menu=_build_menu(),
    )
    _icon_ref[0] = icon

    # Start background stdin reader for subsequent commands
    reader = threading.Thread(target=_stdin_reader, daemon=True)
    reader.start()

    # Notify parent we're ready
    _send("ready")

    # Run pystray main loop (blocks until icon.stop())
    try:
        icon.run()
    except Exception as e:
        _send("error", message=str(e))


if __name__ == "__main__":
    main()
