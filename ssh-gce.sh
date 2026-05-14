#!/bin/bash
set -e
SSH_KEY_PATH="${HOME}/.ssh/ansible_gce_key"
HOST_IP=$(gcloud storage cat gs://mtracey-tofu-state/infra/default.tfstate | jq -r '.outputs.host_ip.value')
echo "Connecting to ansible@$HOST_IP..."
ssh -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no "ansible@$HOST_IP"
