#!/bin/bash
# Re-deploys the bot container on the shared host without rebuilding the image.
set -euo pipefail

GCP_PROJECT_ID=${GCP_PROJECT_ID:-"lotslarp"}
GCP_REGION=${GCP_REGION:-"us-east1"}
SERVICE_NAME="lotslarp-discord-bot"
ARTIFACT_REGISTRY_REPO="discord-bots"
FULL_IMAGE_NAME="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${ARTIFACT_REGISTRY_REPO}/${SERVICE_NAME}:latest"
HOST_IP=$(gcloud storage cat gs://mtracey-tofu-state/infra/default.tfstate | jq -r '.outputs.host_ip.value')

if [[ ! -f .env ]]; then
    echo "Error: .env file not found. Run from the repo root."
    exit 1
fi

echo "=== fix-infra.sh — restoring bot on shared host ($HOST_IP) ==="
echo "Image: $FULL_IMAGE_NAME"
echo ""

echo "[bots]
${HOST_IP} ansible_user=ansible ansible_ssh_private_key_file=${HOME}/.ssh/ansible_gce_key ansible_ssh_common_args='-o StrictHostKeyChecking=no'" > ansible/inventory.ini

ansible-playbook -i ansible/inventory.ini ansible/playbook.yml \
    --extra-vars "docker_image=$FULL_IMAGE_NAME env_file_src=$(pwd)/.env map_url=http://$HOST_IP:8080"

echo ""
echo "✅ Bot restored on $HOST_IP"
