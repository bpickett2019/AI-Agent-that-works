"""Explicit local-only Codex OAuth configuration; never copy credentials into jobs."""
from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path


def require_local_codex() -> None:
    if (
        os.environ.get("CVENT_ENV") != "development"
        or os.environ.get("CVENT_LOCAL_CODEX") != "1"
        or os.environ.get("CVENT_EXECUTION_MODE") != "simple"
        or os.environ.get("CVENT_DEPLOYMENT_SCOPE")
        or os.environ.get("CVENT_STAGING_RESTRICTED_ACCESS") == "1"
    ):
        raise RuntimeError("Codex subscription requires explicit local development Simple Mode; never staging/production")


def codex_environment(directory: Path) -> dict[str, str]:
    require_local_codex()
    directory = directory.resolve()
    auth = Path(os.environ.get("CVENT_PI_AUTH_FILE", str(Path.home() / ".pi/agent/auth.json"))).expanduser().resolve()
    try:
        info = auth.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise RuntimeError("Local Pi auth file must be owned by the current user and private (0600)")
        credential = json.loads(auth.read_text()).get("openai-codex", {})
        if credential.get("type") != "oauth" or not credential.get("refresh") or not credential.get("access"):
            raise ValueError("missing OAuth")
    except (OSError, ValueError, AttributeError) as exc:
        raise RuntimeError("Local ChatGPT/Codex login unavailable; authenticate with pi /login") from exc
    executable = shutil.which("pi")
    if not executable:
        raise RuntimeError("Local Pi executable is unavailable")
    sdk = None
    for parent in Path(executable).resolve().parents:
        package = parent / "package.json"
        if package.is_file() and json.loads(package.read_text()).get("name") == "@earendil-works/pi-coding-agent":
            # Match the installed CLI's SDK build (bundled builds can have newer providers).
            sdk = Path(executable).resolve().parent / "index.js"
            if not sdk.is_file():
                sdk = parent / "dist/index.js"
            break
    if not sdk or not sdk.is_file():
        raise RuntimeError("Installed Pi SDK entry is unavailable")
    return {
        "CVENT_ENV": "development", "CVENT_LOCAL_CODEX": "1", "CVENT_EXECUTION_MODE": "simple",
        "CVENT_PI_PROVIDER": "openai-codex", "CVENT_PI_MODEL": "gpt-6-astra",
        "CVENT_PI_AUTH_FILE": str(auth), "CVENT_PI_SDK_ENTRY": str(sdk),
        "PI_CODING_AGENT_DIR": str(directory / "pi-config"),
        "PI_CODING_AGENT_SESSION_DIR": str(directory / "pi-sessions"),
        "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0",
    }
