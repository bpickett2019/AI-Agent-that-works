#!/usr/bin/env python3
"""Load runtime secrets with the VM managed identity, then exec the app.

Secret values remain only in process memory/environment and are never printed or
written to disk. Production loads every required secret. The explicitly enabled
SSH-tunnel staging fallback loads only Anthropic so Entra/DNS cannot block a
controlled USER 1 acceptance run. Non-secret settings belong in systemd.
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


def selected_secrets() -> dict[str, str]:
    environment = os.environ.get("CVENT_ENV")
    if environment == "production":
        return SECRET_ENV_MAP
    if environment == "development" and os.environ.get("CVENT_STAGING_TUNNEL_FALLBACK") == "1":
        return {"anthropic-api-key": "ANTHROPIC_API_KEY"}
    raise RuntimeError("Key Vault runtime requires production or the explicit staging tunnel fallback")


def load(secret_map: dict[str, str]) -> None:
    vault_url = os.environ.get("CVENT_KEY_VAULT_URL")
    if not vault_url:
        raise RuntimeError("CVENT_KEY_VAULT_URL is required")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    credential = ManagedIdentityCredential(client_id=client_id) if client_id else ManagedIdentityCredential()
    client = SecretClient(vault_url=vault_url, credential=credential)
    for secret_name, environment_name in secret_map.items():
        value = client.get_secret(secret_name).value
        if not value:
            raise RuntimeError(f"Key Vault secret {secret_name!r} is empty")
        os.environ[environment_name] = value


def main() -> None:
    secret_map = selected_secrets()
    load(secret_map)
    command = sys.argv[1:] or [
        sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8877",
        "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1",
    ]
    if os.environ.get("CVENT_STAGING_TUNNEL_FALLBACK") == "1":
        try:
            host = command[command.index("--host") + 1]
        except (ValueError, IndexError) as exc:
            raise RuntimeError("Staging tunnel fallback must declare a loopback --host") from exc
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError("Staging tunnel fallback may only bind to loopback")
    os.execvpe(command[0], command, os.environ)


if __name__ == "__main__":
    main()
