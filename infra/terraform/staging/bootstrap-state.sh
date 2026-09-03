#!/usr/bin/env bash
set -euo pipefail

SUBSCRIPTION_ID=${SUBSCRIPTION_ID:-e7a6e33b-d0a8-4ab6-9aa0-114ac3ad9a88}
RESOURCE_GROUP=rg-chartdarts-stg
LOCATION=westus3
ACCOUNT=cvstgtf82cf39cf49
CONTAINER=tfstate
KEY=cvent-one-shot-staging.tfstate

az account set --subscription "$SUBSCRIPTION_ID"
test "$(az account show --query tenantId -o tsv)" = "661c8d9b-e19e-4330-b412-75dce2d26154"
az group show --name "$RESOURCE_GROUP" --query id -o tsv >/dev/null

if ! az storage account show --resource-group "$RESOURCE_GROUP" --name "$ACCOUNT" >/dev/null 2>&1; then
  az storage account create \
    --resource-group "$RESOURCE_GROUP" --name "$ACCOUNT" --location "$LOCATION" \
    --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 \
    --https-only true --allow-blob-public-access false \
    --allow-shared-key-access false --public-network-access Enabled >/dev/null
fi

if ! az storage container-rm show --resource-group "$RESOURCE_GROUP" \
  --storage-account "$ACCOUNT" --name "$CONTAINER" >/dev/null 2>&1; then
  az storage container-rm create --resource-group "$RESOURCE_GROUP" \
    --storage-account "$ACCOUNT" --name "$CONTAINER" >/dev/null
fi

if ! az storage blob list --account-name "$ACCOUNT" --container-name "$CONTAINER" \
  --auth-mode login --num-results 1 --query '[].name' -o tsv >/dev/null; then
  cat >&2 <<EOF
Azure AD data-plane access is missing. An administrator must assign
Storage Blob Data Contributor on:
/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$ACCOUNT
Do not enable shared-key fallback or add another Contributor assignment.
EOF
  exit 1
fi

terraform init \
  -backend-config="resource_group_name=$RESOURCE_GROUP" \
  -backend-config="storage_account_name=$ACCOUNT" \
  -backend-config="container_name=$CONTAINER" \
  -backend-config="key=$KEY" \
  -backend-config="use_azuread_auth=true"
