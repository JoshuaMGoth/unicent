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
if ! command -v git &>/dev/null; then
    echo "  ⚙ Git not found — installing Xcode Command Line Tools..."
    xcode-select --install 2>/dev/null || true
    echo "  Please complete the Xcode install dialog, then re-run this script."
    exit 1
fi
if ! command -v python3 &>/dev/null; then
    if command -v brew &>/dev/null; then
        echo "  ⚙ Python 3 not found — installing via Homebrew..."
        brew install python3
    else
        echo "  ✗ python3 not found. Install from https://python.org or run: brew install python3"
        exit 1
    fi
fi
echo "  ✓ python3 and git found"

echo "  [2/5] Cloning / updating UniCent..."
if [[ -d "$INSTALL_DIR/.git" ]]; then
    git -C "$INSTALL_DIR" stash 2>/dev/null || true
    git -C "$INSTALL_DIR" pull --ff-only
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
.venv/bin/pip install --upgrade pip --quiet 2>/dev/null || true
.venv/bin/pip install --quiet pyobjc-framework-Quartz rumps pystray Pillow
echo "  ✓ Python packages installed"

echo "  [4/5] Setting up auto-start (LaunchAgent)..."
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
# Fix ownership if root grabbed this dir
if [[ -d "$LAUNCH_AGENTS_DIR" ]] && [[ "$(stat -f '%Su' "$LAUNCH_AGENTS_DIR")" == "root" ]]; then
    sudo chown "$USER" "$LAUNCH_AGENTS_DIR"
fi
mkdir -p "$LAUNCH_AGENTS_DIR"
cp "$INSTALL_DIR/autostart/com.unicent.client.plist" "$LAUNCH_AGENTS_DIR/"
echo "  ✓ LaunchAgent installed"

echo "  [5/5] Creating app bundle & launch script..."

APP_DIR="/Applications/UniCent Client.app"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"
cp "$INSTALL_DIR/assets/UniCent.icns" "$APP_DIR/Contents/Resources/AppIcon.icns"

# Read version from source
APP_VERSION=$(python3 -c "
import sys; sys.path.insert(0,'$INSTALL_DIR')
from shared.version import __version__; print(__version__)
" 2>/dev/null || echo "1.2.0")

cat > "$APP_DIR/Contents/Info.plist" << PLIST
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
    <string>$APP_VERSION</string>
    <key>CFBundleShortVersionString</key>
    <string>$APP_VERSION</string>
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

# Launcher script — does NOT exec to keep the .app process identity
cat > "$APP_DIR/Contents/MacOS/UniCent Client" << 'LAUNCH'
#!/usr/bin/env bash
cd /usr/local/share/unicent
export PYTHONDONTWRITEBYTECODE=1

if [[ -f .venv/bin/python3 ]]; then
    PYTHON=".venv/bin/python3"
else
    PYTHON="python3"
fi

# Run as child process (not exec) so macOS keeps our app identity
# for Accessibility permissions and menu bar name
"$PYTHON" -m client.main "$@"
LAUNCH
chmod +x "$APP_DIR/Contents/MacOS/UniCent Client"

# Ad-hoc codesign so macOS treats this as a proper app
codesign --force --deep -s - "$APP_DIR" 2>/dev/null || true

echo "  ✓ App bundle created at $APP_DIR"

# CLI wrapper for terminal usage
cat > /usr/local/bin/unicent-client << 'SCRIPT'
#!/usr/bin/env bash
# Open the .app bundle so macOS associates it properly
open -W -a "UniCent Client" --args "$@"
SCRIPT
chmod +x /usr/local/bin/unicent-client
echo "  ✓ CLI wrapper created at /usr/local/bin/unicent-client"

# ── LaunchAgent for auto-start ──
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/com.unicent.client.plist"
mkdir -p "$LAUNCH_AGENTS_DIR"

# Stop any existing instance
launchctl bootout "gui/$(id -u)/com.unicent.client" 2>/dev/null || true

cat > "$PLIST_PATH" << 'AGENT'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.unicent.client</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Applications/UniCent Client.app/Contents/MacOS/UniCent Client</string>
        <string>--no-tls</string>
        <string>-v</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/usr/local/share/unicent</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>StandardOutPath</key>
    <string>/tmp/unicent-client.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/unicent-client.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
AGENT
echo "  ✓ LaunchAgent installed (auto-starts on login)"

# ── Accessibility permission ──
echo
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║  Accessibility Permission Required               ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo
echo "  UniCent needs Accessibility permission to control"
echo "  your mouse and keyboard. On first launch, macOS"
echo "  will prompt you to grant access."
echo
echo "  If cursor movement doesn't work:"
echo "    1. Open System Settings → Privacy & Security → Accessibility"
echo "    2. Click the + button"
echo "    3. Add Python (or the Python.app from Xcode's framework)"
echo "    4. Toggle it ON"
echo "    5. Restart UniCent"
echo

echo "  ══════════════════════════════════════"
echo "  ✓ UniCent Client installed!"
echo "  ══════════════════════════════════════"
echo
echo "  Starting UniCent..."
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
echo "  ✓ UniCent is running — look for the U icon in your menu bar"
echo
echo "  To stop:   launchctl bootout gui/\$(id -u)/com.unicent.client"
echo "  To start:  launchctl bootstrap gui/\$(id -u) $PLIST_PATH"
echo
