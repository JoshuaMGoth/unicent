# ──────────────────────────────────────────────────────────
# UniCent Host Installer — Windows (PowerShell)
# ──────────────────────────────────────────────────────────
# Run as Administrator:
#   Set-ExecutionPolicy Bypass -Scope Process -Force
#   .\install-host.ps1
# ──────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
$InstallDir = "$env:ProgramFiles\UniCent"
$RepoURL = "https://github.com/JoshuaMGoth/unicent.git"

Write-Host ""
Write-Host "  ╔══════════════════════════════════════╗"
Write-Host "  ║   UniCent Host — Windows Installer   ║"
Write-Host "  ╚══════════════════════════════════════╝"
Write-Host ""

# Check admin
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "  ✗ Please run as Administrator"
    exit 1
}

# Step 1: Check Python
Write-Host "  [1/5] Checking prerequisites..."
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-Command python3 -ErrorAction SilentlyContinue
}
if (-not $python) {
    Write-Host "  ✗ Python not found. Download from https://www.python.org/downloads/"
    Write-Host "  Make sure to check 'Add Python to PATH' during installation."
    exit 1
}
$pythonCmd = $python.Source
Write-Host "  ✓ Python found: $pythonCmd"

# Check git
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    Write-Host "  ✗ Git not found. Download from https://git-scm.com/download/win"
    exit 1
}
Write-Host "  ✓ Git found"

# Step 2: Clone
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

# Step 3: Python deps
Write-Host "  [3/5] Installing Python dependencies..."
& $pythonCmd -m pip install pystray Pillow pywin32
Write-Host "  ✓ Python packages installed"

# Step 4: Auto-start (Registry)
Write-Host "  [4/5] Setting up auto-start..."
$regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$regValue = "cmd /c `"cd /d $InstallDir && `"$pythonCmd`" -m host.main --no-tls`""
Set-ItemProperty -Path $regPath -Name "UniCentHost" -Value $regValue
Write-Host "  ✓ Auto-start registered in Windows Registry"

# Step 5: Batch launcher
Write-Host "  [5/5] Creating launch script..."
$batchContent = @"
@echo off
cd /d "$InstallDir"
python -m host.main %*
"@
$batchPath = "$InstallDir\unicent-host.bat"
Set-Content -Path $batchPath -Value $batchContent

# Add to PATH if not already
$currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($currentPath -notlike "*$InstallDir*") {
    [Environment]::SetEnvironmentVariable("PATH", "$currentPath;$InstallDir", "User")
    Write-Host "  ✓ Added $InstallDir to PATH"
}

Write-Host ""
Write-Host "  ══════════════════════════════════════"
Write-Host "  ✓ UniCent Host installed!"
Write-Host "  ══════════════════════════════════════"
Write-Host ""
Write-Host "  Run:     unicent-host.bat --no-tls -v"
Write-Host "  Or:      python -m host.main --no-tls -v"
Write-Host ""
