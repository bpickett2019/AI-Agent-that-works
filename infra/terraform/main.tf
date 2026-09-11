data "azurerm_resource_group" "pilot" {
  name = var.resource_group_name
}

data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

resource "random_uuid" "user_role" {}
resource "random_uuid" "admin_role" {}
resource "random_password" "entra_client" {
  length  = 48
  special = true
}
resource "random_password" "session" {
  length  = 64
  special = false
}

locals {
  fqdn           = "${var.dns_label}.${var.location}.cloudapp.azure.com"
  key_vault_name = substr("cvagent${random_string.suffix.result}", 0, 24)
  common_tags = {
    application = "cvent-agent"
    environment = "pilot"
    managed-by  = "terraform"
  }
}

resource "azuread_application" "cvent" {
  display_name     = "Forge CVENT Agent Pilot"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azurerm_client_config.current.object_id]

  web {
    redirect_uris = ["https://${local.fqdn}/auth/callback"]
    logout_url    = "https://${local.fqdn}/"
  }

  app_role {
    allowed_member_types = ["User"]
    description          = "Use an isolated CVENT Agent workspace"
    display_name         = "CVENT Agent User"
    enabled              = true
    id                   = random_uuid.user_role.result
    value                = "Cvent.Agent.User"
  }

  app_role {
    allowed_member_types = ["User"]
    description          = "View all pilot jobs and leases"
    display_name         = "CVENT Agent Administrator"
    enabled              = true
    id                   = random_uuid.admin_role.result
    value                = "Cvent.Agent.Admin"
  }
}

resource "azuread_service_principal" "cvent" {
  client_id                    = azuread_application.cvent.client_id
  app_role_assignment_required = true
  owners                       = [data.azurerm_client_config.current.object_id]
}

resource "azuread_application_password" "cvent" {
  application_id = azuread_application.cvent.id
  display_name   = "terraform-production-v1"
  end_date       = timeadd(timestamp(), "4320h")
  lifecycle {
    ignore_changes = [end_date]
  }
}

resource "azuread_app_role_assignment" "users" {
  for_each            = var.entra_user_principal_object_ids
  app_role_id         = random_uuid.user_role.result
  principal_object_id = each.value
  resource_object_id  = azuread_service_principal.cvent.object_id
}

resource "azuread_app_role_assignment" "admins" {
  for_each            = var.entra_admin_principal_object_ids
  app_role_id         = random_uuid.admin_role.result
  principal_object_id = each.value
  resource_object_id  = azuread_service_principal.cvent.object_id
}

resource "azurerm_user_assigned_identity" "vm" {
  name                = "${var.name_prefix}-identity"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.pilot.name
  tags                = local.common_tags
}

resource "azurerm_key_vault" "app" {
  name                          = local.key_vault_name
  location                      = var.location
  resource_group_name           = data.azurerm_resource_group.pilot.name
  tenant_id                     = var.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  purge_protection_enabled      = true
  soft_delete_retention_days    = 30
  public_network_access_enabled = true
  tags                          = local.common_tags
}

resource "azurerm_role_assignment" "terraform_key_vault" {
  scope                = azurerm_key_vault.app.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "vm_key_vault" {
  scope                = azurerm_key_vault.app.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.vm.principal_id
}

resource "azurerm_key_vault_secret" "entra_client" {
  name         = "entra-client-secret"
  value        = azuread_application_password.cvent.value
  key_vault_id = azurerm_key_vault.app.id
  depends_on   = [azurerm_role_assignment.terraform_key_vault]
}

resource "azurerm_key_vault_secret" "session" {
  name         = "cvent-session-secret"
  value        = random_password.session.result
  key_vault_id = azurerm_key_vault.app.id
  depends_on   = [azurerm_role_assignment.terraform_key_vault]
}

resource "azurerm_virtual_network" "app" {
  name                = "${var.name_prefix}-vnet"
  address_space       = ["10.42.0.0/16"]
  location            = var.location
  resource_group_name = data.azurerm_resource_group.pilot.name
  tags                = local.common_tags
}

resource "azurerm_subnet" "app" {
  name                 = "application"
  resource_group_name  = data.azurerm_resource_group.pilot.name
  virtual_network_name = azurerm_virtual_network.app.name
  address_prefixes     = ["10.42.1.0/24"]
  service_endpoints    = ["Microsoft.KeyVault"]
}

resource "azurerm_subnet" "bastion" {
  name                 = "AzureBastionSubnet"
  resource_group_name  = data.azurerm_resource_group.pilot.name
  virtual_network_name = azurerm_virtual_network.app.name
  address_prefixes     = ["10.42.2.0/26"]
}

resource "azurerm_network_security_group" "app" {
  name                = "${var.name_prefix}-nsg"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.pilot.name
  tags                = local.common_tags

  security_rule {
    name                       = "https"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "Internet"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "ssh-from-bastion"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = "10.42.2.0/26"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "app" {
  subnet_id                 = azurerm_subnet.app.id
  network_security_group_id = azurerm_network_security_group.app.id
}

resource "azurerm_public_ip" "app" {
  name                = "${var.name_prefix}-pip"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.pilot.name
  allocation_method   = "Static"
  sku                 = "Standard"
  domain_name_label   = var.dns_label
  tags                = local.common_tags
}

resource "azurerm_network_interface" "app" {
  name                = "${var.name_prefix}-nic"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.pilot.name
  tags                = local.common_tags

  ip_configuration {
    name                          = "primary"
    subnet_id                     = azurerm_subnet.app.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.app.id
  }
}

resource "azurerm_public_ip" "bastion" {
  name                = "${var.name_prefix}-bastion-pip"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.pilot.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.common_tags
}

resource "azurerm_bastion_host" "app" {
  name                = "${var.name_prefix}-bastion"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.pilot.name
  sku                 = "Basic"
  tags                = local.common_tags

  ip_configuration {
    name                 = "configuration"
    subnet_id            = azurerm_subnet.bastion.id
    public_ip_address_id = azurerm_public_ip.bastion.id
  }
}

resource "azurerm_managed_disk" "data" {
  name                 = "${var.name_prefix}-data"
  location             = var.location
  resource_group_name  = data.azurerm_resource_group.pilot.name
  storage_account_type = "Premium_LRS"
  create_option        = "Empty"
  disk_size_gb         = 256
  tags                 = local.common_tags
}

resource "azurerm_linux_virtual_machine" "app" {
  name                            = "${var.name_prefix}-vm"
  location                        = var.location
  resource_group_name             = data.azurerm_resource_group.pilot.name
  size                            = var.vm_size
  admin_username                  = var.admin_username
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.app.id]
  secure_boot_enabled             = true
  vtpm_enabled                    = true
  patch_assessment_mode           = "AutomaticByPlatform"
  patch_mode                      = "AutomaticByPlatform"
  tags                            = local.common_tags

  admin_ssh_key {
    username   = var.admin_username
    public_key = var.admin_ssh_public_key
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.vm.id]
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
    disk_size_gb         = 64
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  custom_data = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
    repository_url        = var.repository_url
    repository_ref        = var.repository_ref
    fqdn                  = local.fqdn
    key_vault_url         = azurerm_key_vault.app.vault_uri
    managed_identity_id   = azurerm_user_assigned_identity.vm.client_id
    tenant_id             = var.tenant_id
    entra_client_id       = azuread_application.cvent.client_id
  }))

  depends_on = [
    azurerm_role_assignment.vm_key_vault,
    azurerm_key_vault_secret.entra_client,
    azurerm_key_vault_secret.session,
  ]
}

