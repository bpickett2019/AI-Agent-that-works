"""Crash-safe local control plane for users, jobs, worker slots, and event leases.

SQLite is intentional for V1: all writers are on one VM, BEGIN IMMEDIATE provides a
host-wide serialization point, WAL makes reads non-blocking, and lease state
survives application and worker crashes.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from mutation_outcome import mutation_outcome

TERMINAL_STATES = {"completed", "review_required", "failed", "failed_prewrite", "failed_recoverable", "failed_uncertain", "cancelled"}
ACTIVE_STATES = {"starting", "running", "login_required", "stopping"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or utcnow()).isoformat()


class ControlStore:
    def __init__(self, path: Path, slots: int = 3, lease_seconds: int = 30):
        self.path = Path(path)
        self.slots = slots
        self.lease_seconds = lease_seconds
        self._init_lock = threading.Lock()
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    def initialize(self) -> None:
        with self._init_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    subject TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    owner_subject TEXT NOT NULL UNIQUE REFERENCES users(subject),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                    owner_subject TEXT NOT NULL REFERENCES users(subject),
                    event_id TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    event_key TEXT NOT NULL,
                    event_code TEXT NOT NULL DEFAULT '',
                    original_filename TEXT NOT NULL,
                    state TEXT NOT NULL,
                    preferred_slot INTEGER,
                    slot_id INTEGER,
                    pid INTEGER,
                    lease_token TEXT,
                    queued_at TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    heartbeat_at TEXT,
                    error TEXT,
                    uncertain INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_owner_created ON jobs(owner_subject, created_at DESC);
                CREATE INDEX IF NOT EXISTS jobs_state_created ON jobs(state, created_at);
                CREATE TABLE IF NOT EXISTS event_leases (
                    event_id TEXT PRIMARY KEY,
                    holder_job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id),
                    token TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS worker_leases (
                    slot_id INTEGER PRIMARY KEY,
                    holder_job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id),
                    token TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT NOT NULL,
                    actor_subject TEXT NOT NULL,
                    action TEXT NOT NULL,
                    job_id TEXT,
                    details_json TEXT NOT NULL
                );
                """)
                columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
                if "preferred_slot" not in columns:
                    conn.execute("ALTER TABLE jobs ADD COLUMN preferred_slot INTEGER")
                if "event_code" not in columns:
                    conn.execute("ALTER TABLE jobs ADD COLUMN event_code TEXT NOT NULL DEFAULT ''")

    @contextmanager
    def immediate(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @staticmethod
    def row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    def ensure_user(self, subject: str, email: str, display_name: str, is_admin: bool) -> dict[str, Any]:
        now = iso()
        workspace_id = "ws_" + uuid.uuid5(uuid.NAMESPACE_URL, "cvent:" + subject).hex
        with self.immediate() as conn:
            conn.execute(
                """INSERT INTO users(subject,email,display_name,is_admin,created_at,last_seen_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(subject) DO UPDATE SET
                email=excluded.email, display_name=excluded.display_name,
                is_admin=excluded.is_admin, last_seen_at=excluded.last_seen_at""",
                (subject, email, display_name, int(is_admin), now, now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO workspaces(id,owner_subject,created_at) VALUES(?,?,?)",
                (workspace_id, subject, now),
            )
            return dict(conn.execute(
                "SELECT u.*,w.id AS workspace_id FROM users u JOIN workspaces w ON w.owner_subject=u.subject WHERE u.subject=?",
                (subject,),
            ).fetchone())

    def create_job(self, owner: dict[str, Any], event: Any, filename: str, preferred_slot: int | None = None) -> dict[str, Any]:
        if preferred_slot is not None and preferred_slot not in range(1, self.slots + 1):
            raise ValueError("Preferred worker slot is invalid")
        now = iso()
        job_id = "job_" + uuid.uuid4().hex
        with self.immediate() as conn:
            conn.execute(
                """INSERT INTO jobs(id,workspace_id,owner_subject,event_id,event_name,event_key,event_code,
                original_filename,state,preferred_slot,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id, owner["workspace_id"], owner["subject"], event.event_id, event.name,
                 event.event_key, getattr(event, "event_code", ""), filename, "draft", preferred_slot, now, now),
            )
            self._audit(conn, owner["subject"], "job.created", job_id, {"event_id": event.event_id})
            return dict(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return self.row(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def latest_job(self, owner_subject: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return self.row(conn.execute(
                "SELECT * FROM jobs WHERE owner_subject=? ORDER BY created_at DESC LIMIT 1", (owner_subject,)
            ).fetchone())

    def list_jobs(self, owner_subject: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if owner_subject:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE owner_subject=? ORDER BY created_at DESC LIMIT ?",
                    (owner_subject, limit),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [dict(row) for row in rows]

    def _reservation_details(self, conn: sqlite3.Connection, lease: sqlite3.Row) -> dict[str, Any]:
        """Explain a reservation without treating UI/process state as release authority."""
        holder = conn.execute("SELECT * FROM jobs WHERE id=?", (lease["holder_job_id"],)).fetchone()
        state = holder["state"] if holder else "unknown"
        phase = {"starting": "starting browser/agent", "running": "agent running",
                 "login_required": "waiting for Cvent sign-in", "stopping": "stopping safely"}.get(state, "reservation awaiting reconciliation")
        # During a handoff Pi keeps its live lease while state.json/browser-gate
        # record USER ownership; the database can still say running.
        if holder and state in {"running", "login_required"}:
            directory = self.path.parent / "workspaces" / holder["workspace_id"] / "jobs" / holder["id"]
            try:
                gate = json.loads((directory / "browser-gate.json").read_text())
                progress = json.loads((directory / "state.json").read_text())
                if gate.get("ownership") == "USER":
                    phase = "waiting for Cvent sign-in" if progress.get("status") == "login_required" else "waiting for browser control"
            except (OSError, ValueError, AttributeError):
                pass
        return {"job_id": lease["holder_job_id"], "slot_id": lease["slot_id"],
                "job_state": state, "phase": phase, "pid": holder["pid"] if holder else None,
                "heartbeat_at": lease["heartbeat_at"], "expires_at": lease["expires_at"]}

    @staticmethod
    def _reservation_message(blockers: list[dict[str, Any]], event: bool = False) -> str:
        # Deliberately avoid the legacy friendlyError trigger phrases. The
        # existing UI otherwise rewrites every selected slot into "USER 1".
        if len(blockers) == 1:
            item = blockers[0]
            slot = item["slot_id"]
            location = f"worker slot {slot}" if slot is not None else "another worker"
            subject = f"This event is reserved on {location}" if event else f"Worker slot {slot} is reserved"
            return f"{subject}: {item['phase']}. Resume the existing run or ask its operator to stop it safely. This new run was not started or queued."
        summary = "; ".join(f"{item['slot_id']}: {item['phase']}" for item in blockers)
        return f"No worker slots are free ({summary}). Resume an existing run or ask its operator to stop it safely. This new run was not started or queued."

    def reserve_now(self, job_id: str, actor: str) -> dict[str, Any]:
        """Immediately acquire a worker and event lease or reject without waiting.

        A rejected job stays in its safely restartable prior state. Event
        contention is checked before worker capacity so callers receive the
        most specific 409 reason. No externally visible queued state exists.
        """
        now_dt = utcnow()
        now = iso(now_dt)
        expires = iso(now_dt + timedelta(seconds=self.lease_seconds))
        result: dict[str, Any]
        with self.immediate() as conn:
            self._expire_stale(conn, now)
            job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            startable = {"draft", "login_required", "review_required", "failed", "failed_prewrite", "failed_recoverable", "cancelled"}
            if not job or job["state"] not in startable:
                result = {"error": "Job cannot be started from its current state"}
            elif event_lease := conn.execute(
                """SELECT e.*,w.slot_id FROM event_leases e LEFT JOIN worker_leases w
                   ON w.holder_job_id=e.holder_job_id AND w.token=e.token WHERE e.event_id=?""",
                (job["event_id"],),
            ).fetchone():
                blockers = [self._reservation_details(conn, event_lease)]
                result = {"error": self._reservation_message(blockers, event=True)}
                self._audit(conn, actor, "job.start_rejected", job_id,
                            {"reason": "event_busy", "requested_slot": job["preferred_slot"], "blockers": blockers})
            else:
                occupied = {row["slot_id"]: row for row in conn.execute("SELECT * FROM worker_leases")}
                preferred = job["preferred_slot"]
                slot_id = preferred if preferred in range(1, self.slots + 1) and preferred not in occupied else (
                    next((slot for slot in range(1, self.slots + 1) if slot not in occupied), None)
                    if preferred is None else None
                )
                if slot_id is None:
                    blockers = [self._reservation_details(conn, occupied[slot])
                                for slot in sorted(occupied) if preferred is None or slot == preferred]
                    message = self._reservation_message(blockers) if blockers else "Requested worker slot is invalid; choose an available configured slot."
                    result = {"error": message}
                    self._audit(conn, actor, "job.start_rejected", job_id,
                                {"reason": "worker_busy", "requested_slot": preferred, "blockers": blockers})
                else:
                    token = uuid.uuid4().hex
                    values = (job_id, token, now, now, expires)
                    conn.execute(
                        "INSERT INTO event_leases(event_id,holder_job_id,token,acquired_at,heartbeat_at,expires_at) VALUES(?,?,?,?,?,?)",
                        (job["event_id"], *values),
                    )
                    conn.execute(
                        "INSERT INTO worker_leases(slot_id,holder_job_id,token,acquired_at,heartbeat_at,expires_at) VALUES(?,?,?,?,?,?)",
                        (slot_id, *values),
                    )
                    conn.execute(
                        """UPDATE jobs SET state='starting',slot_id=?,lease_token=?,queued_at=NULL,
                        started_at=COALESCE(started_at,?),finished_at=NULL,heartbeat_at=?,error=NULL,
                        uncertain=0,updated_at=? WHERE id=?""",
                        (slot_id, token, now, now, now, job_id),
                    )
                    self._audit(conn, actor, "job.started", job_id, {"slot_id": slot_id, "event_id": job["event_id"]})
                    self._audit(conn, "system", "leases.acquired", job_id, {"slot_id": slot_id, "event_id": job["event_id"]})
                    result = {"slot_id": slot_id, "token": token, "event_id": job["event_id"], "expires_at": expires}
        if result.get("error"):
            raise ValueError(str(result["error"]))
        return result

    def heartbeat(self, job_id: str, token: str) -> bool:
        now_dt = utcnow()
        now = iso(now_dt)
        expires = iso(now_dt + timedelta(seconds=self.lease_seconds))
        with self.immediate() as conn:
            event_count = conn.execute(
                "UPDATE event_leases SET heartbeat_at=?,expires_at=? WHERE holder_job_id=? AND token=?",
                (now, expires, job_id, token),
            ).rowcount
            slot_count = conn.execute(
                "UPDATE worker_leases SET heartbeat_at=?,expires_at=? WHERE holder_job_id=? AND token=?",
                (now, expires, job_id, token),
            ).rowcount
            if event_count == 1 and slot_count == 1:
                conn.execute("UPDATE jobs SET heartbeat_at=?,updated_at=? WHERE id=?", (now, now, job_id))
                return True
            return False

    def valid_event_lease(self, job_id: str, token: str, event_id: str) -> bool:
        with self.connect() as conn:
            return bool(conn.execute(
                """SELECT 1 FROM event_leases WHERE holder_job_id=? AND token=? AND event_id=? AND expires_at>?""",
                (job_id, token, event_id, iso()),
            ).fetchone())

    def mark_running(self, job_id: str, token: str, pid: int) -> bool:
        now = iso()
        with self.immediate() as conn:
            if not conn.execute(
                "SELECT 1 FROM worker_leases WHERE holder_job_id=? AND token=?", (job_id, token)
            ).fetchone():
                return False
            conn.execute(
                "UPDATE jobs SET state='running',pid=?,heartbeat_at=?,updated_at=? WHERE id=?",
                (pid, now, now, job_id),
            )
            return True

    def finish(self, job_id: str, token: str | None, state: str, error: str | None = None,
               uncertain: bool = False, actor: str = "system") -> None:
        if state not in TERMINAL_STATES and state != "login_required":
            raise ValueError("Invalid finish state")
        now = iso()
        with self.immediate() as conn:
            if token:
                event_owned = conn.execute(
                    "SELECT 1 FROM event_leases WHERE holder_job_id=? AND token=?", (job_id, token)
                ).fetchone()
                worker_owned = conn.execute(
                    "SELECT 1 FROM worker_leases WHERE holder_job_id=? AND token=?", (job_id, token)
                ).fetchone()
                if not event_owned or not worker_owned:
                    raise PermissionError("Lease token does not own this job's resources")
                conn.execute("DELETE FROM event_leases WHERE holder_job_id=? AND token=?", (job_id, token))
                conn.execute("DELETE FROM worker_leases WHERE holder_job_id=? AND token=?", (job_id, token))
            else:
                conn.execute("DELETE FROM event_leases WHERE holder_job_id=?", (job_id,))
                conn.execute("DELETE FROM worker_leases WHERE holder_job_id=?", (job_id,))
            conn.execute(
                """UPDATE jobs SET state=?,pid=NULL,slot_id=NULL,lease_token=NULL,finished_at=?,
                error=?,uncertain=?,updated_at=? WHERE id=?""",
                (state, now, error, int(uncertain), now, job_id),
            )
            self._audit(conn, actor, "job.finished", job_id, {"state": state, "uncertain": uncertain, "error": error})

    def cancel_legacy_queued_jobs(self) -> list[str]:
        """Make pre-upgrade queued jobs safely restartable; never auto-run them."""
        now = iso()
        with self.immediate() as conn:
            rows = conn.execute("SELECT id FROM jobs WHERE state='queued' ORDER BY queued_at,created_at").fetchall()
            for row in rows:
                conn.execute(
                    """UPDATE jobs SET state='cancelled',slot_id=NULL,pid=NULL,lease_token=NULL,
                    finished_at=?,error=?,uncertain=0,updated_at=? WHERE id=?""",
                    (now, "Waiting queue was removed; start this job again explicitly", now, row["id"]),
                )
                self._audit(conn, "system", "job.legacy_queue_cancelled", row["id"], {})
            return [row["id"] for row in rows]

    def recover_after_controller_restart(self) -> list[str]:
        """Classify interrupted jobs from durable write-attempt evidence; never auto-retry."""
        now = iso()
        recovered: list[str] = []
        with self.immediate() as conn:
            rows = conn.execute(
                "SELECT id,workspace_id FROM jobs WHERE state IN ('starting','running','stopping')"
            ).fetchall()
            recovered = [row["id"] for row in rows]
            for row in rows:
                outcome = self._mutation_outcome(row["workspace_id"], row["id"])
                state = "failed_uncertain" if outcome["unresolved"] else ("failed_recoverable" if outcome["hasAttempts"] else "failed_prewrite")
                error = (
                    "Controller restarted with an unresolved Cvent write attempt; mutation outcome requires review"
                    if outcome["unresolved"] else ("Controller restarted after conclusively read-back writes; recompute remaining delta"
                                                   if outcome["hasAttempts"] else "Controller restarted before any Cvent write attempt; fresh preflight required")
                )
                conn.execute(
                    """UPDATE jobs SET state=?,uncertain=?,pid=NULL,slot_id=NULL,lease_token=NULL,
                    finished_at=?,error=?,updated_at=? WHERE id=?""",
                    (state, int(outcome["unresolved"]), now, error, now, row["id"]),
                )
                action = "job.recovered_uncertain" if outcome["unresolved"] else ("job.recovered_verified_writes" if outcome["hasAttempts"] else "job.recovered_prewrite")
                self._audit(conn, "system", action, row["id"], outcome)
            conn.execute("DELETE FROM event_leases")
            conn.execute("DELETE FROM worker_leases")
        return recovered

    def active_leases(self) -> dict[str, list[dict[str, Any]]]:
        with self.connect() as conn:
            return {
                "events": [dict(row) for row in conn.execute("SELECT * FROM event_leases ORDER BY event_id")],
                "workers": [dict(row) for row in conn.execute("SELECT * FROM worker_leases ORDER BY slot_id")],
            }

    def audit(self, actor: str, action: str, job_id: str | None, details: dict[str, Any]) -> None:
        with self.immediate() as conn:
            self._audit(conn, actor, action, job_id, details)

    @staticmethod
    def _audit(conn: sqlite3.Connection, actor: str, action: str, job_id: str | None,
               details: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO audit_log(at,actor_subject,action,job_id,details_json) VALUES(?,?,?,?,?)",
            (iso(), actor, action, job_id, json.dumps(details, separators=(",", ":"))),
        )

    def _mutation_outcome(self, workspace_id: str, job_id: str) -> dict[str, Any]:
        directory = self.path.parent / "workspaces" / workspace_id / "jobs" / job_id
        return mutation_outcome(directory)

    def _mutation_attempted(self, workspace_id: str, job_id: str) -> bool:
        return self._mutation_outcome(workspace_id, job_id)["hasAttempts"]

    def _expire_stale(self, conn: sqlite3.Connection, now: str) -> None:
        stale = conn.execute(
            """SELECT DISTINCT j.id,j.workspace_id FROM jobs j JOIN (
            SELECT holder_job_id FROM event_leases WHERE expires_at<=?
            UNION SELECT holder_job_id FROM worker_leases WHERE expires_at<=?
            ) stale ON stale.holder_job_id=j.id""",
            (now, now),
        ).fetchall()
        for row in stale:
            outcome = self._mutation_outcome(row["workspace_id"], row["id"])
            state = "failed_uncertain" if outcome["unresolved"] else ("failed_recoverable" if outcome["hasAttempts"] else "failed_prewrite")
            error = (
                "Worker lease heartbeat expired with an unresolved Cvent write attempt; mutation outcome requires review"
                if outcome["unresolved"] else ("Worker stopped after conclusively read-back writes; recompute remaining delta"
                                               if outcome["hasAttempts"] else "Worker lease heartbeat expired before any Cvent write attempt; fresh preflight required")
            )
            conn.execute(
                """UPDATE jobs SET state=?,uncertain=?,pid=NULL,slot_id=NULL,lease_token=NULL,
                finished_at=?,error=?,updated_at=? WHERE id=? AND state IN ('starting','running','stopping')""",
                (state, int(outcome["unresolved"]), now, error, now, row["id"]),
            )
        conn.execute("DELETE FROM event_leases WHERE expires_at<=?", (now,))
        conn.execute("DELETE FROM worker_leases WHERE expires_at<=?", (now,))
