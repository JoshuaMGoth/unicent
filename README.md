# UniCent

**Cross-platform mouse & keyboard sharing over the network.**

Share a single mouse and keyboard between any combination of Linux, macOS, and Windows computers. Move your cursor to the screen edge and it seamlessly appears on the other machine.

## Features

- **Seamless edge switching** — move mouse to screen edge, cursor appears on the other computer
- **Full cross-platform** — Linux (Arch, Debian, Ubuntu), macOS, and Windows as host *or* client
- **Keyboard shortcuts** — instantly switch control between machines (Ctrl+Alt+S, Ctrl+Alt+1-5)
- **System tray icon** — 'U' icon with full control menu
- **Auto-start on boot** — systemd / LaunchAgent / Registry autostart support
- **Auto-discovery** — finds peers on the local network via UDP broadcast
- **TLS encryption** — optional encrypted communication with certificates
- **Clipboard sharing** — copy on one machine, paste on the other (Ctrl+Alt+C)
- **Multi-monitor support** — handles multiple displays per machine
- **One-command installers** — for Debian, Ubuntu, Arch Linux, macOS, and Windows
- **Low latency** — binary protocol with TCP_NODELAY, ~1ms flush interval

## Architecture

```
┌─────────────────────┐         TCP               ┌─────────────────────┐
│       HOST          │◄────────────────────────►│       CLIENT         │
│  (any OS)           │                           │  (any OS)            │
│                     │  Binary protocol:         │                      │
│  Input capture:     │  - Mouse move (9 bytes)   │  Input injection:    │
│  • Linux evdev      │  - Key event (8 bytes)    │  • macOS Quartz      │
│  • macOS CGEventTap │  - Scroll (9 bytes)       │  • Linux xdotool     │
│  • Windows hooks    │  - Clipboard (JSON)       │  • Windows SendInput │
│                     │  - Switch active (JSON)   │                      │
│  Screen layout mgr  │                           │  Screen detection    │
│  Hotkey detection    │                           │  Clipboard bridge    │
│  Discovery beacon    │                           │  Auto-reconnect      │
└─────────────────────┘                           └─────────────────────┘
```

## Supported Platforms

| OS | Host | Client | Installer |
|----|------|--------|-----------|
| Arch Linux | ✅ | ✅ | `installers/arch/` |
| Debian | ✅ | ✅ | `installers/debian/` |
| Ubuntu | ✅ | ✅ | `installers/ubuntu/` |
| macOS | ✅ | ✅ | `installers/macos/` |
| Windows | ✅ | ✅ | `installers/windows/` |

Any host can connect to any client — all combinations work together.

## Quick Start

### Option 1: One-Command Installer (Remote)

Install directly from GitHub — no clone needed:

**Debian / Ubuntu:**
```bash
# Host
curl -fsSL https://raw.githubusercontent.com/JoshuaMGoth/unicent/main/installers/debian/install-host.sh | sudo bash

# Client
curl -fsSL https://raw.githubusercontent.com/JoshuaMGoth/unicent/main/installers/debian/install-client.sh | sudo bash
```

**Arch Linux:**
```bash
# Host
curl -fsSL https://raw.githubusercontent.com/JoshuaMGoth/unicent/main/installers/arch/install-host.sh | sudo bash

# Client
curl -fsSL https://raw.githubusercontent.com/JoshuaMGoth/unicent/main/installers/arch/install-client.sh | sudo bash
```

**Ubuntu:**
```bash
# Host
curl -fsSL https://raw.githubusercontent.com/JoshuaMGoth/unicent/main/installers/ubuntu/install-host.sh | sudo bash

# Client
curl -fsSL https://raw.githubusercontent.com/JoshuaMGoth/unicent/main/installers/ubuntu/install-client.sh | sudo bash
```

