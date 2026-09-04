---
name: cvent-browser
version: 6.0.0
description: Configure one exact server-selected existing Cvent event from its uploaded RR through bounded Ego operations.
---

# RR-driven Cvent configuration

Use `cvent_browser` for all Cvent reading, configuration, and verification. The gateway attaches Ego to the job's canonical Steel Chromium and persisted login.

The uploaded RR is the configuration authority. Normal event-scoped RR requirements are writable by default and do not require per-field scope IDs or manual approval. Do not create an event. Configure only the exact existing event selected by the server.

## Workflow

1. Compile the uploaded RR with `cvent_prepare_rr`.
2. Read all populated domains with `cvent_expectations`.
3. Verify login; use `cvent_login_handoff` for human SSO/MFA when needed.
4. Find the exact selected event through the authenticated inventory, open it, verify name/key and Draft state, and call `authorizeTarget`.
5. For every RR domain, compare current state, create missing event-scoped configuration, minimally update differences, save, and reread.
6. Record domain results and continue without routine approval pauses.
7. Run final QA and always call `cvent_finish`, which terminates the agent so the controller releases the browser worker and event lease.

Use `intent: write` for mutations. An optional `rrSource` can identify the relevant RR cell in the audit, but it is not an authorization token. Related edits may be grouped before Save. Verify every saved group with a fresh complete snapshot before navigating away.

## Browser operations

Use complete `snapshotText` reads and `controlInventory` only for selector recovery. Consume all chunks of a large snapshot in strict order. Prefer exact role/name locators. `selectOption` supports native selects and exact-label Cvent custom comboboxes.

On unfamiliar pages: read → scroll → understand → configure → Save → fresh reread. Use `recover` once if rendering stalls. Never blindly retry an uncertain write.

## Mandatory safeguards

- Exact selected event identity and active one-writer event lease are required before every write.
- Never navigate to or write another event.
- Never publish/Go Live, delete/archive, or send/test/schedule communications.
- Never access or modify attendees, invitees, contacts, or their records.
- Never mutate account-global, profile-global, or reusable definitions.
- Preserve event name, code, ID/key, URL identity, and Draft status.
- Never bypass SSO/MFA/CAPTCHA, browser ownership, runtime identity, target lock, or uncertainty checks.
- Never expose credentials, tokens, cookies, environment values, or browser storage.

If the bounded capabilities cannot perform an RR-requested event configuration, record the exact gap and smallest required Cvent-specific capability, continue independent work, and finish as `REVIEW_REQUIRED`.
