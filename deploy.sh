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

# Email address for alert notifications (optional)
# If set, a Cloud Monitoring alert policy will be created.
ALERT_EMAIL=${ALERT_EMAIL:-""}

# --- Helper Functions ---

# This function sets up monitoring alerts for the service
setup_monitoring() {
    # Extract ALERT_EMAIL from .env file
    if [ -f .env ]; then
        ALERT_EMAIL=$(grep "^ALERT_EMAIL=" .env | cut -d '=' -f 2- | tr -d '"')
    fi
    
    if [ -z "$ALERT_EMAIL" ]; then
        echo "ALERT_EMAIL is not set. Skipping monitoring setup."
        return
    fi

    echo "--- Setting up Cloud Monitoring ---"
    echo "Alerts will be sent to: $ALERT_EMAIL"

    # 1. Find or create the notification channel
    # Use GA command
    CHANNEL_ID=$(gcloud monitoring channels list --project="$GCP_PROJECT_ID" --filter="displayName=\"Email Alert: $ALERT_EMAIL\"" --format="value(name)" 2>/dev/null)

    if [ -z "$CHANNEL_ID" ]; then
        echo "Notification channel for $ALERT_EMAIL not found. Creating it..."
        
        CHANNEL_JSON=$(mktemp)
        cat > "$CHANNEL_JSON" << EOL
{
  "type": "email",
  "displayName": "Email Alert: $ALERT_EMAIL",
  "labels": { "email_address": "$ALERT_EMAIL" }
}
EOL
        CHANNEL_ID=$(gcloud monitoring channels create --project="$GCP_PROJECT_ID" --channel-content-from-file="$CHANNEL_JSON" --format="value(name)")
        rm "$CHANNEL_JSON"

        if [ -z "$CHANNEL_ID" ]; then
            echo "Error: Failed to create notification channel."
            # Don't exit, just return
            return
        else
            echo "Successfully created notification channel."
            echo "IMPORTANT: A verification email has been sent to $ALERT_EMAIL. You must click the link in it to enable notifications."
        fi
    else
        echo "Found existing notification channel."
    fi

    # 2. Find or create the alert policy
    POLICY_DISPLAY_NAME="Cloud Run Restarts - $SERVICE_NAME"
    # Use GA command and suppress warning if list is empty
    POLICY_ID=$(gcloud monitoring policies list --project="$GCP_PROJECT_ID" --filter="displayName=\"$POLICY_DISPLAY_NAME\"" --format="value(name)" 2>/dev/null)

    if [ -z "$POLICY_ID" ]; then
        echo "Alert policy '$POLICY_DISPLAY_NAME' not found. Creating it..."

        POLICY_JSON=$(mktemp)
        cat > "$POLICY_JSON" << EOL
{
  "displayName": "$POLICY_DISPLAY_NAME",
  "combiner": "OR",
  "conditions": [ {
      "displayName": "Cloud Run Revision has restarted",
      "conditionThreshold": {
        "filter": "metric.type=\\"run.googleapis.com/container/restart_count\\" AND resource.type=\\"cloud_run_revision\\" AND resource.labels.service_name=\\"$SERVICE_NAME\\"",
        "comparison": "COMPARISON_GT",
        "thresholdValue": 0,
        "duration": "600s",
        "trigger": { "count": 1 },
        "aggregations": [ { "alignmentPeriod": "600s", "perSeriesAligner": "ALIGN_DELTA" } ]
      }
  } ],
  "notificationChannels": [ "$CHANNEL_ID" ],
  "documentation": {
    "content": "The $SERVICE_NAME container has restarted. This may indicate a crash loop or a failing liveness probe. Check the service logs for errors.",
    "mimeType": "text/markdown"
  }
}
EOL
        # Use GA command
        if gcloud monitoring policies create --project="$GCP_PROJECT_ID" --policy-from-file="$POLICY_JSON"; then
            echo "Successfully created alert policy."
        else
            echo "Warning: Failed to create alert policy. This is likely because the 'restart_count' metric hasn't been generated yet for this new service."
            echo "The alerting policy can be created later by re-running this script once the service has been running for a few minutes."
        fi
        rm "$POLICY_JSON"
    else
        echo "Found existing alert policy."
    fi

    echo "--- Monitoring setup complete ---"
}


# --- Main Script ---

set -e

echo "--- Configuration ---"
echo "GCP Project ID: $GCP_PROJECT_ID"
echo "GCP Region: $GCP_REGION"
echo "Service Name: $SERVICE_NAME"
echo "Artifact Registry Repo: $ARTIFACT_REGISTRY_REPO"
echo "--------------------"

echo ""
echo "This script will deploy the Discord bot to Google Cloud Run."
# ... (rest of introductory text)