**macOS:**
```bash
# Host
curl -fsSL https://raw.githubusercontent.com/JoshuaMGoth/unicent/main/installers/macos/install-host.sh | bash

# Client
curl -fsSL https://raw.githubusercontent.com/JoshuaMGoth/unicent/main/installers/macos/install-client.sh | bash
```

**Windows (PowerShell as Administrator):**
```powershell
# Host
Set-ExecutionPolicy Bypass -Scope Process -Force
irm https://raw.githubusercontent.com/JoshuaMGoth/unicent/main/installers/windows/install-host.ps1 | iex

# Client
Set-ExecutionPolicy Bypass -Scope Process -Force
irm https://raw.githubusercontent.com/JoshuaMGoth/unicent/main/installers/windows/install-client.ps1 | iex
```

### Option 2: Manual Setup

**Host (the computer with the keyboard/mouse):**
```bash
git clone https://github.com/JoshuaMGoth/unicent.git
cd unicent
pip install pystray Pillow   # Linux/Windows
# or: pip install pyobjc-framework-Quartz rumps   # macOS

# Linux: needs sudo for evdev input capture
sudo python3 -m host.main --no-tls --client-side right -v

# macOS/Windows: no sudo needed
python3 -m host.main --no-tls -v
```

**Client (the computer to be controlled):**
```bash
pip install pystray Pillow   # Linux/Windows
# or: pip install pyobjc-framework-Quartz rumps   # macOS

python3 -m client.main --host <HOST_IP> --no-tls -v
```

### Option 3: Linux Application Launcher (from this repo checkout)

If you want UniCent to appear in your desktop environment's applications list, install user-level launchers:

```bash
chmod +x ./install_linux_applications.sh
./install_linux_applications.sh
```

This creates:

- `~/.local/share/applications/unicent-host.desktop`
- `~/.local/share/applications/unicent-client.desktop`

Launcher behavior:

- `UniCent Host` starts `./run_host.sh --no-tls --client-side left`
- `UniCent Client` starts `./run_client.sh --no-tls`
- The client reuses the saved host IP from `~/.config/unicent/client.json` after the first successful connection

If Linux host input capture fails, add your user to the `input` group and log out/in:

```bash
sudo usermod -aG input "$USER"
```

## Usage

### Host
```bash
python3 -m host.main [OPTIONS]

Options:
  --port PORT          TCP port (default: 27183)
  --client-side SIDE   left or right (default: right)
  --no-tls             Disable TLS encryption
  --no-tray            Disable system tray icon
  --cert FILE          TLS certificate file
  --key FILE           TLS key file
  --ca FILE            CA certificate file
  -v, --verbose        Verbose logging
```

