# ChartDarts staging Terraform reconciliation

This root module is restricted by validation to `rg-chartdarts-stg` in
`westus3`. It does not create or modify an Entra application and it contains no
secret values. The production resource group is not referenced.

The resources were provisioned or reconciled with Azure CLI before this module
was added. **Do not apply this module to an empty state.** First obtain Azure AD
blob data access, initialize the remote backend, import every existing resource,
and review a saved plan. Reject any plan that replaces the VM, OS disk, data
disk, Key Vault, public IP, or backup protection.

Remote state:

- account: `cvstgtf82cf39cf49`
- container: `tfstate` (private)
- key: `cvent-one-shot-staging.tfstate`
- shared-key access: disabled

Run `./bootstrap-state.sh`. The current deployer has resource-group Contributor
but not Storage Blob Data Contributor; the script fails closed until that data
role is assigned on the state storage account.

## Existing-resource import

Set only non-secret values:

```bash
export TF_VAR_admin_ssh_public_key="$(cat ~/.ssh/id_ed25519.pub)"
export TF_VAR_ssh_source_cidr='<approved-single-ip>/32'
./bootstrap-state.sh
```

Then import the current resources. Use `az resource show` or `terraform import`
provider documentation to confirm each ID before importing. At minimum import:

- VNet, subnet, NSG and association
- public IP, NIC and Linux VM
- AAD SSH and Azure Monitor VM extensions
- Premium OS/data disks and data-disk attachment
- Key Vault (access-policy mode; no secret resources)
- Log Analytics workspace, DCR and association
- availability and CPU metric alerts
- Terraform state account/container
- Recovery Services vault and protected VM

After imports:

```bash
terraform fmt -check -recursive
terraform validate
terraform plan -out=staging.tfplan
terraform show staging.tfplan
```

Never apply until the plan is non-destructive and all drift from the earlier
CLI-created VM has been reconciled. The approved application artifact remains
immutable commit `1c5a1784b2207a4516c84c6f9184975a28284b5f`.

## Guest deployment boundary

VM guest deployment is release-based, not manual source editing. The VM keeps
immutable releases under `/opt/cvent-one-shot/releases/<commit>`, an atomic
`current` symlink, a `previous` rollback symlink, and
`/opt/cvent-one-shot/DEPLOYED_COMMIT`. Because the GitHub repository is private
and no deploy credential is stored on the VM, an approved operator transfers a
`git bundle` produced from the exact remote commit and runs
`/usr/local/sbin/deploy-cvent-one-shot <40-character-sha>`.

NinjaOne enrollment media and CrowdStrike packages/configuration remain IT
administered and are intentionally absent from Terraform and source. Required
application secret values are also absent; approved administrators populate
`anthropic-api-key`, `entra-client-secret`, and `cvent-session-secret` directly
in `kvcventstg729`.
