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
    categories = [("Anthropic responses", sum(event.get("durationMs", 0) for event in model)), ("Browser operations", sum(event.get("durationMs", 0) for event in browser)),
        ("RR preflight", preflight.get("totalMs", 0)), *[(f"Stage {name}", value) for name, value in stage_times.items()]]
    summary = {
        "schemaVersion": 1, "environment": next((item for item in systems if item.get("kind") == "environment"), {}), "totalAutomationMs": total_ms,
        "rr": {"stages": preflight.get("stages", []), "totalMs": preflight.get("totalMs", 0), "validationCounts": preflight.get("validationCounts", {})},
        "anthropic": {"calls": len(model), "inputTokens": sum(item.get("inputTokens", 0) for item in model), "outputTokens": sum(item.get("outputTokens", 0) for item in model),
            "cacheReadTokens": sum(item.get("cacheReadTokens", 0) for item in model), "cacheWriteTokens": sum(item.get("cacheWriteTokens", 0) for item in model),
            "totalResponseMs": round(sum(item.get("durationMs", 0) for item in model), 1), "responseP50Ms": percentile([item.get("durationMs", 0) for item in model], .5),
            "responseP95Ms": percentile([item.get("durationMs", 0) for item in model], .95), "firstTokenP50Ms": percentile(first_tokens, .5), "firstTokenP95Ms": percentile(first_tokens, .95)},
        "browser": {"operations": len(browser), "totalMs": round(sum(item.get("durationMs", 0) for item in browser), 1),
            "snapshots": sum(bool(item.get("snapshot")) for item in browser), "fullSnapshots": sum(bool(item.get("fullSnapshot")) for item in browser),
            "navigations": sum(bool(item.get("navigation")) for item in browser), "writes": sum(item.get("intent") == "write" for item in browser),
            "targetedReadbacks": sum(item.get("intent") == "read" and not item.get("fullSnapshot") for item in browser)},
        "stageDurationsMs": stage_times, "forgeStatusUpdates": len(stage_markers), "api": {"reads": 0, "writes": 0}, "computeAndDisk": compute,
        "securitySoftware": {"observedProcessMetrics": compute.get("security", {}), "causalOverheadEstablished": False, "exclusionsApplied": False},
        "topMeasuredTimeCategories": [{"name": name, "durationMs": round(value, 1)} for name, value in sorted(categories, key=lambda item: item[1], reverse=True)[:5]],
    }
    atomic(directory / "performance-summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    import sys
    main(Path(sys.argv[1]).resolve())
