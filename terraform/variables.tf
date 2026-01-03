variable "project_id" {
  description = "Google Cloud Project ID"
  type        = string
  default     = "lotslarp"
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-east1"
}

variable "zone" {
  description = "GCP Zone"
  type        = string
  default     = "us-east1-b"
}

variable "machine_type" {
  description = "GCE Machine Type"
  type        = string
  default     = "e2-micro"
}

variable "ssh_user" {
  description = "SSH Username"
  type        = string
  default     = "ansible"
}

variable "ssh_pub_key_path" {
  description = "Path to SSH public key"
  type        = string
  default     = "~/.ssh/id_rsa.pub"
}
