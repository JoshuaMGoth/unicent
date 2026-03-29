# ──────────────────────────────────────────────────────────
# UniCent Client Installer — Windows (PowerShell)
# ──────────────────────────────────────────────────────────
# Run as Administrator:
#   Set-ExecutionPolicy Bypass -Scope Process -Force
#   .\install-client.ps1
# ──────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
$InstallDir = "$env:ProgramFiles\UniCent"
$RepoURL   = "https://github.com/JoshuaMGoth/unicent.git"
$TaskName  = "UniCent Client"

Write-Host ""
Write-Host "  ╔══════════════════════════════════════╗"
Write-Host "  ║  UniCent Client — Windows Installer  ║"
Write-Host "  ╚══════════════════════════════════════╝"
Write-Host ""

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "  ✗ Please run as Administrator (right-click → Run as administrator)."
    exit 1
}

# ── 1. Prerequisites ─────────────────────────────────
Write-Host "  [1/5] Checking prerequisites..."

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) {
    Write-Host "  ⚙ Python not found — installing via winget..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        winget install Python.Python.3.11 --silent --accept-source-agreements --accept-package-agreements
        $env:PATH = [System.Environment]::GetEnvironmentVariable('PATH','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('PATH','User')
        $python = Get-Command python -ErrorAction SilentlyContinue
    }
    if (-not $python) {
        Write-Host "  ✗ Python install failed. Download from https://www.python.org/downloads/"
        Write-Host "     Check 'Add Python to PATH' during installation, then re-run."
        exit 1
    }
}
$pythonCmd = $python.Source
Write-Host "  ✓ Python: $pythonCmd"

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    Write-Host "  ⚙ Git not found — installing via winget..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        winget install Git.Git --silent --accept-source-agreements --accept-package-agreements
        $env:PATH = [System.Environment]::GetEnvironmentVariable('PATH','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('PATH','User')
        $git = Get-Command git -ErrorAction SilentlyContinue
    }
    if (-not $git) {
        Write-Host "  ✗ Git install failed. Download from https://git-scm.com/download/win"
        exit 1
    }
}
Write-Host "  ✓ Git found"

# ── 2. Clone / update ────────────────────────────────
Write-Host "  [2/5] Cloning / updating UniCent..."
if (Test-Path "$InstallDir\.git") {
    Push-Location $InstallDir
    & git stash 2>$null
    & git pull --ff-only
    Pop-Location
} else {
    if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
    & git clone $RepoURL $InstallDir
}
Write-Host "  ✓ Source code ready at $InstallDir"

# ── 3. Virtual environment + packages ─────────────────
Write-Host "  [3/5] Installing Python dependencies..."
$VenvDir = "$InstallDir\.venv"
if (-not (Test-Path $VenvDir)) {
    & $pythonCmd -m venv $VenvDir
}
$VenvPython  = "$VenvDir\Scripts\python.exe"
$VenvPythonW = "$VenvDir\Scripts\pythonw.exe"
$VenvPip     = "$VenvDir\Scripts\pip.exe"
& $VenvPip install --upgrade pip --quiet
& $VenvPip install --quiet pystray Pillow pywin32
Write-Host "  ✓ Python packages installed in venv"

# ── 4. Launch wrapper + Task Scheduler ────────────────
Write-Host "  [4/5] Creating launchers and auto-start..."
# VBScript — runs pythonw silently (no console window)
$vbsContent = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "$InstallDir"
WshShell.Run """$VenvPythonW"" -m client.main --no-tls", 0, False
"@
$vbsPath = "$InstallDir\unicent-client.vbs"
Set-Content -Path $vbsPath -Value $vbsContent -Encoding UTF8

$batchContent = @"
@echo off
cd /d "$InstallDir"
"$VenvPython" -m client.main %*
"@
Set-Content -Path "$InstallDir\unicent-client.bat" -Value $batchContent -Encoding ASCII

# Task Scheduler
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
$action   = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "`"$vbsPath`"" `
    -WorkingDirectory $InstallDir
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoesOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null
Write-Host "  ✓ Task Scheduler entry created (runs at login)"

# Start Menu shortcut
$StartMenuPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\UniCent Client.lnk"
$wsh = New-Object -ComObject WScript.Shell
$sc  = $wsh.CreateShortcut($StartMenuPath)
$sc.TargetPath       = "wscript.exe"
$sc.Arguments        = "`"$vbsPath`""
$sc.WorkingDirectory = $InstallDir
$sc.Description      = "UniCent Client - mouse/keyboard sharing"
$sc.Save()
Write-Host "  ✓ Start Menu shortcut created"

# ── 5. Start it now ───────────────────────────────────
Write-Host "  [5/5] Starting UniCent Client..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2
Write-Host "  ✓ UniCent Client is running"

Write-Host ""
Write-Host "  ══════════════════════════════════════"
Write-Host "  ✓ UniCent Client installed!"
Write-Host "  ══════════════════════════════════════"
Write-Host ""
Write-Host "  Starts automatically at login (Task Scheduler)."
Write-Host "  Terminal: $InstallDir\unicent-client.bat --host <HOST_IP> --no-tls -v"
Write-Host "  Stop:     Stop-ScheduledTask -TaskName 'UniCent Client'"
Write-Host ""
