#!/bin/bash

# This script fetches logs from the Docker container on the GCE VM.

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

echo "Connecting to $VM_IP to fetch logs..."
echo "--- Press Ctrl+C to stop following logs ---"

# Connect via SSH and run docker logs
# We use -t to allocate a pseudo-terminal so that Ctrl+C propagates correctly if we use -f
ssh -t -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no "$SSH_USER@$VM_IP" "sudo docker logs discord-bot --tail 100 -f"
