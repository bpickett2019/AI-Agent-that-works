---
name: ego-browser
description: Operate the exact job-bound Cvent event using Ego semantic snapshots, coherent multi-action Node.js heredoc rounds, screenshots, mouse, keyboard, forms, Save and readback.
---

# Ego browser — job-bound runtime

Use `bash` with `ego-browser nodejs <<'EOF' ... EOF`. The existing Ego executor
is pinned to this job's Steel tab, browser identity and event lease. Do not open
another browser or switch events. There is no general-purpose shell.

First load the verified RR with `cvent_prepare_rr`. Verify authentication with
`cvent_login_handoff`, then use `cvent_browser` for the existing target binding:
`scanEventList` → `openAuthorizedEvent` → `authorizeTarget`, each with intent
`read`. These are identity checks, not section-specific configuration adapters.
Then operate the live UI yourself with Ego. Read this skill once, not every turn.

Every browser round has one small authorization header, not per-field approval:

```bash
ego-browser nodejs <<'EOF'
// cvent: {"domain":"event_settings","commitMode":"read_only"}
await useOrCreateTaskSpace('configure selected event')
cliLog(await pageInfo())
cliLog(await snapshotText())
EOF
```

For writes, use `commitMode: "save"` (or `"autosave"` only for a proven autosaving
editor) and `rrSources: ["Exact Sheet!B7", ...]` copied from VERIFIED plan evidence.
All non-read actions use write intent in a write round. `click(target,
{intent:'read'})` is available for Edit, tabs and purely navigational controls.
When the header has multiple sources, supply `{rrSource:'Exact Sheet!B7'}` as the
last argument to each mutating helper. With one source it is the default.
No mutation is permitted in `read_only` rounds. Never invent RR sources.

## Helpers

- `useOrCreateTaskSpace(name)` reuses this job's pinned space; never creates another runtime.
- `pageInfo()` returns current page information.
- `snapshotText()` returns Ego's full semantic snapshot. Copy `@N` refs from the
  latest snapshot; do not guess them. Use stable CSS/exact role locators when
  actually observed. A fresh snapshot invalidates old refs.
- `click(target, options?)`, `doubleClick([x,y], options?)`, `hover(target)`.
- `fillInput(target, text, options?)`, `typeText(text, options?)`.
- `selectOption(target, exactLabel, options?)`; options may contain `optionBy:'value'`.
- `setChecked(target, boolean, options?)` checks/unchecks a checkbox.
- `pressKey(key, options?)`, with optional `target` and `rrSource`.
- `scrollBy(dy)`, `scroll({dy})`, `dragMouse([[x,y],[x,y]], options?)`.
- `wait(seconds)`, `waitForElement(target)`; waits are seconds, not milliseconds.
- `gotoAndWait(url)` / `openOrReuseTab(url)` navigate the pinned tab within the exact event.
- `readTarget(target)` returns fresh text/value/checked state.
- `captureScreenshot()` captures and returns the image through the tool result.
- `cliLog(value)` returns data to Pi; no console, process, filesystem, fetch or raw CDP API.

This deployed runtime exposes the helpers above, not arbitrary website/network
APIs. Use semantic workflow for ordinary forms. For visual/virtualized editors,
use screenshots with coordinate clicks and real keyboard operations. Inspect
modals with snapshots and operate their visible buttons. Do not bypass login,
MFA or user takeover. Use `cvent_login_handoff` when authentication is required.

## Coherent execution

Observe → make all predictable moves → Save → wait for readiness → read back →
continue. A script can branch on fresh snapshots and loop over exact RR-backed
records without returning to the model after every primitive. Do not call a
section adapter merely because a form is unfamiliar.

Save is a real click on the observed Save button. After Save, take a fresh
snapshot, targeted read or screenshot and inspect that evidence. Navigation
before Save/readback is blocked. A round ending with unverified changes is
contained as uncertain; do not replay it. A screenshot is an observation, not
proof that all desired values match. Record actual item-level verification with
`cvent_verify_domain`.

Exact identity found → update. Proven absent → create event-local configuration.
Uncertain/fuzzy identity → hold that item and continue independent work. Keep
existing unrelated objects and associations unchanged. Never delete, archive,
create/rename an event, publish/Go Live, send/test/schedule communications,
access attendees/contacts, mutate global definitions, or leave the selected event.
