# ──────────────────────────────────────────────────────────
# UniCent Client Installer — Windows (PowerShell)
# ──────────────────────────────────────────────────────────
# Run as Administrator:
#   Set-ExecutionPolicy Bypass -Scope Process -Force
#   .\install-client.ps1
# ──────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
$InstallDir = "$env:ProgramFiles\UniCent"
$RepoURL = "https://github.com/JoshuaMGoth/unicent.git"

Write-Host ""
Write-Host "  ╔══════════════════════════════════════╗"
Write-Host "  ║  UniCent Client — Windows Installer  ║"
Write-Host "  ╚══════════════════════════════════════╝"
Write-Host ""

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "  ✗ Please run as Administrator"
    exit 1
}

Write-Host "  [1/5] Checking prerequisites..."
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) {
    Write-Host "  ✗ Python not found. Download from https://www.python.org/downloads/"
    exit 1
}
$pythonCmd = $python.Source
Write-Host "  ✓ Python found: $pythonCmd"

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    Write-Host "  ✗ Git not found. Download from https://git-scm.com/download/win"
    exit 1
}
Write-Host "  ✓ Git found"

Write-Host "  [2/5] Cloning / updating UniCent..."
if (Test-Path "$InstallDir\.git") {
    Push-Location $InstallDir
    & git pull --ff-only
    Pop-Location
} else {
    if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
    & git clone $RepoURL $InstallDir
}
Write-Host "  ✓ Source code ready at $InstallDir"

Write-Host "  [3/5] Installing Python dependencies..."
& $pythonCmd -m pip install pystray Pillow pywin32
Write-Host "  ✓ Python packages installed"

Write-Host "  [4/5] Setting up auto-start..."
$regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$regValue = "cmd /c `"cd /d $InstallDir && `"$pythonCmd`" -m client.main --no-tls`""
Set-ItemProperty -Path $regPath -Name "UniCentClient" -Value $regValue
Write-Host "  ✓ Auto-start registered in Windows Registry"

Write-Host "  [5/5] Creating launch script..."
$batchContent = @"
@echo off
cd /d "$InstallDir"
python -m client.main %*
"@
$batchPath = "$InstallDir\unicent-client.bat"
Set-Content -Path $batchPath -Value $batchContent

$currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($currentPath -notlike "*$InstallDir*") {
    [Environment]::SetEnvironmentVariable("PATH", "$currentPath;$InstallDir", "User")
    Write-Host "  ✓ Added $InstallDir to PATH"
}

Write-Host ""
Write-Host "  ══════════════════════════════════════"
Write-Host "  ✓ UniCent Client installed!"
Write-Host "  ══════════════════════════════════════"
Write-Host ""
Write-Host "  Run:     unicent-client.bat --host <HOST_IP> --no-tls -v"
Write-Host ""
