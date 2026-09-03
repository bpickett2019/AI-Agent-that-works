#!/usr/bin/env python3
"""Canonical browser identity scoped to exactly one job and one Steel worker."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import websockets

from runtime_config import DEFAULT_EVENT_NAME, slot_by_id

ROOT = Path(__file__).resolve().parent
CURRENT = Path(os.environ.get("CVENT_JOB_DIR", ROOT / "data" / "current"))
RUNTIME = CURRENT / "browser-runtime.json"
_ENV_SLOT = slot_by_id(int(os.environ.get("CVENT_WORKER_SLOT", "1")))
CDP_HTTP = os.environ.get("CVENT_CDP_ORIGIN", _ENV_SLOT.cdp_origin)
AUTHORIZED_NAME = os.environ.get("CVENT_AUTHORIZED_EVENT_NAME", DEFAULT_EVENT_NAME)


def now():
    return datetime.now(timezone.utc).isoformat()


def get_json(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def ws_local(url, cdp_http=CDP_HTTP):
    port = urlparse(cdp_http).port
    return url.replace("ws://127.0.0.1/", f"ws://127.0.0.1:{port}/").replace(
        "ws://localhost/", f"ws://127.0.0.1:{port}/"
    ).replace("ws://0.0.0.0/", f"ws://127.0.0.1:{port}/")


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


async def page_command(ws_url, method, params=None, cdp_http=CDP_HTTP):
    origin = cdp_http
    async with websockets.connect(
        ws_local(ws_url, cdp_http), origin=origin, open_timeout=10, max_size=16 * 1024 * 1024
    ) as socket:
        await socket.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            reply = json.loads(await asyncio.wait_for(socket.recv(), 10))
            if reply.get("id") == 1:
                if reply.get("error"):
                    raise RuntimeError(reply["error"].get("message", "CDP error"))
                return reply.get("result", {})


def command(ws_url, method, params=None, cdp_http=CDP_HTTP):
    return asyncio.run(page_command(ws_url, method, params, cdp_http))


def pages(cdp_http=CDP_HTTP):
    return [item for item in get_json(cdp_http + "/json/list") if item.get("type") == "page"]


def select_page(items, preferred=None):
    if preferred:
        found = next((item for item in items if item.get("id") == preferred), None)
        if found:
            return found
    return next(
        (item for item in items if "cvent.com" in (item.get("url") or "")), items[-1] if items else None
    )


def evaluate(page, expression, cdp_http=CDP_HTTP):
    result = command(
        page["webSocketDebuggerUrl"], "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True}, cdp_http,
    )
    return result.get("result", {}).get("value")


def marker_script(marker):
    value = json.dumps(marker)
    return (
        f"window.name={value};Object.defineProperty(window,'__CVENT_BROWSER_RUNTIME_ID',"
        f"{{value:{value},configurable:false,writable:false}});"
    )


def initialize(job_dir=None, slot_id=None, authorized_name=None, authorized_event_id=None, authorized_event_key=None, viewer_url=None):
    current = Path(job_dir or CURRENT)
    slot = slot_by_id(int(slot_id or os.environ.get("CVENT_WORKER_SLOT", "1")))
    cdp_http = os.environ.get("CVENT_CDP_ORIGIN", slot.cdp_origin)
    api_origin = os.environ.get("CVENT_STEEL_API_ORIGIN", slot.api_origin)
    name = authorized_name or os.environ.get("CVENT_AUTHORIZED_EVENT_NAME", AUTHORIZED_NAME)
    version = get_json(cdp_http + "/json/version")
    items = pages(cdp_http)
    page = select_page(items)
    if not page:
        raise RuntimeError("Steel has no page target; refusing to create a second browser")
    marker = "cvent-runtime-" + uuid.uuid4().hex
    script = marker_script(marker)
    command(page["webSocketDebuggerUrl"], "Page.addScriptToEvaluateOnNewDocument", {"source": script}, cdp_http)
    evaluate(page, script + "window.__CVENT_BROWSER_RUNTIME_ID", cdp_http)
    browser_ws = ws_local(version["webSocketDebuggerUrl"], cdp_http)
    runtime = {
        "browserRuntimeId": marker,
        "steelWorkspaceId": current.name,
        "providerSessionId": slot.container_name,
        "workerSlot": slot.slot_id,
        "apiOrigin": api_origin,
        "cdpEndpoint": browser_ws,
        "cdpHttpOrigin": cdp_http,
        "viewerUrl": viewer_url or f"/api/jobs/{current.name}/viewer",
        "authorizedEventName": name,
        "authorizedEventId": authorized_event_id or os.environ.get("CVENT_AUTHORIZED_EVENT_ID", ""),
        "authorizedEventKey": authorized_event_key or os.environ.get("CVENT_AUTHORIZED_EVENT_KEY", ""),
        "targetBrowserIdentity": {
            "browser": version.get("Browser"),
            "browserWebSocketId": browser_ws.rsplit("/", 1)[-1],
            "targetId": page["id"],
            "marker": marker,
            "url": page.get("url"),
            "title": page.get("title"),
        },
        "createdAt": now(),
        "verifiedAt": None,
    }
    path = current / "browser-runtime.json"
    atomic(path, runtime)
    os.chmod(path, 0o600)
    return runtime


def load(path=RUNTIME):
    data = json.loads(Path(path).read_text())
    required = ("browserRuntimeId", "providerSessionId", "cdpEndpoint", "viewerUrl", "targetBrowserIdentity")
    if any(not data.get(item) for item in required):
        raise RuntimeError("Invalid BrowserRuntime")
    return data


def local_probe(runtime):
    cdp_http = runtime["cdpHttpOrigin"]
    version = get_json(cdp_http + "/json/version")
    if ws_local(version["webSocketDebuggerUrl"], cdp_http) != runtime["cdpEndpoint"]:
        raise RuntimeError("Steel browser identity changed")
    items = pages(cdp_http)
    page = select_page(items, runtime["targetBrowserIdentity"]["targetId"])
    if not page or page["id"] != runtime["targetBrowserIdentity"]["targetId"]:
        raise RuntimeError("Canonical target tab changed")
    marker = evaluate(
        page, "window.__CVENT_BROWSER_RUNTIME_ID || (window.name.startsWith('cvent-runtime-') ? window.name : null)",
        cdp_http,
    )
    if marker is None:
        evaluate(page, marker_script(runtime["browserRuntimeId"]) + "window.__CVENT_BROWSER_RUNTIME_ID", cdp_http)
        marker = runtime["browserRuntimeId"]
    if marker != runtime["browserRuntimeId"]:
        raise RuntimeError("Runtime marker mismatch")
    return {"marker": marker, "targetId": page["id"], "url": page.get("url"), "title": page.get("title")}


def tool_probe(runtime, script):
    environment = os.environ.copy()
    environment.update({
        "CVENT_JOB_DIR": str(Path(script[script.index("--runtime") + 1]).resolve().parent),
        "CVENT_WORKER_SLOT": str(runtime.get("workerSlot", 1)),
        "CVENT_CDP_ORIGIN": runtime["cdpHttpOrigin"],
        "CVENT_STEEL_API_ORIGIN": runtime["apiOrigin"],
        "CVENT_AUTHORIZED_EVENT_NAME": runtime["authorizedEventName"],
        "CVENT_AUTHORIZED_EVENT_ID": runtime.get("authorizedEventId", ""),
        "CVENT_AUTHORIZED_EVENT_KEY": runtime.get("authorizedEventKey", ""),
    })
    process = subprocess.run(script, cwd=ROOT, text=True, capture_output=True, timeout=45, env=environment)
    lines = process.stdout.splitlines()
    result = next(
        (json.loads(line.split("=", 1)[1]) for line in reversed(lines) if line.startswith("BROWSER_TOOL_RESULT=")),
        None,
    )
    if process.returncode or not result:
        return {"ok": False, "error": (process.stderr or process.stdout)[-800:]}
    return result


def probe(path=RUNTIME, full=True):
    path = Path(path)
    runtime = load(path)
    viewer = local_probe(runtime)
    result = {"ok": True, "browserRuntimeId": runtime["browserRuntimeId"], "viewer": viewer}
    if full:
        ego = tool_probe(
            runtime,
            ["node", "ego_direct.mjs", "--runtime", str(path), "--operation", "probe", "--params", "{}"],
        )
        result["ego"] = ego
        markers = [viewer.get("marker"), ego.get("marker")]
        targets = [viewer.get("targetId"), ego.get("targetId")]
        result["sameBrowserVerified"] = (
            len(set(markers)) == 1 and markers[0] == runtime["browserRuntimeId"] and len(set(targets)) == 1
        )
        if not result["sameBrowserVerified"]:
            raise RuntimeError("Cross-browser identity probe failed closed")
    runtime["targetBrowserIdentity"].update({"url": viewer["url"], "title": viewer["title"]})
    runtime["verifiedAt"] = now()
    runtime["identityProbe"] = result
    atomic(path, runtime)
    os.chmod(path, 0o600)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "probe", "status"])
    parser.add_argument("--runtime", default=str(RUNTIME))
    args = parser.parse_args()
    try:
        result = initialize(Path(args.runtime).parent) if args.command == "init" else (
            probe(Path(args.runtime)) if args.command == "probe" else load(Path(args.runtime))
        )
        print("BROWSER_RUNTIME_RESULT=" + json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        print("BROWSER_RUNTIME_RESULT=" + json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
