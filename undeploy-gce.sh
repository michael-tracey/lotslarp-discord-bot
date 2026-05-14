#!/bin/bash
# Permanently destroys the old dedicated lotslarp-bot GCE VM and its resources.
# Run this once you are confident the bot is stable on the shared host.
set -e

SSH_KEY_PATH="${HOME}/.ssh/ansible_gce_key"
GCP_PROJECT_ID=${GCP_PROJECT_ID:-"lotslarp"}

echo "⚠️  WARNING: This will permanently destroy the old dedicated bot VM and all its GCE resources."
echo "   Artifact Registry images and Firestore data will NOT be affected."
echo ""
echo "   Only run this after confirming the bot is healthy on the new shared host (34.148.234.178)."
echo ""
read -p "Type 'destroy' to confirm: " confirm
if [[ "$confirm" != "destroy" ]]; then
    echo "Aborted."
    exit 1
fi

echo "--- Destroying old infrastructure (OpenTofu) ---"
cd terraform

tofu destroy -auto-approve \
    -var="project_id=$GCP_PROJECT_ID" \
    -var="ssh_user=ansible" \
    -var="ssh_pub_key_path=${SSH_KEY_PATH}.pub"

echo "✅ Old dedicated VM destroyed."
