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
python3 -m pip install --user pyobjc-framework-Quartz rumps pystray Pillow 2>/dev/null \
    || pip3 install pyobjc-framework-Quartz rumps pystray Pillow
echo "  ✓ Python packages installed"

echo "  [4/5] Setting up auto-start (LaunchAgent)..."
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_AGENTS_DIR"
cp "$INSTALL_DIR/autostart/com.unicent.host.plist" "$LAUNCH_AGENTS_DIR/"
echo "  ✓ LaunchAgent installed"
echo "  Note: To enable, run:  launchctl load ~/Library/LaunchAgents/com.unicent.host.plist"

echo "  [5/5] Creating launch script..."
cat > /usr/local/bin/unicent-host << 'SCRIPT'
#!/usr/bin/env bash
cd /usr/local/share/unicent
exec python3 -m host.main "$@"
SCRIPT
chmod +x /usr/local/bin/unicent-host
echo "  ✓ Launch with: unicent-host"

echo
echo "  ══════════════════════════════════════"
echo "  ✓ UniCent Host installed!"
echo "  ══════════════════════════════════════"
echo
echo "  IMPORTANT: Grant Accessibility permissions!"
echo "  System Settings → Privacy & Security → Accessibility"
echo "  Add Terminal.app (or iTerm2) to the list."
echo
echo "  Run:     unicent-host --no-tls -v"
echo
