"""Build final job reporting only from persisted controller/browser artifacts."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(errors="replace").splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
            except json.JSONDecodeError:
                pass
    except OSError:
        pass
    return rows


def _deployment_sha(root: Path, directory: Path, state: dict[str, Any]) -> str:
    if state.get("deployed_sha"):
        return str(state["deployed_sha"])
    try:
        match = re.search(r"/releases/([0-9a-f]{40})/", (directory / "activity.log").read_text(errors="replace"))
        if match:
            return match.group(1)
    except OSError:
        pass
    for path in (root / ".deployed-git-sha", root.parent.parent / "DEPLOYED_COMMIT"):
        try:
            value = path.read_text().strip()
            if re.fullmatch(r"[0-9a-f]{40}", value):
                return value
        except OSError:
            pass
    return "unknown"


def build_telemetry_report(directory: Path, job: dict[str, Any], root: Path) -> dict[str, Any]:
    """Merge model verdict text with authoritative persisted operation/domain counts."""
    state = _json(directory / "state.json", {})
    existing = _json(directory / "final-report.json", {})
    verification = _json(directory / "final-verification.json", {"domains": {}})
    results = _json(directory / "domain-results.json", {"domains": {}})
    validation = _json(directory / "rr-validation.json", {"items": []})
    events = _jsonl(directory / "performance-events.jsonl")
    operations = [event for event in events if event.get("kind") == "browser_operation"]
    runtime = _json(directory / "browser-runtime.json", {})
    if runtime.get("executionMode") == "simple" or existing.get("execution_mode") == "simple":
        # Reporting must not reimpose the legacy domain ledger or erase Pi's QA.
        # Count dispatched/completed UI work separately from verified commits;
        # a snapshot alone is not a persisted readback.
        audit = _jsonl(directory / "scope-write-audit.jsonl")
        completed = [row for row in audit if row.get("result") == "ui_action_completed"]
        verified = [row for row in audit if row.get("result") == "succeeded" and row.get("resolvedBy") == "pi"]
        return {
            **existing,
            "telemetry_source": "pi_verdict_and_native_ego_audit",
            "execution_mode": "simple",
            "status": existing.get("status") or ("DRAFT_COMPLETE" if state.get("status") == "completed" else "REVIEW_REQUIRED" if state.get("status") == "review_required" else "INCOMPLETE"),
            "job_id": job.get("id"),
            "deployed_sha": _deployment_sha(root, directory, state),
            "event": {"name": job.get("event_name"), "id": job.get("event_id"), "key": job.get("event_key"), "code": job.get("event_code")},
            "timestamps": {
                "job_created_at": job.get("created_at"), "job_started_at": job.get("started_at") or state.get("started_at"),
                "process_started_at": state.get("process_started_at") or state.get("last_process_started_at"),
                "job_finished_at": job.get("finished_at"), "report_generated_at": datetime.now(timezone.utc).isoformat(),
            },
            "browser_operations": len(operations),
            "writes": sum(bool(row.get("dataChange")) and not row.get("isSave") for row in completed),
            "saves": sum(bool(row.get("isSave")) for row in completed),
            "readbacks": len(verified),
            "count_semantics": "writes=completed UI data edits; saves=completed Save clicks; readbacks=Pi-acknowledged persisted commit observations",
            "maximum_consecutive_zero_progress_rounds": None,
            "domains": {},
            "checklist": {key: state.get(key, []) for key in ("completed", "pending", "review_required")},
            "real_reads": existing.get("real_reads", []),
            "real_writes": existing.get("real_writes", []),
        }
    requested: dict[str, int] = defaultdict(int)
    for item in validation.get("items", []):
        if item.get("domain"):
            requested[str(item["domain"])] += 1

    domain_counts: dict[str, dict[str, int]] = defaultdict(lambda: {
        "browser_operations": 0, "writes": 0, "saves": 0, "readbacks": 0,
    })
    modern_counts = any(any(key in event for key in ("writes", "saves", "readbacks")) for event in operations)
    for event in operations:
        domain = str(event.get("section") or "")
        if not domain:
            continue
        values = domain_counts[domain]
        values["browser_operations"] += 1
        values["writes"] += int(event.get("writes") or 0)
        values["saves"] += int(event.get("saves") or 0)
        values["readbacks"] += int(event.get("readbacks") or 0)

    # Older releases persisted exact Ego counts in activity.log but did not put
    # those fields on browser_operation events. Use that persisted source only
    # as a compatibility fallback; never infer counts from model prose.
    if not modern_counts:
        pattern = re.compile(r"Ego ([a-z_]+): \d+ actions, (\d+) writes, (\d+) saves, (\d+) readbacks", re.I)
        try:
            activity = (directory / "activity.log").read_text(errors="replace")
        except OSError:
            activity = ""
        for domain, writes, saves, readbacks in pattern.findall(activity):
            values = domain_counts[domain]
            values["writes"] += int(writes)
            values["saves"] += int(saves)
            values["readbacks"] += int(readbacks)

    domains: dict[str, Any] = {}
    order: list[str] = []
    plan = _json(directory / "configuration-plan.json", {"mission": []})
    for mission in plan.get("mission", []):
        if mission.get("domain") and mission["domain"] not in order:
            order.append(mission["domain"])
    for domain in list(requested) + list(results.get("domains", {})) + list(verification.get("domains", {})):
        if domain not in order:
            order.append(domain)

    real_reads: list[str] = []
    real_writes: list[str] = []
    for domain in order:
        persisted = results.get("domains", {}).get(domain, {})
        verified = verification.get("domains", {}).get(domain, {})
        items = verified.get("items", [])
        statuses = defaultdict(int)
        for item in items:
            statuses[str(item.get("status") or "UNKNOWN")] += 1
        trusted = _json(directory / f"trusted-{domain}-result.json", {})
        trusted_records = trusted.get("records", []) if isinstance(trusted, dict) else []
        already = list(persisted.get("already_correct", []))
        already.extend(str(item.get("reference")) for item in trusted_records if item.get("status") == "EXACT_MATCH_ALREADY_CORRECT")
        created = list(persisted.get("created", []))
        updated = list(persisted.get("updated", []))
        held = list(persisted.get("held", persisted.get("blocked", [])))
        held.extend(str(item.get("reference")) for item in trusted_records if item.get("status") in {
            "MATCH_UNCERTAIN_HUMAN_REVIEW", "CONTROL_NOT_FOUND", "CONTROL_NOT_AVAILABLE", "VERIFY_FAILED",
        })
        prohibited = list(persisted.get("prohibited", []))
        prohibited.extend(str(item.get("itemId")) for item in items if item.get("status") == "PROHIBITED")
        counts = domain_counts[domain]
        checkpoint = str(persisted.get("checkpoint") or "").upper()
        status = "COMPLETE" if checkpoint == "COMPLETE" or (verified.get("cventEvidence") and domain in state.get("completed", [])) else str(persisted.get("status") or "INCOMPLETE").upper()
        if status == "REVIEW_REQUIRED" and checkpoint == "COMPLETE":
            status = "COMPLETE"
        evidence = [str(value) for value in verified.get("cventEvidence", [])]
        real_reads.extend(f"{domain}: {value}" for value in evidence)
        real_writes.extend(f"{domain}: {value}" for value in persisted.get("verified_writes", []))
        if counts["writes"] and not persisted.get("verified_writes"):
            real_writes.append(f"{domain}: {counts['writes']} persisted write(s), {counts['saves']} Save(s), {counts['readbacks']} readback(s)")
        domains[domain] = {
            "requested_items": requested.get(domain, 0),
            "already_correct": sorted(set(filter(None, already))),
            "already_correct_count": len(set(filter(None, already))),
            "created": created,
            "created_count": len(created),
            "updated": updated,
            "updated_count": len(updated),
            "held": sorted(set(filter(None, held))),
            "held_count": len(set(filter(None, held))),
            "prohibited": sorted(set(filter(None, prohibited))),
            "prohibited_count": len(set(filter(None, prohibited))),
            **counts,
            "status": status,
            "verification_timestamp": verified.get("verifiedAt") or persisted.get("verified_at"),
        }

    progress = _json(directory / "domain-progress.json", {"domains": {}})
    maximum_zero_progress = max((int(item.get("maximumConsecutiveZeroProgressRounds") or 0)
                                 for item in progress.get("domains", {}).values()), default=0)
    report = dict(existing)
    report.update({
        "telemetry_source": "persisted_job_artifacts",
        "status": existing.get("status") or ("DRAFT_COMPLETE" if state.get("status") == "completed" else "REVIEW_REQUIRED" if state.get("status") == "review_required" else "INCOMPLETE"),
        "job_id": job.get("id"),
        "deployed_sha": _deployment_sha(root, directory, state),
        "event": {"name": job.get("event_name"), "id": job.get("event_id"), "key": job.get("event_key"), "code": job.get("event_code")},
        "timestamps": {
            "job_created_at": job.get("created_at"), "job_started_at": job.get("started_at") or state.get("started_at"),
            "process_started_at": state.get("process_started_at") or state.get("last_process_started_at"), "job_finished_at": job.get("finished_at"),
            "report_generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "browser_operations": len(operations),
        "writes": sum(values["writes"] for values in domain_counts.values()),
        "saves": sum(values["saves"] for values in domain_counts.values()),
        "readbacks": sum(values["readbacks"] for values in domain_counts.values()),
        "maximum_consecutive_zero_progress_rounds": maximum_zero_progress,
        "domains": domains,
        "real_reads": real_reads,
        "real_writes": real_writes,
    })
    return report


def write_telemetry_report(directory: Path, job: dict[str, Any], root: Path) -> dict[str, Any]:
    report = build_telemetry_report(directory, job, root)
    temporary = directory / "final-report.json.tmp"
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(directory / "final-report.json")
    return report
