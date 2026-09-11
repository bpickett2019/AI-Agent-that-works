#!/usr/bin/env python3
"""Refresh one workspace's selectable events from its authenticated Cvent profile."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from browser_gate import BrowserGate
import browser_runtime
from runtime_config import (DATA_ROOT, WORKER_SLOTS, browser_auth_metadata_path,
                            browser_cache_dir, browser_profile_dir, workspace_dir)

SENTINEL = "00000000-0000-4000-8000-000000000000"


def reply(stdout: str) -> dict:
    marker = "BROWSER_ROUTER_RESULT="
    index = stdout.rfind(marker)
    if index < 0:
        raise RuntimeError("Browser inventory reader returned no structured result")
    return json.loads(stdout[index + len(marker):].strip())


def main() -> int:
    workspace_id = os.environ["CVENT_WORKSPACE_ID"]
    workspace = workspace_dir(workspace_id)
    profiles = []
    for slot in WORKER_SLOTS:
        try:
            metadata = json.loads(browser_auth_metadata_path(workspace_id, slot.slot_id).read_text())
        except Exception:
            continue
        if metadata.get("authenticated") is True and browser_profile_dir(workspace_id, slot.slot_id).is_dir():
            profiles.append(slot)
    if not profiles:
        raise RuntimeError("AUTH_REQUIRED: no verified persistent Cvent profile can refresh event inventory")
    last_error = None
    for slot in profiles:
        refresh_id = "inventory_" + uuid.uuid4().hex
        folder = workspace / "event-inventory-refresh" / refresh_id
        folder.mkdir(parents=True, mode=0o700)
        env = os.environ.copy()
        env.update({
            "CVENT_JOB_DIR": str(folder), "CVENT_JOB_ID": refresh_id,
            "CVENT_WORKSPACE_ID": workspace_id, "CVENT_WORKER_SLOT": str(slot.slot_id),
            "CVENT_BROWSER_PROFILE_DIR": str(browser_profile_dir(workspace_id, slot.slot_id)),
            "CVENT_BROWSER_CACHE_DIR": str(browser_cache_dir(workspace_id, slot.slot_id)),
            "CVENT_STEEL_API_ORIGIN": slot.api_origin, "CVENT_CDP_ORIGIN": slot.cdp_origin,
            "CVENT_AUTHORIZED_EVENT_ID": SENTINEL, "CVENT_AUTHORIZED_EVENT_KEY": SENTINEL,
            "CVENT_AUTHORIZED_EVENT_NAME": "CVENT_EVENT_INVENTORY_READ_ONLY",
        })
        owns = False
        try:
            ensured = subprocess.run([sys.executable, str(ROOT / "steel_session.py"), "ensure"], cwd=ROOT,
                                     env=env, text=True, capture_output=True, timeout=120)
            if ensured.returncode:
                raise RuntimeError((ensured.stderr or ensured.stdout)[-1200:])
            owns = True
            os.environ.update(env)
            runtime = browser_runtime.initialize(folder, slot.slot_id, "CVENT_EVENT_INVENTORY_READ_ONLY",
                                                  SENTINEL, SENTINEL, env["CVENT_BROWSER_PROFILE_DIR"])
            runtime["accessMode"] = "read_only_inventory"
            runtime_path = folder / "browser-runtime.json"
            runtime_path.write_text(json.dumps(runtime, indent=2))
            BrowserGate(folder).initialize()
            def browser(operation: str, params: dict | None = None, timeout: int = 90) -> dict:
                process = subprocess.run(
                    [sys.executable, str(ROOT / "browser_tool.py"), "--runtime", str(runtime_path),
                     "--operation", operation, "--params", json.dumps(params or {})],
                    cwd=ROOT, env=env, text=True, capture_output=True, timeout=timeout,
                )
                result = reply(process.stdout)
                if process.returncode or not result.get("ok"):
                    raise RuntimeError(result.get("error") or process.stderr[-1000:])
                return result
            browser("navigate", {"url": "https://app.cvent.com/Subscribers/Events2/EventSelection",
                                  "timeoutSeconds": 90}, 100)
            time.sleep(2)
            auth = browser("authStatus")
            if not auth.get("authenticated"):
                raise RuntimeError("AUTH_REQUIRED: persistent Cvent profile did not authenticate")
            inventory = browser("eventInventory", {"maxScrolls": 100, "timeoutSeconds": 120}, 130)
            events = inventory.get("events")
            if not isinstance(events, list) or not events:
                raise RuntimeError("EVENT_NOT_FOUND: authenticated Cvent inventory contained no accessible events")
            payload = {"schemaVersion": 1, "workspaceId": workspace_id,
                       "source": "authenticated-cvent-inventory",
                       "capturedAt": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                       "workerSlot": slot.slot_id, "events": events}
            target = workspace / "event-inventory.json"
            temporary = target.with_name(target.name + f".{os.getpid()}.tmp")
            temporary.write_text(json.dumps(payload, indent=2));temporary.chmod(0o600);temporary.replace(target)
            print(json.dumps({"ok": True, "workerSlot": slot.slot_id, "events": len(events)}))
            return 0
        except Exception as exc:
            last_error = exc
        finally:
            if owns:
                subprocess.run([sys.executable, str(ROOT / "steel_session.py"), "release"], cwd=ROOT,
                               env=env, text=True, capture_output=True, timeout=60)
            shutil.rmtree(folder, ignore_errors=True)
    raise RuntimeError(str(last_error or "No authenticated profile was available"))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
