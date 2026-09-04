#!/usr/bin/env python3
"""Low-overhead, read-only host/process/storage metrics for one Cvent job."""
from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def append(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": now(), **payload}, separators=(",", ":")) + "\n")


def mount_for(path: Path):
    resolved = path.resolve()
    best = None
    try:
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            left, right = line.split(" - ", 1)
            fields, fs = left.split(), right.split()
            mount = Path(fields[4].replace("\\040", " "))
            try:
                resolved.relative_to(mount)
            except ValueError:
                continue
            if best is None or len(str(mount)) > len(str(best["mountPoint"])):
                best = {"path": str(resolved), "mountPoint": str(mount), "device": fields[2], "filesystem": fs[0], "source": fs[1], "options": fields[5]}
    except Exception:
        pass
    return best or {"path": str(resolved)}


def docker_root():
    try:
        return subprocess.check_output(["docker", "info", "--format", "{{.DockerRootDir}}"], text=True, timeout=10).strip()
    except Exception:
        return None


def proc_snapshot():
    totals = {"chromium": {"rssKb": 0, "cpuTicks": 0, "processes": 0}, "pi_node": {"rssKb": 0, "cpuTicks": 0, "processes": 0}, "steel": {"rssKb": 0, "cpuTicks": 0, "processes": 0}, "security": {"rssKb": 0, "cpuTicks": 0, "processes": 0}}
    security_names = ("mdatp", "defender", "ninja", "azuremonitor", "omsagent", "waagent")
    for directory in Path("/proc").iterdir():
        if not directory.name.isdigit():
            continue
        try:
            comm = (directory / "comm").read_text().strip().lower()
            cmd = (directory / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore").lower()
            stat = (directory / "stat").read_text().split()
            rss = 0
            for line in (directory / "status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]); break
            category = None
            if "chrom" in comm or "chrom" in cmd: category = "chromium"
            elif "steel" in cmd: category = "steel"
            elif comm in {"node", "pi"} and ("pi" in cmd or "cvent" in cmd): category = "pi_node"
            elif any(name in comm or name in cmd for name in security_names): category = "security"
            if category:
                totals[category]["rssKb"] += rss
                totals[category]["cpuTicks"] += int(stat[13]) + int(stat[14])
                totals[category]["processes"] += 1
        except Exception:
            continue
    return totals


def linux_snapshot():
    cpu = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    mem = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1); mem[key] = int(value.strip().split()[0])
    vm = {}
    for line in Path("/proc/vmstat").read_text().splitlines():
        key, value = line.split();
        if key in {"pswpin", "pswpout", "pgpgin", "pgpgout"}: vm[key] = int(value)
    disks = {}
    for line in Path("/proc/diskstats").read_text().splitlines():
        fields = line.split(); name = fields[2]
        if name.startswith(("sd", "vd", "nvme")):
            disks[name] = {"reads": int(fields[3]), "readSectors": int(fields[5]), "readMs": int(fields[6]), "writes": int(fields[7]), "writeSectors": int(fields[9]), "writeMs": int(fields[10]), "ioMs": int(fields[12]), "weightedIoMs": int(fields[13])}
    return {"kind": "system_sample", "cpuTicks": [int(value) for value in cpu], "memoryKb": mem, "vm": vm, "disks": disks, "loadAverage": os.getloadavg(), "processGroups": proc_snapshot()}


def monitor(output: Path, stop_event, paths: list[Path], interval=5):
    placement = [mount_for(path) for path in paths if path.exists()]
    root = docker_root()
    if root:
        placement.append(mount_for(Path(root)))
    append(output, {"kind": "environment", "hostname": platform.node(), "platform": platform.platform(), "cpuCount": os.cpu_count(), "storagePlacement": placement, "dockerRoot": root})
    while not stop_event.is_set():
        started = time.monotonic()
        try:
            if platform.system() == "Linux":
                append(output, linux_snapshot())
        except Exception as exc:
            append(output, {"kind": "monitor_error", "errorType": type(exc).__name__})
        stop_event.wait(max(0.2, interval - (time.monotonic() - started)))
