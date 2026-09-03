from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import signal
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import websockets
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.middleware.sessions import SessionMiddleware

from auth import EntraAuth, Identity
from browser_gate import BrowserGate
from browser_runtime import command as browser_command, load as load_browser_runtime, local_probe, pages as browser_pages, select_page, tool_probe
from control_store import ACTIVE_STATES, TERMINAL_STATES, ControlStore
from job_runner import JobRunner, UploadTooLarge, atomic_json, now, read_json
from runtime_config import DATA_ROOT, ROOT, authorized_events, browser_profile_dir, job_dir, validate_production_environment
from scope_manifest import load_manifest as load_scope_manifest
from workbook_ops import info as workbook_info_data, sheet as workbook_sheet_data, update as update_workbook_data

def session_secret() -> str:
    configured = os.environ.get("CVENT_SESSION_SECRET")
    if configured:
        return configured
    # Development restarts and multiple local workers must verify the same signed
    # session/CSRF cookie. Production still requires an approved external secret.
    path = DATA_ROOT / ".development-session-secret"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    return path.read_text().strip()


app = FastAPI(title="CVENT Agent", docs_url=None, redoc_url=None)
_session_secret = session_secret()
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret,
    session_cookie="cvent_agent_session",
    max_age=8 * 60 * 60,
    same_site="lax",
    https_only=os.environ.get("CVENT_ENV") == "production",
)
auth = EntraAuth()
app.include_router(auth.router)
store = ControlStore(DATA_ROOT / "control.db", slots=3, lease_seconds=int(os.environ.get("CVENT_LEASE_SECONDS", "30")))
runner = JobRunner(store)


def product_facing(value):
    if value == "PI_EGO":
        return "CVENT_EGO"
    if isinstance(value, str):
        return re.sub(r"\bpi(?:\s+agent)?\b", "CVENT Agent", value.replace(str(ROOT), "[CVENT Agent application]"), flags=re.I)
    if isinstance(value, list):
        return [product_facing(item) for item in value]
    if isinstance(value, dict):
        return {key: product_facing(item) for key, item in value.items()}
    return value


def current_user(request: Request, mutate: bool = False) -> dict:
    identity = auth.identity(request)
    if mutate:
        auth.validate_csrf(request)
    return store.ensure_user(identity.subject, identity.email, identity.display_name, identity.is_admin)


def authorize_job(identity: dict, job_id: str | None = None) -> dict:
    job = store.get_job(job_id) if job_id else store.latest_job(identity["subject"])
    if not job:
        raise HTTPException(404, "No job found")
    if job["owner_subject"] != identity["subject"] and not identity["is_admin"]:
        # Do not reveal whether another user's identifier exists.
        raise HTTPException(404, "No job found")
    return job


def directory_for(job: dict) -> Path:
    return job_dir(job["workspace_id"], job["id"])


def active_job(job: dict):
    return runner.active(job["id"])


def safe_job(job: dict, include_owner: bool = False) -> dict:
    result = {key: job.get(key) for key in (
        "id", "workspace_id", "event_id", "event_name", "original_filename", "state", "preferred_slot", "slot_id",
        "queued_at", "started_at", "finished_at", "heartbeat_at", "error", "uncertain", "created_at", "updated_at",
    )}
    if include_owner:
        result["owner_subject"] = job["owner_subject"]
    return result


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; connect-src 'self' ws: wss:; frame-src 'self'; object-src 'none'; base-uri 'self'",
    )
    if os.environ.get("CVENT_ENV") == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.on_event("startup")
def startup():
    validate_production_environment()
    runner.start_scheduler()


@app.on_event("shutdown")
def shutdown():
    runner.shutdown()


@app.get("/healthz")
def healthz():
    return {"ok": True, "workers": 3}


@app.get("/internal/leases/validate", include_in_schema=False)
def validate_internal_lease(request: Request, job_id: str, event_id: str):
    if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "Internal endpoint")
    token = request.headers.get("x-cvent-lease-token", "")
    if not token or not store.valid_event_lease(job_id, token, event_id):
        raise HTTPException(409, "Canonical event lease is absent, stale, or owned by another job")
    return Response(status_code=204)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    try:
        current_user(request)
    except HTTPException as exc:
        if exc.status_code == 401:
            return HTMLResponse(
                "<!doctype html><title>Forge · CVENT Agent</title><main style='font:16px system-ui;max-width:40rem;margin:10vh auto'>"
                "<h1>Forge CVENT Agent</h1><p>Sign in with your authorized Microsoft Entra account.</p>"
                "<a href='/auth/login'>SIGN IN</a></main>", status_code=401,
            )
        raise
    return HTMLResponse(
        (ROOT / "templates/index.html").read_text(),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache", "Expires": "0"},
    )


