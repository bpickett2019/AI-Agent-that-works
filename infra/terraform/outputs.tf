output "application_url" {
  value = "https://${local.fqdn}"
}

output "entra_client_id" {
  value = azuread_application.cvent.client_id
}

output "key_vault_name" {
  value = azurerm_key_vault.app.name
}

output "managed_identity_client_id" {
  value = azurerm_user_assigned_identity.vm.client_id
}

output "vm_name" {
  value = azurerm_linux_virtual_machine.app.name
}

output "anthropic_secret_command" {
  description = "Run from a secure shell with the key in ANTHROPIC_API_KEY; never place it in tfvars or shell history."
  value       = "read -s ANTHROPIC_API_KEY && az keyvault secret set --vault-name ${azurerm_key_vault.app.name} --name anthropic-api-key --value \"\u0024ANTHROPIC_API_KEY\" >/dev/null && unset ANTHROPIC_API_KEY"
}
