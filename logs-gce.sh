#!/bin/bash
set -e
SSH_KEY_PATH="${HOME}/.ssh/ansible_gce_key"
HOST_IP=$(gcloud storage cat gs://mtracey-tofu-state/infra/default.tfstate | jq -r '.outputs.host_ip.value')
echo "Fetching logs from $HOST_IP — Ctrl+C to stop"
ssh -t -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no "ansible@$HOST_IP" "docker logs discord-bot --tail 100 -f"
