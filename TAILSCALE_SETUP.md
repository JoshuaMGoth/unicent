# Mouse-Share with Tailscale Setup Guide

## Overview

This guide helps you set up mouse-share to work reliably after reboots using your Tailscale network. Mouse-share will auto-connect using your Tailscale IP addresses.

## Quick Setup (Mac Client)

### 1. Get Your Host's Tailscale IP

On your host machine (the one with the monitor):

```bash
tailscale ip -4
```

This will output something like: `100.64.0.1`

### 2. Configure the Mac Client

On your Mac, run:

```bash
cd /path/to/mouse-share
./configure_tailscale.sh 100.64.0.1
```

Replace `100.64.0.1` with your actual host Tailscale IP.

### 3. Test Connection

```bash
python3 -m client.main --no-tls -v
```

You should see:
```
● Connected to 100.64.0.1:27183
```

Once connected successfully, the IP is saved to `~/.config/unicent/client.json`

### 4. Enable Auto-Start

To automatically connect on Mac reboot:

```bash
launchctl load ~/Library/LaunchAgents/com.unicent.client.plist
```

To check if it's running:

```bash
launchctl list | grep unicent
```

To disable auto-start:

```bash
launchctl unload ~/Library/LaunchAgents/com.unicent.client.plist
```

## How It Works

1. **Configuration Storage**: Your host's Tailscale IP is stored in `~/.config/unicent/client.json`
2. **Auto-Start**: The LaunchAgent automatically launches the client on login
3. **Auto-Reconnect**: If the connection drops, it automatically reconnects
4. **Smart Startup**: The wrapper script reads your config and connects to the stored IP

## Troubleshooting

### Check if Client is Running

```bash
ps aux | grep client.main
```

### View Connection Logs

```bash
tail -f /tmp/unicent-client.log
tail -f /tmp/unicent-client.err
```

### View Current Configuration

```bash
cat ~/.config/unicent/client.json
```

### Update Host IP

If your host's Tailscale IP changes, re-run:

```bash
./configure_tailscale.sh <NEW_IP>
```

### Manual Connection

If auto-connect doesn't work:

```bash
python3 -m client.main --host 100.64.0.1 --no-tls -v
```

## Why Tailscale?

- **Reliable**: Works across networks and firewalls
- **Automatic**: Peer discovery and connection management
- **Secure**: End-to-end encryption built-in (--no-tls still works because Tailscale encrypts)
- **Low-latency**: Direct peer connections when possible
- **No Port Forwarding**: No need to expose your machine to the internet

## Notes

- The `--no-tls` flag is recommended when using Tailscale (Tailscale provides encryption)
- Each machine must have Tailscale installed and running
- Tailscale devices must be on the same tailnet to connect
- Connection persists across network changes and reboots
