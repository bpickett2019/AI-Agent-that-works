#!/usr/bin/env python3
"""Load production secrets with the VM managed identity, then exec the app.

Secret values remain only in process memory/environment and are never printed or
written to disk. Non-secret deployment settings belong in systemd Environment=.
"""
from __future__ import annotations

import os
import sys

from azure.identity import ManagedIdentityCredential
from azure.keyvault.secrets import SecretClient

SECRET_ENV_MAP = {
    "anthropic-api-key": "ANTHROPIC_API_KEY",
    "entra-client-secret": "ENTRA_CLIENT_SECRET",
    "cvent-session-secret": "CVENT_SESSION_SECRET",
}


def load() -> None:
    vault_url = os.environ.get("CVENT_KEY_VAULT_URL")
    if not vault_url:
        raise RuntimeError("CVENT_KEY_VAULT_URL is required")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    credential = ManagedIdentityCredential(client_id=client_id) if client_id else ManagedIdentityCredential()
    client = SecretClient(vault_url=vault_url, credential=credential)
    for secret_name, environment_name in SECRET_ENV_MAP.items():
        value = client.get_secret(secret_name).value
        if not value:
            raise RuntimeError(f"Key Vault secret {secret_name!r} is empty")
        os.environ[environment_name] = value


def main() -> None:
    if os.environ.get("CVENT_ENV") != "production":
        raise RuntimeError("run_with_keyvault.py is production-only")
    load()
    command = sys.argv[1:] or [
        sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8877",
        "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1",
    ]
    os.execvpe(command[0], command, os.environ)


if __name__ == "__main__":
    main()
