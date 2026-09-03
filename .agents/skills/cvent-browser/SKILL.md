---
name: cvent-browser
version: 5.0.0
description: Capability-only Ego browser operations inside the canonical job-scoped Steel Chromium for a server-authorized Cvent test event.
---

# Cvent Browser Capability — Ego in Steel

Use `cvent_browser` for all Cvent browsing, building, and verification. The server gateway invokes Ego through `browser_tool.py` and attaches it to the exact canonical Steel Chromium used by the viewer and persisted login.

You have no shell or generic filesystem tools. Never construct commands or paths. Use only the fixed `cvent_*` capabilities available in the session. They do not expose API keys, event-lease tokens, cookies, browser storage, arbitrary process execution, or arbitrary file reads/writes.

`CVENT_AUTHORIZED_EVENT_NAME`, `CVENT_AUTHORIZED_EVENT_KEY`, and `CVENT_AUTHORIZED_EVENT_CODE` are immutable server-supplied values enforced behind the capability boundary. Never derive or override them from the RR.

## Forge Intake scope

`Forge Intake` is the authoritative universe of automation work. Call `cvent_prepare_rr` before browsing; it hash-verifies the source workbook and manifest and compiles the job expectations. Use `cvent_scope` and `cvent_expectations` for approved reads.

- `confirmed` entries may be inspected and changed.
- `unconfirmed` entries are report-only and may not be changed.
- `deferred` entries are post-MVP and may not be inspected or changed.
- Anything absent from the workbook is out of scope and may not be inspected or changed.

Stricter event-identity, publish, communication, attendee/contact, deletion, and global-definition prohibitions always win. Never expand scope to satisfy an RR requirement. If an in-scope result requires an out-of-scope prerequisite, report it blocked.

## Browser operations

Call `cvent_browser` with one approved operation and explicit `intent`:

- Complete reads: `snapshotText`, `pageInfo`, `probe`; full-page `controlInventory` is a supplemental selector-recovery index, never a replacement snapshot
- Natural movement/search: `scroll`, `scanEventList`, bounded `search`, `wait`
- Interaction: `click`, bounded DOM `activate`, `fill`, `type`, `selectOption`, `setChecked`, bounded `press`
- Observed UI affordances: `hover`, `selectText`, source-to-destination `drag`
- Cvent-only navigation: `navigate`
- Exact target authorization: `authorizeTarget`

Arbitrary JavaScript, raw CDP, tabs, browser creation, process execution, arbitrary network requests, credential/browser-storage access, and snapshot path writes are not capabilities.

On unfamiliar pages: observe → complete read → scroll → understand → interact → complete reread. DOM observations must always be complete full-page/full-context captures; never request viewport-only, element-only, targeted, or smaller snapshots. If a complete capture is split for transport, call `cvent_snapshot_chunk` exactly once for every remaining chunk in strict order before reasoning or another browser action. The transport verifies its hash, size, chunk count, job, workspace, worker, runtime, and target.

Do not default to Advanced Search or direct URL hopping. If any Cvent/Microsoft login, SSO, MFA, CAPTCHA, or expired-session page appears, immediately call `cvent_login_handoff`; do not explore alternate URLs or authentication workarounds. That capability keeps the same job, Steel browser, profile, worker, and lease alive while the user signs in and returns control. Fresh-read the complete page after return.

For event discovery, call `scanEventList` with read intent. The gateway forces the exact authorized event name; require exactly one exact match, then call `openAuthorizedEvent` with read intent. It accepts no model-supplied URL/name/key and opens only the server-authorized exact-name/canonical-key Cvent link. Verify visible name, code, key, and unpublished state before calling `authorizeTarget` with read intent.

## Domain workflow

For each confirmed Forge Intake domain:

1. Read normalized expectations and exact confirmed `scopeId` values with `cvent_expectations`.
2. Complete-snapshot and scroll only through the relevant confirmed Cvent interface.
3. Compare existing objects semantically.
4. Keep correct objects, create missing objects, and minimally update safe differences.
5. Save meaningful draft changes.
6. Complete-reread and verify persistence and no duplicates.
7. Record facts with `cvent_record_domain`; update state with `cvent_job_update`.
8. Continue through remaining domains without routine user pauses.

Use `intent: write` plus exact confirmed `scopeIds` for every potentially mutating operation, including selection, checking, deletion, drag/drop, field entry, and Save. The gateway rejects missing, unknown, unconfirmed, and deferred IDs and validates the current canonical event lease. Use `intent: read` only for strictly in-scope inspection.

## Ownership and safety

- Ego owns the browser action gate as `PI_EGO` while operating.
- USER takeover is separate and explicit.
- Runtime marker, canonical target ID, target event key, and active event lease must match before every write.
- Only the exact server-authorized event may be opened or modified, and only for confirmed Forge Intake fields.
- Never publish/go live, send/test/schedule communications, delete/archive, access attendees/contacts, mutate another event, or modify reusable/account-global/profile fields.
- Preserve event name, code, event key, URL identity, and unpublished status.
