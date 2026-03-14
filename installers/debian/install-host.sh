#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# UniCent Host Installer — Debian / Ubuntu
# ──────────────────────────────────────────────────────────
set -euo pipefail

INSTALL_DIR="/opt/unicent"
REPO_URL="https://github.com/JoshuaMGoth/unicent.git"
ICON_SIZE=128

echo
echo "  ╔══════════════════════════════════════╗"
echo "  ║     UniCent Host — Debian Installer  ║"
echo "  ╚══════════════════════════════════════╝"
echo

# Must be root
if [[ $EUID -ne 0 ]]; then
    echo "  ✗ Please run as root:  sudo bash $0"
    exit 1
fi

echo "  [1/5] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv \
    git xdotool xclip libgirepository1.0-dev \
    gir1.2-appindicator3-0.1 2>/dev/null || true
echo "  ✓ System packages installed"

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
python3 -m pip install --break-system-packages pystray Pillow 2>/dev/null \
    || python3 -m pip install pystray Pillow
echo "  ✓ Python packages installed"

echo "  [4/5] Setting up auto-start..."
# For the user who invoked sudo:
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

echo
echo "  ══════════════════════════════════════"
echo "  ✓ UniCent Host installed!"
echo "  ══════════════════════════════════════"
echo
echo "  Run:     sudo unicent-host --no-tls -v"
echo "  Or:      unicent-host --no-tls --client-side left"
echo
