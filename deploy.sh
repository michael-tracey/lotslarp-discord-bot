#!/bin/bash

# This script deploys the Discord bot to Google Cloud Run.

# --- Configuration ---
# The following variables will be used to configure the deployment.
# You can either set them here or as environment variables.

# Google Cloud Project ID
GCP_PROJECT_ID=${GCP_PROJECT_ID:-"lotslarp"}

# Google Cloud Region
GCP_REGION=${GCP_REGION:-"us-east1"}

# The name of the Cloud Run service
SERVICE_NAME=${SERVICE_NAME:-"lotslarp-discord-bot"}

# The name of the Artifact Registry repository
ARTIFACT_REGISTRY_REPO=${ARTIFACT_REGISTRY_REPO:-"discord-bots"}

# --- Script ---

set -e

echo "--- Configuration ---"
echo "GCP Project ID: $GCP_PROJECT_ID"
echo "GCP Region: $GCP_REGION"
echo "Service Name: $SERVICE_NAME"
echo "Artifact Registry Repo: $ARTIFACT_REGISTRY_REPO"
echo "--------------------"

echo ""
echo "This script will deploy the Discord bot to Google Cloud Run."
echo "It will also create/update secrets in Google Secret Manager from your .env file."
echo ""
echo "Please make sure you have the following tools installed:"
echo "- gcloud"
echo "- docker"
echo ""
echo "And that you are authenticated with gcloud:"
echo "gcloud auth login"
echo "gcloud auth configure-docker"
echo ""

if [ ! -f .env ]; then
    echo ".env file not found. Please copy .env.example to .env and fill in your secrets."
    exit 1
fi

read -p "Do you want to continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    exit 1
fi

# Create/update secrets
echo "Creating/updating secrets in Google Secret Manager..."
while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" =~ ^\s*# || -z "$line" ]]; then
        continue
    fi
    key=$(echo "$line" | cut -d '=' -f 1)
    value=$(echo "$line" | cut -d '=' -f 2-)
    # Remove surrounding quotes if present
    value=$(echo "$value" | sed 's/^"//;s/"$//')
    
    # Check if secret exists
    if gcloud secrets describe "$key" --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
        echo "Updating secret: $key"
        printf "%s" "$value" | gcloud secrets versions add "$key" --project="$GCP_PROJECT_ID" --data-file=-
    else
        echo "Creating secret: $key"
        if gcloud secrets create "$key" --replication-policy=automatic --project="$GCP_PROJECT_ID"; then
            printf "%s" "$value" | gcloud secrets versions add "$key" --project="$GCP_PROJECT_ID" --data-file=-
        else
            echo "Failed to create secret: $key. It may already exist. Trying to update instead..."
            printf "%s" "$value" | gcloud secrets versions add "$key" --project="$GCP_PROJECT_ID" --data-file=-
        fi
    fi
done < .env


echo "Submitting build to Google Cloud Build..."

gcloud builds submit --region=$GCP_REGION --config=cloudbuild.yaml \
    --substitutions=_SERVICE_NAME=$SERVICE_NAME,_REGION=$GCP_REGION,_ARTIFACT_REGISTRY_REPO=$ARTIFACT_REGISTRY_REPO \
    .

echo "Deployment successful!"