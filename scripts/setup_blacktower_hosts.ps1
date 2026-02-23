# Setup hosts entry on blacktower from p1 (WSL)
# This script runs from p1 (WSL) and copies/executes the PowerShell script on blacktower

$BLACKTOWER_IP = "192.168.178.95"
$BLACKTOWER_USER = "eero_22"
$SCRIPT_NAME = "add_p1_hosts_entry.ps1"

Write-Host "Setting up hosts entry on blacktower (Windows)..." -ForegroundColor Cyan
Write-Host "Connecting to $BLACKTOWER_USER@$BLACKTOWER_IP..." -ForegroundColor Cyan
Write-Host ""
Write-Host "NOTE: You'll need to run the script on blacktower as Administrator" -ForegroundColor Yellow
Write-Host ""

# Get script directory (convert WSL path to Windows path if needed)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $scriptDir $SCRIPT_NAME

# Copy script to blacktower
Write-Host "Copying script to blacktower..." -ForegroundColor Cyan
scp "$scriptPath" "${BLACKTOWER_USER}@${BLACKTOWER_IP}:C:\Users\$BLACKTOWER_USER\add_p1_hosts_entry.ps1"

Write-Host ""
Write-Host "Script copied to blacktower." -ForegroundColor Green
Write-Host ""
Write-Host "To complete setup, run this on blacktower (as Administrator):" -ForegroundColor Yellow
Write-Host "  PowerShell -ExecutionPolicy Bypass -File C:\Users\$BLACKTOWER_USER\add_p1_hosts_entry.ps1" -ForegroundColor White
Write-Host ""
Write-Host "Or manually run: .\add_p1_hosts_entry.ps1 in PowerShell (as Administrator)" -ForegroundColor White

