# RR-driven write policy checkpoint

This is a partial implementation checkpoint, not end-to-end acceptance.

## Staging lifecycle

- Old job `job_63b1ad06c15949ed99d2996bf7d692cc`: rechecked zero reported mutations, no uncertainty/readback marker, stopped Pi state and idle browser gate. Terminated process group 3650514 with SIGKILL without SIGCONT. The existing controller released both leases and classified it `failed_recoverable` (wrapper audit attempts existed); uncertainty remains zero.
- Pushed and deployed exact `436d7d8830105914eb6054647fc71819d2d201e1`. All 96 tests passed on staging. Health returned `{"ok":true,"workers":3}`.
- Uploaded the same original BDNY RR through the staging UI. Local and server input SHA-256: `da7ea1d56616357080ba4a69eea74aa11266478bc13c3581cd6b3fdd7cd1bb51`.
- Fresh job: `job_5f0786e702674072a21513c01c28c2b0`, PID 3731418, USER 1. Provider preflight passed; independent RR preflight compiled 658 writable fields.
- The fresh job requires human Cvent login. At the latest check the browser gate was USER/USER, agentPaused true, no authorized-target lock, no write audit, no uncertainty marker, no pending readback. Worker/event leases remain held for the login handoff. The old process is not reused.
- The local Ego staging task space 16 was handed to the user. Do not seize it back without confirmation.
- The additional changes below are **not deployed over this active handoff**. Do not assume the fresh process has loaded them. Check runtime state before arranging their deployment and a fresh execution.

## Additional source changes

- Fix gateway schema to accept an unspecified `groupRegistration` as null; do not coerce it to false or reject the section.
- Resolve existing objects using the actual grid Code column, never any cell containing a matching name/code. Duplicate/missing identity metadata is review-required. Missing exact identities do not trigger renaming of similar objects.
- Split registration edit plans into actionable properties and explicit `CONTROL_NOT_AVAILABLE` field gaps. Save and verify available changes; an absent group control no longer vetoes an independently editable name. Do not infer active status merely from existence.
- Admission availability comparison uses complete labels rather than substring matching.
- Emit explicit per-item outcomes and created/updated/already-correct/failure/field-gap counts. Instrument internal Ego helper calls, navigation time, targeted reads and full snapshots without additional model/browser primitive turns.
- Preserve trusted section results in job-local artifacts.
- Require explicit per-item Cvent readback evidence for `MATCH`; omitted RR items are `NOT_CONFIGURED` or `AMBIGUOUS`, not implicit matches. Reject duplicate, conflicting and cross-domain verification identities.
- Show a domain as complete only when every expected RR item is VERIFIED and has explicit MATCH readback, with no blocked domain result.
- Harden event-query conflict handling and denial of account/shared routes, test-send controls, new-event creation/copy/clone and non-Cvent write origins. Save and event-local item-creation controls remain permitted by policy; permission is not a claim that their UI adapters exist.

103 tests pass locally. A mocked registration mission proves that an available name update is saved/read back while an unavailable group setting is held, and that absent SPONCOMP does not repurpose the existing type. This is **not a live Cvent write benchmark**.

## Still unimplemented or unverified

- SPONCOMP: exact missing registration type; safe event-local creation route/editor/readback not yet implemented. Shared-definition creation remains forbidden.
- Registration types: actual group-setting location and independent active readback remain unresolved; live field-level execution of the new patch is unverified.
- Admission items: seven-item post-deployment write/readback mission has not run; route compatibility alone is not acceptance.
- Pricing: 24 combinations / 72 tier values / three metadata headers. No trusted pricing write/create/readback mission yet. Headers must never be emitted as fee records.
- Remaining RR domains and site configuration have not been executed or finally verified. There is no successful after benchmark, no proven accuracy result and no full-event/site PASS.
- Authentication must complete before live selected-event/current-state preflight or further Cvent capability investigation. Never bypass SSO/MFA or ownership, and never treat the uploaded RR as proof of current Cvent state.
