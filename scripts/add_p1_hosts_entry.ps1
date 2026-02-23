# Add p1 hostname entry to Windows hosts file on blacktower
# This script should be run ON blacktower (Windows) as Administrator

$P1_IP = "192.168.178.129"
$HOSTNAME = "p1"
$HOSTS_FILE = "$env:SystemRoot\System32\drivers\etc\hosts"

Write-Host "Adding $HOSTNAME -> $P1_IP to $HOSTS_FILE..."

# Check if running as Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator" -ForegroundColor Red
    Write-Host "Right-click PowerShell and select 'Run as Administrator'" -ForegroundColor Yellow
    exit 1
}

# Read current hosts file
$hostsContent = Get-Content $HOSTS_FILE -ErrorAction Stop

# Check if entry already exists
$entryExists = $hostsContent | Select-String -Pattern "^\s*$P1_IP\s+.*\s+$HOSTNAME\s*$" -Quiet
if ($entryExists) {
    Write-Host "Entry already exists in $HOSTS_FILE" -ForegroundColor Green
    $hostsContent | Select-String -Pattern "$P1_IP.*$HOSTNAME|$HOSTNAME.*$P1_IP"
    exit 0
}

# Remove any existing entry for p1 (in case IP changed)
$hostsContent = $hostsContent | Where-Object { $_ -notmatch "\s+$HOSTNAME\s*$" }

# Add new entry
$newEntry = "$P1_IP    $HOSTNAME"
$hostsContent += $newEntry

# Write back to hosts file
$hostsContent | Set-Content $HOSTS_FILE -Encoding ASCII

Write-Host "✓ Successfully added $HOSTNAME -> $P1_IP to $HOSTS_FILE" -ForegroundColor Green
Write-Host ""
Write-Host "You can now use: ssh eero_22@p1" -ForegroundColor Cyan

