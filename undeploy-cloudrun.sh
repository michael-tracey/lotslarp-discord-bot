#!/bin/bash

# This script deletes the Cloud Run service and related secrets.

set -e

# Configuration
GCP_PROJECT_ID=${GCP_PROJECT_ID:-"lotslarp"}
GCP_REGION=${GCP_REGION:-"us-east1"}
SERVICE_NAME=${SERVICE_NAME:-"lotslarp-discord-bot"}
ARTIFACT_REGISTRY_REPO=${ARTIFACT_REGISTRY_REPO:-"discord-bots"}

echo "⚠️  WARNING: This will DELETE the Cloud Run service '$SERVICE_NAME'."
echo "   It will also attempt to delete the 'True Secrets' managed by the deploy script."
echo "   It will NOT delete the Firestore database."
echo ""
read -p "Are you sure you want to proceed? (y/N) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    echo "Aborted."
    exit 1
fi

echo "--- Deleting Cloud Run Service ---"
gcloud run services delete "$SERVICE_NAME" \
    --region "$GCP_REGION" \
    --project "$GCP_PROJECT_ID" \
    --quiet || echo "Service not found or already deleted."



echo "--- Cleaning up Secrets ---"
# List of "True Secrets" defined in deploy-cloudrun.sh
TRUE_SECRETS=("LOTSLARP_DISCORD_BOT_DISCORD_TOKEN" "LOTSLARP_DISCORD_BOT_GEMINI_API_KEY")

for secret in "${TRUE_SECRETS[@]}"; do
    if gcloud secrets describe "$secret" --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
        echo "Deleting secret: $secret"
        gcloud secrets delete "$secret" --project="$GCP_PROJECT_ID" --quiet
    else
        echo "Secret $secret not found or already deleted."
    fi
done

# Cleanup all other LOTSLARP_ secrets?
# This mimics the deploy script's cleanup logic to be thorough
echo "Checking for other leftover LOTSLARP_ secrets..."
all_secrets=$(gcloud secrets list --project="$GCP_PROJECT_ID" --format="value(name)")
for secret_name in $all_secrets; do
    simple_name=$(basename "$secret_name")
    if [[ "$simple_name" == LOTSLARP_* ]]; then
        # Check if it's one we just deleted (redundant check but safe)
        if gcloud secrets describe "$simple_name" --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
             echo "Deleting leftover secret: $simple_name"
             gcloud secrets delete "$simple_name" --project="$GCP_PROJECT_ID" --quiet
        fi
    fi
done

echo "--- Cleaning up Images ---"
echo "Deleting ALL images for this service from Artifact Registry..."
# Note: This deletes EVERYTHING in the repo for this image, not just old ones.
# Since we are "undeploying the system", this makes sense to stop storage costs.

gcloud artifacts docker images delete \
    "$GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/$ARTIFACT_REGISTRY_REPO/$SERVICE_NAME" \
    --project="$GCP_PROJECT_ID" \
    --delete-tags --quiet || echo "No images found or failed to delete."

echo "✅ Cloud Run system undeployed."
