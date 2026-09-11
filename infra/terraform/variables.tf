variable "subscription_id" {
  description = "Azure subscription containing rg-cvent-agent-pilot."
  type        = string
}

variable "tenant_id" {
  description = "Microsoft Entra tenant ID."
  type        = string
}

variable "resource_group_name" {
  type    = string
  default = "rg-cvent-agent-pilot"
  validation {
    condition     = var.resource_group_name == "rg-cvent-agent-pilot"
    error_message = "Production V1 is restricted to rg-cvent-agent-pilot."
  }
}

variable "location" {
  type    = string
  default = "eastus2"
  validation {
    condition     = var.location == "eastus2"
    error_message = "Production V1 is restricted to eastus2."
  }
}

variable "name_prefix" {
  type    = string
  default = "cvent-agent-pilot"
}

variable "vm_size" {
  description = "Three Chromium workers need 8 vCPU and 32 GiB RAM for the pilot."
  type        = string
  default     = "Standard_D8as_v5"
}

variable "admin_username" {
  type    = string
  default = "azureadmin"
}

variable "admin_ssh_public_key" {
  description = "SSH public key; port 22 is reachable only through Azure Bastion."
  type        = string
}

variable "dns_label" {
  description = "Globally unique label used as <label>.eastus2.cloudapp.azure.com for HTTPS and Entra redirect."
  type        = string
}

variable "repository_url" {
  type    = string
  default = "https://github.com/bpickett2019/cvent-one-shot.git"
}

variable "repository_ref" {
  description = "Immutable tested Git commit SHA to deploy."
  type        = string
  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.repository_ref))
    error_message = "repository_ref must be a full 40-character commit SHA."
  }
}

variable "entra_user_principal_object_ids" {
  description = "User or group object IDs assigned Cvent.Agent.User."
  type        = set(string)
  default     = []
}

variable "entra_admin_principal_object_ids" {
  description = "User or group object IDs assigned Cvent.Agent.Admin."
  type        = set(string)
  default     = []
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "alert_email" {
  description = "Operations email for VM availability alerts."
  type        = string
}
