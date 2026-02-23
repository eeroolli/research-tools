#!/bin/bash
# Add p1 hostname entry to /etc/hosts on blacktower
# This script should be run ON blacktower

set -e

P1_IP="192.168.178.129"
HOSTNAME="p1"
HOSTS_FILE="/etc/hosts"

echo "Adding $HOSTNAME -> $P1_IP to $HOSTS_FILE..."

# Check if entry already exists
if grep -q "^[[:space:]]*${P1_IP}[[:space:]]" "$HOSTS_FILE" && grep -q "[[:space:]]${HOSTNAME}[[:space:]]*$" "$HOSTS_FILE"; then
    echo "Entry already exists in $HOSTS_FILE"
    grep "$P1_IP.*$HOSTNAME" "$HOSTS_FILE" || grep "$P1_IP" "$HOSTS_FILE"
    exit 0
fi

# Remove any existing entry for p1 (in case IP changed)
sudo sed -i "/[[:space:]]${HOSTNAME}[[:space:]]*$/d" "$HOSTS_FILE" 2>/dev/null || true

# Add new entry
echo "$P1_IP    $HOSTNAME" | sudo tee -a "$HOSTS_FILE" > /dev/null

echo "✓ Successfully added $HOSTNAME -> $P1_IP to $HOSTS_FILE"
echo ""
echo "You can now use: ssh eero_22@p1"

