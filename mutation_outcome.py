"""Determine whether durable browser mutation evidence has a resolved outcome."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def mutation_outcome(directory: Path) -> dict:
    directory = Path(directory)
    uncertain_marker = directory / "browser-mutation-uncertain.json"
    pending_marker = directory / "browser-write-readback-required.json"
    audit = directory / "scope-write-audit.jsonl"
    attempted, succeeded, rejected = Counter(), Counter(), Counter()
    malformed = False
    if audit.exists():
        for line in audit.read_text(errors="replace").splitlines():
            try:
                item = json.loads(line)
                key = (str(item.get("operation", "")), str(item.get("rrSource") or ""))
                if item.get("result") == "attempted": attempted[key] += 1
                elif item.get("result") == "succeeded": succeeded[key] += 1
                elif item.get("result") == "rejected_prewrite": rejected[key] += 1
                elif item.get("result") in {"failed", "uncertain"}: attempted[key] += 1
            except Exception:
                malformed = True
    # The router records admission before dispatch, then explicitly cancels it
    # only when the trusted adapter proves zero mutations were dispatched.
    effective = {key: max(0, count - rejected[key]) for key, count in attempted.items()}
    unmatched = sum(max(0, count - succeeded[key]) for key, count in effective.items())
    has_attempts = bool(sum(effective.values()))
    unresolved = uncertain_marker.exists() or pending_marker.exists() or malformed or unmatched > 0
    return {
        "attempted": sum(effective.values()), "rejectedPrewrite": sum(rejected.values()), "succeeded": sum(succeeded.values()), "unmatchedAttempts": unmatched,
        "hasAttempts": has_attempts, "uncertainMarker": uncertain_marker.exists(),
        "pendingReadback": pending_marker.exists(), "malformedAudit": malformed, "unresolved": unresolved,
    }