@app.get("/api/me")
def me(request: Request):
    identity = current_user(request)
    value = auth.me(request)
    value["workspace_id"] = identity["workspace_id"]
    return JSONResponse(value, headers={"Cache-Control": "no-store"})


@app.get("/api/events")
def events(request: Request):
    current_user(request)
    return [{"event_id": event.event_id, "name": event.name, "event_code": event.event_code}
            for event in authorized_events()]


@app.get("/api/jobs")
def jobs(request: Request):
    identity = current_user(request)
    return [safe_job(job) for job in store.list_jobs(identity["subject"])]


@app.get("/api/admin/jobs")
def admin_jobs(request: Request):
    identity = auth.require_admin(request)
    store.ensure_user(identity.subject, identity.email, identity.display_name, identity.is_admin)
    return [safe_job(job, include_owner=True) for job in store.list_jobs()]


@app.get("/api/admin/leases")
def admin_leases(request: Request):
    identity = auth.require_admin(request)
    store.ensure_user(identity.subject, identity.email, identity.display_name, identity.is_admin)
    return store.active_leases()


@app.get("/api/status")
def status(request: Request, job_id: str | None = None, worker_slot: int | None = None):
    identity = current_user(request)
    if worker_slot is not None and worker_slot not in range(1, store.slots + 1):
        raise HTTPException(400, "Worker profile must be 1, 2, or 3")
    job = None
    if job_id:
        job = authorize_job(identity, job_id)
    elif worker_slot is not None:
        job = next((item for item in store.list_jobs(identity["subject"], limit=1000)
                    if int(item.get("slot_id") or item.get("preferred_slot") or 1) == worker_slot), None)
    else:
        job = store.latest_job(identity["subject"])
    if not job:
        return JSONResponse({
            "status": "waiting_for_rr", "current_stage": "upload",
            "current_action": f"User {worker_slot or 1} is ready for an RR workbook",
            "completed": [], "review_required": [], "activity_log": [], "agent_process_running": False,
            "browser": {"running": False, "worker_slot": worker_slot},
            "browser_gate": {"ownership": "AGENT", "desiredOwnership": "AGENT"},
            "browser_strategy": "EGO DIRECT · JOB-ISOLATED STEEL RUNTIME", "automation_scope": scope_summary(),
            "events": len(authorized_events()), "selected_worker": worker_slot or 1,
        }, headers={"Cache-Control": "no-store"})
    directory = directory_for(job)
    state = read_json(directory / "state.json", {})
    persisted = store.get_job(job["id"])
    state.update({"job": safe_job(persisted), "run_mode": "mock", "browser_strategy": "EGO DIRECT · JOB-ISOLATED STEEL RUNTIME"})
    if persisted and persisted["state"] in TERMINAL_STATES:
        state.update({"status": persisted["state"], "current_action": persisted.get("error") or state.get("current_action")})
    if persisted and persisted["state"] == "queued":
        lease = next((item for item in store.active_leases()["events"] if item["event_id"] == persisted["event_id"]), None)
        if lease and lease["holder_job_id"] != persisted["id"]:
            holder = store.get_job(lease["holder_job_id"])
            state["current_action"] = (
                f"Queued — this event is currently leased by User {holder.get('slot_id') or holder.get('preferred_slot') or '?'}; "
                "a different authorized event can run concurrently"
            )
    state["automation_scope"] = scope_summary()
    state["activity_log"] = (directory / "activity.log").read_text(errors="replace").splitlines()[-200:] if (directory / "activity.log").exists() else []
    state["final_report"] = read_json(directory / "final-report.json", None)
    state["browser_gate"] = BrowserGate(directory).read()
    active = active_job(job)
    state["agent_process_running"] = bool(active and active.process and active.process.poll() is None)
    state["agent_pid"] = active.process.pid if state["agent_process_running"] else None
    state["agent_session_saved"] = bool(state.get("pi_session"))
    state["browser"] = {"running": bool(active), "worker_slot": active.slot_id if active else None,
                        "viewer_url": f"/api/jobs/{job['id']}/viewer" if active else None}
    saved_auth = read_json(directory / "auth-settings.json", {})
    state["auth_settings"] = {
        "organization_id": saved_auth.get("organization_id", ""),
        "authenticated_at": saved_auth.get("authenticated_at"),
        "cookies_saved": bool(saved_auth.get("authenticated_at") and saved_auth.get("profile_slot") and
                              browser_profile_dir(job["workspace_id"], int(saved_auth["profile_slot"])).exists()),
        "microsoft_sso_persistent": bool(saved_auth.get("microsoft_sso_persistent")),
        "cvent_cookie_count": saved_auth.get("cvent_cookie_count", 0),
        "microsoft_cookie_count": saved_auth.get("microsoft_cookie_count", 0),
    }
    workbook = directory / "input.xlsx"
    state["rr_version"] = str(workbook.stat().st_mtime_ns) if workbook.exists() else None
    if state["agent_process_running"] and state.get("process_started_at"):
        try:
            state["elapsed_seconds"] = max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(state["process_started_at"])).total_seconds()))
        except Exception:
            state["elapsed_seconds"] = 0
    else:
        state["elapsed_seconds"] = 0
    state.pop("pi_pid", None)
    state.pop("pi_session", None)
    return JSONResponse(product_facing(state), headers={"Cache-Control": "no-store"})


