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
```

Every browser operation must use:

```bash
./browser_tool.py --runtime "$RUNTIME" --tool ego \
  --operation <operation> --params '<json>'
```

Ego is the only browser tool. Do not create another browser, Steel session, task space, profile, or tab.

## Operations

- Reads: `snapshotText`, `pageInfo`, `tabs`, `probe`
- Natural movement/search: `scroll`, `scanEventList`, `wait`
- Interaction: `click`, `fill`, `type`
- Bounded escape hatches: `js`, `cdp`
- Target authorization: `authorizeTarget`

On unfamiliar pages: observe → read → scroll → understand → interact → reread. Do not default to Advanced Search or direct URL hopping.

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

For each RR-derived domain:

1. Read the normalized expected state.
2. Snapshot and scroll through the complete relevant Cvent interface.
3. Compare existing objects semantically.
4. Keep correct objects, create missing objects, and minimally update safe differences.
5. Save meaningful draft changes.
6. Fresh-read and verify persistence and no duplicates.
7. Continue through the remaining domains without routine user pauses.

Use `intent: write` for every potentially mutating operation and `intent: read` for inspection. Known repeated operations may use Ego JS/CDP only after the interaction is fully understood and independently verified.

## Ownership and safety

- Ego owns the browser action gate as `PI_EGO` while operating.
- USER takeover is separate and explicit.
- Runtime marker, canonical target ID, and event key must match before every write.
- Only `(C+D) Medtrade Testing Clone 2` may be opened or modified.
- Never publish/go live, send/test/schedule communications, delete/archive, access attendees/contacts, mutate another event, or modify reusable/account-global/profile fields.
- Preserve event name, code, event key, URL identity, and unpublished status.
