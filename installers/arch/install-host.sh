#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# UniCent Host Installer — Arch Linux
# ──────────────────────────────────────────────────────────
set -euo pipefail

INSTALL_DIR="/opt/unicent"
REPO_URL="https://github.com/JoshuaMGoth/unicent.git"

echo
echo "  ╔══════════════════════════════════════╗"
echo "  ║     UniCent Host — Arch Installer    ║"
echo "  ╚══════════════════════════════════════╝"
echo

if [[ $EUID -ne 0 ]]; then
    echo "  ✗ Please run as root:  sudo bash $0"
    exit 1
fi

echo "  [1/5] Installing system dependencies..."
pacman -Sy --noconfirm --needed python python-pip git xclip xsel \
    wl-clipboard python-pillow libappindicator-gtk3 2>/dev/null || true
echo "  ✓ System packages installed"

# Add user to input group for evdev access
if [[ -n "${SUDO_USER:-}" ]]; then
    usermod -aG input "$SUDO_USER" 2>/dev/null || true
    echo "  ✓ Added $SUDO_USER to 'input' group (re-login required)"
fi

echo "  [2/5] Cloning / updating UniCent..."
if [[ -d "$INSTALL_DIR/.git" ]]; then
    cd "$INSTALL_DIR" && git pull --ff-only
else
    rm -rf "$INSTALL_DIR"
    git clone "$REPO_URL" "$INSTALL_DIR"
fi
echo "  ✓ Source code ready at $INSTALL_DIR"

echo "  [3/5] Installing Python dependencies..."
cd "$INSTALL_DIR"
python3 -m pip install --break-system-packages pystray Pillow evdev 2>/dev/null \
    || python3 -m pip install pystray Pillow evdev
echo "  ✓ Python packages installed"

echo "  [4/5] Setting up auto-start..."
SUDO_USER_HOME=$(eval echo ~"${SUDO_USER:-root}")
AUTOSTART_DIR="$SUDO_USER_HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
cp "$INSTALL_DIR/autostart/unicent-host.desktop" "$AUTOSTART_DIR/"
echo "  ✓ Auto-start configured for ${SUDO_USER:-root}"

echo "  [5/5] Creating launch script..."
cat > /usr/local/bin/unicent-host << 'SCRIPT'
#!/usr/bin/env bash
cd /opt/unicent
exec python3 -m host.main "$@"
SCRIPT
chmod +x /usr/local/bin/unicent-host
echo "  ✓ Launch with: unicent-host"

# Install icon to system location
mkdir -p /usr/share/icons/hicolor/128x128/apps
cp "$INSTALL_DIR/assets/icon-u-128.png" /usr/share/icons/hicolor/128x128/apps/unicent.png
gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true
echo "  ✓ System icon installed"

echo
echo "  ══════════════════════════════════════"
echo "  ✓ UniCent Host installed!"
echo "  ══════════════════════════════════════"
echo
echo "  Run:     sudo unicent-host --no-tls -v"
echo "  Note:    Host needs sudo for input capture (evdev)"
echo
