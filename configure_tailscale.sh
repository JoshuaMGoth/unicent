#!/usr/bin/env bash
# 
# Configure UniCent client for Tailscale auto-connect
# 
# Usage: ./configure_tailscale.sh <HOST_TAILSCALE_IP>
# 
# This script configures the UniCent client to auto-connect to the host
# using the specified Tailscale IP address.
#

set -e

if [ $# -ne 1 ]; then
    echo "Usage: $0 <HOST_TAILSCALE_IP>"
    echo ""
    echo "Example:"
    echo "  $0 100.64.0.1"
    echo ""
    echo "To find your host's Tailscale IP, run on the host machine:"
    echo "  tailscale ip -4"
    exit 1
fi

HOST_IP="$1"

# Validate IP address format
if ! [[ "$HOST_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    echo "Error: Invalid IP address format: $HOST_IP"
    exit 1
fi

CONFIG_DIR="$HOME/.config/unicent"
CONFIG_FILE="$CONFIG_DIR/client.json"

# Create config directory
mkdir -p "$CONFIG_DIR"

# Create/update config file
python3 << 'PYTHON'
import sys
import json
import os

config_dir = os.path.expanduser('~/.config/unicent')
config_file = os.path.join(config_dir, 'client.json')

os.makedirs(config_dir, mode=0o700, exist_ok=True)

config = {}
if os.path.exists(config_file):
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
    except:
        pass

# Update with new host IP
config['host_ip'] = sys.argv[1]

# Write config
with open(config_file, 'w') as f:
    json.dump(config, f, indent=2)

print(f"✓ Configuration saved to {config_file}")
print(f"  Host IP: {config['host_ip']}")

PYTHON "$HOST_IP"

echo ""
echo "Configuration complete!"
echo ""
echo "The UniCent client will now auto-connect to the host at $HOST_IP"
echo ""
echo "To enable auto-start on macOS:"
echo "  launchctl load ~/Library/LaunchAgents/com.unicent.client.plist"
echo ""
echo "To view connection logs:"
echo "  tail -f /tmp/unicent-client.log"
echo ""
