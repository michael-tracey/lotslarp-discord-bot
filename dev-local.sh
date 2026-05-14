#!/bin/bash

# Stops the GCE cloud instance and runs the bot locally for development.
# Re-run this script with --resume to restart the cloud instance when done.

set -e

GCP_PROJECT_ID=${GCP_PROJECT_ID:-"lotslarp"}
INSTANCE_NAME="lotslarp-discord-bot-vm"
ZONE="us-east1-b"
VENV_DIR=".venv"
BOT_SCRIPT="discord_bot.py"

# ── Resume mode ───────────────────────────────────────────────────────────────
if [[ "${1}" == "--resume" ]]; then
    echo "Starting cloud instance $INSTANCE_NAME..."
    gcloud compute instances start "$INSTANCE_NAME" --zone "$ZONE" --project "$GCP_PROJECT_ID"
    echo "✅ Cloud instance is starting. Check status with: ./status-gce.sh"
    exit 0
fi

# ── Preflight checks ──────────────────────────────────────────────────────────
if [ ! -f .env ]; then
    echo "❌ .env file not found. Copy .env.example and fill in values."
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    echo "❌ python3 not found."
    exit 1
fi

if ! command -v gcloud &>/dev/null; then
    echo "❌ gcloud CLI not found. Cloud instance will not be paused."
    SKIP_GCLOUD=1
fi

# ── Stop cloud instance ───────────────────────────────────────────────────────
if [[ -z "$SKIP_GCLOUD" ]]; then
    CLOUD_STATUS=$(gcloud compute instances describe "$INSTANCE_NAME" \
        --zone "$ZONE" --project "$GCP_PROJECT_ID" --format="get(status)" 2>/dev/null || echo "UNKNOWN")

    if [[ "$CLOUD_STATUS" == "RUNNING" ]]; then
        echo "Stopping cloud instance $INSTANCE_NAME (status: $CLOUD_STATUS)..."
        gcloud compute instances stop "$INSTANCE_NAME" --zone "$ZONE" --project "$GCP_PROJECT_ID"
        echo "✅ Cloud instance stopped."
    elif [[ "$CLOUD_STATUS" == "TERMINATED" || "$CLOUD_STATUS" == "STOPPED" ]]; then
        echo "Cloud instance is already stopped (status: $CLOUD_STATUS). Continuing."
    else
        echo "⚠️  Cloud instance status: $CLOUD_STATUS. Proceeding without stopping."
    fi
fi

# ── Set up virtualenv ─────────────────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment in $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

echo "Installing/updating dependencies..."
pip install -q -r requirements.txt

# ── Auto-resume trap ──────────────────────────────────────────────────────────
_on_exit() {
    echo ""
    if [[ -z "$SKIP_GCLOUD" ]]; then
        read -r -p "Restart cloud instance $INSTANCE_NAME? (y/n): " resume
        if [[ "$resume" =~ ^[Yy] ]]; then
            echo "Starting cloud instance..."
            gcloud compute instances start "$INSTANCE_NAME" --zone "$ZONE" --project "$GCP_PROJECT_ID"
            echo "✅ Cloud instance is starting. Check status with: ./status-gce.sh"
        else
            echo "Cloud instance left stopped. Run './dev-local.sh --resume' to start it later."
        fi
    fi
}
trap _on_exit EXIT

# ── Run bot ───────────────────────────────────────────────────────────────────
echo ""
echo "Starting bot locally. Press Ctrl+C to stop."
echo "──────────────────────────────────────────────────────────────────"

# Load .env and run (python-dotenv handles loading inside the bot itself,
# but export here too so any subprocess can see the vars)
set -a
# shellcheck disable=SC1091
source .env
set +a

python3 "$BOT_SCRIPT"
