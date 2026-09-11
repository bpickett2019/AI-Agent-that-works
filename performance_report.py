#!/usr/bin/env python3
"""Aggregate job-local timing, model, browser, compute, and storage evidence."""
from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path


def read_json(path, default):
    try: return json.loads(path.read_text())
    except Exception: return default


def lines(path):
    result = []
    try:
        for line in path.read_text().splitlines():
            try: result.append(json.loads(line))
            except Exception: pass
    except Exception: pass
    return result


def percentile(values, p):
    if not values: return 0
    ordered = sorted(values); index = max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))
    return round(ordered[index], 1)


def iso_ms(first, last):
    try: return round((datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds() * 1000, 1)
    except Exception: return 0


def event_span_ms(events):
    if not events: return 0
    try:
        ends = [datetime.fromisoformat(item["timestamp"]).timestamp() * 1000 for item in events]
        starts = [end - float(item.get("durationMs", 0)) for end, item in zip(ends, events)]
        return round(max(ends) - min(starts), 1)
    except Exception: return 0


def legacy_human_handoff_ms(directory):
    """Backfill runs recorded before explicit human_handoff telemetry existed."""
    try:
        started = None
        total = 0.0
        for line in (directory / "activity.log").read_text().splitlines():
            timestamp, _, message = line.partition("  ")
            if "browser control handed to user for SSO/MFA" in message:
                started = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            elif started and "User returned browser control" in message:
                ended = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                total += (ended - started).total_seconds() * 1000
                started = None
        return round(total, 1)
    except Exception:
        return 0


def atomic(path, payload):
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(fd, "w") as handle: json.dump(payload, handle, indent=2); handle.write("\n")
    os.chmod(temporary, 0o600); os.replace(temporary, path)


def main(directory):
    preflight = read_json(directory / "preflight-performance.json", {})
    events = lines(directory / "performance-events.jsonl")
    systems = lines(directory / "system-metrics.jsonl")
    browser = [event for event in events if event.get("kind") == "browser_operation"]
    model = [event for event in events if event.get("kind") == "anthropic_response"]
    first_tokens = [event.get("durationMs", 0) for event in events if event.get("kind") == "anthropic_first_token"]
    stage_markers = [event for event in events if event.get("kind") == "stage_marker"]
    first_browser = next((event for event in events if event.get("kind") == "first_browser_action"), {})
    trusted_procedures = [event for event in events if event.get("kind") == "trusted_section_procedure"]
    human_handoffs = [event for event in events if event.get("kind") == "human_handoff"]
    model_turns = [event for event in events if event.get("kind") == "model_response_progress"]
    ego_rounds = [event for event in events if event.get("kind") == "ego_execution_round"]
    stage_times = {}
    for index, event in enumerate(stage_markers):
        end = stage_markers[index + 1]["timestamp"] if index + 1 < len(stage_markers) else (events[-1]["timestamp"] if events else event["timestamp"])
        stage_times[event.get("stage", "unknown")] = stage_times.get(event.get("stage", "unknown"), 0) + iso_ms(event["timestamp"], end)
    samples = [item for item in systems if item.get("kind") == "system_sample"]
    compute = {}
    if len(samples) >= 2:
        first, last = samples[0], samples[-1]
        cpu_delta = [b - a for a, b in zip(first["cpuTicks"], last["cpuTicks"])]
        total = sum(cpu_delta) or 1; idle = cpu_delta[3] + (cpu_delta[4] if len(cpu_delta) > 4 else 0)
        mem_used = [sample["memoryKb"].get("MemTotal", 0) - sample["memoryKb"].get("MemAvailable", 0) for sample in samples]
        swap_used = [sample["memoryKb"].get("SwapTotal", 0) - sample["memoryKb"].get("SwapFree", 0) for sample in samples]
        compute = {"averageCpuPercent": round(100 * (total - idle) / total, 1), "ioWaitPercent": round(100 * (cpu_delta[4] if len(cpu_delta) > 4 else 0) / total, 1),
            "maxRamUsedKb": max(mem_used, default=0), "maxSwapUsedKb": max(swap_used, default=0), "maxLoad1": max((sample["loadAverage"][0] for sample in samples), default=0), "disks": {}}
        disk_names = set(first.get("disks", {})) & set(last.get("disks", {}))
        for name in disk_names:
            a, b = first["disks"][name], last["disks"][name]; operations = (b["reads"] - a["reads"]) + (b["writes"] - a["writes"])
            service_ms = (b["readMs"] - a["readMs"]) + (b["writeMs"] - a["writeMs"])
            compute["disks"][name] = {"reads": b["reads"] - a["reads"], "writes": b["writes"] - a["writes"],
                "throughputBytes": ((b.get("readSectors", 0) - a.get("readSectors", 0)) + (b.get("writeSectors", 0) - a.get("writeSectors", 0))) * 512,
                "averageOperationLatencyMs": round(service_ms / operations, 3) if operations else 0, "ioBusyMs": b["ioMs"] - a["ioMs"]}
        for group in ("chromium", "pi_node", "steel", "security"):
            compute[group] = {"maxRssKb": max((sample.get("processGroups", {}).get(group, {}).get("rssKb", 0) for sample in samples), default=0),
                "maxProcesses": max((sample.get("processGroups", {}).get(group, {}).get("processes", 0) for sample in samples), default=0)}
    state = read_json(directory / "state.json", {})
    total_ms = iso_ms(state.get("started_at"), state.get("updated_at")) if state.get("started_at") else 0
    human_ms = round(sum(event.get("durationMs", 0) for event in human_handoffs), 1) if human_handoffs else legacy_human_handoff_ms(directory)
    non_human_ms = max(0, round(total_ms - human_ms, 1))
    model_ms = round(sum(event.get("durationMs", 0) for event in model), 1)
    sections = {}
    observed_sections = {str(event.get("section")) for event in events if event.get("section")}
    for section in sorted(observed_sections):
        section_turns = [event for event in model_turns if event.get("section") == section]
        section_rounds = [event for event in ego_rounds if event.get("domain") == section]
        section_browser = [event for event in browser if event.get("section") == section]
        section_model = [event for event in model if event.get("section") == section]
        section_events = [event for event in events if event.get("section") == section or event.get("domain") == section]
        action_count = sum(event.get("actionCount", 0) for event in section_rounds)
        sections[section] = {
            "modelTurns": len(section_turns),
            "modelTurnsWithAction": sum(event.get("browserOperations", 0) > 0 for event in section_turns),
            "modelTurnsWithZeroProgress": sum(bool(event.get("zeroProgress")) for event in section_turns),
            "egoRounds": len(section_rounds),
            "actionsPerEgoRound": round(action_count / len(section_rounds), 2) if section_rounds else 0,
            "browserOperations": len(section_browser),
            "modelTimeMs": round(sum(event.get("durationMs", 0) for event in section_model), 1),
            "browserTimeMs": round(sum(event.get("durationMs", 0) for event in section_browser), 1),
            "totalSectionTimeMs": event_span_ms(section_events),
            "modelCallBudgetExceeded": sum(event.get("kind") == "MODEL_CALL_BUDGET_EXCEEDED" for event in section_events),
        }
    categories = [("Anthropic responses", model_ms), ("Browser operations", sum(event.get("durationMs", 0) for event in browser)),
        ("Human handoff", human_ms), ("RR preflight", preflight.get("totalMs", 0)), *[(f"Stage {name}", value) for name, value in stage_times.items()]]
    summary = {
        "schemaVersion": 2, "environment": next((item for item in systems if item.get("kind") == "environment"), {}), "totalAutomationMs": total_ms,
        "humanHandoffMs": human_ms, "nonHumanAutomationMs": non_human_ms,
        "modelActiveShareOfNonHumanPercent": round(100 * model_ms / non_human_ms, 1) if non_human_ms else 0,
        "rr": {"stages": preflight.get("stages", []), "totalMs": preflight.get("totalMs", 0), "validationCounts": preflight.get("validationCounts", {})},
        "anthropic": {"calls": len(model), "inputTokens": sum(item.get("inputTokens", 0) for item in model), "outputTokens": sum(item.get("outputTokens", 0) for item in model),
            "cacheReadTokens": sum(item.get("cacheReadTokens", 0) for item in model), "cacheWriteTokens": sum(item.get("cacheWriteTokens", 0) for item in model),
            "totalResponseMs": model_ms, "responseP50Ms": percentile([item.get("durationMs", 0) for item in model], .5),
            "responseP95Ms": percentile([item.get("durationMs", 0) for item in model], .95), "firstTokenP50Ms": percentile(first_tokens, .5), "firstTokenP95Ms": percentile(first_tokens, .95)},
        "browser": {"operations": len(browser), "totalMs": round(sum(item.get("durationMs", 0) for item in browser), 1),
            "snapshots": sum(bool(item.get("snapshot")) for item in browser), "fullSnapshots": sum(bool(item.get("fullSnapshot")) for item in browser),
            "navigations": sum(bool(item.get("navigation")) for item in browser),
            "writes": sum(int(item.get("writes", 0) or 0) for item in browser),
            "saves": sum(int(item.get("saves", 0) or 0) for item in browser),
            "readbacks": sum(int(item.get("readbacks", 0) or 0) for item in browser),
            "targetedReadbacks": sum(item.get("intent") == "read" and not item.get("fullSnapshot") for item in browser)},

        "executionLoop": {"timeToFirstBrowserActionMs": first_browser.get("durationMs", 0),
            "modelTurns": len(model_turns), "modelTurnsWithAction": sum(event.get("browserOperations", 0) > 0 for event in model_turns),
            "modelTurnsWithZeroProgress": sum(bool(event.get("zeroProgress")) for event in model_turns),
            "modelCallBudgetExceeded": sum(event.get("kind") == "MODEL_CALL_BUDGET_EXCEEDED" for event in events),
            "egoRounds": len(ego_rounds), "actionsPerEgoRound": round(sum(event.get("actionCount", 0) for event in ego_rounds) / len(ego_rounds), 2) if ego_rounds else 0,
            "sectionStateMissions": sum(event.get("kind") == "browser_operation" and event.get("operation") == "sectionState" for event in events),
            "contextPrunes": sum(event.get("kind") == "context_pruned" for event in events),
            "trustedSectionProcedures": [{"domain": event.get("domain"), "status": event.get("status"),
                "records": event.get("records", 0), "mutations": event.get("mutationCount", 0), "durationMs": event.get("durationMs", 0)}
                for event in trusted_procedures],
            "maximumConsecutiveZeroProgressRounds": max((int(value.get("maximumConsecutiveZeroProgressRounds", 0) or 0)
                for value in read_json(directory / "domain-progress.json", {}).get("domains", {}).values()), default=0)},

        "sections": sections,
        "stageDurationsMs": stage_times, "forgeStatusUpdates": len(stage_markers), "api": {"reads": 0, "writes": 0}, "computeAndDisk": compute,
        "securitySoftware": {"observedProcessMetrics": compute.get("security", {}), "causalOverheadEstablished": False, "exclusionsApplied": False},
        "topMeasuredTimeCategories": [{"name": name, "durationMs": round(value, 1)} for name, value in sorted(categories, key=lambda item: item[1], reverse=True)[:5]],
    }
    atomic(directory / "performance-summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    import sys
    main(Path(sys.argv[1]).resolve())
