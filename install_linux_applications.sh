#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_PATH="$PROJECT_DIR/assets/icon-u-128.png"

mkdir -p "$APPS_DIR"

cat > "$APPS_DIR/unicent-host.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=UniCent Host
Comment=UniCent mouse and keyboard sharing host
Exec=$PROJECT_DIR/run_host.sh --no-tls --client-side left
Path=$PROJECT_DIR
Icon=$ICON_PATH
Terminal=false
Categories=Utility;Network;
Keywords=mouse;keyboard;sharing;network;remote;
StartupNotify=false
EOF

cat > "$APPS_DIR/unicent-client.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=UniCent Client
Comment=UniCent mouse and keyboard sharing client
Exec=$PROJECT_DIR/run_client.sh --no-tls --host 100.107.164.122
Path=$PROJECT_DIR
Icon=$ICON_PATH
Terminal=false
Categories=Utility;Network;
Keywords=mouse;keyboard;sharing;network;remote;
StartupNotify=false
EOF

chmod 644 "$APPS_DIR/unicent-host.desktop" "$APPS_DIR/unicent-client.desktop"
update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true

echo
echo "Installed application launchers:"
echo "  $APPS_DIR/unicent-host.desktop"
echo "  $APPS_DIR/unicent-client.desktop"
echo
echo "You can now start 'UniCent Host' or 'UniCent Client' from your applications list."
echo "The client launcher reuses the saved host IP from ~/.config/unicent/client.json if present."
echo "If the host cannot capture input on Linux, add your user to the input group and log back in:"
echo "  sudo usermod -aG input \"$USER\""