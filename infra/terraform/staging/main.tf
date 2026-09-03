data "azurerm_resource_group" "staging" {
  name = var.resource_group_name
}

locals {
  common_tags = {
    application = "cvent-one-shot"
    environment = "staging"
    managed-by  = "terraform"
  }
}

resource "azurerm_virtual_network" "app" {
  name                = "cvent-pi-dev-vnet"
  address_space       = ["10.42.0.0/16"]
  location            = var.location
  resource_group_name = data.azurerm_resource_group.staging.name
  tags                = local.common_tags
}

resource "azurerm_network_security_group" "app" {
  name                = "cvent-pi-dev-nsg"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.staging.name
  tags                = local.common_tags

  security_rule {
    name                       = "AllowRestrictedSsh"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.ssh_source_cidr
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet" "app" {
  name                 = "dev"
  resource_group_name  = data.azurerm_resource_group.staging.name
  virtual_network_name = azurerm_virtual_network.app.name
  address_prefixes     = ["10.42.1.0/24"]
  service_endpoints    = ["Microsoft.KeyVault"]
}

resource "azurerm_subnet_network_security_group_association" "app" {
  subnet_id                 = azurerm_subnet.app.id
  network_security_group_id = azurerm_network_security_group.app.id
}

resource "azurerm_public_ip" "app" {
  name                = "cvent-pi-dev-pip"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.staging.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.common_tags
}

resource "azurerm_network_interface" "app" {
  name                           = "cvent-pi-dev-nic"
  location                       = var.location
  resource_group_name            = data.azurerm_resource_group.staging.name
  accelerated_networking_enabled = true
  tags                           = local.common_tags

  ip_configuration {
    name                          = "primary"
    subnet_id                     = azurerm_subnet.app.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.app.id
  }
}

resource "azurerm_linux_virtual_machine" "app" {
  name                            = "cvent-pi-dev-vm"
  location                        = var.location
  resource_group_name             = data.azurerm_resource_group.staging.name
  size                            = "Standard_D8as_v5"
  admin_username                  = "piadmin"
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.app.id]
  secure_boot_enabled             = true
  vtpm_enabled                    = true
  patch_assessment_mode           = "AutomaticByPlatform"
  patch_mode                      = "AutomaticByPlatform"
  tags = merge(local.common_tags, {
    architecture    = "three-worker"
    deployed-commit = var.deployed_commit
  })

  admin_ssh_key {
    username   = "piadmin"
    public_key = var.admin_ssh_public_key
  }

  identity {
    type = "SystemAssigned"
  }

  os_disk {
    name                 = "cvent-pi-dev-osdisk"
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
    disk_size_gb         = 128
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  boot_diagnostics {}
}

resource "azurerm_virtual_machine_extension" "entra_ssh" {
  name                       = "AADSSHLoginForLinux"
  virtual_machine_id         = azurerm_linux_virtual_machine.app.id
  publisher                  = "Microsoft.Azure.ActiveDirectory"
  type                       = "AADSSHLoginForLinux"
  type_handler_version       = "1.0"
  auto_upgrade_minor_version = true
}

resource "azurerm_managed_disk" "data" {
  name                 = "cvent-pi-stg-data"
  location             = var.location
  resource_group_name  = data.azurerm_resource_group.staging.name
  storage_account_type = "Premium_LRS"
  create_option        = "Empty"
  disk_size_gb         = 256
  tags = merge(local.common_tags, {
    persistence = "profiles-state-evidence"
  })
}

resource "azurerm_virtual_machine_data_disk_attachment" "data" {
  managed_disk_id    = azurerm_managed_disk.data.id
  virtual_machine_id = azurerm_linux_virtual_machine.app.id
  lun                = 0
  caching            = "ReadWrite"
}

resource "azurerm_key_vault" "app" {
  name                          = "kvcventstg729"
  location                      = var.location
  resource_group_name           = data.azurerm_resource_group.staging.name
  tenant_id                     = var.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = false
  public_network_access_enabled = true
  soft_delete_retention_days    = 90
  purge_protection_enabled      = false
  tags                          = local.common_tags

  network_acls {
    bypass         = "AzureServices"
    default_action = "Deny"
  }

  access_policy {
    tenant_id = var.tenant_id
    object_id = var.key_vault_operator_object_id
    secret_permissions = [
      "Backup", "Delete", "Get", "List", "Recover", "Restore", "Set",
    ]
  }

  access_policy {
    tenant_id          = var.tenant_id
    object_id          = azurerm_linux_virtual_machine.app.identity[0].principal_id
    secret_permissions = ["Get", "List"]
  }
}

# Secret values are deliberately absent. Approved administrators populate the
# required names directly in Key Vault; Terraform must never own their values.

resource "azurerm_log_analytics_workspace" "app" {
  name                = "cvent-pi-stg-law"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.staging.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.common_tags
}

resource "azurerm_monitor_data_collection_rule" "app" {
  name                = "cvent-pi-stg-dcr"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.staging.name
  tags                = local.common_tags

  destinations {
    log_analytics {
      workspace_resource_id = azurerm_log_analytics_workspace.app.id
      name                  = "stagingLogs"
    }
  }

  data_flow {
    streams      = ["Microsoft-Syslog"]
    destinations = ["stagingLogs"]
  }

  data_flow {
    streams      = ["Microsoft-Perf"]
    destinations = ["stagingLogs"]
  }

  data_sources {
    syslog {
      facility_names = ["auth", "authpriv", "daemon", "syslog", "user"]
      log_levels     = ["Warning", "Error", "Critical", "Alert", "Emergency"]
      name           = "systemWarnings"
      streams        = ["Microsoft-Syslog"]
    }

    performance_counter {
      name                          = "hostPerformance"
      sampling_frequency_in_seconds = 60
      streams                       = ["Microsoft-Perf"]
      counter_specifiers = [
        "\\Processor Information(_Total)\\% Processor Time",
        "\\Memory\\Available MBytes",
        "\\Memory\\% Used Memory",
        "\\Logical Disk(*)\\% Used Space",
        "\\Logical Disk(*)\\Free Megabytes",
      ]
    }
  }
}

resource "azurerm_virtual_machine_extension" "monitor" {
  name                       = "AzureMonitorLinuxAgent"
  virtual_machine_id         = azurerm_linux_virtual_machine.app.id
  publisher                  = "Microsoft.Azure.Monitor"
  type                       = "AzureMonitorLinuxAgent"
  type_handler_version       = "1.0"
  automatic_upgrade_enabled  = true
  auto_upgrade_minor_version = true
}

resource "azurerm_monitor_data_collection_rule_association" "app" {
  name                    = "cvent-pi-stg-dcr-association"
  target_resource_id      = azurerm_linux_virtual_machine.app.id
  data_collection_rule_id = azurerm_monitor_data_collection_rule.app.id
  depends_on              = [azurerm_virtual_machine_extension.monitor]
}

resource "azurerm_monitor_metric_alert" "availability" {
  name                = "cvent-pi-stg-vm-unavailable"
  resource_group_name = data.azurerm_resource_group.staging.name
  scopes              = [azurerm_linux_virtual_machine.app.id]
  description         = "Staging CVENT VM availability below healthy."
  severity            = 1
  frequency           = "PT1M"
  window_size         = "PT5M"

  criteria {
    metric_namespace = "Microsoft.Compute/virtualMachines"
    metric_name      = "VmAvailabilityMetric"
    aggregation      = "Average"
    operator         = "LessThan"
    threshold        = 1
  }
}

resource "azurerm_monitor_metric_alert" "cpu" {
  name                = "cvent-pi-stg-high-cpu"
  resource_group_name = data.azurerm_resource_group.staging.name
  scopes              = [azurerm_linux_virtual_machine.app.id]
  description         = "Staging CVENT VM CPU above 90 percent."
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"

  criteria {
    metric_namespace = "Microsoft.Compute/virtualMachines"
    metric_name      = "Percentage CPU"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = 90
  }
}

resource "azurerm_storage_account" "state" {
  name                            = "cvstgtf82cf39cf49"
  resource_group_name             = data.azurerm_resource_group.staging.name
  location                        = var.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  account_kind                    = "StorageV2"
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false
  public_network_access_enabled   = true
  tags = merge(local.common_tags, {
    purpose = "terraform-state"
  })
}

resource "azurerm_storage_container" "state" {
  name                  = "tfstate"
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
}

resource "azurerm_recovery_services_vault" "app" {
  name                = "cvent-pi-stg-rsv"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.staging.name
  sku                 = "Standard"
  storage_mode_type   = "LocallyRedundant"
  tags                = local.common_tags
}

# The imported VM currently uses the vault's Azure-created DefaultPolicy.
# Keep protection enabled; do not recreate or replace it during import.
data "azurerm_backup_policy_vm" "default" {
  name                = "DefaultPolicy"
  recovery_vault_name = azurerm_recovery_services_vault.app.name
  resource_group_name = data.azurerm_resource_group.staging.name
}

resource "azurerm_backup_protected_vm" "app" {
  resource_group_name = data.azurerm_resource_group.staging.name
  recovery_vault_name = azurerm_recovery_services_vault.app.name
  source_vm_id        = azurerm_linux_virtual_machine.app.id
  backup_policy_id    = data.azurerm_backup_policy_vm.default.id
}
