"""Per-job cross-process browser action gate and explicit human ownership state."""
from __future__ import annotations

import fcntl
import json
import os
import time
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CURRENT = Path(os.environ.get("CVENT_JOB_DIR", ROOT / "data" / "current"))
GATE = CURRENT / "browser-gate.json"
LOCK = CURRENT / "browser-gate.lock"
ACTORS = {"PI_EGO", "USER", "NONE"}
_ACTION_LOCK_FD = ContextVar("browser_action_lock_fd", default=None)


def child_lock_fds():
    """Keep the kernel action lock alive in a dispatched browser child."""
    fd = _ACTION_LOCK_FD.get()
    return () if fd is None else (fd,)


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
    def lock_file(self, timeout=None):
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        with self.lock.open("a+") as handle:
            deadline = None if timeout is None else time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | (fcntl.LOCK_NB if deadline is not None else 0))
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Browser action gate is occupied by a live helper or child")
                    time.sleep(0.025)
            try:
                yield handle.fileno()
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @contextmanager
    def action(self, runtime_id, actor, mutation_possible=False):
        if actor not in ACTORS or actor in ("USER", "NONE"):
            raise RuntimeError("Invalid automation actor")
        with self.lock_file(timeout=2) as fd:
            data = self.read()
            if data.get("ownership") != "AGENT" or data.get("desiredOwnership") != "AGENT":
                raise RuntimeError("Browser is not agent-owned; action paused")
            if data.get("activeActor") not in (None, "NONE"):
                if data.get("lockProtocol") != "inherited-flock-v1":
                    raise RuntimeError("Browser action gate is occupied; legacy helper requires operator review")
                # Acquiring this kernel lock proves the old helper AND every
                # dispatched child released their inherited descriptor. A PID
                # check alone would not prove that no mutation remains in flight.
                if data.get("mutationPossible"):
                    marker = self.job_dir / "browser-mutation-uncertain.json"
                    if not marker.exists():
                        temporary = marker.with_suffix(".tmp")
                        temporary.write_text(json.dumps({"at": now(), "error": "Mutating helper terminated before gate cleanup; readback required", "browserRuntimeId": data.get("browserRuntimeId")}))
                        temporary.chmod(0o600)
                        temporary.replace(marker)
                data["abandonedActionRecoveredAt"] = now()
            data.update({"activeActor": actor, "automationOwner": actor, "browserRuntimeId": runtime_id,
                         "activePid": os.getpid(), "lockProtocol": "inherited-flock-v1",
                         "mutationPossible": bool(mutation_possible)})
            self.write(data)
            token = _ACTION_LOCK_FD.set(fd)
            try:
                yield fd
            finally:
                _ACTION_LOCK_FD.reset(token)
                data = self.read()
                data.update({"activeActor": "NONE", "automationOwner": "PI_EGO", "activePid": None, "mutationPossible": False})
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
def action(runtime_id, actor, mutation_possible=False):
    with _default().action(runtime_id, actor, mutation_possible) as fd:
        yield fd
