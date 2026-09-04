# CVENT Agent

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

Pi is explicitly configured as `anthropic/claude-sonnet-4-6`. The Anthropic key
is read only from `ANTHROPIC_API_KEY`; Azure production loads it from Key Vault
with a VM managed identity. No API key is accepted in the UI, source, Terraform
variables, or process command line.

## Local development

```bash
cd /Users/bp/cvent-one-shot
python3 -m pip install -r requirements.txt
npm ci
export CVENT_ENV=development
export CVENT_DEV_AUTH_SUBJECT=local-operator
export CVENT_DEV_AUTH_NAME='Local operator'
export CVENT_DEV_AUTH_ADMIN=1
export ANTHROPIC_API_KEY='<load from your secret manager>'
python3 -m uvicorn app:app --host 127.0.0.1 --port 8877
```

Open <http://127.0.0.1:8877>. Docker must be running. Local development auth is
explicit and cannot activate when `CVENT_ENV=production`.

The default server allowlist contains only the unpublished protected event
`(C+D) Medtrade Testing Clone 2`, event key
`e712e34c-6117-4d13-bf4c-8ed54cf2b495`. Additional test events must be supplied
through the deployment's server-side allowlist and explicitly authorized; RR
uploads never choose or authorize arbitrary Cvent targets.

## Safety model

The uploaded RR is the authority for normal event-scoped configuration. RR-driven
configuration is writable by default and does not require per-field approval or
scope IDs. Immediately before every write, `browser_tool.py` verifies:

1. the per-job BrowserActionGate is agent-owned;
2. the canonical event lease exists, is unexpired, and belongs to this job/token;
3. runtime, authorized-target, and live-page event identities match;
4. the target is not a protected publish, communication-send, attendee/contact,
   delete/archive, event-identity, or account-global action.

Only Ego direct in the job's canonical Steel Chromium may automate Cvent. The
viewer is display-only until explicit takeover. Related form edits can be grouped,
but each saved configuration group must receive fresh readback before navigation
or completion. Never publish/Go Live, send communications, delete/archive, access
attendees/contacts, mutate another event, or mutate reusable/global definitions.

Pi runs with `--no-builtin-tools`: it has no shell, generic read/write, process,
environment, or arbitrary-path access. The explicit
`extensions/cvent-job-tools.ts` extension exposes only fixed job-scoped
`cvent_*` capabilities. It invokes approved RR helpers and `browser_tool.py`
without a shell, passes helper subprocesses an allowlisted environment, and
never forwards Anthropic, Entra, or session secrets. Arbitrary JavaScript, raw
CDP, and browser cookie/storage/network access are not exposed to the model. When Cvent requires
SSO/MFA, the login-handoff capability keeps the same worker and browser alive,
gives the viewer to the user, and blocks further automation until control is
returned. The same persistent per-slot Chromium profile is reused across handoffs;
no authentication material is copied into prompts or logs.

Before Steel or Pi starts, a one-token Anthropic availability probe fails closed
when the approved account cannot serve requests. During execution, each section
uses a compact RR-derived mission and a verified event-local route. Admission Items
and Registration Types run as trusted multi-step Ego procedures: Pi chooses only
the section enum while reviewed code owns routes, locators, edits, saves, and
readback for every record without returning to the model between browser primitives.
The Pi-facing browser tool is read-only and exposes no selector-driven writes. Full
snapshots are reserved for unknown layouts or recovery. Discount creation uses only the fixed
RR-derived bulk-import workbook. Provider failure after zero writes is
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
