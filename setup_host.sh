#!/bin/bash
# Setup script for UniCent HOST on Arch Linux.
#
# Works in both full Arch installations and the Arch installer environment.
# Installs required packages and configures the system.
#
# Usage: sudo ./setup_host.sh

set -e

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║       UniCent HOST Setup             ║"
echo "  ║     Arch Linux                       ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# Check root
if [ "$EUID" -ne 0 ]; then
    echo "  [ERROR] This script must be run as root (sudo)."
    exit 1
fi

# Detect if we're in the installer or a full system
IS_INSTALLER=false
if [ -f /run/archiso/bootmnt/arch/boot/x86_64/vmlinuz-linux ] || \
   mountpoint -q /run/archiso 2>/dev/null; then
    IS_INSTALLER=true
    echo "  Detected: Arch Linux Installer Environment"
else
    echo "  Detected: Arch Linux Installation"
fi

# --- Install dependencies ---
echo ""
echo "  [1/4] Installing dependencies..."

if $IS_INSTALLER; then
    # In the installer, we use pacman with --needed
    # Python3 should already be available
    if command -v python3 &>/dev/null; then
        echo "    Python3 is available: $(python3 --version)"
    else
        echo "    Installing python..."
        pacman -Sy --noconfirm python 2>/dev/null || true
    fi

    # Install pip if not available
    if ! python3 -m pip --version &>/dev/null 2>&1; then
        echo "    Installing pip..."
        pacman -Sy --noconfirm python-pip 2>/dev/null || {
            # Fallback: bootstrap pip
            curl -sS https://bootstrap.pypa.io/get-pip.py | python3 2>/dev/null || true
        }
    fi

    # openssl should be available
    if command -v openssl &>/dev/null; then
        echo "    OpenSSL is available: $(openssl version)"
    fi
else
    # Full system: use pacman
    echo "    Updating package database..."
    pacman -Sy --noconfirm 2>/dev/null || true
    pacman -S --needed --noconfirm python python-pip openssl 2>/dev/null || true
fi

# --- Install Python packages ---
echo ""
echo "  [2/4] Installing Python packages..."

# evdev is needed for input capture
# Try system package first, then pip
if ! python3 -c "import evdev" 2>/dev/null; then
    echo "    Installing python-evdev..."
    pacman -S --needed --noconfirm python-evdev 2>/dev/null || \
        python3 -m pip install evdev --break-system-packages 2>/dev/null || \
        python3 -m pip install evdev 2>/dev/null || {
            echo "    [WARNING] Could not install evdev via pip."
            echo "    Trying to build from source..."
            pacman -S --needed --noconfirm gcc linux-headers 2>/dev/null || true
            python3 -m pip install evdev --break-system-packages 2>/dev/null || true
        }
fi

# Verify
if python3 -c "import evdev" 2>/dev/null; then
    echo "    evdev: OK"
else
    echo "    [WARNING] evdev not available - will use raw input fallback"
fi

# --- Generate certificates ---
echo ""
echo "  [3/4] Generating TLS certificates..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_DIR="$SCRIPT_DIR/certs"

if [ -f "$CERT_DIR/server.crt" ]; then
    echo "    Certificates already exist in $CERT_DIR/"
    echo "    To regenerate, delete the certs/ directory and run again."
else
    chmod +x "$SCRIPT_DIR/generate_certs.sh"
    bash "$SCRIPT_DIR/generate_certs.sh" "$CERT_DIR"
fi

# --- Configure permissions ---
echo ""
echo "  [4/4] Configuring permissions..."

# Ensure input devices are accessible
if [ -d /dev/input ]; then
    DEVICE_COUNT=$(ls /dev/input/event* 2>/dev/null | wc -l)
    echo "    Found $DEVICE_COUNT input devices"

    # Check if current user can access them
    if [ -r /dev/input/event0 ]; then
        echo "    Input devices are accessible"
    else
        echo "    [NOTE] Input devices require root access"
        echo "    Run UniCent host with: sudo python3 -m host.main"
    fi
else
    echo "    [WARNING] /dev/input not found"
fi

# --- Done ---
echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║           Setup Complete!            ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
echo "  To start the host:"
echo "    cd $SCRIPT_DIR"
echo "    sudo python3 -m host.main"
echo ""
echo "  Options:"
echo "    --port PORT     Set server port (default: 27183)"
echo "    --no-tls        Disable encryption"
echo "    --no-grab       Don't grab input devices"
echo "    -v              Verbose logging"
echo ""
echo "  Copy these files to the macOS client:"
echo "    $CERT_DIR/ca.crt"
echo "    $CERT_DIR/client.crt"
echo "    $CERT_DIR/client.key"
echo ""
