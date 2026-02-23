# Setup SSH port forwarding from Windows to WSL
# This script should be run ON Windows (p1's host) as Administrator
# It forwards Windows port 22 to WSL SSH port 22

Write-Host "Setting up SSH port forwarding from Windows to WSL..." -ForegroundColor Cyan

# Check if running as Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator" -ForegroundColor Red
    Write-Host "Right-click PowerShell and select 'Run as Administrator'" -ForegroundColor Yellow
    exit 1
}

# Get WSL IP address
Write-Host "Getting WSL IP address..." -ForegroundColor Cyan
$wslIP = (wsl hostname -I).Trim()
if (-not $wslIP) {
    Write-Host "ERROR: Could not get WSL IP address. Is WSL running?" -ForegroundColor Red
    exit 1
}

Write-Host "WSL IP address: $wslIP" -ForegroundColor Green

$listenPort = 22
$connectPort = 22

# Remove existing rule if it exists
Write-Host "Removing existing port forwarding rule (if any)..." -ForegroundColor Cyan
netsh interface portproxy delete v4tov4 listenport=$listenPort listenaddress=0.0.0.0 2>$null

# Add new port forwarding rule
Write-Host "Adding port forwarding rule..." -ForegroundColor Cyan
netsh interface portproxy add v4tov4 listenport=$listenPort listenaddress=0.0.0.0 connectport=$connectPort connectaddress=$wslIP

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to add port forwarding rule" -ForegroundColor Red
    exit 1
}

# Configure Windows Firewall
Write-Host "Configuring Windows Firewall..." -ForegroundColor Cyan
netsh advfirewall firewall delete rule name="WSL SSH" 2>$null
netsh advfirewall firewall add rule name="WSL SSH" dir=in action=allow protocol=TCP localport=$listenPort

if ($LASTEXITCODE -ne 0) {
    Write-Host "WARNING: Firewall rule may not have been added successfully" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "✓ Port forwarding configured successfully!" -ForegroundColor Green
Write-Host "  Windows port $listenPort -> WSL $wslIP:$connectPort" -ForegroundColor Cyan
Write-Host ""
Write-Host "You can now SSH from blacktower using: ssh eero_22@p1" -ForegroundColor Cyan
Write-Host ""
Write-Host "NOTE: If WSL IP changes after restart, run this script again." -ForegroundColor Yellow