def scope_summary():
    try:
        scope = load_scope_manifest()
        return {"valid": True, "authority": scope["authority"], "counts": scope["counts"], "sha256": scope["sourceSha256"]}
    except Exception as exc:
        return {"valid": False, "error": str(exc)}


@app.get("/api/scope")
def automation_scope(request: Request):
    current_user(request)
    try:
        return JSONResponse(load_scope_manifest(), headers={"Cache-Control": "no-store"})
    except Exception as exc:
        raise HTTPException(500, f"Automation scope is invalid: {exc}") from exc


@app.post("/api/upload")
def upload(request: Request, rr: UploadFile = File(...), event_id: str = Form(...), worker_slot: int = Form(1)):
    identity = current_user(request, mutate=True)
    if worker_slot not in range(1, store.slots + 1):
        raise HTTPException(400, "Worker profile must be 1, 2, or 3")
    name = rr.filename or ""
    if not name.lower().endswith(".xlsx"):
        raise HTTPException(400, "Upload an .xlsx file")
    event = next((item for item in authorized_events() if item.event_id == event_id.lower()), None)
    if not event:
        raise HTTPException(403, "Event is not in the server-side authorization allowlist")
    job = store.create_job(identity, event, Path(name).name, preferred_slot=worker_slot)
    directory = job_dir(job["workspace_id"], job["id"])
    try:
        runner.create_files(
            job, rr.file, int(os.environ.get("CVENT_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
        )
        workbook_info_data(directory)  # Reject malformed/non-Excel input before it can be queued.
    except UploadTooLarge as exc:
        store.finish(job["id"], None, "failed", str(exc), False, identity["subject"])
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(413, str(exc)) from exc
    except Exception as exc:
        store.finish(job["id"], None, "failed", "Invalid RR workbook", False, identity["subject"])
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(400, "The uploaded file is not a valid .xlsx workbook") from exc
    return {"ok": True, "file": name, "job_id": job["id"], "event_id": event.event_id, "worker_slot": worker_slot}


@app.get("/api/workbook")
def workbook_info(request: Request, job_id: str | None = None):
    identity = current_user(request)
    return JSONResponse(workbook_info_data(directory_for(authorize_job(identity, job_id))), headers={"Cache-Control": "no-store"})


@app.get("/api/workbook/sheet")
def workbook_sheet(request: Request, name: str, start: int = 1, limit: int = 80, job_id: str | None = None):
    identity = current_user(request)
    return JSONResponse(workbook_sheet_data(directory_for(authorize_job(identity, job_id)), name, start, limit),
                        headers={"Cache-Control": "no-store"})


@app.patch("/api/workbook")
def update_workbook(request: Request, payload: dict, job_id: str | None = None):
    identity = current_user(request, mutate=True)
    job = authorize_job(identity, job_id)
    if job["state"] not in {"draft", "cancelled", "failed", "failed_prewrite", "review_required", "login_required"}:
        raise HTTPException(409, "This job is not editable in its current state")
    result = update_workbook_data(directory_for(job), payload, bool(active_job(job)))
    store.audit(identity["subject"], "workbook.updated", job["id"], {"saved": result["saved"]})
    return result


@app.post("/api/auth-settings")
def save_auth_settings(request: Request, job_id: str | None = None):
    identity = current_user(request, mutate=True)
    job = authorize_job(identity, job_id)
    _, active = require_active(identity, job["id"])
    directory = directory_for(job)
    runtime = load_browser_runtime(directory / "browser-runtime.json")
    page = select_page(browser_pages(runtime["cdpHttpOrigin"]), runtime["targetBrowserIdentity"]["targetId"])
    if not page:
        raise HTTPException(409, "No Cvent page is open in this job's Steel browser")
    live = local_probe(runtime)
    host = (urlparse(live.get("url", "")).hostname or "").lower()
    if not host.endswith("cvent.com") or "login" in live.get("url", "").lower():
        raise HTTPException(409, "Finish Cvent Microsoft SSO before saving login status")
    reply = browser_command(page["webSocketDebuggerUrl"], "Network.getAllCookies", {}, runtime["cdpHttpOrigin"])
    cookies = reply.get("cookies", [])
    organization_id = next((cookie.get("value", "") for cookie in cookies
                            if cookie.get("name") == "org-id" and cookie.get("domain", "").endswith("cvent.com")), "")
    if not organization_id:
        raise HTTPException(409, "Authenticated Cvent organization cookie was not found")
    facts = {
        "organization_id": organization_id,
        "microsoft_sso_persistent": any(cookie.get("name") == "ESTSAUTHPERSISTENT" for cookie in cookies),
        "cvent_cookie_count": sum(cookie.get("domain", "").endswith("cvent.com") for cookie in cookies),
        "microsoft_cookie_count": sum("microsoftonline.com" in cookie.get("domain", "") for cookie in cookies),
        "cvent_session_cookie_count": sum(
            cookie.get("domain", "").endswith("cvent.com") and cookie.get("session") is True for cookie in cookies
        ),
        "profile_slot": active.slot_id,
        "authenticated_at": now(),
    }
    path = directory / "auth-settings.json"
    atomic_json(path, facts)
    os.chmod(path, 0o600)
    store.audit(identity["subject"], "cvent_login.confirmed", job["id"], {"organization_id": organization_id})
    return {"ok": True, **facts}


@app.post("/api/start")
def start(request: Request, job_id: str | None = None):
    identity = current_user(request, mutate=True)
    job = authorize_job(identity, job_id)
    if not (directory_for(job) / "input.xlsx").exists():
        raise HTTPException(400, "Upload the RR workbook first")
    gate = BrowserGate(directory_for(job))
    if gate.read().get("ownership") != "AGENT":
        active = active_job(job)
        if not active and job["state"] in {"login_required", "failed_prewrite", "failed", "review_required"}:
            gate.initialize()
            store.audit(identity["subject"], "browser.stale_control_reset_on_start", job["id"], {})
        else:
            raise HTTPException(409, "Return browser control to the agent before starting")
    if not scope_summary().get("valid"):
        raise HTTPException(500, "Automation scope is invalid")
    try:
        runner.queue(job["id"], identity["subject"])
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "job_id": job["id"], "state": "queued"}


@app.post("/api/continue")
def continue_job(request: Request, job_id: str | None = None):
    identity = current_user(request, mutate=True)
    job = authorize_job(identity, job_id)
    gate = BrowserGate(directory_for(job))
    if gate.read().get("ownership") != "AGENT":
        active = active_job(job)
        if active and active.process and active.process.poll() is None:
            raise HTTPException(409, "Return browser control to the agent before continuing")
        # A completed/timed-out login handoff has no live browser or process to
        # return. Reset only that stale gate before acquiring a fresh worker.
        gate.initialize()
    try:
        runner.resume(job["id"], identity["subject"])
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "job_id": job["id"], "state": "queued"}


