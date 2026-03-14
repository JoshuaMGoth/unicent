# UniCent

**Cross-platform mouse & keyboard sharing over WiFi/network.**

Share a single mouse and keyboard between an Arch Linux machine (including the installer environment) and macOS computers. Move your cursor to the screen edge and it seamlessly appears on the other machine.

## Features

- **Seamless edge switching** — move mouse to screen edge, cursor appears on the other computer
- **Keyboard shortcuts** — instantly switch control between machines
- **Toggle menu** — quick-select which computer to control
- **Auto-discovery** — automatically finds peers on the local network
- **TLS encryption** — all communication encrypted with certificates
- **Clipboard sharing** — copy on one machine, paste on the other
- **Multi-monitor support** — handles multiple displays per machine
- **Minimal dependencies** — works from Arch Linux installer environment
- **Low latency** — binary protocol with TCP_NODELAY, ~1ms flush interval

## Architecture

```
┌─────────────────────┐         TLS/TCP          ┌─────────────────────┐
│   HOST (Arch Linux) │◄────────────────────────►│  CLIENT (macOS)     │
│                     │                           │                     │
│  evdev input capture│  Binary protocol:         │  Quartz injection   │
│  Screen layout mgr  │  - Mouse move (9 bytes)   │  Screen detection   │
│  Hotkey detection    │  - Key event (8 bytes)    │  Clipboard bridge   │
│  Discovery beacon    │  - Scroll (9 bytes)       │  Auto-reconnect     │
│  TLS server          │  - Clipboard (JSON)       │  TLS client         │
└─────────────────────┘                           └─────────────────────┘
         ▲                                                    ▲
         │                                                    │
    UDP broadcast                                       UDP broadcast
    (discovery)                                         (discovery)
```

## Quick Start

### 1. Host Setup (Arch Linux)

```bash
# Clone or copy UniCent to the machine
cd mouse-share

# Run setup (installs dependencies, generates TLS certs)
sudo ./setup_host.sh

# Start the host
sudo ./run_host.sh
```

If you're in the **Arch installer environment**:
```bash
# Ensure network connectivity first
ip link
dhcpcd  # or: systemctl start dhcpcd

# Run setup
sudo ./setup_host.sh

# Start
sudo python3 -m host.main --no-tls  # or with TLS if certs were generated
```

### 2. Client Setup (macOS)

```bash
# Clone or copy UniCent to the Mac
cd mouse-share

# Run setup (installs Python packages)
./setup_client.sh

# Copy TLS certificates from host (if using TLS)
# On the host: scp certs/ca.crt certs/client.* user@mac:~/mouse-share/certs/

# Start the client (auto-discovers host)
./run_client.sh

# Or specify host IP directly
python3 -m client.main --host 192.168.1.100
```

### 3. Grant macOS Accessibility Permissions

macOS requires Accessibility access to inject input events:

1. Open **System Settings** → **Privacy & Security** → **Accessibility**
2. Click **+** and add your terminal app (Terminal, iTerm2, etc.)
3. Enable the toggle
4. Restart the client

## Usage

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Alt+S` or `ScrollLock` | Switch to next computer |
| `Ctrl+Alt+1` | Switch to host (local) |
| `Ctrl+Alt+2` | Switch to client 1 |
| `Ctrl+Alt+3` | Switch to client 2 |
| `Ctrl+Alt+T` | Show computer selection menu |
| `Ctrl+Alt+C` | Sync clipboard |
| `Ctrl+Alt+Q` | Quit |

### Edge Switching

The virtual screen layout arranges all machines left-to-right:

```
┌──────────┐ ┌──────────┐ ┌──────────┐
│  HOST    │ │ CLIENT 1 │ │ CLIENT 2 │
│ 1920x1080│ │ 2560x1440│ │ 1920x1080│
└──────────┘ └──────────┘ └──────────┘
```

Moving the mouse cursor to the right edge of the host screen will make it appear on the left edge of Client 1's screen (and vice versa).

## Command Line Options

### Host
```
sudo python3 -m host.main [options]

