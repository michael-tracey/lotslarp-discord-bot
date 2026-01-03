output "public_ip" {
  value       = google_compute_instance.bot_vm.network_interface[0].access_config[0].nat_ip
  description = "Public IP address of the bot VM"
}