@app.post("/api/stop-agent")
def stop_agent(request: Request, job_id: str | None = None):
    identity = current_user(request, mutate=True)
    job = authorize_job(identity, job_id)
    try:
        runner.stop(job["id"], identity["subject"], uncertain=job["state"] in ACTIVE_STATES)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "job_id": job["id"]}


def require_active(identity: dict, job_id: str):
    job = authorize_job(identity, job_id)
    active = active_job(job)
    if not active:
        raise HTTPException(503, "This job does not currently own a browser worker")
    return job, active


@app.post("/api/open-browser")
def open_browser(request: Request, job_id: str | None = None):
    identity = current_user(request, mutate=True)
    job = authorize_job(identity, job_id)
    active = active_job(job)
    if not active:
        raise HTTPException(409, "Start or continue the job to acquire an isolated browser worker")
    runtime_path = directory_for(job) / "browser-runtime.json"
    if not runtime_path.exists():
        return {"running": False, "starting": True, "worker_slot": active.slot_id}
    runtime = load_browser_runtime(runtime_path)
    return {"running": True, "worker_slot": active.slot_id, "browserRuntime": runtime, "displayOnly": True}


@app.get("/api/jobs/{job_id}/viewer", response_class=HTMLResponse)
def steel_viewer(request: Request, job_id: str):
    identity = current_user(request)
    _, active = require_active(identity, job_id)
    slot = __import__("runtime_config").slot_by_id(active.slot_id)
    try:
        with urllib.request.urlopen(slot.api_origin + "/v1/sessions/debug", timeout=10) as response:
            html = response.read().decode("utf-8")
    except Exception as exc:
        raise HTTPException(503, f"Job Steel viewer unavailable: {exc}") from exc
    ws_scheme = "wss" if request.url.scheme == "https" else "ws"
    ws_base = f"{ws_scheme}://{request.headers.get('host')}/api/jobs/{job_id}/viewer-ws"
    http_base = f"/api/jobs/{job_id}/steel"
    for host in ("0.0.0.0:3000", "127.0.0.1:3000", "localhost:3000"):
        html = html.replace("ws://" + host, ws_base).replace("http://" + host, http_base)
    safety = f"""<script>(()=>{{let user=false;const stop=e=>{{if(!user){{e.preventDefault();e.stopImmediatePropagation();try{{document.activeElement?.blur()}}catch{{}}}}}};['pointerdown','pointerup','pointermove','mousedown','mouseup','mousemove','click','dblclick','contextmenu','wheel','touchstart','touchmove','touchend','keydown','keyup','keypress','focusin'].forEach(n=>document.addEventListener(n,stop,{{capture:true,passive:false}}));async function sync(){{try{{const r=await fetch('/api/browser/ownership?job_id={job_id}',{{cache:'no-store'}}),d=await r.json();user=d.ownership==='USER'&&d.desiredOwnership==='USER';document.documentElement.dataset.controlOwner=user?'USER':'AGENT';document.body.style.pointerEvents=user?'auto':'none';if(!user)try{{document.activeElement?.blur()}}catch{{}}}}catch{{user=false;document.body.style.pointerEvents='none'}}}}sync();setInterval(sync,400)}})()</script>"""
    html = html.replace("</body>", safety + "</body>")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/api/jobs/{job_id}/steel/{path:path}")
