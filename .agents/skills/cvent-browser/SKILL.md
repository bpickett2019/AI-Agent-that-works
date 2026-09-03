---
name: cvent-browser
version: 2.0.0
description: Pi-controlled Ego and Browser Use tools for the one locked (C+D) Medtrade Clone 2 Steel Chromium.
---

# Cvent Browser Tools

Pi is the only reasoning agent. Run from `/Users/bp/cvent-one-shot` and pass the canonical runtime on every call:

```bash
RUNTIME=/Users/bp/cvent-one-shot/data/current/browser-runtime.json
```

## Priority 1 — Ego direct

Use `browser_tool.py --runtime "$RUNTIME" --tool ego` with operations:

`snapshotText`, `pageInfo`, `click`, `fill`, `type`, `navigate`, `openOrReuseTab`, `js`, `cdp`, `wait`, `tabs`, `switchTab`, `authorizeTarget`.

Examples:

```bash
./browser_tool.py --runtime "$RUNTIME" --tool ego --operation snapshotText --params '{}'
./browser_tool.py --runtime "$RUNTIME" --tool ego --operation fill --params '{"target":"input[aria-label=Search]","text":"(C+D) Medtrade Clone 2","intent":"read"}'
```

Discovery is read-only. After exactly one literal clone match is open and visible, call `authorizeTarget` with `{"eventName":"(C+D) Medtrade Clone 2","intent":"read"}`. This creates the required event-key lock.

## Priority 2 — Browser Use direct

Use `--tool browser-use` for: `browser_get_state`, `browser_navigate`, `browser_click`, `browser_type`, `browser_scroll`, `browser_extract_content`, `tabs`, `wait`, `send_keys`.

Browser Use indices come from `browser_get_state`. It is direct tooling; Pi chooses every action.

## Priority 3 — bounded autonomous fallback

Use only when direct tools are not progressing:

```bash
./browser_tool.py --runtime "$RUNTIME" --tool fallback \
  --operation retry_with_browser_use_agent --params "$CONTRACT"
```

The JSON contract must include exact `eventId`, `eventName`, `resourceDomain`, `expectedState`, `allowedActions`, `prohibitedActions`, and `successCriteria`. After fallback, verify independently with Ego.

## Hard rules

- Every call is serialized by BrowserActionGate.
- A runtime marker mismatch, wrong target ID, wrong event key, or USER ownership fails closed.
- Use `intent: write` for mutations and `intent: read` for discovery/inspection.
- Only `(C+D) Medtrade Clone 2` is authorized.
- Never publish/go live, send/test/schedule communications, delete/archive, access attendees/contacts, mutate another event, or modify reusable/account-global/profile fields.
- Keep one Steel Chromium and one Cvent execution path. No concurrent Ego task spaces.
