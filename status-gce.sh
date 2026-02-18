#!/bin/bash

# This script checks the status of the Discord bot on GCE.
# It outputs server details, docker status, engine status, 
# bot process status, and the last 5 lines of logs.

set -e

# Configuration
SSH_KEY_PATH="${HOME}/.ssh/ansible_gce_key"
SSH_USER="ansible"
INSTANCE_NAME="lotslarp-discord-bot-vm"
ZONE="us-east1-b"

echo "Finding server IP..."

# 1. Try OpenTofu
if [ -d "terraform/.terraform" ] || [ -d "terraform/.tofu" ]; then
    VM_IP=$(cd terraform && tofu output -raw public_ip 2>/dev/null || echo "")
fi

# 2. Fallback to gcloud if VM_IP is empty
if [ -z "$VM_IP" ]; then
    VM_IP=$(gcloud compute instances describe "$INSTANCE_NAME" 
        --zone "$ZONE" 
        --format='get(networkInterfaces[0].accessConfigs[0].natIP)' 2>/dev/null || echo "")
fi

if [ -z "$VM_IP" ]; then
    echo "Error: Could not determine VM IP."
    exit 1
fi

echo "Checking status on $VM_IP..."
echo "--------------------------------------------------"

# Define the status check commands to run on the server
REMOTE_COMMANDS=$(cat <<EOF
echo "--- Server Details ---"
echo "Hostname: \$(hostname)"
echo "Uptime: \$(uptime -p)"
echo "Memory: \$(free -h | awk '/^Mem:/ {print \$3 "/" \$2}')"
echo "Disk: \$(df -h / | awk 'NR==2 {print \$3 "/" \$2 " (" \$5 ")"}')"

echo ""
echo "--- Docker Status ---"
if systemctl is-active --quiet docker; then
    echo "Docker Engine: ✅ Active"
else
    echo "Docker Engine: ❌ Inactive"
fi
docker --version

echo ""
echo "--- Bot Process Status ---"
BOT_CONTAINER=\$(sudo docker ps --filter name=discord-bot --format "{{.ID}}")
if [ -n "\$BOT_CONTAINER" ]; then
    STATUS=\$(sudo docker inspect --format='{{.State.Status}}' discord-bot)
    UPTIME=\$(sudo docker inspect --format='{{.State.StartedAt}}' discord-bot)
    echo "Container: ✅ Running (\$STATUS)"
    echo "Started at: \$UPTIME"
    
    echo ""
    echo "--- Process Details (Inside Container) ---"
    sudo docker exec discord-bot ps aux | grep python | grep -v grep || echo "No python process found inside container."
    
    echo ""
    echo "--- Last 5 Log Lines ---"
    sudo docker logs discord-bot --tail 5
else
    echo "Container: ❌ discord-bot is NOT running"
fi
EOF
)

# Run the commands via SSH with a timeout and countdown
echo "Attempting to connect to $VM_IP..."
(
    for i in {20..1}; do
        printf "\rTrying to connect... %2d seconds remaining" $i
        sleep 1
    done
) &
COUNTDOWN_PID=$!

if ssh -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no -o LogLevel=QUIET -o ConnectTimeout=20 "$SSH_USER@$VM_IP" "$REMOTE_COMMANDS"; then
    kill $COUNTDOWN_PID 2>/dev/null
    printf "\rConnected successfully.                         \n"
else
    kill $COUNTDOWN_PID 2>/dev/null
    echo ""
    echo "--------------------------------------------------"
    echo "❌ ERROR: SSH connection failed or timed out."
    echo "Gathering diagnostics from Google Cloud..."
    echo ""
    
    INSTANCE_STATUS=$(gcloud compute instances describe "$INSTANCE_NAME" --zone "$ZONE" --format="get(status)" 2>/dev/null || echo "UNKNOWN")
    echo "VM Instance Status: $INSTANCE_STATUS"
    
    if [ "$INSTANCE_STATUS" != "RUNNING" ]; then
        echo "The VM is not in RUNNING state. You may need to start it."
    else
        echo "The VM is RUNNING but SSH is unresponsive. Checking serial port output for errors..."
        echo "--- Last 20 lines of Serial Port Output ---"
        gcloud compute instances get-serial-port-output "$INSTANCE_NAME" --zone "$ZONE" 2>&1 | tail -n 20
    fi
    
    echo ""
    echo "Troubleshooting Menu:"
    echo "1) View full Serial Port Output"
    echo "2) Check Firewall Rules (Port 22)"
    echo "3) Reset the VM Instance (may fix DHCP/Network issues)"
    echo "4) Exit"
    read -p "Select an option [1-4]: " choice
    
    case $choice in
        1)
            echo "--- Full Serial Port Output ---"
            gcloud compute instances get-serial-port-output "$INSTANCE_NAME" --zone "$ZONE"
            ;;
        2)
            echo "--- Checking Firewall Rules for Port 22 ---"
            gcloud compute firewall-rules list --filter="ALLOW:22 OR ALLOW:tcp:22"
            ;;
        3)
            echo "--- Resetting instance $INSTANCE_NAME ---"
            gcloud compute instances reset "$INSTANCE_NAME" --zone "$ZONE"
            ;;
        *)
            echo "Exiting troubleshooting."
            ;;
    esac
fi

echo "--------------------------------------------------"
