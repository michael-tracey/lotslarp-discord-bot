#!/bin/bash

# This script destroys the GCE infrastructure provisioned by OpenTofu.

set -e

# Configuration
SSH_KEY_PATH="${HOME}/.ssh/ansible_gce_key"

echo "⚠️  WARNING: This will DESTROY the Google Compute Engine VM and all associated resources."
echo "   It will NOT delete the Artifact Registry images or the Firestore database."
echo ""
read -p "Are you sure you want to proceed? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    echo "Aborted."
    exit 1
fi

echo "--- Destroying Infrastructure (OpenTofu) ---"
cd terraform

if [ ! -d ".terraform" ] && [ ! -d ".tofu" ]; then
    echo "Error: OpenTofu state not found. Nothing to destroy or wrong directory?"
    exit 1
fi

# We need the variables to destroy properly
# (Though technically only the state file matters, passing variables suppresses warnings)
GCP_PROJECT_ID=${GCP_PROJECT_ID:-"lotslarp"}
SSH_USER="ansible"

tofu destroy -auto-approve \
    -var="project_id=$GCP_PROJECT_ID" \
    -var="ssh_user=$SSH_USER" \
    -var="ssh_pub_key_path=${SSH_KEY_PATH}.pub"

echo "✅ Infrastructure destroyed."

# Optional: Cleanup SSH key
if [ -f "$SSH_KEY_PATH" ]; then
    echo "Removing Ansible SSH key..."
    rm "$SSH_KEY_PATH" "$SSH_KEY_PATH.pub"
fi

echo "Cleanup complete."