### Client
```bash
python3 -m client.main [OPTIONS]

Options:
  --host HOST          Host IP address (or auto-discover)
  --port PORT          Host TCP port (default: 27183)
  --no-tls             Disable TLS encryption
  --no-tray            Disable system tray / menu bar icon
  --cert FILE          Client TLS certificate file
  --ca FILE            CA certificate file
  -v, --verbose        Verbose logging
```

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+Alt+S | Switch to next machine |
| Ctrl+Alt+1 | Switch to host (machine #1) |
| Ctrl+Alt+2–9 | Switch to client #2 through #9 |
| Ctrl+Alt+C | Sync clipboard between all machines |
| Ctrl+Alt+W | Wake & activate the current client's display |
| Ctrl+Alt+R | Refresh screen layout |

### System Tray

The 'U' icon appears in your system tray (or macOS menu bar). Right-click for:
- Current control status
- Switch between machines
- Toggle client side (left/right)
- Sync clipboard
- View connected clients
- Quit

## macOS: Required Permissions

macOS requires **Accessibility** permission for UniCent to move the cursor and inject input events. Without this, the connection will appear to work but the cursor won't actually move.

### After Installing (One-Time Setup)

The macOS installer will automatically open System Settings and reveal the correct binary. If you need to do it manually:

1. Find the Python binary UniCent uses:
   ```bash
   /usr/local/share/unicent/.venv/bin/python3 -c "import sys; print(sys.executable)"
   ```
   This will print a path like:
   `/Applications/Xcode.app/Contents/Developer/.../Python3.framework/.../Python.app/Contents/MacOS/Python`

2. Open **System Settings → Privacy & Security → Accessibility**

3. Click the **+** button and add the `Python.app` bundle that contains the binary from step 1. You can reveal it in Finder with:
   ```bash
   # Find and open the Python.app bundle in Finder
   open -R "$(python3 -c "
   import sys, os
   p = sys.executable
   while p != '/':
       if p.endswith('.app'): print(p); break
       p = os.path.dirname(p)
   ")"
   ```

4. Make sure the toggle next to it is **ON**

5. **Restart the UniCent client/host** — macOS only applies the permission to newly launched processes.

> **Note:** If you update Python or Xcode, the binary path may change and you'll need to re-add the new `Python.app` to Accessibility.

## Auto-Start on Boot

The installers configure auto-start automatically. To set up manually:

### Linux (XDG Autostart)
```bash
cp autostart/unicent-host.desktop ~/.config/autostart/
# or for client:
cp autostart/unicent-client.desktop ~/.config/autostart/
```

### macOS (LaunchAgent)
```bash
cp autostart/com.unicent.host.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.unicent.host.plist
# or for client:
cp autostart/com.unicent.client.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.unicent.client.plist
```

### Windows (Registry)
The PowerShell installers add a Registry entry to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.

## Project Structure

```
unicent/
├── host/                   # Host-side code
│   ├── main.py             # Host entry point + cursor helpers
│   ├── server.py           # TCP server + client management
│   ├── input_capture.py    # Cross-platform input capture (evdev/CGEventTap/hooks)
│   ├── screen_manager.py   # Virtual screen layout + screen detection
│   └── tray.py             # System tray icon (pystray)
├── client/                 # Client-side code
│   ├── main.py             # Client entry point
│   ├── connection.py       # TCP connection + auto-reconnect
│   ├── input_inject.py     # Cross-platform input injection (Quartz/xdotool/SendInput)
│   ├── screen_manager.py   # Screen detection + clipboard
│   └── tray.py             # System tray / menu bar (rumps on macOS, pystray elsewhere)
├── shared/                 # Shared protocol + utilities
│   ├── protocol.py         # Binary wire protocol
│   ├── keymap.py           # evdev ↔ macOS/Windows key mappings
│   └── discovery.py        # UDP auto-discovery
├── assets/                 # Icon files
│   ├── icon-u-*.png        # 'U' icons (16-512px)
│   └── icon-u.svg          # SVG source
├── autostart/              # Auto-start configs
│   ├── unicent-host.desktop
│   ├── unicent-client.desktop
│   ├── com.unicent.host.plist
│   └── com.unicent.client.plist
├── installers/             # One-command installers
│   ├── debian/             # Debian install scripts
│   ├── ubuntu/             # Ubuntu install scripts
│   ├── arch/               # Arch Linux install scripts
│   ├── macos/              # macOS install scripts
│   └── windows/            # Windows PowerShell scripts
└── README.md
```

## Dependencies

### Host
| Platform | Dependencies |
|----------|-------------|
| Linux | python3, xdotool, xclip, pystray, Pillow |
| macOS | python3, pyobjc-framework-Quartz, rumps, pystray, Pillow |
| Windows | python3, pystray, Pillow |

### Client
| Platform | Dependencies |
|----------|-------------|
| Linux | python3, xdotool, xclip, pystray, Pillow |
| macOS | python3, pyobjc-framework-Quartz, rumps |
| Windows | python3, pystray, Pillow |

## Website

[joshuagoth.com/downloads/unicent](https://joshuagoth.com/downloads/unicent/)

## License

MIT

---

*A [JoshuaGoth Software](https://joshuagoth.com) project.*
