# Azure staging USER 1 runbook

This is the controlled fallback for one approved tester while staging Entra is
unfinished. The temporary public path is protected by an Azure NSG source-IP
allowlist and Caddy Basic Auth. Forge, Steel, and CDP stay loopback-only. Entra
remains the required final authentication method.

## Administrator: add the Anthropic key without exposing it

Run in PowerShell with the Az modules installed. Confirm the signed-in account and
subscription before entering the secret. `Read-Host -AsSecureString` keeps the
value out of command arguments, shell history, console output, Git, Terraform,
and files.

```powershell
Connect-AzAccount -Tenant '661c8d9b-e19e-4330-b412-75dce2d26154'
Set-AzContext -Subscription 'e7a6e33b-d0a8-4ab6-9aa0-114ac3ad9a88'
$secret = Read-Host 'Paste approved Emerald Anthropic API key' -AsSecureString
Set-AzKeyVaultSecret -VaultName 'kvcventstg729' -Name 'anthropic-api-key' -SecretValue $secret |
  Select-Object VaultName, Name, Version, Enabled, Created, Updated
Remove-Variable secret
```

Do not pass the value to `az --value`, paste it into chat, or place it in an
environment file. Notify the staging operator only that population is complete.
The operator will perform exactly one provider probe.

## Operator: controlled access

Prerequisites on the tester machine:

- a modern browser;
- the tester's current public IPv4 explicitly approved for TCP 443 in the staging NSG;
- the temporary Basic Auth username and password delivered through an approved channel.

The tester opens `https://staging.app-chartsdarts-dashboard.com/?worker=1` and
enters the temporary Basic Auth credential. The page must visibly say
**RESTRICTED STAGING ACCESS**. Never browse to the VM public IP on port 8877.
Ports 3005-3007 and 9334-9336 must remain private.

The old SSH loopback tunnel is emergency/operator access only; it is not the
normal tester workflow and SSH remains restricted to the operator source IP.

## Tester workflow

1. Open Forge at the URL supplied by the operator.
2. Confirm the header says **RESTRICTED STAGING ACCESS** and select **USER 1**.
3. Enter/select the exact operator-authorized existing Cvent event. Inventory must prove its canonical identity and lifecycle. Draft, Active/Open, and Completed may proceed only when Cvent exposes the requested event-local controls as editable; Cancelled/Archived/unknown locked statuses fail closed. Never change lifecycle to proceed.
4. Upload the approved `.xlsx` RR workbook.
5. Start the build.
6. If Forge says login is required, click **TAKE CONTROL**.
7. Complete Microsoft/Cvent SSO and MFA yourself. Never send credentials or MFA
   codes to the agent or operator.
8. Confirm the browser shows the expected authenticated Cvent account.
9. Click **RETURN TO AGENT**. Forge performs a fresh read-only authentication
   check and persists only this USER slot's browser profile automatically.
10. Monitor status. Stop immediately if Forge instructs you not to retry or the
    visible event/account is not the approved target.
11. A pass requires **BUILD COMPLETED · FINAL READBACK PASSED**. Opening the event
    is not completion.

The first operator acceptance build and zero-write idempotent rerun must pass
before this workflow is handed to the tester.
