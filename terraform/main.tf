provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

# --- Service Account ---
resource "google_service_account" "bot_sa" {
  account_id   = "discord-bot-vm-sa"
  display_name = "Discord Bot VM Service Account"
}

# --- IAM Permissions ---
# Allow reading images from Artifact Registry
resource "google_project_iam_member" "artifact_registry_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.bot_sa.email}"
}

# Allow accessing Firestore
resource "google_project_iam_member" "datastore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.bot_sa.email}"
}

# Allow logging
resource "google_project_iam_member" "logging_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.bot_sa.email}"
}

# --- Compute Instance ---
resource "google_compute_instance" "bot_vm" {
  name         = "lotslarp-discord-bot-vm"
  machine_type = var.machine_type
  zone         = var.zone

  tags = ["discord-bot"]

  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2204-lts"
      size  = 10 # 10GB is enough for basic docker usage
      type  = "pd-standard"
    }
  }

  network_interface {
    network = "default"
    access_config {
      # Ephemeral public IP
    }
  }

  service_account {
    email  = google_service_account.bot_sa.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    ssh-keys = "${var.ssh_user}:${file(var.ssh_pub_key_path)}"
  }

  # Allow stopping for updates if needed
  allow_stopping_for_update = true
}

# --- Firewall Rule (Optional, only if you need inbound traffic) ---
# Discord bots are outbound-only via Websocket, so we don't need to open ports 
# unless running the health check server publicly.
# If you want to access the health check port 8080:
resource "google_compute_firewall" "allow_health_check" {
  name    = "allow-discord-bot-health"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["8080"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["discord-bot"]
}
