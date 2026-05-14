#!/bin/bash
set -e
SSH_KEY_PATH="${HOME}/.ssh/ansible_gce_key"
HOST_IP=$(gcloud storage cat gs://mtracey-tofu-state/infra/default.tfstate | jq -r '.outputs.host_ip.value')

read -p "Restart the discord-bot container on $HOST_IP? (y/n): " confirm
if [[ $confirm != [yY] ]]; then
    echo "Cancelled."
    exit 0
fi

echo "Restarting discord-bot container..."
ssh -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no "ansible@$HOST_IP" "docker restart discord-bot"
echo "✅ Container restarted."
