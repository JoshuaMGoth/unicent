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

### Option 1: One-Command Installer

Pick the right installer for your OS and role:

```bash
# Debian/Ubuntu — Host
sudo bash installers/debian/install-host.sh

# Debian/Ubuntu — Client
sudo bash installers/debian/install-client.sh

# Arch Linux — Host
sudo bash installers/arch/install-host.sh

# Arch Linux — Client
sudo bash installers/arch/install-client.sh

# macOS — Host
bash installers/macos/install-host.sh

# macOS — Client
bash installers/macos/install-client.sh

# Windows — Host (PowerShell as Admin)
Set-ExecutionPolicy Bypass -Scope Process -Force
.\installers\windows\install-host.ps1

# Windows — Client (PowerShell as Admin)
.\installers\windows\install-client.ps1
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
| Ctrl+Alt+1 | Switch to machine #1 (host) |
| Ctrl+Alt+2 | Switch to machine #2 (first client) |
| Ctrl+Alt+3-5 | Switch to machine #3-5 |
| Ctrl+Alt+C | Sync clipboard to all clients |

### System Tray

The 'U' icon appears in your system tray (or macOS menu bar). Right-click for:
- Current control status
- Switch between machines
- Toggle client side (left/right)
- Sync clipboard
- View connected clients
- Quit

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

## License

MIT
