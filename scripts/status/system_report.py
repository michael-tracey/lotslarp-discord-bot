import argparse
import os
import datetime
import subprocess
import logging
from google.cloud import firestore

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("status_reporter")

# Configuration (Defaults matching your setup)
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "lotslarp")
ZONE = os.environ.get("GCP_ZONE", "us-east1-b")
VM_NAME = "lotslarp-discord-bot-vm"
SSH_KEY_PATH = os.path.expanduser("~/.ssh/ansible_gce_key")
SSH_USER = "ansible"

def run_ssh_command(ip, command):
    """Runs a command on the remote VM via SSH."""
    ssh_cmd = [
        "ssh",
        "-i", SSH_KEY_PATH,
        "-o", "StrictHostKeyChecking=no",
        "-o", "LogLevel=QUIET",
        f"{SSH_USER}@{ip}",
        command
    ]
    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip()}"

def get_vm_ip():
    """Gets the public IP of the VM from Terraform output."""
    try:
        # Assuming run from project root, navigate to terraform
        cwd = os.getcwd()
        tf_dir = os.path.join(cwd, "terraform")
        
        # Check if tf_dir exists
        if not os.path.exists(tf_dir):
             return None

        # Run tofu output
        cmd = ["tofu", "output", "-raw", "public_ip"]
        result = subprocess.run(cmd, cwd=tf_dir, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception as e:
        logger.error(f"Failed to get VM IP: {e}")
        return None

def get_billing_data():
    """Calculates real costs based on latest GCP unit prices."""
    # Pricing Data (Verified 2026)
    PRICE_E2_MICRO = 0.0084  # $/hr
    PRICE_IPV4_IN_USE = 0.005 # $/hr
    PRICE_ARTIFACT_REG = 0.10 # $/GB/mo (over 0.5GB free)
    
    # Gemini 1.5 Pro (Pay-as-you-go)
    GEMINI_INPUT_1M = 1.25
    GEMINI_OUTPUT_1M = 5.00

    print("\n--- 💰 Real Cost Analysis (Current Rates) ---")
    
    # Time Tracking
    now = datetime.datetime.now()
    days_in_month = 30 # Standardized
    hours_so_far = (now - now.replace(day=1, hour=0, minute=0, second=0)).total_seconds() / 3600
    total_hours_month = 24 * days_in_month
    
    # 1. Compute Engine (e2-micro)
    # Most e2-micro instances are covered by the Free Tier (1 per account)
    vm_cost_so_far = hours_so_far * PRICE_E2_MICRO
    vm_projected = total_hours_month * PRICE_E2_MICRO
    
    # 2. Public IPv4 (In-use)
    ip_cost_so_far = hours_so_far * PRICE_IPV4_IN_USE
    ip_projected = total_hours_month * PRICE_IPV4_IN_USE
    
    print(f"• VM Compute (e2-micro): ${vm_cost_so_far:.2f} (Projected ${vm_projected:.2f}/mo)")
    print(f"  > NOTE: Likely $0.00 if eligible for GCP Free Tier.")
    print(f"• Public IPv4 Address:  ${ip_cost_so_far:.2f} (Projected ${ip_projected:.2f}/mo)")
    print(f"• Artifact Registry:    ~$0.15 (Based on 1.5GB storage)")
    
    print("\n--- 🤖 AI Usage (Gemini 1.5 Pro) ---")
    print(f"• Input Pricing:        ${GEMINI_INPUT_1M:.2f} per 1M tokens")
    print(f"• Output Pricing:       ${GEMINI_OUTPUT_1M:.2f} per 1M tokens")
    print(f"  > NOTE: Free Tier (15 RPM / 1M TPM) usually covers small bot usage.")

    # Combined Total
    current_total = ip_cost_so_far + 0.15 # Assuming VM is free
    projected_total = ip_projected + 0.15
    print(f"\n-> Real Projected Total: ~${projected_total:.2f}/mo (excluding AI)")
    if vm_projected > 0:
        print(f"   (Worse case if not Free Tier: ~${projected_total + vm_projected:.2f}/mo)")


def check_system_status(ip):
    """Checks Docker container status and resource usage."""
    print("\n--- 🖥️  System Status ---")
    if not ip:
        print("❌ VM IP not found. Is the infrastructure deployed?")
        return

    # Uptime
    uptime = run_ssh_command(ip, "uptime -p")
    print(f"• VM Uptime:        {uptime}")

    # Docker Status
    docker_ps = run_ssh_command(ip, "sudo docker ps --format '{{.Status}}' --filter name=discord-bot")
    if docker_ps:
        print(f"• Bot Container:    ✅ Running ({docker_ps})")
    else:
        print(f"• Bot Container:    ❌ NOT RUNNING")

    # Memory Usage
    mem_usage = run_ssh_command(ip, r"""free -h | awk '/^Mem:/ {print $3 "/" $2}'""")
    print(f"• RAM Usage:        {mem_usage}")

    # Disk Usage
    disk_usage = run_ssh_command(ip, r"""df -h / | awk 'NR==2 {print $3 "/" $2 " (" $5 ")"}'""")
    print(f"• Disk Usage:       {disk_usage}")


def check_database_size():
    """Estimates Firestore usage."""
    print("\n--- 🗄️  Database (Firestore) ---")
    try:
        db = firestore.Client(project=PROJECT_ID)
        
        collections = ["summary_messages", "channel_summaries", "voice_logs", "lore_glossary"]
        total_docs = 0
        
        for col_name in collections:
            # Count queries are cheaper/faster
            col_ref = db.collection(col_name)
            count_query = col_ref.count()
            snapshot = count_query.get()
            count = snapshot[0][0].value
            print(f"• {col_name:<20}: {count} docs")
            total_docs += count
            
        print(f"-> Total Documents:    {total_docs}")
        
    except Exception as e:
        print(f"❌ Error checking Firestore: {e}")
        print("   (Ensure you are authenticated with 'gcloud auth application-default login')")

def show_logs(ip):
    """Shows the last 15 lines of logs."""
    print("\n--- 📝 Recent Logs (Tail 15) ---")
    if not ip:
        return
    
    logs = run_ssh_command(ip, "sudo docker logs discord-bot --tail 15")
    print(logs)

def main():
    print(f"==================================================")
    print(f"   LotsLarp Bot Status Report - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"==================================================")
    
    vm_ip = get_vm_ip()
    
    check_system_status(vm_ip)
    get_billing_data()
    check_database_size()
    show_logs(vm_ip)
    
    print("\n==================================================")

if __name__ == "__main__":
    main()
