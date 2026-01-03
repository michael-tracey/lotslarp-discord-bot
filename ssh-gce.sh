#!/bin/bash

# This script SSHs into the Google Compute Engine VM.

set -e

# Configuration
SSH_KEY_PATH="${HOME}/.ssh/ansible_gce_key"
SSH_USER="ansible"

# Navigate to terraform directory to get the output
cd terraform

# Get Public IP from OpenTofu state
if [ ! -d ".terraform" ] && [ ! -d ".tofu" ]; then
    echo "Error: OpenTofu/Terraform state not found. Have you run deploy-gce.sh?"
    exit 1
fi

echo "Fetching VM IP..."
VM_IP=$(tofu output -raw public_ip)

if [ -z "$VM_IP" ]; then
    echo "Error: Could not determine VM IP."
    exit 1
fi

echo "Connecting to $SSH_USER@$VM_IP..."

# Connect via SSH
ssh -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no "$SSH_USER@$VM_IP"
