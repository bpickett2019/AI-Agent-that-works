#!/usr/bin/env python3
"""Non-Cvent empirical acceptance for V1 scheduling, leases, and recovery."""
from __future__ import annotations

import concurrent.futures
import json
import platform
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_store import ControlStore
import browser_tool


def timed_acquire(store, job_id):
    started = time.perf_counter()
    lease = store.acquire(job_id)
    return {"acquired": bool(lease), "slot": lease["slot_id"] if lease else None,
            "milliseconds": round((time.perf_counter() - started) * 1000, 3), "lease": lease}


def create(store, user, event_id):
    event = SimpleNamespace(event_id=event_id, event_key=event_id, name=f"Authorized {event_id}")
    job = store.create_job(user, event, "acceptance.xlsx")
    store.queue_job(job["id"], user["subject"])
    return job


def main():
    with tempfile.TemporaryDirectory(prefix="cvent-control-acceptance-") as temp:
        store = ControlStore(Path(temp) / "control.db", slots=3, lease_seconds=30)
        users = [store.ensure_user(f"subject-{i}", f"user{i}@example.test", f"User {i}", False) for i in range(9)]
        scaling = []
        cursor = 0
        for count in (1, 2, 3):
            jobs = [create(store, users[cursor + i], f"distinct-{count}-{i}") for i in range(count)]
            cursor += count
            started = time.perf_counter()
            with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
                outcomes = list(pool.map(lambda job: timed_acquire(store, job["id"]), jobs))
            wall = round((time.perf_counter() - started) * 1000, 3)
            scaling.append({
                "workers": count, "wall_milliseconds": wall,
                "all_acquired": all(outcome["acquired"] for outcome in outcomes),
                "unique_slots": sorted({outcome["slot"] for outcome in outcomes}),
                "acquire_milliseconds": [outcome["milliseconds"] for outcome in outcomes],
            })
            for job, outcome in zip(jobs, outcomes):
                store.finish(job["id"], outcome["lease"]["token"], "completed")

        same_jobs = [create(store, users[6 + i], "same-event") for i in range(3)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            same = list(pool.map(lambda job: timed_acquire(store, job["id"]), same_jobs))
        winner_index = next(index for index, outcome in enumerate(same) if outcome["acquired"])
        winner = same[winner_index]
        store.finish(same_jobs[winner_index]["id"], winner["lease"]["token"], "completed")
        next_index = next(index for index, outcome in enumerate(same) if not outcome["acquired"])
        successor = timed_acquire(store, same_jobs[next_index]["id"])
        store.finish(same_jobs[next_index]["id"], successor["lease"]["token"], "completed")

        crash_users = [store.ensure_user(f"crash-{i}", f"crash{i}@example.test", f"Crash {i}", False) for i in range(3)]
        crash_a = create(store, crash_users[0], "crash-event-x")
        crash_b = create(store, crash_users[1], "crash-event-x")
        crash_c = create(store, crash_users[2], "crash-event-y")
        crash_a_lease = store.acquire(crash_a["id"])
        crash_b_waiting = store.acquire(crash_b["id"]) is None
        crash_c_lease = store.acquire(crash_c["id"])
        store.mark_running(crash_a["id"], crash_a_lease["token"], 11111)
        store.mark_running(crash_c["id"], crash_c_lease["token"], 33333)
        expired = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
        with store.immediate() as conn:
            conn.execute("UPDATE event_leases SET expires_at=? WHERE holder_job_id=?", (expired, crash_a["id"]))
            conn.execute("UPDATE worker_leases SET expires_at=? WHERE holder_job_id=?", (expired, crash_a["id"]))
        crash_b_lease = store.acquire(crash_b["id"])
        crash_a_state = store.get_job(crash_a["id"])
        crash_c_unaffected = store.valid_event_lease(crash_c["id"], crash_c_lease["token"], "crash-event-y")
        # A lock from an earlier browser runtime cannot authorize B's first write.
        preflight_dir = Path(temp) / "preflight"
        preflight_dir.mkdir()
        original_current, original_probe = browser_tool.CURRENT, browser_tool.local_probe
        browser_tool.CURRENT = preflight_dir
        browser_tool.local_probe = lambda runtime: {"url": "https://app.cvent.com/event?evtstub=crash-event-x"}
        runtime = {"browserRuntimeId": "runtime-new", "authorizedEventName": "Authorized crash-event-x", "authorizedEventId": "crash-event-x", "authorizedEventKey": "crash-event-x"}
        (preflight_dir / "authorized-target.json").write_text(json.dumps({"name": "Authorized crash-event-x", "event_id": "crash-event-x", "event_key": "crash-event-x", "url": "https://app.cvent.com/event?evtstub=crash-event-x", "browser_runtime_id": "runtime-stale"}))
        stale_preflight_blocked = False
        try:
            browser_tool.guard(runtime, "click", {"intent": "write", "scopeIds": ["scope-004"]})
        except RuntimeError as exc:
            stale_preflight_blocked = "Write blocked" in str(exc)
        finally:
            browser_tool.CURRENT, browser_tool.local_probe = original_current, original_probe
        store.finish(crash_b["id"], crash_b_lease["token"], "failed", "Synthetic preflight complete", False)
        store.finish(crash_c["id"], crash_c_lease["token"], "completed")

        recovery_user = store.ensure_user("recovery", "recovery@example.test", "Recovery", False)
        recovery_job = create(store, recovery_user, "recovery-event")
        recovery_lease = store.acquire(recovery_job["id"])
        store.mark_running(recovery_job["id"], recovery_lease["token"], 999999)
        recovered = store.recover_after_controller_restart()
        recovered_job = store.get_job(recovery_job["id"])

        evidence = {
            "scope": "local control-plane only; no Cvent navigation or mutation and no Anthropic call",
            "platform": {"python": platform.python_version(), "system": platform.platform()},
            "scaling": scaling,
            "same_event": {
                "contenders": 3, "simultaneous_acquisitions": sum(item["acquired"] for item in same),
                "successor_acquired_after_release": successor["acquired"],
            },
            "same_event_crash": {
                "a_event_x_acquired": bool(crash_a_lease), "b_event_x_waiting": crash_b_waiting,
                "c_event_y_concurrent": bool(crash_c_lease), "a_after_expiry": crash_a_state["state"],
                "a_uncertain": bool(crash_a_state["uncertain"]), "b_acquired_after_expiry": bool(crash_b_lease),
                "c_unaffected": crash_c_unaffected, "stale_runtime_target_lock_blocked_first_write": stale_preflight_blocked,
                "required_next_step": "fresh complete Cvent observation plus authorizeTarget before any write",
            },
            "recovery": {
                "recovered_job_ids": recovered, "state": recovered_job["state"],
                "uncertain": bool(recovered_job["uncertain"]), "leases_after_recovery": store.active_leases(),
            },
            "passed": (
                all(item["all_acquired"] and len(item["unique_slots"]) == item["workers"] for item in scaling)
                and sum(item["acquired"] for item in same) == 1
                and successor["acquired"]
                and crash_b_waiting and bool(crash_c_lease) and crash_a_state["state"] == "failed_uncertain"
                and bool(crash_b_lease) and crash_c_unaffected and stale_preflight_blocked
                and recovered_job["state"] == "failed_uncertain"
                and store.active_leases() == {"events": [], "workers": []}
            ),
        }
        print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
