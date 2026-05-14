#!/bin/bash
set -e

SSH_KEY_PATH="${HOME}/.ssh/ansible_gce_key"
SSH_USER="ansible"
HOST_IP=$(gcloud storage cat gs://mtracey-tofu-state/infra/default.tfstate | jq -r '.outputs.host_ip.value')

echo "Checking status on $HOST_IP..."
echo "--------------------------------------------------"

ssh -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no -o ConnectTimeout=20 "$SSH_USER@$HOST_IP" bash << 'ENDSSH'
echo "--- Server Details ---"
echo "Hostname: $(hostname)"
echo "Uptime: $(uptime -p)"
echo "Memory: $(free -h | awk '/^Mem:/ {print $3 "/" $2}')"
echo "Disk: $(df -h / | awk 'NR==2 {print $3 "/" $2 " (" $5 ")"}')"

echo ""
echo "--- Docker Status ---"
docker --version
systemctl is-active docker && echo "Docker Engine: Running" || echo "Docker Engine: Stopped"

echo ""
echo "--- Bot Container ---"
if docker ps --filter name=discord-bot --format "{{.ID}}" | grep -q .; then
    echo "Container: Running ($(docker inspect --format='{{.State.Status}}' discord-bot))"
    echo "Started at: $(docker inspect --format='{{.State.StartedAt}}' discord-bot)"
    echo ""
    echo "--- Last 5 Log Lines ---"
    docker logs discord-bot --tail 5
else
    echo "Container: discord-bot is NOT running"
fi
ENDSSH
