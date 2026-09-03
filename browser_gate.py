"""Per-job cross-process browser action gate and explicit human ownership state."""
from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CURRENT = Path(os.environ.get("CVENT_JOB_DIR", ROOT / "data" / "current"))
GATE = CURRENT / "browser-gate.json"
LOCK = CURRENT / "browser-gate.lock"
ACTORS = {"PI_EGO", "USER", "NONE"}


def now():
    return datetime.now(timezone.utc).isoformat()


class BrowserGate:
    def __init__(self, job_dir: Path):
        self.job_dir = Path(job_dir)
        self.gate = self.job_dir / "browser-gate.json"
        self.lock = self.job_dir / "browser-gate.lock"

    def read(self):
        try:
            data = json.loads(self.gate.read_text())
            if "piPaused" in data:
                data["agentPaused"] = data.pop("piPaused")
            if data.get("activeActor") == "CVENT_EGO":
                data["activeActor"] = "PI_EGO"
            data.setdefault("automationOwner", "PI_EGO")
            return data
        except Exception:
            return {
                "ownership": "AGENT", "desiredOwnership": "AGENT", "activeActor": "NONE",
                "automationOwner": "PI_EGO", "agentPaused": False, "updatedAt": now(),
            }

    def write(self, data):
        self.gate.parent.mkdir(parents=True, exist_ok=True)
        data["updatedAt"] = now()
        tmp = self.gate.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.gate)

    def initialize(self):
        data = {
            "ownership": "AGENT", "desiredOwnership": "AGENT", "activeActor": "NONE",
            "automationOwner": "PI_EGO", "agentPaused": False, "transition": None, "updatedAt": now(),
        }
        self.write(data)
        self.lock.touch()
        return data

    def request_user(self):
        data = self.read()
        data.update({"desiredOwnership": "USER", "transition": "WAITING_FOR_SAFE_BOUNDARY"})
        self.write(data)
        return data

    def shield_agent(self):
        data = self.read()
        data.update({"desiredOwnership": "AGENT", "transition": "VERIFYING_AFTER_USER"})
        self.write(data)
        return data

    @contextmanager
    def lock_file(self):
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        with self.lock.open("a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @contextmanager
    def action(self, runtime_id, actor):
        if actor not in ACTORS or actor in ("USER", "NONE"):
            raise RuntimeError("Invalid automation actor")
        with self.lock_file():
            data = self.read()
            if data.get("ownership") != "AGENT" or data.get("desiredOwnership") != "AGENT":
                raise RuntimeError("Browser is not agent-owned; action paused")
            if data.get("activeActor") not in (None, "NONE"):
                raise RuntimeError("Browser action gate is occupied")
            data.update({"activeActor": actor, "automationOwner": actor, "browserRuntimeId": runtime_id})
            self.write(data)
            try:
                yield
            finally:
                data = self.read()
                data.update({"activeActor": "NONE", "automationOwner": "PI_EGO"})
                self.write(data)


def _default() -> BrowserGate:
    # Resolve globals at call time so existing safety tests can use temporary files.
    gate = BrowserGate(GATE.parent)
    gate.gate = GATE
    gate.lock = LOCK
    return gate


def read():
    return _default().read()


def write(data):
    return _default().write(data)


def initialize():
    return _default().initialize()


def request_user():
    return _default().request_user()


def shield_agent():
    return _default().shield_agent()


@contextmanager
def lock_file():
    with _default().lock_file():
        yield


@contextmanager
def action(runtime_id, actor):
    with _default().action(runtime_id, actor):
        yield
