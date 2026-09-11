"""Determine whether durable browser mutation evidence has a resolved outcome."""
from __future__ import annotations

import json
import hashlib
from collections import Counter
from pathlib import Path


def mutation_outcome(directory: Path) -> dict:
    directory = Path(directory)
    uncertain_marker = directory / "browser-mutation-uncertain.json"
    pending_marker = directory / "browser-write-readback-required.json"
    audit = directory / "scope-write-audit.jsonl"
    attempted, succeeded, rejected, not_persisted, persisted = Counter(), Counter(), Counter(), Counter(), Counter()
    malformed = False
    resolutions = {}
    resolution_file = directory / 'mutation-resolutions.json'
    if resolution_file.exists():
        try:
            for resolution in json.loads(resolution_file.read_text())['resolutions']:
                evidence = (directory / resolution['evidencePath']).resolve()
                if (resolution['outcome'] not in {'NOT_PERSISTED', 'PERSISTED'} or resolution['actor'] != 'operator'
                        or not evidence.is_relative_to(directory.resolve())
                        or hashlib.sha256(evidence.read_bytes()).hexdigest() != resolution['evidenceSha256']):
                    raise ValueError('Invalid mutation resolution evidence')
                resolutions[(resolution['attemptAt'], resolution['operation'], resolution['rrSource'])] = resolution
        except Exception:
            malformed = True
    if audit.exists():
        for line in audit.read_text(errors="replace").splitlines():
            try:
                item = json.loads(line)
                key = (str(item.get("operation", "")), str(item.get("rrSource") or ""))
                if item.get("result") == "attempted":
                    attempted[key] += 1
                    resolution = resolutions.get((item.get('at'), *key))
                    if resolution and resolution['outcome'] == 'NOT_PERSISTED': not_persisted[key] += 1
                    elif resolution and resolution['outcome'] == 'PERSISTED': persisted[key] += 1
                elif item.get("result") == "succeeded": succeeded[key] += 1
                elif item.get("result") == "rejected_prewrite": rejected[key] += 1
                elif item.get("result") in {"failed", "uncertain"}: attempted[key] += 1
            except Exception:
                malformed = True
    # The router records admission before dispatch, then explicitly cancels it
    # only when the trusted adapter proves zero mutations were dispatched.
    effective = {key: max(0, count - rejected[key]) for key, count in attempted.items()}
    unmatched = sum(max(0, count - succeeded[key] - not_persisted[key] - persisted[key]) for key, count in effective.items())
    has_attempts = bool(sum(effective.values()))
    unresolved = uncertain_marker.exists() or pending_marker.exists() or malformed or unmatched > 0
    return {
        "attempted": sum(effective.values()), "rejectedPrewrite": sum(rejected.values()), "succeeded": sum(succeeded.values()), "unmatchedAttempts": unmatched,
        "notPersisted": sum(not_persisted.values()), "persistedResolved": sum(persisted.values()), "hasAttempts": has_attempts, "uncertainMarker": uncertain_marker.exists(),
        "pendingReadback": pending_marker.exists(), "malformedAudit": malformed, "unresolved": unresolved,
    }
