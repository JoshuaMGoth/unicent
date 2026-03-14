#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# UniCent Client Installer — Arch Linux
# ──────────────────────────────────────────────────────────
set -euo pipefail

INSTALL_DIR="/opt/unicent"
REPO_URL="https://github.com/JoshuaMGoth/unicent.git"

echo
echo "  ╔══════════════════════════════════════╗"
echo "  ║    UniCent Client — Arch Installer   ║"
echo "  ╚══════════════════════════════════════╝"
echo

if [[ $EUID -ne 0 ]]; then
    echo "  ✗ Please run as root:  sudo bash $0"
    exit 1
fi

echo "  [1/5] Installing system dependencies..."
pacman -Sy --noconfirm --needed python python-pip git xdotool xclip \
    python-pillow libappindicator-gtk3 2>/dev/null || true
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
SUDO_USER_HOME=$(eval echo ~"${SUDO_USER:-root}")
AUTOSTART_DIR="$SUDO_USER_HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
cp "$INSTALL_DIR/autostart/unicent-client.desktop" "$AUTOSTART_DIR/"
echo "  ✓ Auto-start configured for ${SUDO_USER:-root}"

echo "  [5/5] Creating launch script..."
cat > /usr/local/bin/unicent-client << 'SCRIPT'
#!/usr/bin/env bash
cd /opt/unicent
exec python3 -m client.main "$@"
SCRIPT
chmod +x /usr/local/bin/unicent-client
echo "  ✓ Launch with: unicent-client"

echo
echo "  ══════════════════════════════════════"
echo "  ✓ UniCent Client installed!"
echo "  ══════════════════════════════════════"
echo
echo "  Run:     unicent-client --host <HOST_IP> --no-tls -v"
echo
