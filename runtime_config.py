"""Validated runtime configuration for the three-worker single-VM deployment."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get("CVENT_DATA_ROOT", ROOT / "data")).resolve()
DEFAULT_EVENT_NAME = "(C+D) Medtrade Testing Clone 2"
DEFAULT_EVENT_KEY = "e712e34c-6117-4d13-bf4c-8ed54cf2b495"
STEEL_IMAGE = os.environ.get(
    "CVENT_STEEL_IMAGE",
    "ghcr.io/steel-dev/steel-browser@sha256:21cf2a5785aa9478d0f7933c04bce96ca79f3d7a93d9824ea184800d29d3cd02",
)


@dataclass(frozen=True)
class AuthorizedEvent:
    event_id: str
    name: str
    event_key: str
    event_code: str = ""


@dataclass(frozen=True)
class WorkerSlot:
    slot_id: int
    api_port: int
    cdp_port: int

    @property
    def container_name(self) -> str:
        return f"cvent-agent-steel-{self.slot_id}"

    @property
    def api_origin(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    @property
    def cdp_origin(self) -> str:
        return f"http://127.0.0.1:{self.cdp_port}"


WORKER_SLOTS = tuple(WorkerSlot(i, 3004 + i, 9333 + i) for i in range(1, 4))


def _safe_component(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", value):
        raise ValueError("Unsafe filesystem identifier")
    return value


def subject_key(subject: str) -> str:
    """Pseudonymous stable directory key; raw Entra object IDs never become paths."""
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()[:32]


def workspace_dir(workspace_id: str) -> Path:
    return DATA_ROOT / "workspaces" / _safe_component(workspace_id)


def job_dir(workspace_id: str, job_id: str) -> Path:
    return workspace_dir(workspace_id) / "jobs" / _safe_component(job_id)


def browser_profile_dir(workspace_id: str, slot_id: int) -> Path:
    """One persistent, non-shared Chromium profile per user workspace and worker slot."""
    slot = slot_by_id(slot_id)
    return workspace_dir(workspace_id) / "browser-profiles" / f"slot-{slot.slot_id}" / "chromium-profile"


def browser_cache_dir(workspace_id: str, slot_id: int) -> Path:
    slot = slot_by_id(slot_id)
    return workspace_dir(workspace_id) / "browser-profiles" / f"slot-{slot.slot_id}" / "steel-cache"


def slot_by_id(slot_id: int) -> WorkerSlot:
    try:
        return next(slot for slot in WORKER_SLOTS if slot.slot_id == slot_id)
    except StopIteration as exc:
        raise ValueError(f"Unknown worker slot {slot_id}") from exc


def authorized_events() -> tuple[AuthorizedEvent, ...]:
    raw = os.environ.get("CVENT_AUTHORIZED_EVENTS_JSON")
    encoded = os.environ.get("CVENT_AUTHORIZED_EVENTS_B64")
    if not raw and encoded:
        raw = base64.b64decode(encoded).decode("utf-8")
    values = json.loads(raw) if raw else [{
        "event_id": DEFAULT_EVENT_KEY,
        "name": DEFAULT_EVENT_NAME,
        "event_key": DEFAULT_EVENT_KEY,
        "event_code": "",
    }]
    if not isinstance(values, list) or not values:
        raise RuntimeError("CVENT_AUTHORIZED_EVENTS_JSON must be a non-empty JSON list")
    events: list[AuthorizedEvent] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            raise RuntimeError("Every authorized event must be an object")
        event = AuthorizedEvent(
            event_id=str(value.get("event_id", "")).strip().lower(),
            name=str(value.get("name", "")).strip(),
            event_key=str(value.get("event_key", "")).strip().lower(),
            event_code=str(value.get("event_code", "")).strip(),
        )
        if not event.event_id or not event.event_key or not event.name:
            raise RuntimeError("Authorized events require event_id, event_key, and name")
        if event.event_id != event.event_key:
            raise RuntimeError("event_id must be the canonical Cvent event_key")
        if event.event_id in seen:
            raise RuntimeError(f"Duplicate authorized event ID: {event.event_id}")
        seen.add(event.event_id)
        events.append(event)
    return tuple(events)


def event_by_id(event_id: str) -> AuthorizedEvent:
    match = next((event for event in authorized_events() if event.event_id == event_id.lower()), None)
    if not match:
        raise KeyError("Event is not in the server-side authorization allowlist")
    return match


def pi_provider() -> str:
    provider = os.environ.get("CVENT_PI_PROVIDER", "anthropic")
    if provider != "anthropic":
        raise RuntimeError("CVENT_PI_PROVIDER must be anthropic")
    return provider


def pi_model() -> str:
    model = os.environ.get("CVENT_PI_MODEL", "claude-sonnet-4-6")
    if model not in {"claude-sonnet-4-6", "anthropic/claude-sonnet-4-6"}:
        raise RuntimeError("CVENT_PI_MODEL must be claude-sonnet-4-6")
    return model.split("/", 1)[-1]


def validate_production_environment() -> None:
    if os.environ.get("CVENT_ENV", "development") != "production":
        return
    required = (
        "ANTHROPIC_API_KEY",
        "ENTRA_TENANT_ID",
        "ENTRA_CLIENT_ID",
        "ENTRA_CLIENT_SECRET",
        "CVENT_SESSION_SECRET",
    )
    missing = [name for name in required if not os.environ.get(name)]
    if not os.environ.get("CVENT_AUTHORIZED_EVENTS_JSON") and not os.environ.get("CVENT_AUTHORIZED_EVENTS_B64"):
        missing.append("CVENT_AUTHORIZED_EVENTS_JSON or CVENT_AUTHORIZED_EVENTS_B64")
    if missing:
        raise RuntimeError("Missing production environment variables: " + ", ".join(missing))
    if len(os.environ["CVENT_SESSION_SECRET"]) < 32:
        raise RuntimeError("CVENT_SESSION_SECRET must contain at least 32 characters")
    pi_provider()
    pi_model()
    authorized_events()
