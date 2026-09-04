# Azure staging USER 1 runbook

This is the controlled fallback for one approved tester while staging Entra/DNS
is unfinished. Forge, Steel, and CDP stay loopback-only. The operator establishes
the tunnel; the tester does not receive a VM shell.

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
- network egress to SSH port 22;
- the tester's current public IPv4 approved in the staging NSG;
- an operator-controlled SSH credential for the VM tunnel.

The operator runs and keeps open:

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 8877:127.0.0.1:8877 \
  piadmin@57.154.50.217
```

The tester opens `http://127.0.0.1:8877/?worker=1`. Never browse to the VM public
IP on port 8877. Do not forward ports 3005-3007 or 9334-9336.

## Tester workflow

1. Open Forge at the URL supplied by the operator.
2. Confirm the header says **RESTRICTED STAGING ACCESS** and select **USER 1**.
3. Enter/select the exact operator-authorized Draft/unpublished Cvent event.
4. Upload the approved `.xlsx` RR workbook.
5. Start the build.
6. If Forge says login is required, click **TAKE CONTROL**.
7. Complete Microsoft/Cvent SSO and MFA yourself. Never send credentials or MFA
   codes to the agent or operator.
8. Confirm the browser shows the expected authenticated Cvent account.
9. Click **SAVE LOGIN INFO**.
10. Click **RETURN TO AGENT**.
11. Monitor status. Stop immediately if Forge instructs you not to retry or the
    visible event/account is not the approved target.
12. A pass requires **BUILD COMPLETED · FINAL READBACK PASSED**. Opening the event
    is not completion.

The first operator acceptance build and zero-write idempotent rerun must pass
before this workflow is handed to the tester.