# Check for Firestore Database and create if it does not exist
echo "Checking for Firestore database..."
if gcloud firestore databases describe --project="$GCP_PROJECT_ID" --database="(default)" >/dev/null 2>&1; then
    echo "Firestore database already exists."
else
    echo "Firestore database not found. Creating a new one in nam5..."
    if gcloud firestore databases create --project="$GCP_PROJECT_ID" --location="nam5" --type="firestore-native" --delete-protection; then
        echo "Successfully created Firestore database."
    else
        echo "Failed to create Firestore database."
        exit 1
    fi
fi

# Deploy Firestore indexes
echo "Deploying Firestore indexes..."

# Create composite index for sent_date + timestamp query
echo "Creating composite index for summary_messages (sent_date, timestamp)..."
if gcloud firestore indexes composite create \
    --project="$GCP_PROJECT_ID" \
    --collection-group="summary_messages" \
    --field-config="field-path=sent_date,order=ascending" \
    --field-config="field-path=timestamp,order=ascending" \
    --quiet 2>/dev/null; then
    echo "Successfully created composite index for sent_date + timestamp."
else
    echo "Composite index may already exist (this is okay)."
fi

# Create single field index for timestamp (if needed)
echo "Creating single field index for summary_messages (timestamp)..."
if gcloud firestore indexes fields create \
    --project="$GCP_PROJECT_ID" \
    --collection-group="summary_messages" \
    --field-path="timestamp" \
    --index="order=ascending" \
    --quiet 2>/dev/null; then
    echo "Successfully created single field index for timestamp."
else
    echo "Single field index may already exist (this is okay)."
fi

# Create composite index for voice_logs (channel_name, joined_at)
echo "Creating composite index for voice_logs (channel_name, joined_at)..."
if gcloud firestore indexes composite create \
    --project="$GCP_PROJECT_ID" \
    --collection-group="voice_logs" \
    --field-config="field-path=channel_name,order=ascending" \
    --field-config="field-path=joined_at,order=ascending" \
    --quiet 2>/dev/null; then
    echo "Successfully created composite index for voice_logs."
else
    echo "Voice logs composite index may already exist (this is okay)."
fi

# Create composite index for voice_status_logs (channel_name, timestamp)
echo "Creating composite index for voice_status_logs (channel_name, timestamp)..."
if gcloud firestore indexes composite create \
    --project="$GCP_PROJECT_ID" \
    --collection-group="voice_status_logs" \
    --field-config="field-path=channel_name,order=ascending" \
    --field-config="field-path=timestamp,order=ascending" \
    --quiet 2>/dev/null; then
    echo "Successfully created composite index for voice_status_logs."
else
    echo "Voice status logs composite index may already exist (this is okay)."
fi

if [ ! -f .env ]; then
    echo ".env file not found. Please copy .env.example to .env and fill in your secrets."
    exit 1
fi

# Create/update secrets
echo "Creating/updating secrets in Google Secret Manager..."
while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" =~ ^\s*# || -z "$line" ]]; then continue; fi
    key=$(echo "$line" | cut -d '=' -f 1)
    value=$(echo "$line" | cut -d '=' -f 2-)
    value=$(echo "$value" | sed 's/^"//;s/"$//')
    
    if gcloud secrets describe "$key" --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
        # Check if value has changed
        current_value=$(gcloud secrets versions access latest --secret="$key" --project="$GCP_PROJECT_ID" 2>/dev/null)
        if [ "$current_value" != "$value" ]; then
            echo "Updating secret: $key"
            printf "%s" "$value" | gcloud secrets versions add "$key" --project="$GCP_PROJECT_ID" --data-file=-
        else
            echo "Secret $key is up to date."
        fi
    else
        echo "Creating secret: $key"
        gcloud secrets create "$key" --replication-policy=automatic --project="$GCP_PROJECT_ID"
        printf "%s" "$value" | gcloud secrets versions add "$key" --project="$GCP_PROJECT_ID" --data-file=-
    fi
done < .env

# Check for glossary.csv and upload if present
if [ -f "glossary.csv" ]; then
    echo "Found glossary.csv. Ensuring dependencies are installed..."
    python3 -m pip install -r requirements.txt --quiet
    echo "Uploading to Firestore..."
    if python3 upload_glossary.py; then
        echo "Glossary upload successful."
    else
        echo "Warning: Glossary upload failed. Continuing deployment..."
    fi
else
    echo "glossary.csv not found. Skipping glossary upload."
fi

echo "Submitting build to Google Cloud Build..."
gcloud builds submit --region=$GCP_REGION --config=cloudbuild.yaml \
    --substitutions=_SERVICE_NAME=$SERVICE_NAME,_REGION=$GCP_REGION,_ARTIFACT_REGISTRY_REPO=$ARTIFACT_REGISTRY_REPO \
    .

# --- Post-Deployment Steps ---
# These are called now that the main deployment has finished.
setup_monitoring

echo "Deployment successful!"
