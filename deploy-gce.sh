#!/bin/bash

# This script deploys the Discord bot to a Google Compute Engine VM using OpenTofu and Ansible.

set -e

# --- Configuration ---
GCP_PROJECT_ID=${GCP_PROJECT_ID:-"lotslarp"}
GCP_REGION=${GCP_REGION:-"us-east1"}
SERVICE_NAME="lotslarp-discord-bot"
ARTIFACT_REGISTRY_REPO="discord-bots"
IMAGE_TAG="latest" # Or specific tag if preferred

# SSH Key for Ansible
SSH_KEY_PATH="${HOME}/.ssh/ansible_gce_key"
SSH_USER="ansible"

# Check for .env
if [ ! -f .env ]; then
    echo "Error: .env file not found."
    exit 1
fi

echo "--- Deploying to GCE ---"

# 1. Build & Push Docker Image (reusing Cloud Build logic lightly or assuming it's done)
# Ideally, we should build locally or trigger a build. For simplicity, let's trigger a build.
echo "Triggering Cloud Build to ensure 'latest' image is up to date..."
gcloud beta builds submit --region=$GCP_REGION --config=cloudbuild.yaml \
    --substitutions=_SERVICE_NAME=$SERVICE_NAME,_REGION=$GCP_REGION,_ARTIFACT_REGISTRY_REPO=$ARTIFACT_REGISTRY_REPO \
    .

FULL_IMAGE_NAME="$GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/$ARTIFACT_REGISTRY_REPO/$SERVICE_NAME:$IMAGE_TAG"

# 2. Ensure SSH Key Exists
if [ ! -f "$SSH_KEY_PATH" ]; then
    echo "Generating SSH key for Ansible..."
    ssh-keygen -t rsa -b 4096 -f "$SSH_KEY_PATH" -C "$SSH_USER" -N ""
fi

# 3. Provision Infrastructure with OpenTofu
echo "Provisioning Infrastructure (OpenTofu)..."
cd terraform

# Init (OpenTofu uses .terraform directory for compatibility usually, but we run init to be sure)
if [ ! -d ".terraform" ] && [ ! -d ".tofu" ]; then
    tofu init
fi

# Apply
tofu apply -auto-approve \
    -var="project_id=$GCP_PROJECT_ID" \
    -var="ssh_user=$SSH_USER" \
    -var="ssh_pub_key_path=${SSH_KEY_PATH}.pub"

# Get Public IP
VM_IP=$(tofu output -raw public_ip)
MAP_URL="http://$VM_IP:8080"
echo "VM Public IP: $VM_IP"
echo "Calculated Map URL: $MAP_URL"

# Wait for SSH to become available
echo "Waiting for SSH to become available on $VM_IP..."
MAX_RETRIES=30
RETRY_COUNT=0
while ! nc -z -w5 "$VM_IP" 22; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "Error: SSH did not become available after $MAX_RETRIES attempts."
        exit 1
    fi
    echo "SSH not ready yet (attempt $RETRY_COUNT/$MAX_RETRIES). Waiting..."
    sleep 5
done
echo "✅ SSH is available!"

cd ..

# 4. Configure with Ansible
echo "Configuring VM with Ansible..."

# Create temporary inventory
INVENTORY_FILE="ansible/inventory.ini"
echo "[bots]" > "$INVENTORY_FILE"
echo "$VM_IP ansible_user=$SSH_USER ansible_ssh_private_key_file=$SSH_KEY_PATH ansible_ssh_common_args='-o StrictHostKeyChecking=no'" >> "$INVENTORY_FILE"

# Run Playbook
# We pass the local .env file path to Ansible
ansible-playbook -i "$INVENTORY_FILE" ansible/playbook.yml \
    --extra-vars "docker_image=$FULL_IMAGE_NAME env_file_src=$(pwd)/.env map_url=$MAP_URL"

# 5. Cleanup Old Images
echo "--- Cleaning up old images ---"
echo "Fetching image list..."
IMAGES_TO_DELETE=$(gcloud artifacts docker images list \
    "$GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/$ARTIFACT_REGISTRY_REPO/$SERVICE_NAME" \
    --include-tags \
    --sort-by="~UPDATE_TIME" \
    --format="value(DIGEST)" \
    | tail -n +5)

if [ -n "$IMAGES_TO_DELETE" ]; then
    echo "Found old images to delete..."
    for digest in $IMAGES_TO_DELETE; do
        echo "Deleting image: $digest"
        gcloud artifacts docker images delete \
            "$GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/$ARTIFACT_REGISTRY_REPO/$SERVICE_NAME@$digest" \
            --delete-tags --quiet || echo "Failed to delete $digest"
    done
else
    echo "No old images to clean up."
fi

echo "✅ GCE Deployment Complete!"
