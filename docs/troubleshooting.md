# UniCent Troubleshooting Guide

This page covers the most common issues encountered when installing or running UniCent.

---

## Table of Contents

1. [Client not connecting / stuck in "Discovering..."](#1-client-not-connecting--stuck-in-discovering)
2. [UniCent not starting after you quit it](#2-unicent-not-starting-after-you-quit-it)
3. [Wrong Python / missing packages error](#3-wrong-python--missing-packages-error)
4. [Connection refused on port 27183](#4-connection-refused-on-port-27183)
5. [Input not injecting on macOS (Accessibility error)](#5-input-not-injecting-on-macos-accessibility-error)
6. [Permission denied writing LaunchAgents (macOS)](#6-permission-denied-writing-launchagents-macos)
7. ["UniCent is already running" — won't start](#7-unicent-is-already-running--wont-start)
8. [Windows: task does not appear in Task Scheduler](#8-windows-task-does-not-appear-in-task-scheduler)
9. [Windows: connection refused / firewall blocking](#9-windows-connection-refused--firewall-blocking)
10. [Updating an existing installation](#10-updating-an-existing-installation)

---

## 1. Client not connecting / stuck in "Discovering..."

**Symptom:** The client tray icon shows "Disconnected" or keeps scanning forever without finding the host.

**Cause:** By default the client uses UDP broadcast (port 27182) to auto-discover the host. UDP broadcast does **not** cross Tailscale subnets or any routed network — it only works on a flat LAN. If the client and host are on different machines connected via Tailscale, discovery will never succeed.

**Fix:**

Set the host IP directly:

1. Click the tray icon → **Set Host IP...**
2. Enter the Tailscale IP of the machine running the host (e.g. `100.94.218.44`).

Or persist it in the config file so it survives restarts:

```bash
mkdir -p ~/.config/unicent
echo '{"host_ip": "100.94.218.44"}' > ~/.config/unicent/client.json
```

Replace `100.94.218.44` with the Tailscale IP shown on the host machine (`tailscale ip -4`).

**macOS LaunchAgent:** If the config file alone is not enough because the process starts before you log in, also ensure the `--host` flag is passed in your LaunchAgent plist:

```xml
<key>ProgramArguments</key>
<array>
    <string>/usr/local/share/unicent/.venv/bin/python3</string>
    <string>-m</string>
    <string>client.main</string>
    <string>--host</string>
    <string>100.94.218.44</string>
</array>
```

Re-run the installer (`installers/macos/install-client.sh`) to regenerate the plist with the current host IP.

---

## 2. UniCent not starting after you quit it

**Symptom:** You quit UniCent from the tray and it never comes back. Nothing appears in the menu bar / system tray.

**Cause (macOS):** There was a bug in early versions of `com.unicent.client.plist` where `KeepAlive` was set to `{SuccessfulExit: false}`. This tells `launchd` not to restart the app after it exits cleanly — which is exactly what happens when you choose Quit. This bug was fixed in commit `8935249`.

**Fix:** Re-run the macOS client installer:

```bash
cd /usr/local/share/unicent
git pull
bash installers/macos/install-client.sh
```

**Cause (Windows):** The Task Scheduler trigger may be set to run only once. The installer uses a `logon` trigger, so re-logging in restores the process. If that does not happen, open Task Scheduler, find **UniCent Client**, and verify the trigger is set to **At log on** with **Repeat** enabled.

---

## 3. Wrong Python / missing packages error

**Symptom:** UniCent crashes immediately with `ModuleNotFoundError: No module named 'rumps'`, `pystray`, `pynput`, or similar.

**Cause:** The LaunchAgent plist or Task Scheduler action was pointing to the system Python (`/usr/bin/python3` on macOS or `python` in `PATH` on Windows) instead of the UniCent virtual environment, which has all required packages installed.

**Fix:** Re-run the installer for your platform. It creates a `.venv` inside `/usr/local/share/unicent/` and writes the correct path into the autostart entry.

```bash
# macOS client
bash /usr/local/share/unicent/installers/macos/install-client.sh

# macOS host
bash /usr/local/share/unicent/installers/macos/install-host.sh
```

The correct Python path is:
```
/usr/local/share/unicent/.venv/bin/python3       # macOS / Linux
C:\UniCent\.venv\Scripts\python.exe               # Windows
```

---

## 4. Connection refused on port 27183

**Symptom:** `nc -zv <host-ip> 27183` returns "Connection refused". The client log shows `ConnectionRefusedError`.

**Cause:** The UniCent host process is not running on the target machine.

**Diagnosis:**

```bash
# macOS
launchctl list | grep unicent

# Linux
systemctl --user status unicent-host
# or check if the process is running:
pgrep -a python | grep unicent

# Windows (PowerShell)
Get-ScheduledTask -TaskName "UniCent Host" | Select-Object -ExpandProperty State
```

**Fix:**

- **macOS:** The LaunchAgent may not be installed. Run `bash installers/macos/install-host.sh`.
- **Linux:** The host may have crashed. Check `~/.local/share/unicent/host.log` for errors, then start it with `~/.local/bin/unicent-host` or via the desktop launcher.
- **Windows:** Open Task Scheduler → find **UniCent Host** → right-click → **Run**.

---

## 5. Input not injecting on macOS (Accessibility error)

**Symptom:** The host log (macOS) shows:

```
Failed to create CGEventTap — check Accessibility permissions
```

Mouse movement and keystrokes received from the client are not forwarded.

**Cause:** macOS requires explicit Accessibility permission before any process can simulate input via `CGEventTap`. This is a security feature and cannot be bypassed.

**Fix:**

1. Open **System Settings → Privacy & Security → Accessibility**.
2. Click the **+** button and add the UniCent host application (or your terminal / Python binary if running without the `.app` bundle).
3. Make sure the toggle next to UniCent is **on**.
4. Restart the host process:

```bash
launchctl bootout "gui/$(id -u)/com.unicent.host"
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.unicent.host.plist
```

The installer (`install-host.sh`) automatically opens the Accessibility settings pane at the end of installation to make this step easy to find.

---

## 6. Permission denied writing LaunchAgents (macOS)

**Symptom:** The installer fails with:

```
cp: /Users/yourname/Library/LaunchAgents/com.unicent.client.plist: Permission denied
```

Or `launchctl bootstrap` fails silently and the agent never loads.

**Cause:** The `~/Library/LaunchAgents/` directory is owned by `root` instead of your user account. This can happen after certain system upgrades or if the directory was created by a `sudo` command.

**Fix:**

```bash
sudo chown "$USER" ~/Library/LaunchAgents
```

Then re-run the installer.

---

## 7. "UniCent is already running" — won't start

**Symptom:** You try to start UniCent manually (or the LaunchAgent fires) but the log immediately shows:

```
UniCent Client is already running — exiting.
```

No tray icon appears.

**Cause:** UniCent uses a file lock (`/tmp/unicent-client.lock`) to prevent multiple instances. If a previous process crashed or was killed without releasing the lock, any new start attempt will exit immediately thinking another instance is running.

**Fix:** Find and kill the stale process, then the lock clears automatically:

```bash
# Find the old process
pgrep -a python | grep "client.main"
# or on macOS
ps aux | grep unicent

# Kill it (replace <PID> with the actual PID)
kill <PID>
```

If no process is holding the lock but the file still exists (rare), delete it:

```bash
rm -f /tmp/unicent-client.lock
```

UniCent will create a fresh lock on its next start.

---

## 8. Windows: task does not appear in Task Scheduler

**Symptom:** After running `install-client.ps1` or `install-host.ps1`, the task is not visible in Task Scheduler, or it appears but never runs.

**Cause:** The installer must be run as Administrator for Task Scheduler modifications to take effect.

**Fix:**

1. Right-click PowerShell → **Run as Administrator**.
2. Navigate to the UniCent directory and re-run the installer:

```powershell
cd C:\UniCent
.\installers\windows\install-client.ps1
```

To manually trigger the task afterwards:

```powershell
Start-ScheduledTask -TaskName "UniCent Client"
```

---

## 9. Windows: connection refused / firewall blocking

**Symptom:** The host is running on Windows but clients cannot connect. `Test-NetConnection -ComputerName <ip> -Port 27183` fails from another machine.

**Cause:** Windows Defender Firewall is blocking inbound TCP 27183.

The installer creates this rule automatically, but if it was skipped or removed:

```powershell
# Run as Administrator
New-NetFirewallRule -DisplayName "UniCent Host" `
    -Direction Inbound -Protocol TCP -LocalPort 27183 `
    -Action Allow -Profile Any
```

Also verify Tailscale is connected on the host (`tailscale status`) and that the client is using the correct Tailscale IP, not the LAN IP.

---

## 10. Updating an existing installation

**Why a `git pull` alone is not enough:**

The LaunchAgent plist (macOS) and the Task Scheduler entry (Windows) are written to your system **at install time**. If a bug existed in those files at install time, a `git pull` updates the source template but does not update what is already registered with `launchd` / Task Scheduler.

**To fully update an existing installation, re-run the installer:**

```bash
# macOS client
cd /usr/local/share/unicent && git pull
bash installers/macos/install-client.sh

# macOS host
cd /usr/local/share/unicent && git pull
bash installers/macos/install-host.sh
```

```powershell
# Windows (run as Administrator)
cd C:\UniCent
git pull
.\installers\windows\install-client.ps1
.\installers\windows\install-host.ps1
```

```bash
# Linux
cd /usr/local/share/unicent && git pull
bash install_linux_applications.sh
```

**One-liner for macOS client (recovery):**

If you cannot or do not want to re-run the full installer, this one-liner re-registers the fixed plist:

```bash
launchctl bootout "gui/$(id -u)/com.unicent.client" 2>/dev/null; \
  cd /usr/local/share/unicent && git pull && \
  cp autostart/com.unicent.client.plist ~/Library/LaunchAgents/ && \
  launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.unicent.client.plist
```

---

## Still stuck?

- Check the log files:
  - **macOS / Linux client:** `~/.local/share/unicent/client.log`
  - **macOS / Linux host:** `~/.local/share/unicent/host.log`
  - **Windows:** `C:\UniCent\logs\`
- Open a bug report via **Tray → Tools → Report a Bug...** so the logs are attached automatically.
- Or file an issue on [GitHub](https://github.com/JoshuaMGoth/unicent/issues).
