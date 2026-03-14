#!/bin/bash
# Setup script for UniCent CLIENT on macOS.
#
# Installs Python dependencies and configures permissions.
#
# Usage: ./setup_client.sh

set -e

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║       UniCent CLIENT Setup           ║"
echo "  ║     macOS                            ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# Check macOS
if [ "$(uname)" != "Darwin" ]; then
    echo "  [ERROR] This script is for macOS only."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_DIR="$SCRIPT_DIR/certs"

# --- Check Python ---
echo "  [1/4] Checking Python..."

PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON="python3"
    echo "    Python3: $($PYTHON --version)"
elif command -v python &>/dev/null; then
    PY_VER=$(python --version 2>&1)
    if [[ "$PY_VER" == *"3."* ]]; then
        PYTHON="python"
        echo "    Python: $PY_VER"
    fi
fi

if [ -z "$PYTHON" ]; then
    echo "    [ERROR] Python 3 not found!"
    echo ""
    echo "    Install Python 3 using one of:"
    echo "      1. brew install python3"
    echo "      2. Download from https://www.python.org/downloads/macos/"
    echo ""
    exit 1
fi

# --- Install pip if needed ---
if ! $PYTHON -m pip --version &>/dev/null 2>&1; then
    echo "    Installing pip..."
    curl -sS https://bootstrap.pypa.io/get-pip.py | $PYTHON 2>/dev/null || {
        echo "    [WARNING] Could not install pip"
        echo "    Install manually: https://pip.pypa.io/en/stable/installation/"
    }
fi

# --- Install Python packages ---
echo ""
echo "  [2/4] Installing Python packages..."

# Install pyobjc frameworks for Quartz access
echo "    Installing pyobjc-framework-Quartz..."
$PYTHON -m pip install pyobjc-framework-Quartz --quiet --break-system-packages 2>/dev/null || \
    $PYTHON -m pip install pyobjc-framework-Quartz --quiet 2>/dev/null || \
    $PYTHON -m pip install pyobjc-framework-Quartz --user --quiet 2>/dev/null || {
        echo "    [ERROR] Failed to install pyobjc-framework-Quartz"
        echo "    Try: pip3 install pyobjc-framework-Quartz"
        exit 1
    }

echo "    Installing pyobjc-framework-ApplicationServices..."
$PYTHON -m pip install pyobjc-framework-ApplicationServices --quiet --break-system-packages 2>/dev/null || \
    $PYTHON -m pip install pyobjc-framework-ApplicationServices --quiet 2>/dev/null || \
    $PYTHON -m pip install pyobjc-framework-ApplicationServices --user --quiet 2>/dev/null || true

# Verify imports
echo ""
echo "  Verifying installations..."
$PYTHON -c "import Quartz; print('    Quartz: OK')" 2>/dev/null || {
    echo "    [WARNING] Quartz import failed"
}

# --- Check certificates ---
echo ""
echo "  [3/4] Checking TLS certificates..."

mkdir -p "$CERT_DIR"

if [ -f "$CERT_DIR/ca.crt" ] && [ -f "$CERT_DIR/client.crt" ]; then
    echo "    Certificates found in $CERT_DIR/"
    echo "    CA cert:     $(openssl x509 -noout -subject -in "$CERT_DIR/ca.crt" 2>/dev/null)"
    echo "    Client cert: $(openssl x509 -noout -subject -in "$CERT_DIR/client.crt" 2>/dev/null)"
else
    echo "    [WARNING] TLS certificates not found!"
    echo ""
    echo "    Copy these files from the host machine:"
    echo "      ca.crt, client.crt, client.key"
    echo ""
    echo "    Place them in: $CERT_DIR/"
    echo ""
    echo "    Example (from host machine):"
    echo "      scp certs/ca.crt certs/client.* user@$(hostname):$CERT_DIR/"
    echo ""
    echo "    Or use --no-tls to run without encryption."
fi

# --- Accessibility permissions ---
echo ""
echo "  [4/4] Accessibility permissions..."
echo ""
echo "    UniCent needs Accessibility access to inject input events."
echo "    When you first run the client, macOS will prompt for permission."
echo ""
echo "    If it doesn't work:"
echo "    1. Open System Settings → Privacy & Security → Accessibility"
echo "    2. Add your terminal app (Terminal.app, iTerm2, etc.)"
echo "    3. Enable the toggle"
echo "    4. Restart the client"
echo ""

# --- Done ---
echo "  ╔══════════════════════════════════════╗"
echo "  ║           Setup Complete!            ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
echo "  To start the client:"
echo "    cd $SCRIPT_DIR"
echo "    $PYTHON -m client.main"
echo ""
echo "  Options:"
echo "    --host HOST     Host IP address (auto-discover if omitted)"
echo "    --port PORT     Host port (default: 27183)"
echo "    --no-tls        Disable encryption"
echo "    -v              Verbose logging"
echo ""
