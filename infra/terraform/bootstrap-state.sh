#!/usr/bin/env bash
set -euo pipefail

RESOURCE_GROUP=${RESOURCE_GROUP:-rg-cvent-agent-pilot}
LOCATION=${LOCATION:-eastus2}
SUBSCRIPTION_ID=${SUBSCRIPTION_ID:?Set SUBSCRIPTION_ID}
if command -v sha256sum >/dev/null; then
  SUFFIX=$(printf '%s' "$SUBSCRIPTION_ID" | sha256sum | cut -c1-10)
else
  SUFFIX=$(printf '%s' "$SUBSCRIPTION_ID" | shasum -a 256 | cut -c1-10)
fi
ACCOUNT=${TF_STATE_ACCOUNT:-cvagenttf${SUFFIX}}
CONTAINER=${TF_STATE_CONTAINER:-tfstate}

az account set --subscription "$SUBSCRIPTION_ID"
az group show --name "$RESOURCE_GROUP" >/dev/null
az storage account create \
  --name "$ACCOUNT" --resource-group "$RESOURCE_GROUP" --location "$LOCATION" \
  --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 \
  --allow-blob-public-access false --https-only true >/dev/null
az storage container create \
  --name "$CONTAINER" --account-name "$ACCOUNT" --auth-mode login >/dev/null

cat <<EOF
terraform init \\
  -backend-config="resource_group_name=$RESOURCE_GROUP" \\
  -backend-config="storage_account_name=$ACCOUNT" \\
  -backend-config="container_name=$CONTAINER" \\
  -backend-config="key=cvent-agent-production-v1.tfstate" \\
  -backend-config="use_azuread_auth=true"
EOF
