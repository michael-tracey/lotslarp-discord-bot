#!/bin/bash
set -e

GCP_PROJECT_ID=${GCP_PROJECT_ID:-"lotslarp"}
GCP_REGION=${GCP_REGION:-"us-east1"}
SERVICE_NAME="lotslarp-discord-bot"
ARTIFACT_REGISTRY_REPO="discord-bots"
IMAGE_TAG="latest"
SSH_KEY_PATH="${HOME}/.ssh/ansible_gce_key"
SSH_USER="ansible"
HOST_IP=$(gcloud storage cat gs://mtracey-tofu-state/infra/default.tfstate | jq -r '.outputs.host_ip.value')

if [ ! -f .env ]; then
    echo "Error: .env file not found."
    exit 1
fi

FULL_IMAGE_NAME="$GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/$ARTIFACT_REGISTRY_REPO/$SERVICE_NAME:$IMAGE_TAG"

echo "--- Deploying to shared host ($HOST_IP) ---"

echo "Building and pushing Docker image..."
gcloud beta builds submit --project=$GCP_PROJECT_ID --region=$GCP_REGION --config=cloudbuild.yaml \
    --substitutions=_SERVICE_NAME=$SERVICE_NAME,_REGION=$GCP_REGION,_ARTIFACT_REGISTRY_REPO=$ARTIFACT_REGISTRY_REPO \
    .

echo "[bots]
${HOST_IP} ansible_user=${SSH_USER} ansible_ssh_private_key_file=${SSH_KEY_PATH} ansible_ssh_common_args='-o StrictHostKeyChecking=no'" > ansible/inventory.ini

echo "Running Ansible..."
ansible-playbook -i ansible/inventory.ini ansible/playbook.yml \
    --extra-vars "docker_image=$FULL_IMAGE_NAME env_file_src=$(pwd)/.env map_url=http://$HOST_IP:8080"

echo "Cleaning up old Artifact Registry images..."
IMAGES_TO_DELETE=$(gcloud artifacts docker images list \
    "$GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/$ARTIFACT_REGISTRY_REPO/$SERVICE_NAME" \
    --project=$GCP_PROJECT_ID \
    --include-tags \
    --sort-by="~UPDATE_TIME" \
    --format="value(DIGEST)" \
    | tail -n +5)

if [ -n "$IMAGES_TO_DELETE" ]; then
    for digest in $IMAGES_TO_DELETE; do
        gcloud artifacts docker images delete \
            "$GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/$ARTIFACT_REGISTRY_REPO/$SERVICE_NAME@$digest" \
            --project=$GCP_PROJECT_ID \
            --delete-tags --quiet || true
    done
fi

echo "✅ Deployment complete — bot running on $HOST_IP"
