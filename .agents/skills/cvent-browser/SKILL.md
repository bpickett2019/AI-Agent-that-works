---
name: cvent-browser
version: 7.0.0
description: Configure one exact server-selected existing Cvent event from its uploaded RR through adaptive bounded Ego operations.
---

# RR-driven adaptive Cvent configuration

Ego is the default live Cvent UI operator. The gateway attaches it to the job's
canonical Steel Chromium and persisted login. Specialized section procedures
are optional optimizations for high-volume or stable workflows, not a
prerequisite for ordinary navigation and editing.

The uploaded RR is the configuration authority. Normal event-scoped RR
requirements are writable without per-field approval when the exact existing
event, lease, editable lifecycle, non-destructive action, and RR source are all
proven. Never create or change the lifecycle of the event itself.

## Workflow

1. Compile and independently validate the uploaded RR with `cvent_prepare_rr`.
2. Read the complete mission and each populated domain once; do not reinterpret
   Excel while browsing.
3. Verify login; use `cvent_login_handoff` for human SSO/MFA only.
4. Find the exact selected event through authenticated inventory, open the one
   canonical name/key match, retain its observed lifecycle, and authorize it.
5. For every domain, inspect current state, dynamically map the live UI, compare
   exact identities, create missing event-local objects where proven safe,
   update differences, Save/autosave, and freshly read back.
6. Record item/domain evidence and continue end to end without routine pauses.
7. Run final RR-versus-Cvent QA and call `cvent_finish` exactly once.

## Adaptive Ego operations

Use `cvent_browser` for bounded semantic snapshots, control inventories,
navigation, clicks, fills, selections, checks, scrolling, waits, uploads, Save,
and readback. Use exact visible locators or selectors returned by the current
page; never guess a selector or use fuzzy identity. JavaScript, raw CDP,
credentials, cookies, storage, non-Cvent network access, and shell tools remain
unavailable.

After inspecting an editor, prefer `cvent_ego_actions` to execute its coherent
multi-action sequence and readback in one model tool call. This reduces model
round-trips without embedding event-specific routes or DOM assumptions in the
application. If an intermediate observation is needed, use a primitive action,
inspect again, and continue.

Use `cvent_execute_section` only when its existing bulk procedure genuinely
fits the current UI and makes the work faster or safer. If it encounters a
changed layout, continue with adaptive Ego rather than reporting that a bespoke
adapter is required. Use bulk import for very large discount sets.

Exact identity found means compare/update. Proven absent across the complete
relevant inventory means create only through a visibly event-local creation
control. Uncertain identity means hold that object; never rename or repurpose a
similar one. A missing control blocks only that property.

Every mutation uses `intent: write` and includes exact independently validated
`rrSource` evidence. Opening/navigating uses `intent: read`; a mutating control
cannot be disguised as a read. Verify every saved/autosaved group before
navigating away. Never replay an uncertain mutation.

## Mandatory safeguards

- Exact selected event identity, bound lifecycle, and active one-writer lease
  are required before every write.
- Never navigate to or write another event.
- Never publish/Go Live, delete/archive, or send/test/schedule communications.
- Never access or modify attendees, invitees, contacts, or their records.
- Never mutate account-global, shared Contact Type, profile-global, or reusable
  definitions.
- Preserve event name, code, ID/key, URL identity, and lifecycle status.
- Never bypass SSO/MFA/CAPTCHA, browser ownership, target lock, or uncertainty.
- Never expose credentials, tokens, cookies, environment values, or storage.

If a property genuinely cannot be identified or edited through the live Cvent
UI, hold only that property, continue all independent work, and report the
concrete Cvent capability gap.
