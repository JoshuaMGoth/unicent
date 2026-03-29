#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# UniCent Host Installer — macOS
# ──────────────────────────────────────────────────────────
set -euo pipefail

INSTALL_DIR="/usr/local/share/unicent"
REPO_URL="https://github.com/JoshuaMGoth/unicent.git"
APP_DIR="/Applications/UniCent Host.app"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

echo
echo "  ╔══════════════════════════════════════╗"
echo "  ║     UniCent Host — macOS Installer   ║"
echo "  ╚══════════════════════════════════════╝"
echo

# ── 1. Prerequisites ─────────────────────────────────────
echo "  [1/6] Checking prerequisites..."
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

# ── 2. Clone / update source ─────────────────────────────
echo "  [2/6] Cloning / updating UniCent..."
if [[ -d "$INSTALL_DIR/.git" ]]; then
    cd "$INSTALL_DIR"
    git -C "$INSTALL_DIR" stash 2>/dev/null || true
    git -C "$INSTALL_DIR" pull --ff-only
else
    sudo mkdir -p "$(dirname "$INSTALL_DIR")"
    sudo git clone "$REPO_URL" "$INSTALL_DIR"
    sudo chown -R "$USER" "$INSTALL_DIR"
fi
echo "  ✓ Source code ready at $INSTALL_DIR"

# ── 3. Python venv + dependencies ────────────────────────
echo "  [3/6] Installing Python dependencies..."
cd "$INSTALL_DIR"
if [[ ! -d ".venv" ]]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip --quiet 2>/dev/null || true
.venv/bin/pip install --quiet pyobjc-framework-Quartz rumps pystray Pillow
echo "  ✓ Python packages installed"

# ── 4. App bundle ────────────────────────────────────────
echo "  [4/6] Creating app bundle..."
APP_EXEC="$APP_DIR/Contents/MacOS/UniCent Host"

# Write to /Applications — writable by admin without sudo on macOS 10.14+
# Fall back to sudo if needed
_app_mkdir() { mkdir -p "$1" 2>/dev/null || sudo mkdir -p "$1"; }
_app_write() { tee "$1" > /dev/null 2>/dev/null || sudo tee "$1" > /dev/null; }

_app_mkdir "$APP_DIR/Contents/MacOS"
_app_mkdir "$APP_DIR/Contents/Resources"
[[ -f "$INSTALL_DIR/assets/UniCent.icns" ]] && \
    { cp "$INSTALL_DIR/assets/UniCent.icns" "$APP_DIR/Contents/Resources/AppIcon.icns" 2>/dev/null || \
      sudo cp "$INSTALL_DIR/assets/UniCent.icns" "$APP_DIR/Contents/Resources/AppIcon.icns"; } || true

APP_VERSION=$("$INSTALL_DIR/.venv/bin/python3" -c \
    "import sys; sys.path.insert(0,'$INSTALL_DIR'); from shared.version import __version__; print(__version__)" \
    2>/dev/null || echo "1.0")

_app_write "$APP_DIR/Contents/Info.plist" << PLIST
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
    <string>${APP_VERSION}</string>
    <key>CFBundleShortVersionString</key>
    <string>${APP_VERSION}</string>
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

_app_write "$APP_EXEC" << 'LAUNCH'
#!/usr/bin/env bash
cd /usr/local/share/unicent
if [[ -f .venv/bin/python3 ]]; then
    exec .venv/bin/python3 -m host.main "$@"
else
    exec python3 -m host.main "$@"
fi
LAUNCH
chmod +x "$APP_EXEC" 2>/dev/null || sudo chmod +x "$APP_EXEC"
codesign --force --deep -s - "$APP_DIR" 2>/dev/null || true
echo "  ✓ App bundle at $APP_DIR"

# ── 5. LaunchAgent ───────────────────────────────────────
echo "  [5/6] Installing LaunchAgent..."
PLIST_PATH="$LAUNCH_AGENTS_DIR/com.unicent.host.plist"

# Fix ownership if root grabbed this dir
if [[ -d "$LAUNCH_AGENTS_DIR" ]] && [[ "$(stat -f '%Su' "$LAUNCH_AGENTS_DIR")" == "root" ]]; then
    sudo chown "$USER" "$LAUNCH_AGENTS_DIR"
fi
mkdir -p "$LAUNCH_AGENTS_DIR"

cat > "$PLIST_PATH" << AGENT
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.unicent.host</string>
    <key>ProgramArguments</key>
    <array>
        <string>${APP_EXEC}</string>
        <string>--no-tls</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${INSTALL_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>/tmp/unicent-host.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/unicent-host.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
AGENT

# Unload any old instance, bootstrap into GUI session (modern launchctl)
launchctl bootout "gui/$(id -u)/com.unicent.host" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
echo "  ✓ LaunchAgent installed and started"

# ── 6. Accessibility permission ─────────────────────────
echo "  [6/6] Requesting Accessibility permission..."
echo
# Open the app once — this gives it a GUI context so macOS
# auto-fires the 'wants to control this computer' dialog.
sleep 1
open -a "UniCent Host" 2>/dev/null || open "$APP_DIR" 2>/dev/null || true
sleep 2
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" 2>/dev/null || true

echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║  ⚠  One-time permission required                    ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo
echo "  macOS automatically opened System Settings."
echo "  ➜  In Privacy & Security → Accessibility,"
echo "     make sure 'UniCent Host' is listed and toggled ON."
echo "  ➜  If prompted, click 'Open System Settings' first."
echo "  ➜  Only needed once — persists across reboots."
echo
echo "  ══════════════════════════════════════"
echo "  ✓ UniCent Host installed!"
echo "  ══════════════════════════════════════"
echo
echo "  Starts automatically at login (LaunchAgent)."
echo "  App:    open -a 'UniCent Host'"
echo "  Log:    tail -f /tmp/unicent-host.err"
echo "  Reload: launchctl kickstart -k gui/\$(id -u)/com.unicent.host"
echo