def steel_http_proxy(request: Request, job_id: str, path: str):
    identity = current_user(request)
    _, active = require_active(identity, job_id)
    slot = __import__("runtime_config").slot_by_id(active.slot_id)
    url = f"{slot.api_origin}/{path}"
    if request.url.query:
        url += "?" + request.url.query
    try:
        with urllib.request.urlopen(url, timeout=20) as upstream:
            return Response(upstream.read(), status_code=upstream.status,
                            media_type=upstream.headers.get_content_type())
    except Exception as exc:
        raise HTTPException(502, f"Viewer proxy failed: {exc}") from exc


@app.websocket("/api/jobs/{job_id}/viewer-ws/{path:path}")
async def steel_websocket_proxy(websocket: WebSocket, job_id: str, path: str):
    try:
        identity_value = auth.identity(websocket)  # SessionMiddleware also populates WebSocket scopes.
        identity = store.ensure_user(identity_value.subject, identity_value.email, identity_value.display_name, identity_value.is_admin)
        _, active = require_active(identity, job_id)
    except HTTPException:
        await websocket.close(code=4403)
        return
    slot = __import__("runtime_config").slot_by_id(active.slot_id)
    upstream_url = f"ws://127.0.0.1:{slot.api_port}/{path}"
    if websocket.url.query:
        upstream_url += "?" + websocket.url.query
    gate = BrowserGate(directory_for(authorize_job(identity, job_id)))
    await websocket.accept()
    try:
        async with websockets.connect(upstream_url, origin=slot.api_origin, max_size=16 * 1024 * 1024) as upstream:
            async def client_to_upstream():
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        break
                    ownership = gate.read()
                    user_owned = ownership.get("ownership") == "USER" and ownership.get("desiredOwnership") == "USER"
                    # The cast stream needs no client message for display. Drop
                    # every mouse/key/navigation/clipboard message server-side
                    # until explicit, completed human takeover.
                    if not user_owned:
                        continue
                    if message.get("text") is not None:
                        await upstream.send(message["text"])
                    elif message.get("bytes") is not None:
                        await upstream.send(message["bytes"])

            async def upstream_to_client():
                async for message in upstream:
                    if isinstance(message, str):
                        await websocket.send_text(message)
                    else:
                        await websocket.send_bytes(message)

            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except (WebSocketDisconnect, websockets.ConnectionClosed):
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/api/browser/ownership")
def browser_ownership(request: Request, job_id: str | None = None):
    identity = current_user(request)
    job = authorize_job(identity, job_id)
    return JSONResponse(BrowserGate(directory_for(job)).read(), headers={"Cache-Control": "no-store"})


