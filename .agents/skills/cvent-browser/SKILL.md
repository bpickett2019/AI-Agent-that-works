---
name: cvent-browser
version: 4.0.0
description: Ego browser operations inside the canonical Steel Chromium for the locked (C+D) Medtrade Testing Clone 2 event.
---

# Cvent Browser Tools — Ego in Steel

Use Ego direct for all Cvent browsing, building, and verification. Ego attaches to the exact canonical Steel Chromium used by the viewer and persisted login.

```bash
cd /Users/bp/cvent-one-shot
RUNTIME=/Users/bp/cvent-one-shot/data/current/browser-runtime.json
SCOPE=/Users/bp/cvent-one-shot/scope/intake-emerald-scope.json
```

Every browser operation must use:

```bash
./browser_tool.py --runtime "$RUNTIME" --tool ego \
  --operation <operation> --params '<json>'
```

Ego is the only browser tool. Do not create another browser, Steel session, task space, profile, or tab.

## Forge Intake scope

`scope/intake-emerald.xlsx` is the authoritative universe of automation work. Verify and use `scope/intake-emerald-scope.json` before browsing:

- `confirmed` entries may be inspected and changed.
- `unconfirmed` entries are report-only and may not be changed.
- `deferred` entries are post-MVP and may not be inspected or changed.
- Anything absent from the workbook is out of scope and may not be inspected or changed.

Stricter event-identity, publish, communication, attendee/contact, deletion, and global-definition prohibitions always win. Never expand scope to satisfy an RR requirement. If an in-scope result requires an out-of-scope prerequisite, report it blocked.

## Operations

- Reads: `snapshotText`, `pageInfo`, `tabs`, `probe`
- Natural movement/search: `scroll`, `scanEventList`, `wait`
- Interaction: `click`, `fill`, `type`
- Bounded escape hatches: `js`, `cdp`
- Target authorization: `authorizeTarget`

On unfamiliar pages: observe → read → scroll → understand → interact → reread. DOM observations must always remain complete full-page/full-context reads; never use viewport-only, element-only, truncated, targeted, or smaller DOM snapshots as a performance shortcut. Targeted readiness checks may supplement but never replace complete reads. Do not default to Advanced Search or direct URL hopping.

## Event discovery

Cancel any stale Advanced Search form and scan a normal list view:

```bash
./browser_tool.py --runtime "$RUNTIME" --tool ego \
  --operation scanEventList \
  --params '{"intent":"read","exactName":"(C+D) Medtrade Testing Clone 2","maxScrolls":30}'
```

Require exactly one exact match before opening it. The only authorized target is:

- Name: `(C+D) Medtrade Testing Clone 2`
- Event key: `e712e34c-6117-4d13-bf4c-8ed54cf2b495`
- Event code: `NLNMYJD28PH`

## Domain workflow

For each confirmed Forge Intake domain:

1. Read the normalized expected state and its exact confirmed `scopeId` values.
2. Snapshot and scroll only through the relevant confirmed Cvent interface.
3. Compare existing objects semantically.
4. Keep correct objects, create missing objects, and minimally update safe differences.
5. Save meaningful draft changes.
6. Fresh-read and verify persistence and no duplicates.
7. Continue through the remaining domains without routine user pauses.

Use `intent: write` plus exact confirmed `scopeIds` for every potentially mutating operation, including Save. The router rejects missing, unknown, unconfirmed, and deferred IDs. Use `intent: read` only for strictly in-scope inspection. Known repeated operations may use Ego JS/CDP only after the interaction is fully understood and independently verified.

## Ownership and safety

- Ego owns the browser action gate as `PI_EGO` while operating.
- USER takeover is separate and explicit.
- Runtime marker, canonical target ID, and event key must match before every write.
- Only `(C+D) Medtrade Testing Clone 2` may be opened or modified, and only for confirmed Forge Intake fields.
- Never publish/go live, send/test/schedule communications, delete/archive, access attendees/contacts, mutate another event, or modify reusable/account-global/profile fields.
- Preserve event name, code, event key, URL identity, and unpublished status.
