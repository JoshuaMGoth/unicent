#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# UniCent Client Installer — macOS
# ──────────────────────────────────────────────────────────
set -euo pipefail

INSTALL_DIR="/usr/local/share/unicent"
REPO_URL="https://github.com/JoshuaMGoth/unicent.git"

echo
echo "  ╔══════════════════════════════════════╗"
echo "  ║   UniCent Client — macOS Installer   ║"
echo "  ╚══════════════════════════════════════╝"
echo

echo "  [1/5] Checking prerequisites..."
if ! command -v python3 &>/dev/null; then
    echo "  ✗ python3 not found. Install from https://python.org or via brew."
    exit 1
fi
if ! command -v git &>/dev/null; then
    echo "  ✗ git not found. Install Xcode Command Line Tools:  xcode-select --install"
    exit 1
fi
echo "  ✓ python3 and git found"

echo "  [2/5] Cloning / updating UniCent..."
if [[ -d "$INSTALL_DIR/.git" ]]; then
    cd "$INSTALL_DIR" && git pull --ff-only
else
    sudo rm -rf "$INSTALL_DIR"
    sudo git clone "$REPO_URL" "$INSTALL_DIR"
    sudo chown -R "$USER" "$INSTALL_DIR"
fi
echo "  ✓ Source code ready at $INSTALL_DIR"

echo "  [3/5] Installing Python dependencies..."
cd "$INSTALL_DIR"
if [[ ! -d ".venv" ]]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip 2>/dev/null || true
.venv/bin/pip install pyobjc-framework-Quartz rumps pystray Pillow
echo "  ✓ Python packages installed (venv)"

echo "  [4/5] Setting up auto-start (LaunchAgent)..."
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_AGENTS_DIR"
cp "$INSTALL_DIR/autostart/com.unicent.client.plist" "$LAUNCH_AGENTS_DIR/"
echo "  ✓ LaunchAgent installed"
echo "  Note: To enable, run:  launchctl load ~/Library/LaunchAgents/com.unicent.client.plist"

echo "  [5/5] Creating launch script & app bundle..."
cat > /usr/local/bin/unicent-client << 'SCRIPT'
#!/usr/bin/env bash
cd /usr/local/share/unicent

# Get Python interpreter
PYTHON=""
if [[ -f .venv/bin/python3 ]]; then
    PYTHON=".venv/bin/python3"
else
    PYTHON="python3"
fi

# Read host IP from config if not provided as argument
HOST_ARG=""
if [[ ! " $* " =~ " --host " ]]; then
    # Try to read stored host IP
    CONFIG_FILE="$HOME/.config/unicent/client.json"
    if [[ -f "$CONFIG_FILE" ]]; then
        HOST_IP=$($PYTHON -c "import json; config=json.load(open('$CONFIG_FILE')); print(config.get('host_ip', ''))" 2>/dev/null || echo "")
        if [[ -n "$HOST_IP" ]]; then
            HOST_ARG="--host $HOST_IP"
        fi
    fi
fi

# Execute client with optional host argument from config
exec $PYTHON -m client.main $HOST_ARG "$@"
SCRIPT
chmod +x /usr/local/bin/unicent-client
echo "  ✓ Launch script created at /usr/local/bin/unicent-client"

# Build .app bundle
APP_DIR="/Applications/UniCent Client.app"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"
cp "$INSTALL_DIR/assets/UniCent.icns" "$APP_DIR/Contents/Resources/AppIcon.icns"
cat > "$APP_DIR/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>UniCent Client</string>
    <key>CFBundleDisplayName</key>
    <string>UniCent Client</string>
    <key>CFBundleIdentifier</key>
    <string>com.unicent.client</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>UniCent Client</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST
cat > "$APP_DIR/Contents/MacOS/UniCent Client" << 'LAUNCH'
#!/usr/bin/env bash
cd /usr/local/share/unicent

# Get Python interpreter
PYTHON=""
if [[ -f .venv/bin/python3 ]]; then
    PYTHON=".venv/bin/python3"
else
    PYTHON="python3"
fi

# Read host IP from config if not provided as argument
HOST_ARG=""
if [[ ! " $* " =~ " --host " ]]; then
    # Try to read stored host IP
    CONFIG_FILE="$HOME/.config/unicent/client.json"
    if [[ -f "$CONFIG_FILE" ]]; then
        HOST_IP=$($PYTHON -c "import json; config=json.load(open('$CONFIG_FILE')); print(config.get('host_ip', ''))" 2>/dev/null || echo "")
        if [[ -n "$HOST_IP" ]]; then
            HOST_ARG="--host $HOST_IP"
        fi
    fi
fi

# Execute client with optional host argument from config
exec $PYTHON -m client.main $HOST_ARG "$@"
LAUNCH
chmod +x "$APP_DIR/Contents/MacOS/UniCent Client"
echo "  ✓ App bundle created at $APP_DIR"

echo
echo "  ══════════════════════════════════════"
echo "  ✓ UniCent Client installed!"
echo "  ══════════════════════════════════════"
echo
echo "  IMPORTANT: Grant Accessibility permissions!"
echo "  System Settings → Privacy & Security → Accessibility"
echo "  Add Terminal.app (or iTerm2) to the list."
echo
echo "  Run:     unicent-client --host <HOST_IP> --no-tls -v"
echo "  Or:      Open 'UniCent Client' from Applications"
echo
