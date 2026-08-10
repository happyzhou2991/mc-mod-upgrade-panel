# Build the MC Mod Upgrade Panel into a single exe (for distribution to others).
# Usage: powershell -ExecutionPolicy Bypass -File build_exe.ps1
# NOTE: keep messages ASCII-only (PowerShell 5.1 reads .ps1 as ANSI).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "== checking PyInstaller =="
python -m PyInstaller --version 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  installing PyInstaller ..."
    python -m pip install pyinstaller
}

Write-Host "== building (1-2 min) =="
python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name MCModUpgradePanel `
    --collect-submodules mcupgrade `
    panel.py

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "OK. exe at: $PSScriptRoot\dist\MCModUpgradePanel.exe" -ForegroundColor Green
    Write-Host "Ship the exe alone; config/cache will be created next to it." -ForegroundColor Green
} else {
    Write-Host "BUILD FAILED - send me the error above." -ForegroundColor Red
    exit 1
}