@app.post("/api/browser/take-control")
def take_control(request: Request, job_id: str | None = None):
    identity = current_user(request, mutate=True)
    job = authorize_job(identity, job_id)
    active = active_job(job)
    if not active or not active.process or active.process.poll() is not None:
        raise HTTPException(409, "CVENT Agent is not actively running")
    runtime = load_browser_runtime(directory_for(job) / "browser-runtime.json")
    local_probe(runtime)
    gate = BrowserGate(directory_for(job))
    gate.request_user()
    with gate.lock_file():
        os.killpg(active.process.pid, signal.SIGSTOP)
        value = gate.read()
        value.update({
            "ownership": "USER", "desiredOwnership": "USER", "activeActor": "USER", "automationOwner": "USER",
            "agentPaused": True, "pausedPids": [active.process.pid], "transition": None,
            "browserRuntimeId": runtime["browserRuntimeId"],
        })
        gate.write(value)
    store.audit(identity["subject"], "browser.take_control", job["id"], {})
    return {"ok": True, "gate": gate.read()}


@app.post("/api/browser/return-to-agent")
def return_to_agent(request: Request, job_id: str | None = None):
    identity = current_user(request, mutate=True)
    job = authorize_job(identity, job_id)
    directory = directory_for(job)
    gate = BrowserGate(directory)
    active = active_job(job)
    if not active or not active.process or active.process.poll() is not None:
        # A prior login handoff may outlive its worker. There is no process or
        # live browser to resume, so clear only this stale gate and require a
        # fresh runtime/lease/preflight on Continue.
        if gate.read().get("ownership") == "USER" and job["state"] in {"login_required", "failed_prewrite", "failed", "review_required"}:
            gate.initialize()
            store.audit(identity["subject"], "browser.return_stale_control", job["id"], {})
            return {"ok": True, "staleReset": True, "gate": gate.read(), "instruction": "Continue to acquire a fresh isolated browser runtime"}
        raise HTTPException(409, "CVENT Agent is not actively running")
    runtime_path = directory / "browser-runtime.json"
    runtime = load_browser_runtime(runtime_path)
    gate.shield_agent()
    with gate.lock_file():
        try:
            viewer = local_probe(runtime)
            ego = tool_probe(runtime, ["node", "ego_direct.mjs", "--runtime", str(runtime_path), "--operation", "snapshotText", "--params", "{}"])
            ego_page = tool_probe(runtime, ["node", "ego_direct.mjs", "--runtime", str(runtime_path), "--operation", "pageInfo", "--params", "{}"])
            if not ego.get("ok") or not ego_page.get("ok"):
                raise RuntimeError("Fresh Ego browser read failed")
            lock = read_json(directory / "authorized-target.json", {})
            if lock and (lock.get("event_id") != job["event_id"] or lock.get("event_key") != job["event_key"]):
                raise RuntimeError("Human left the authorized Cvent event; CVENT Agent remains paused")
            state = {"browserRuntimeId": runtime["browserRuntimeId"], "viewer": viewer, "ego": ego,
                     "egoPage": ego_page, "inspectedAt": now()}
            atomic_json(directory / "human-handoff-state.json", state)
            value = gate.read()
            value.update({
                "ownership": "AGENT", "desiredOwnership": "AGENT", "activeActor": "NONE",
                "automationOwner": "PI_EGO", "agentPaused": False, "pausedPids": [], "transition": None,
            })
            gate.write(value)
            os.killpg(active.process.pid, signal.SIGCONT)
        except Exception:
            value = gate.read()
            value.update({
                "ownership": "NONE", "desiredOwnership": "AGENT", "activeActor": "NONE",
                "automationOwner": "NONE", "transition": "RETURN_BLOCKED", "agentPaused": True,
            })
            gate.write(value)
            raise
    store.audit(identity["subject"], "browser.return_to_agent", job["id"], {})
    return {"ok": True, "gate": gate.read(), "state": state}
