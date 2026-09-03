output "resource_group" {
  value = data.azurerm_resource_group.staging.name
}

output "vm" {
  value = {
    id                  = azurerm_linux_virtual_machine.app.id
    name                = azurerm_linux_virtual_machine.app.name
    size                = azurerm_linux_virtual_machine.app.size
    system_principal_id = azurerm_linux_virtual_machine.app.identity[0].principal_id
    private_ip_address  = azurerm_network_interface.app.private_ip_address
    public_ip_address   = azurerm_public_ip.app.ip_address
  }
}

output "persistent_data_disk_id" {
  value = azurerm_managed_disk.data.id
}

output "key_vault_uri" {
  value = azurerm_key_vault.app.vault_uri
}

output "log_analytics_workspace_id" {
  value = azurerm_log_analytics_workspace.app.id
}

output "terraform_backend" {
  value = {
    storage_account = azurerm_storage_account.state.name
    container       = azurerm_storage_container.state.name
    key             = "cvent-one-shot-staging.tfstate"
  }
}

output "deployed_commit" {
  value = var.deployed_commit
}
