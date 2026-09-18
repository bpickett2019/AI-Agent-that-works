"""Authenticated, workspace-local Cvent event inventory and exact target resolution."""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from runtime_config import ROOT, AuthorizedEvent, workspace_dir

EVENT_KEY = re.compile(r"^[0-9a-f-]{20,80}$", re.I)
CACHE_MAX_AGE_SECONDS = int(os.environ.get("CVENT_EVENT_INVENTORY_TTL_SECONDS", "300"))


def cache_path(workspace_id: str) -> Path:
    return workspace_dir(workspace_id) / "event-inventory.json"


def _href_key(href: str) -> str | None:
    try:
        parsed = urlparse(href)
        if parsed.scheme != "https" or not (parsed.hostname == "cvent.com" or (parsed.hostname or "").endswith(".cvent.com")):
            return None
        values = [value.strip().lower() for name, items in parse_qs(parsed.query).items()
                  if name.lower() in {"evtstub", "eventid", "event"} for value in items]
        if values and values[0] and all(value == values[0] for value in values):
            return values[0]
        match = re.search(r"/events/([0-9a-f-]{20,80})", parsed.path, re.I)
        return match.group(1).lower() if match else None
    except (TypeError, ValueError):
        return None


def _validated(payload: object, workspace_id: str) -> tuple[AuthorizedEvent, ...]:
    if not isinstance(payload, dict) or payload.get("workspaceId") != workspace_id or payload.get("source") != "authenticated-cvent-inventory":
        raise RuntimeError("Event inventory is not bound to this authenticated workspace")
    raw = payload.get("events")
    if not isinstance(raw, list):
        raise RuntimeError("Authenticated event inventory is malformed")
    events: list[AuthorizedEvent] = []
    identities: set[str] = set()
    for value in raw:
        if not isinstance(value, dict):
            continue
        key = str(value.get("eventKey") or "").strip().lower()
        name = str(value.get("name") or "").strip()
        href_key = _href_key(str(value.get("href") or ""))
        if not name or not EVENT_KEY.fullmatch(key) or href_key != key:
            continue
        if key in identities:
            raise RuntimeError(f"EVENT_AMBIGUOUS: authenticated inventory repeats canonical event {key}")
        identities.add(key)
        events.append(AuthorizedEvent(event_id=key, event_key=key, name=name,
                                      event_code=str(value.get("code") or "").strip()))
    if not events:
        raise RuntimeError("No accessible Cvent events were found in authenticated inventory")
    return tuple(events)


def read_events(workspace_id: str) -> tuple[AuthorizedEvent, ...]:
    try:
        payload = json.loads(cache_path(workspace_id).read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise RuntimeError("Authenticated Cvent event inventory has not been established") from exc
    return _validated(payload, workspace_id)


def cache_is_fresh(workspace_id: str) -> bool:
    try:
        payload = json.loads(cache_path(workspace_id).read_text())
        captured = datetime.fromisoformat(str(payload["capturedAt"]).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - captured).total_seconds() <= CACHE_MAX_AGE_SECONDS
    except (FileNotFoundError, KeyError, ValueError, TypeError, json.JSONDecodeError, OSError):
        return False


def refresh_events(workspace_id: str) -> tuple[AuthorizedEvent, ...]:
    env = os.environ.copy()
    env["CVENT_WORKSPACE_ID"] = workspace_id
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "refresh_event_inventory.py")],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=210,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-2000:] or "Authenticated event inventory refresh failed")
    return read_events(workspace_id)


def events_for_workspace(workspace_id: str) -> tuple[AuthorizedEvent, ...]:
    if cache_is_fresh(workspace_id):
        return read_events(workspace_id)
    try:
        return refresh_events(workspace_id)
    except (RuntimeError, subprocess.TimeoutExpired):
        # A prior authenticated inventory remains usable for selection; every job
        # re-resolves it in live Cvent before any write. Never substitute config.
        return read_events(workspace_id)


def selectable_events(workspace_id: str) -> tuple[AuthorizedEvent, ...]:
    """Intake authorization is not proof of a live authenticated Cvent target.

    Preserve the original target -> upload -> browser -> login flow when an
    operator supplies the explicit allowlist. Jobs must still resolve the exact
    canonical event in the authenticated browser before any Cvent write.
    """
    raw = os.environ.get("CVENT_AUTHORIZED_EVENTS_JSON")
    encoded = os.environ.get("CVENT_AUTHORIZED_EVENTS_B64")
    if raw is None and encoded is None:
        return events_for_workspace(workspace_id)
    try:
        values = json.loads(raw if raw is not None else base64.b64decode(encoded, validate=True).decode("utf-8"))
        if not isinstance(values, list) or not values:
            raise ValueError("expected a non-empty event list")
        events = []
        seen = set()
        for value in values:
            key = str(uuid.UUID(value["event_key"]))
            event_id = str(uuid.UUID(value["event_id"]))
            name = value["name"]
            code = value.get("event_code", "")
            if event_id != key or key in seen or not isinstance(name, str) or not name.strip() or not isinstance(code, str):
                raise ValueError("ambiguous or invalid event identity")
            seen.add(key)
            events.append(AuthorizedEvent(key, name.strip(), key, code.strip()))
        return tuple(events)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise RuntimeError("Invalid server-authorized target list; require unique canonical event_id/event_key and exact name") from exc


def resolve_event(workspace_id: str, event_id: str) -> AuthorizedEvent:
    wanted = str(event_id or "").strip().lower()
    matches = [event for event in selectable_events(workspace_id) if event.event_id == wanted]
    if not matches:
        raise KeyError("EVENT_NOT_FOUND: selected event is absent from the authorized target list")
    if len(matches) != 1:
        raise KeyError("EVENT_AMBIGUOUS: selected event does not resolve uniquely")
    return matches[0]
