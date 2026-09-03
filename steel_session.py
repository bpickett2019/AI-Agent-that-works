#!/usr/bin/env python3
"""Lifecycle for one job-scoped, localhost-only Steel Browser container."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from browser_runtime import command, pages, select_page
from runtime_config import ROOT, STEEL_IMAGE, slot_by_id

JOB_DIR = Path(os.environ.get("CVENT_JOB_DIR", ROOT / "data" / "current")).resolve()
JOB_ID = os.environ.get("CVENT_JOB_ID", JOB_DIR.name)
SLOT = slot_by_id(int(os.environ.get("CVENT_WORKER_SLOT", "1")))
API = os.environ.get("CVENT_STEEL_API_ORIGIN", SLOT.api_origin)
CDP = os.environ.get("CVENT_CDP_ORIGIN", SLOT.cdp_origin)
VIEWER = os.environ.get("CVENT_VIEWER_URL", f"/api/jobs/{JOB_ID}/viewer")
CONTAINER = SLOT.container_name
PROFILE = Path(os.environ.get("CVENT_BROWSER_PROFILE_DIR", JOB_DIR / "chromium-profile")).resolve()
CACHE = Path(os.environ.get("CVENT_BROWSER_CACHE_DIR", JOB_DIR / "steel-cache")).resolve()


def clear_stale_profile_locks():
    if container_running():
        return
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            (PROFILE / name).unlink()
        except FileNotFoundError:
            pass


def recover_container_profile_locks():
    cleanup = subprocess.run(
        ["docker", "exec", CONTAINER, "sh", "-lc",
         "rm -f /tmp/steel-chrome/SingletonLock /tmp/steel-chrome/SingletonSocket /tmp/steel-chrome/SingletonCookie"],
        text=True, capture_output=True, timeout=15,
    )
    if cleanup.returncode:
        raise RuntimeError((cleanup.stderr or cleanup.stdout)[-1500:])
    restarted = subprocess.run(["docker", "restart", CONTAINER], text=True, capture_output=True, timeout=60)
    if restarted.returncode:
        raise RuntimeError((restarted.stderr or restarted.stdout)[-1500:])


def get_json(url, timeout=2):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def container_running():
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER], text=True, capture_output=True
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def container_job_id():
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{index .Config.Labels \"com.forge.cvent.job\"}}", CONTAINER],
        text=True, capture_output=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def status():
    running = container_running()
    browser = None
    error = None
    if running:
        if container_job_id() != JOB_ID:
            return {
                "provider": "steel-oss", "running": False, "status": "conflict", "id": CONTAINER,
                "profile_id": str(PROFILE), "viewer_url": VIEWER,
                "error": "Worker slot container belongs to another job",
            }
        try:
            browser = get_json(CDP + "/json/version").get("Browser")
        except Exception as exc:
            running = False
            error = str(exc)
    return {
        "provider": "steel-oss", "running": running, "status": "live" if running else "stopped",
        "id": CONTAINER, "profile_id": str(PROFILE), "viewer_url": VIEWER,
        "api_url": API, "cdp_url": CDP, "browser": browser, "error": error,
    }


def create_container():
    PROFILE.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    os.chmod(PROFILE, 0o700)
    os.chmod(CACHE, 0o700)
    existing_job = container_job_id()
    if existing_job and existing_job != JOB_ID:
        running = container_running()
        if running:
            raise RuntimeError(f"Worker slot {SLOT.slot_id} is already owned by job {existing_job}")
        subprocess.run(["docker", "rm", "-f", CONTAINER], text=True, capture_output=True, timeout=30, check=True)
    elif existing_job:
        result = subprocess.run(["docker", "start", CONTAINER], text=True, capture_output=True, timeout=60)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout)[-1500:])
        return
    clear_stale_profile_locks()
    command_line = [
        "docker", "run", "-d", "--name", CONTAINER, "--restart", "unless-stopped", "--init",
        "--shm-size", "2g", "--label", f"com.forge.cvent.job={JOB_ID}",
        "--label", f"com.forge.cvent.slot={SLOT.slot_id}",
        "-e", "FILTER_CHROME_ARGS=--disable-dev-shm-usage --restore-last-session",
        "-p", f"127.0.0.1:{SLOT.api_port}:3000", "-p", f"127.0.0.1:{SLOT.cdp_port}:9223",
        "-v", f"{CACHE}:/app/.cache", "-v", f"{PROFILE}:/tmp/steel-chrome", STEEL_IMAGE,
    ]
    result = subprocess.run(command_line, text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-1500:])


def ensure():
    running = container_running()
    owner = container_job_id() if running else ""
    if owner and owner != JOB_ID:
        raise RuntimeError(f"Worker slot {SLOT.slot_id} is already owned by job {owner}")
    if not running:
        create_container()
    recovered = False
    for attempt in range(120):
        live = status()
        if live["running"]:
            return live
        if attempt == 20 and container_running() and not recovered:
            recover_container_profile_locks()
            recovered = True
        time.sleep(0.5)
    raise RuntimeError("Open-source Steel CDP did not become ready")


def release():
    if container_job_id() not in ("", JOB_ID):
        return {"released": False, "provider": "steel-oss", "error": "Container ownership changed"}
    if container_running():
        stopped = subprocess.run(["docker", "stop", "-t", "10", CONTAINER], text=True, capture_output=True, timeout=30)
        if stopped.returncode and "No such container" not in (stopped.stderr or ""):
            return {"released": False, "provider": "steel-oss", "error": (stopped.stderr or stopped.stdout)[-1000:]}
    result = subprocess.run(["docker", "rm", "-f", CONTAINER], text=True, capture_output=True, timeout=60)
    released = result.returncode == 0 or "No such container" in (result.stderr or "")
    if released:
        clear_stale_profile_locks()
    return {
        "released": released, "provider": "steel-oss",
        "error": None if released else (result.stderr or result.stdout)[-1000:],
    }


def cdp_url():
    ensure()
    ws_url = get_json(CDP + "/json/version")["webSocketDebuggerUrl"]
    return ws_url.replace("ws://127.0.0.1/", f"ws://127.0.0.1:{SLOT.cdp_port}/").replace(
        "ws://localhost/", f"ws://127.0.0.1:{SLOT.cdp_port}/"
    )


def auth_status(url, title):
    value = (url or "").lower()
    host = value.split("/")[2] if "://" in value else ""
    name = (title or "").strip().lower()
    microsoft = any(item in host for item in (
        "login.microsoftonline.com", "login.live.com", "login.windows.net",
        "account.activedirectory.windowsazure.com",
    ))
    if microsoft:
        return "microsoft_sso"
    if "cvent.com" in host and ("login" in value or name in {"log in", "sign in"}):
        return "login_required"
    if "cvent.com" in host:
        return "authenticated"
    return "unknown"


def page(url=None):
    ensure()
    target = select_page(pages(CDP))
    if not target:
        raise RuntimeError("Steel has no page target")

    def live_state():
        reply = command(
            target["webSocketDebuggerUrl"], "Runtime.evaluate",
            {"expression": "({url:location.href,title:document.title,ready:document.readyState})", "returnByValue": True},
            CDP,
        )
        return reply.get("result", {}).get("value", {})

    current = live_state()
    if url and current.get("url") != url:
        command(target["webSocketDebuggerUrl"], "Page.navigate", {"url": url}, CDP)
        for _ in range(60):
            time.sleep(0.25)
            current = live_state()
            if current.get("ready") == "complete" and current.get("url") != "about:blank":
                break
    auth = auth_status(current.get("url"), current.get("title"))
    return {
        **status(), "url": current.get("url"), "title": current.get("title"),
        "auth_status": auth, "login_required": auth != "authenticated",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["ensure", "status", "release", "cdp", "page"])
    parser.add_argument("--url")
    args = parser.parse_args()
    try:
        result = page(args.url) if args.command == "page" else {
            "ensure": ensure, "status": status, "release": release, "cdp": lambda: {"cdp_url": cdp_url()},
        }[args.command]()
        print("STEEL_RESULT=" + json.dumps(result))
    except Exception as exc:
        print("STEEL_RESULT=" + json.dumps({
            "provider": "steel-oss", "running": False, "error": f"{type(exc).__name__}: {exc}",
        }))
        sys.exit(1)
