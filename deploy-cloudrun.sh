#!/bin/bash

# This script deploys the Discord bot to Google Cloud Run.

# --- Configuration ---
GCP_PROJECT_ID=${GCP_PROJECT_ID:-"lotslarp"}
GCP_REGION=${GCP_REGION:-"us-east1"}
SERVICE_NAME=${SERVICE_NAME:-"lotslarp-discord-bot"}
ARTIFACT_REGISTRY_REPO=${ARTIFACT_REGISTRY_REPO:-"discord-bots"}

# --- Constants ---
# List of "True Secrets" that MUST be in Secret Manager.
# All other .env variables will be passed as plain environment variables via YAML file.
TRUE_SECRETS=("LOTSLARP_DISCORD_BOT_DISCORD_TOKEN" "LOTSLARP_DISCORD_BOT_GEMINI_API_KEY" "LOTSLARP_ADMIN_PASSWORD")

# --- Helper Functions ---
setup_monitoring() {
    if [ -f .env ]; then
        ALERT_EMAIL=$(grep "^ALERT_EMAIL=" .env | cut -d '=' -f 2- | tr -d '"')
    fi
    
    if [ -z "$ALERT_EMAIL" ]; then
        echo "ALERT_EMAIL is not set. Skipping monitoring setup."
        return
    fi
    echo "--- Monitoring setup complete (alert email: $ALERT_EMAIL) ---"
}

is_true_secret() {
    local key="$1"
    for secret in "${TRUE_SECRETS[@]}"; do
        if [[ "$secret" == "$key" ]]; then
            return 0
        fi
    done
    return 1
}

# --- Main Script ---

set -e

echo "--- Configuration ---"
echo "GCP Project ID: $GCP_PROJECT_ID"
echo "GCP Region: $GCP_REGION"
echo "Service Name: $SERVICE_NAME"
echo "--------------------"

if [ ! -f .env ]; then
    echo ".env file not found. Please copy .env.example to .env and fill in your secrets."
    exit 1
fi

# 1. Process Secrets and Env Vars
echo "Processing .env file..."
ENV_VARS_FILE="env_vars.yaml"
# Start fresh
> "$ENV_VARS_FILE"

SET_SECRETS_STRING=""

while IFS= read -r line || [[ -n "$line" ]]; do
    # Skip comments and empty lines
    if [[ "$line" =~ ^\s*# || -z "$line" ]]; then continue; fi
    
    key=$(echo "$line" | cut -d '=' -f 1)
    value=$(echo "$line" | cut -d '=' -f 2-)
    # Remove surrounding quotes for processing
    value=$(echo "$value" | sed 's/^"//;s/"$//')
    
    # Skip DCE_CLI_PATH as it is set in the Dockerfile for cloud environments
    if [[ "$key" == "DCE_CLI_PATH" ]]; then
        echo "⏭️  Skipping $key (Using Dockerfile default)"
        continue
    fi
    
    if is_true_secret "$key"; then
        echo "🔒 Secret: $key (Managing in Secret Manager)"
        
        # Check if secret exists
        if ! gcloud secrets describe "$key" --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
             echo "Creating new secret: $key"
             gcloud secrets create "$key" --replication-policy=automatic --project="$GCP_PROJECT_ID"
        fi

        # Check if value has changed
        current_value=$(gcloud secrets versions access latest --secret="$key" --project="$GCP_PROJECT_ID" 2>/dev/null || echo "")
        if [ "$current_value" != "$value" ]; then
            echo "Updating secret value: $key"
            printf "%s" "$value" | gcloud secrets versions add "$key" --project="$GCP_PROJECT_ID" --data-file=-
        else
            echo "Secret $key is up to date."
        fi

        # CLEANUP: Keep only 'latest' version
        versions=$(gcloud secrets versions list "$key" --project="$GCP_PROJECT_ID" --filter="state=enabled" --sort-by="~createTime" --format="value(name)")
        count=0
        for version in $versions; do
            count=$((count + 1))
            if [ "$count" -gt 1 ]; then
                gcloud secrets versions destroy "$version" --secret="$key" --project="$GCP_PROJECT_ID" --quiet
            fi
        done

        if [ -n "$SET_SECRETS_STRING" ]; then
            SET_SECRETS_STRING="$SET_SECRETS_STRING,$key=$key:latest"
        else
            SET_SECRETS_STRING="$key=$key:latest"
        fi

    else
        echo "📝 Config: $key (Adding to env_vars.yaml)"
        # Write to YAML file. Escape single quotes for YAML.
        yaml_value=$(echo "$value" | sed "s/'/''/g")
        echo "$key: '$yaml_value'" >> "$ENV_VARS_FILE"
    fi

done < .env

# 2. Cleanup Unused Secrets from Secret Manager
echo "--- Checking for unused secrets to delete ---"
all_secrets=$(gcloud secrets list --project="$GCP_PROJECT_ID" --format="value(name)")

for secret_name in $all_secrets; do
    simple_name=$(basename "$secret_name")
    if ! is_true_secret "$simple_name"; then
        if [[ "$simple_name" == LOTSLARP_* ]]; then
            echo "🗑️  Deleting unused secret: $simple_name"
            gcloud secrets delete "$simple_name" --project="$GCP_PROJECT_ID" --quiet
        fi
    fi
done

# 3. Build Image
echo "--- Submitting Build ---"
gcloud beta builds submit --region=$GCP_REGION --config=cloudbuild.yaml \
    --substitutions=_SERVICE_NAME=$SERVICE_NAME,_REGION=$GCP_REGION,_ARTIFACT_REGISTRY_REPO=$ARTIFACT_REGISTRY_REPO \
    .

# 4. Deploy to Cloud Run
echo "--- Deploying to Cloud Run ---"

# PRE-CLEANUP: The service currently has references to secrets that we just deleted.
# We must clear them first to avoid "Secret not found" errors during the new revision creation.
echo "Clearing old secret references..."
gcloud run services update "$SERVICE_NAME" \
    --region "$GCP_REGION" \
    --clear-secrets \
    --quiet || echo "Warning: Failed to clear secrets (service might not exist yet), continuing..."

IMAGE_URL="$GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/$ARTIFACT_REGISTRY_REPO/$SERVICE_NAME:latest"

# Note: We use --set-secrets to REPLACE all existing secret references with our clean list.
CMD="gcloud run deploy $SERVICE_NAME \
  --image $IMAGE_URL \
  --region $GCP_REGION \
  --platform managed \
  --port 8080 \
  --cpu 1 \
  --memory 512Mi \
  --no-cpu-throttling \
  --min-instances 1 \
  --max-instances 3 \
  --allow-unauthenticated"

if [ -n "$SET_SECRETS_STRING" ]; then
    CMD="$CMD --set-secrets=$SET_SECRETS_STRING"
fi

if [ -f "$ENV_VARS_FILE" ]; then
    CMD="$CMD --env-vars-file=$ENV_VARS_FILE"
fi

echo "Executing gcloud run deploy..."
eval $CMD

# Clean up temp file
rm -f "$ENV_VARS_FILE"

# Post-Deploy
setup_monitoring

# 5. Cleanup Old Images
echo "--- Cleaning up old images ---"
echo "Fetching image list..."
IMAGES_TO_DELETE=$(gcloud artifacts docker images list \
    "$GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/$ARTIFACT_REGISTRY_REPO/$SERVICE_NAME" \
    --include-tags \
    --sort-by=\"~UPDATE_TIME\" \
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

echo "✅ Deployment successful!"
