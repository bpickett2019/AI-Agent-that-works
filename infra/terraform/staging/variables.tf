variable "subscription_id" {
  type    = string
  default = "e7a6e33b-d0a8-4ab6-9aa0-114ac3ad9a88"
  validation {
    condition     = var.subscription_id == "e7a6e33b-d0a8-4ab6-9aa0-114ac3ad9a88"
    error_message = "This root module is restricted to the ChartDarts staging subscription."
  }
}

variable "tenant_id" {
  type    = string
  default = "661c8d9b-e19e-4330-b412-75dce2d26154"
}

variable "resource_group_name" {
  type    = string
  default = "rg-chartdarts-stg"
  validation {
    condition     = var.resource_group_name == "rg-chartdarts-stg"
    error_message = "This root module must never target the production resource group."
  }
}

variable "location" {
  type    = string
  default = "westus3"
  validation {
    condition     = var.location == "westus3"
    error_message = "ChartDarts staging is restricted to westus3."
  }
}

variable "deployed_commit" {
  type    = string
  default = "1c5a1784b2207a4516c84c6f9184975a28284b5f"
  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.deployed_commit))
    error_message = "deployed_commit must be a complete immutable Git SHA."
  }
}

variable "admin_ssh_public_key" {
  description = "Approved staging administrator SSH public key. Never supply a private key."
  type        = string
}

variable "ssh_source_cidr" {
  description = "Single approved operator IPv4 /32. Never use an Internet-wide CIDR."
  type        = string
  validation {
    condition     = can(regex("^(?:[0-9]{1,3}\\.){3}[0-9]{1,3}/32$", var.ssh_source_cidr))
    error_message = "ssh_source_cidr must be a single IPv4 /32."
  }
}

variable "key_vault_operator_object_id" {
  description = "Object ID approved to administer staging Key Vault secrets."
  type        = string
  default     = "4a6e7af6-72bb-4f11-8fb3-fb7842fcb2e6"
}