Options:
  -p, --port PORT    Server port (default: 27183)
  --no-tls           Disable TLS encryption
  --no-grab          Don't grab input devices exclusively
  --certs DIR        Certificate directory (default: certs)
  -v, --verbose      Debug logging
```

### Client
```
python3 -m client.main [options]

Options:
  --host HOST        Host IP (auto-discover if omitted)
  -p, --port PORT    Host port (default: 27183)
  --no-tls           Disable TLS encryption
  --certs DIR        Certificate directory (default: certs)
  -v, --verbose      Debug logging
```

## TLS Encryption

Generate certificates on the host:
```bash
./generate_certs.sh
```

This creates:
- `certs/ca.crt` — Certificate Authority (copy to client)
- `certs/server.crt`, `server.key` — Host server cert
- `certs/client.crt`, `client.key` — Client cert (copy to client)

Transfer to the macOS client:
```bash
scp certs/ca.crt certs/client.crt certs/client.key user@mac:~/mouse-share/certs/
```

## Protocol Details

The binary protocol is designed for minimal latency:

| Message | Type ID | Payload | Total Size |
|---------|---------|---------|------------|
| Mouse Move | `0x01` | dx(i16) + dy(i16) | 9 bytes |
| Mouse Button | `0x02` | button(u8) + state(u8) | 7 bytes |
| Scroll | `0x03` | dx(i16) + dy(i16) | 9 bytes |
| Key Event | `0x04` | keycode(u16) + state(u8) | 8 bytes |
| Control msgs | `0x10+` | JSON payload | variable |

All messages share a 5-byte header: `[type: u8][length: u32 BE]`

Optimizations:
- `TCP_NODELAY` disables Nagle's algorithm
- 1ms flush interval for batched writes
- Events are read in batches from evdev
- Direct binary encoding (no serialization overhead for input events)

## Project Structure

```
mouse-share/
├── shared/                  # Shared modules
│   ├── protocol.py          # Binary wire protocol
│   ├── discovery.py         # UDP network auto-discovery
│   └── keymap.py            # Linux ↔ macOS key code mapping
├── host/                    # Arch Linux host
│   ├── main.py              # Entry point
│   ├── input_capture.py     # evdev input reading + hotkeys
│   ├── screen_manager.py    # Virtual screen layout
│   └── server.py            # TLS server + event forwarding
├── client/                  # macOS client
│   ├── main.py              # Entry point
│   ├── input_inject.py      # Quartz/CoreGraphics injection
│   ├── screen_manager.py    # macOS screen detection
│   └── connection.py        # TLS client connection
├── generate_certs.sh        # TLS certificate generator
├── setup_host.sh            # Host dependency installer
├── setup_client.sh          # Client dependency installer
├── run_host.sh              # Quick start: host
└── run_client.sh            # Quick start: client
```

## Requirements

### Host (Arch Linux)
- Python 3.6+
- `python-evdev` (for input device capture)
- Root access (for `/dev/input` access)
- OpenSSL (for certificate generation)

### Client (macOS)
- Python 3.6+
- `pyobjc-framework-Quartz` (for input injection)
- Accessibility permissions (for input injection)
- macOS 10.13+ (High Sierra or later)

## Troubleshooting

### Host: "No input devices found"
- Run with `sudo`
- Check that `/dev/input/event*` devices exist: `ls /dev/input/event*`
- In the Arch installer, input devices should be available by default

### Host: "Cannot open input device"
- Ensure no other program has grabbed the device
- Check permissions: `ls -la /dev/input/event*`

### Client: Input injection not working
- Grant Accessibility permissions in System Settings
- Make sure you're adding the correct terminal app
- Try restarting the terminal app after granting permissions

### Client: Cannot connect
- Check that both machines are on the same network
- Verify the host IP: `ip addr` on the host
- Try with `--no-tls` if certificate issues: `python3 -m client.main --host IP --no-tls`
- Check firewall: the host uses TCP port 27183 and UDP port 27182

### Clipboard not syncing
- On macOS, `pbcopy`/`pbpaste` must be available
- On Linux without X11, clipboard is internal only

## License

MIT
