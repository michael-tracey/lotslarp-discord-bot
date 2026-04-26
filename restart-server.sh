#!/bin/bash

# This script restarts the Google Compute Engine (GCE) instance.
# It performs a hard reset, which is useful if the server is unresponsive.

set -e

# Configuration
INSTANCE_NAME="lotslarp-discord-bot-vm"
ZONE="us-east1-b"

echo "--- GCE Server Restart ---"
echo "Instance: $INSTANCE_NAME"
echo "Zone: $ZONE"
echo "--------------------------"

# Confirm with user
read -p "Are you sure you want to restart the server? (y/n): " confirm
if [[ $confirm != [yY] && $confirm != [yY][eE][sS] ]]; then
    echo "Restart cancelled."
    exit 0
fi

echo "🔄 Requesting reset for $INSTANCE_NAME..."

if gcloud compute instances reset "$INSTANCE_NAME" --zone "$ZONE"; then
    echo "✅ Reset command sent successfully."
    echo "The server is now rebooting. It may take 1-2 minutes to become responsive again."
    echo "You can check the status using: ./status-gce.sh"
else
    echo "❌ Failed to restart the instance. Check your gcloud configuration and permissions."
    exit 1
fi