resource "azurerm_virtual_machine_data_disk_attachment" "app" {
  managed_disk_id    = azurerm_managed_disk.data.id
  virtual_machine_id = azurerm_linux_virtual_machine.app.id
  lun                = 0
  caching            = "ReadWrite"
}

resource "azurerm_recovery_services_vault" "app" {
  name                = "${var.name_prefix}-backup"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.pilot.name
  sku                 = "Standard"
  tags                = local.common_tags
}

resource "azurerm_backup_policy_vm" "daily" {
  name                = "${var.name_prefix}-daily"
  resource_group_name = data.azurerm_resource_group.pilot.name
  recovery_vault_name = azurerm_recovery_services_vault.app.name
  timezone            = "UTC"

  backup {
    frequency = "Daily"
    time      = "05:00"
  }

  retention_daily {
    count = 14
  }
}

resource "azurerm_backup_protected_vm" "app" {
  resource_group_name = data.azurerm_resource_group.pilot.name
  recovery_vault_name = azurerm_recovery_services_vault.app.name
  source_vm_id        = azurerm_linux_virtual_machine.app.id
  backup_policy_id    = azurerm_backup_policy_vm.daily.id
  depends_on          = [azurerm_virtual_machine_data_disk_attachment.app]
}

resource "azurerm_log_analytics_workspace" "app" {
  name                = "${var.name_prefix}-logs"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.pilot.name
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days
  tags                = local.common_tags
}

resource "azurerm_monitor_data_collection_rule" "app" {
  name                = "${var.name_prefix}-dcr"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.pilot.name
  tags                = local.common_tags

  destinations {
    log_analytics {
      workspace_resource_id = azurerm_log_analytics_workspace.app.id
      name                  = "logs"
    }
  }

  data_flow {
    streams      = ["Microsoft-Syslog"]
    destinations = ["logs"]
  }

  data_sources {
    syslog {
      facility_names = ["auth", "authpriv", "daemon", "syslog", "user"]
      log_levels     = ["Warning", "Error", "Critical", "Alert", "Emergency"]
      name           = "system"
      streams        = ["Microsoft-Syslog"]
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
  name                    = "${var.name_prefix}-dcr-association"
  target_resource_id      = azurerm_linux_virtual_machine.app.id
  data_collection_rule_id = azurerm_monitor_data_collection_rule.app.id
  depends_on              = [azurerm_virtual_machine_extension.monitor]
}

resource "azurerm_monitor_action_group" "operations" {
  name                = "${var.name_prefix}-operations"
  resource_group_name = data.azurerm_resource_group.pilot.name
  short_name          = "cventops"

  email_receiver {
    name          = "operations"
    email_address = var.alert_email
  }
}

resource "azurerm_monitor_metric_alert" "availability" {
  name                = "${var.name_prefix}-availability"
  resource_group_name = data.azurerm_resource_group.pilot.name
  scopes              = [azurerm_linux_virtual_machine.app.id]
  description         = "Alert when the pilot VM availability metric reports unavailable."
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

  action {
    action_group_id = azurerm_monitor_action_group.operations.id
  }
}
