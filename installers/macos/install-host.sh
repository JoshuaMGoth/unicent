#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# UniCent Host Installer — macOS
# ──────────────────────────────────────────────────────────
set -euo pipefail

INSTALL_DIR="/usr/local/share/unicent"
REPO_URL="https://github.com/JoshuaMGoth/unicent.git"

echo
echo "  ╔══════════════════════════════════════╗"
echo "  ║     UniCent Host — macOS Installer   ║"
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
cp "$INSTALL_DIR/autostart/com.unicent.host.plist" "$LAUNCH_AGENTS_DIR/"
echo "  ✓ LaunchAgent installed"
echo "  Note: To enable, run:  launchctl load ~/Library/LaunchAgents/com.unicent.host.plist"

echo "  [5/5] Creating launch script & app bundle..."
cat > /usr/local/bin/unicent-host << 'SCRIPT'
#!/usr/bin/env bash
cd /usr/local/share/unicent
if [[ -f .venv/bin/python3 ]]; then
    exec .venv/bin/python3 -m host.main "$@"
else
    exec python3 -m host.main "$@"
fi
SCRIPT
chmod +x /usr/local/bin/unicent-host
echo "  ✓ Launch with: unicent-host"

# Build .app bundle
APP_DIR="/Applications/UniCent Host.app"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"
cp "$INSTALL_DIR/assets/UniCent.icns" "$APP_DIR/Contents/Resources/AppIcon.icns"
cat > "$APP_DIR/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>UniCent Host</string>
    <key>CFBundleDisplayName</key>
    <string>UniCent Host</string>
    <key>CFBundleIdentifier</key>
    <string>com.unicent.host</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>UniCent Host</string>
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
cat > "$APP_DIR/Contents/MacOS/UniCent Host" << 'LAUNCH'
#!/usr/bin/env bash
cd /usr/local/share/unicent
if [[ -f .venv/bin/python3 ]]; then
    exec .venv/bin/python3 -m host.main "$@"
else
    exec python3 -m host.main "$@"
fi
LAUNCH
chmod +x "$APP_DIR/Contents/MacOS/UniCent Host"
echo "  ✓ App bundle created at $APP_DIR"

# ── Grant Accessibility permission (required for input capture) ──
echo
echo "  [!] macOS requires Accessibility permission for input capture."
echo

# Find the real Python binary that will run UniCent
PYTHON_BIN=""
if [[ -f "$INSTALL_DIR/.venv/bin/python3" ]]; then
    PYTHON_BIN=$("$INSTALL_DIR/.venv/bin/python3" -c "import sys; print(sys.executable)" 2>/dev/null || echo "")
fi
if [[ -z "$PYTHON_BIN" ]]; then
    PYTHON_BIN=$(python3 -c "import sys; print(sys.executable)" 2>/dev/null || echo "")
fi

# Find the .app bundle containing the Python binary (macOS framework Python)
PYTHON_APP=""
if [[ -n "$PYTHON_BIN" ]]; then
    _p="$PYTHON_BIN"
    while [[ "$_p" != "/" ]]; do
        if [[ "$_p" == *.app ]]; then
            PYTHON_APP="$_p"
            break
        fi
        _p=$(dirname "$_p")
    done
fi

if [[ -n "$PYTHON_APP" ]]; then
    echo "  The Python binary that needs permission is:"
    echo "    $PYTHON_APP"
    echo
    echo "  Opening System Settings and Finder now..."
    open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" 2>/dev/null || true
    open -R "$PYTHON_APP" 2>/dev/null || true
    echo
    echo "  ➜  Drag 'Python.app' from the Finder window into the"
    echo "     Accessibility list in System Settings, then toggle it ON."
else
    echo "  System Settings → Privacy & Security → Accessibility"
    echo "  Add the Python binary used by UniCent to the list."
    echo "  (Run: python3 -c 'import sys; print(sys.executable)' to find it)"
fi

echo
echo "  ══════════════════════════════════════"
echo "  ✓ UniCent Host installed!"
echo "  ══════════════════════════════════════"
echo
echo "  Run:     unicent-host --no-tls -v"
echo "  Or:      Open 'UniCent Host' from Applications"
echo
