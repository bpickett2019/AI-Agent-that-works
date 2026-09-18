# AI Agent that works

## Current version: restored Monday local runner

This fork restores the September 14, 2026 morning **Astra + Simple Mode** runner.
See [recovery provenance and limitations](docs/MONDAY-ROLLBACK-2026-09-14.md).
Normal, RR-authorized configuration edits and Save/readback are **enabled**, not
read-only. The signed-in Cvent account must have edit rights to the selected event;
this application cannot grant or bypass Cvent account permissions. Publishing,
communication sends, deletion, cross-event and account-global changes stay blocked.

For a fresh checkout, use Python 3.11+ and the locally installed Pi with your
existing ChatGPT/Codex OAuth login:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm ci
cp .env.example .env.local
# Edit .env.local: supply your exact authorized Cvent event UUID, name and code.
unset ANTHROPIC_API_KEY OPENAI_API_KEY
python -m uvicorn app:app --env-file .env.local --host 127.0.0.1 --port 8880
```

Open <http://127.0.0.1:8880>. Docker must be running. Select the approved event,
upload the RR, then explicitly start the build and complete Cvent login when asked.
Starting the UI alone does not run a build. Empty, draft and finished workspaces
make no background polling requests after their initial page load. Live status
polling is enabled only for an active job with a stored RR workbook and bound
event; these local status requests never call the model. Uploading alone does
not spend model tokens—START BUILD/CONTINUE must be explicitly requested.
An existing active job retains its stored workbook/target even when new-upload
fields are blank; its loaded workbook and bound target are displayed separately.
`.env.local`, OAuth credentials,
workbooks, browser profiles and job logs are not committed. Without the explicit
Simple Mode/Codex settings, the inherited code defaults to Anthropic/controlled mode.

## Upstream architecture and alternative deployments

Forge CVENT Agent production V1 supports Microsoft Entra authentication and up
to three simultaneous, isolated jobs on one Azure VM. Users can access only
their own workspaces/jobs; administrators receive all-job and lease visibility.

Each active job has its own Pi process/session/config, pinned Steel container,
Chromium profile/cache, API/CDP endpoints, BrowserRuntime, Ego process calls,
BrowserActionGate, authenticated viewer, files, logs, evidence, and report.
SQLite/WAL provides crash-safe host-wide worker and canonical Cvent event leases.
Jobs for different approved events can use all three workers. A same-event job
or a fourth simultaneous job is rejected immediately with HTTP 409 and remains
safely restartable; V1 has no waiting queue.

The inherited production default is `anthropic/claude-sonnet-4-6`. The Anthropic key
is read only from `ANTHROPIC_API_KEY`; Azure production loads it from Key Vault
with a VM managed identity. No API key is accepted in the UI, source, Terraform
variables, or process command line.

## Local ChatGPT subscription / Astra

The local-only Simple Mode runner can use `openai-codex/gpt-6-astra` through the
operator's existing Pi OAuth login. It does not use an OpenAI API key or the
Anthropic key. This is explicitly rejected in staging/production.

Keep the existing local data root, authorized-event list, identity, and loopback
lease URL, and start the server with these additional settings:

```bash
export CVENT_ENV=development CVENT_EXECUTION_MODE=simple CVENT_LOCAL_CODEX=1
export CVENT_PI_PROVIDER=openai-codex CVENT_PI_MODEL=gpt-6-astra
export CVENT_PI_AUTH_FILE="$HOME/.pi/agent/auth.json"
# From /Users/bp/cvent-local-dynamic, with the existing local settings:
python3 -m uvicorn app:app --host 127.0.0.1 --port 8878
```

`local_codex.py` validates private, operator-owned OAuth storage. The Pi SDK
launcher uses its canonical path for shared refresh locking while retaining
per-job settings, sessions, and the existing restricted Cvent extension/tools.
Credentials are never copied into job directories. Startup performs a no-tools
subscription availability probe before Steel or Cvent; quota exhaustion still
fails closed. No fallback to another model or API billing is allowed.

A successful provider probe or workbook-read smoke test is **not** evidence of a
completed Cvent build. A live full-RR run still requires the selected event,
user authentication, and persisted readback verification.

## Emergency Simple Mode

Set `CVENT_EXECUTION_MODE=simple` in the server environment and restart with no active leases. The unchanged UI launches one Pi mission with the original RR evidence and selected event. Pi owns its checklist, Ego actions, Save/readback and recovery; the legacy domain/adaptor/provenance/atomic-round controller is bypassed. Browser ownership, canonical-event leases, target checks, permanent action blocks and audits remain. Owned reads remain available on error/login pages so Pi can recover; mutations still require live target/authentication proof. Ego stdout is saved as readable text. Final reporting preserves Pi's QA and counts native UI edits, Save clicks and acknowledged commit observations separately. Use assisted rollout until live full-RR completion is established; unit tests alone are not acceptance.

## Local development

For **offline dynamic Excel → Pi → Ego regression checks**, run
`bash scripts/test_local_dynamic.sh` from this checkout. No API key, SSO, live
browser, or deployment is needed. See [local implementation and test scope](docs/LOCAL-DYNAMIC-EXCEL-EGO.md).

The server command below is separate: even on localhost, starting a live job
can contact the model provider and Cvent. Do not use it for offline validation.

```bash
cd /Users/bp/cvent-one-shot
python3 -m pip install -r requirements.txt
npm ci
export CVENT_ENV=development
export CVENT_EXECUTION_MODE=simple
export CVENT_DEV_AUTH_SUBJECT=local-operator
export CVENT_DEV_AUTH_NAME='Local operator'
export CVENT_DEV_AUTH_ADMIN=1
export ANTHROPIC_API_KEY='<load from your secret manager>'
python3 -m uvicorn app:app --host 127.0.0.1 --port 8877
```

Open <http://127.0.0.1:8877>. Docker must be running. Local development auth is
explicit and cannot activate when `CVENT_ENV=production`.

For the original **target → upload → browser → login → execute** flow, configure
`CVENT_AUTHORIZED_EVENTS_JSON` (or its base64 equivalent `CVENT_AUTHORIZED_EVENTS_B64`)
with an explicit list of `{event_id, event_key, name, event_code}` objects. IDs must
be the same canonical Cvent UUID. That list is available before Cvent login, so
intake does not depend on an authenticated browser. Without explicit configuration,
selection uses the workspace's authenticated inventory as before.

After START BUILD, the existing worker launches Steel and Pi; login happens in that
browser. `openAuthorizedEvent` must independently re-resolve the selected exact
identity in live Cvent before writes. Intake authorization is not live target proof,
and RR content never selects or changes event identity.

## Safety model

The uploaded RR is the authority for normal event-scoped configuration. RR-driven
configuration is writable by default and does not require per-field approval or
scope IDs. Immediately before every write, `browser_tool.py` verifies:

1. the per-job BrowserActionGate is agent-owned;
2. the canonical event lease exists, is unexpired, and belongs to this job/token;
3. runtime, authorized-target, and live-page canonical event identity match;
4. the requested event-local controls are visibly editable (lifecycle labels do not impose a blanket block);
5. the target is not a protected publish, communication-send, attendee/contact,
   delete/archive, event-identity, or account-global action.

Only Ego direct in the job's canonical Steel Chromium may automate Cvent. The
viewer is display-only until explicit takeover. Related form edits can be grouped,
but each saved configuration group must receive fresh readback before navigation
or completion. Never publish/Go Live, send communications, delete/archive, access
attendees/contacts, mutate another event, or mutate reusable/global definitions.

Pi runs with `--no-builtin-tools` and explicitly registered job-bound `read`,
`bash`, and `cvent_*` tools. `read` loads the Ego skill and verified RR artifacts;
`bash` accepts upstream `ego-browser nodejs` heredocs, not general shell commands.
The upstream skill is vendored at the commit recorded in
`skills/ego-browser/UPSTREAM_COMMIT`; its TaskSpace/Page behavior is securely
bound to the existing Steel tab. The executor runs coherent scripts with
per-action event/lease, RR-source, protected-control and Save/readback checks. No
section adapter is required. The explicit `extensions/cvent-job-tools.ts` extension
invokes approved RR helpers and `browser_tool.py`
without a shell, passes helper subprocesses an allowlisted environment, and
never forwards Anthropic, Entra, or session secrets. General host JavaScript, raw CDP, and browser cookie/storage/network APIs are
not exposed; browser scripts receive only the documented Ego helper surface. When Cvent requires
SSO/MFA, the login-handoff capability keeps the same worker and browser alive,
gives the viewer to the user, and blocks further automation until control is
returned. The same persistent per-slot Chromium profile is reused across handoffs;
no authentication material is copied into prompts or logs.

Before Steel or Pi starts, a one-token Anthropic availability probe fails closed
when the approved account cannot serve requests. During execution, each section uses a compact validated RR-derived mission. Ego
observes the current Cvent UI semantically (`snapshotText`) or visually
(`screenshot`), copies native refs from the latest semantic snapshot, then
executes all currently predictable navigation, mouse, keyboard, form, Save, and
verification actions continuously in one model tool call and one Ego process
(up to 80, without treating 80 as a target). Ordinary known sections target 1–3
model turns. Primitive calls are reserved for genuinely state-dependent recovery.
Turn telemetry flags `MODEL_RESPONSE_WITH_ZERO_PROGRESS`, excess section calls,
and low-action coherent rounds; the final performance summary reports model
turns, turns with action, zero-progress turns, Ego rounds, action density, and
model/browser/total time per section. Existing section procedures remain optional high-volume
optimizations rather than write prerequisites. Pi may also execute coherent
Node.js helper heredocs using the loaded `skills/ego-browser/SKILL.md`; raw CDP
and general host APIs remain unavailable. Discount creation may use the fixed RR-derived
bulk-import workbook. Provider failure after zero writes is
`failed_prewrite`; after conclusively read-back writes it is
`failed_recoverable` and resumes with fresh state/delta computation; only an
unresolved mutation is `failed_uncertain` and blocks replay.

## Validation

```bash
npm test
python3 -m compileall -q .
docker compose --profile manual config
```

The manual Compose profile exposes the same three localhost-only diagnostic slot
pairs used by the app: `3005/9334`, `3006/9335`, and `3007/9336`. Normally the
application creates/removes the pinned Steel containers dynamically so each
container mounts only its active job's private profile.

## Azure deployment

See [`docs/PRODUCTION-V1.md`](docs/PRODUCTION-V1.md) and
[`infra/terraform`](infra/terraform). The design intentionally does not use AKS,
Service Bus, or a distributed database until measured pilot demand justifies a
scale-out architecture.

The audited pre-refactor map is in
[`docs/CURRENT-STATE-AUDIT.md`](docs/CURRENT-STATE-AUDIT.md). Performance notes
are in [`docs/PERFORMANCE-NOTES.md`](docs/PERFORMANCE-NOTES.md). Complete
section-level state collection and fresh targeted verification after each saved
configuration group remain mandatory; repeated full-page snapshots are not.
