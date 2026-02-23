#!/bin/bash
# Setup hosts entry on blacktower (Windows) from p1 (WSL)
# This script runs from p1 and SSHs to blacktower to add the hosts entry

set -e

BLACKTOWER_IP="192.168.178.95"
BLACKTOWER_USER="eero_22"
SCRIPT_NAME="add_p1_hosts_entry.ps1"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Setting up hosts entry on blacktower (Windows)..."
echo "Connecting to $BLACKTOWER_USER@$BLACKTOWER_IP..."

# Copy the PowerShell script to blacktower
# On Windows, we'll copy to user's home directory
# Try different path formats for Windows
REMOTE_SCRIPT_PATH="~/add_p1_hosts_entry.ps1"

echo "Copying PowerShell script to blacktower..."
scp "$SCRIPT_DIR/$SCRIPT_NAME" "$BLACKTOWER_USER@$BLACKTOWER_IP:$REMOTE_SCRIPT_PATH"

echo ""
echo "Attempting to execute script on blacktower (requires Administrator privileges)..."
echo "If this fails, you'll need to run it manually on blacktower."
echo ""

# Try to execute via PowerShell (may require Administrator)
# Note: This might fail if not running as admin, but we'll try
# Use Windows-style path for PowerShell
POWERSHELL_PATH="~/add_p1_hosts_entry.ps1"
ssh "$BLACKTOWER_USER@$BLACKTOWER_IP" "powershell.exe -ExecutionPolicy Bypass -File $POWERSHELL_PATH" || {
    echo ""
    echo "⚠ Could not execute automatically (may need Administrator privileges)"
    echo ""
    echo "To complete setup, run this on blacktower (as Administrator):"
    echo "  PowerShell -ExecutionPolicy Bypass -File ~/add_p1_hosts_entry.ps1"
    echo ""
    echo "Or navigate to your home directory and run:"
    echo "  .\add_p1_hosts_entry.ps1"
    exit 0
}

echo ""
echo "✓ Hosts entry setup complete on blacktower"
echo "You can now SSH from blacktower using: ssh eero_22@p1"

