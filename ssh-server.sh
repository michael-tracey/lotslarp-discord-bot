#!/bin/bash

# This script SSHs into the Discord bot server (GCE VM).
# It attempts to find the IP via OpenTofu first, then gcloud.

set -e

# Configuration
SSH_KEY_PATH="${HOME}/.ssh/ansible_gce_key"
SSH_USER="ansible"
INSTANCE_NAME="lotslarp-discord-bot-vm"
ZONE="us-east1-b" # Default zone, can be overridden

echo "Attempting to find server IP..."

# 1. Try OpenTofu
if [ -d "terraform/.terraform" ] || [ -d "terraform/.tofu" ]; then
    echo "Checking OpenTofu state..."
    VM_IP=$(cd terraform && tofu output -raw public_ip 2>/dev/null || echo "")
fi

# 2. Fallback to gcloud if VM_IP is empty
if [ -z "$VM_IP" ]; then
    echo "OpenTofu state not found or empty. Checking gcloud..."
    VM_IP=$(gcloud compute instances describe "$INSTANCE_NAME" 
        --zone "$ZONE" 
        --format='get(networkInterfaces[0].accessConfigs[0].natIP)' 2>/dev/null || echo "")
fi

if [ -z "$VM_IP" ]; then
    echo "Error: Could not determine VM IP. Make sure the instance is running and you have gcloud configured."
    exit 1
fi

echo "Connecting to $SSH_USER@$VM_IP..."

# Connect via SSH
ssh -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no "$SSH_USER@$VM_IP"
