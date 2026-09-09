# BDNY staging diagnostic checkpoint — 2026-09-09

**Partial repair, not a completed configuration or successful benchmark.**

## Job and runtime

- Job: `job_63b1ad06c15949ed99d2996bf7d692cc`.
- Authorized event: Draft `(C+D) Medtrade Testing Clone 2`, `e712e34c-6117-4d13-bf4c-8ed54cf2b495`.
- At 17:05:12 UTC: database `running`, stage `optional_items`; same Pi PID `3650514` is stopped on an explicit operator diagnostic hold. No restart/replay.
- Worker 1 and exact-event leases remain held and renewing. Gate has `activeActor: NONE`, `agentPaused: true`, `operatorDiagnosticHold: true`.
- Deployed release remains `2a79e03a374ea05397a116ad2ac36e932597438c`. Source repairs are not deployed. A separate diagnostic adapter under `/opt/cvent-one-shot/diagnostics/job_63b1ad06-reader/` was used only for guarded reads. It is an intermediate diagnostic copy, not the final patch or an active release.
- These are timestamped observations: recheck live state, gate, leases and uncertainty before any further action. Do not blindly resume the paused process with its old loaded extension.

## Root causes and repairs

1. **Pricing reader syntax:** embedded JavaScript used `headings:` and `buttons:` inside a `const` declaration. Changed to initializers; regression tests compile and execute the browser expression, including a synthetic 75-row fixture. Checking only the enclosing MJS syntax had missed this.
2. **Pricing rendering:** the planner SPA initially presents an empty loading shell. Added bounded internal readiness polling; a timeout is an unavailable section, not an empty successful inventory. This final polling change is locally tested, not live-deployed.
3. **Live pricing read:** the isolated syntax-fixed reader returned 17 rendered grid/header rows at `planner-registration-ui.app.cvent.com/pricing/fees` with the exact event key. This proves reading, not pricing reconciliation. The compiled RR contains **24 combinations, 72 tier values and 3 tier headers**, not 75 independent fee rows. No trusted pricing write procedure currently exists.
4. **Admission routes:** actual event-local links use `evtStub` and `/subscribers/events2/AgendaAndFees/AdmissionItemDetails`. Normalize event parameter names; reject conflicting event aliases. Require the exact HTTPS host, known detail path, and a single nonempty item identifier. Read-only validation found one exact grid row and one valid detail route for each of `EXONLY`, `FULL`, `CONF1SUN`, `CONF1MON`, `CONEXPO`, `SPECPROGTO`, `Press`. No configuration mission was rerun.
5. **Registration projection:** `Y` was projected as false; missing group settings were also projected as false. Support Y/N, preserve unspecified as null, and reject unknown booleans rather than guessing.
6. **Registration UI:** the inspected event-local Attendee editor has capacity, open-for-registration, registration path, virtual, invitation-list and item-association settings; no group-registration control was observed. This does not establish where group settings belong. Do not redirect writes into shared definitions or infer a path-level setting without a reviewed mapping.
7. **Registration readback:** active status was copied from the desired value; code matching accepted incidental body substrings. Require independently observed labeled values and block unsupported active/code readback before mutation. Do not treat existence, desired values or a successful wrapper call as field accuracy.
8. **Output transport:** immediate `process.exit` could truncate pipe-backed adapter output. Await the stdout completion callback before exiting; regression test captures a complete 2 MiB result.

## Per-type checkpoint

`Present` means exact code existence in the earlier grid inventory only. Active, group and full field accuracy remain **unverified**. No rows below were configured during diagnosis.

| Code | RR active | RR group | Grid existence | Result |
|---|---|---|---|---|
| ATT | ACTIVATE | Y | Present | Blocked; actual fields unverified |
| MANREP | ACTIVATE | Y | Present | Blocked; actual fields unverified |
| NONEX | ACTIVATE | Y | Present | Blocked; actual fields unverified |
| ATTED | ACTIVATE | Y | Present | Blocked; actual fields unverified |
| ATTSTU | ACTIVATE | Y | Present | Blocked; actual fields unverified |
| ATTFLXTO | ACTIVATE | Y | Present | Blocked; actual fields unverified |
| EXCOMP | ACTIVATE | Y | Present | Blocked; actual fields unverified |
| EXPAID | ACTIVATE | Y | Present | Blocked; actual fields unverified |
| PRESSED | ACTIVATE | Y | Present | Blocked; actual fields unverified |
| PRESSNED | ACTIVATE | Y | Present | Blocked; actual fields unverified |
| ATTGUE | ACTIVATE | Unspecified | Present | Blocked; actual fields unverified |
| SPKR | ACTIVATE | Unspecified | Present | Blocked; actual fields unverified |
| SPONCOMP | ACTIVATE | Unspecified | Missing | Required; not created |
| EAC | REQUIRED | Unspecified | Present | Blocked; actual fields unverified |
| SHOWGUE | REQUIRED | Unspecified | Present | Blocked; actual fields unverified |
| STAFF | REQUIRED | Unspecified | Present | Blocked; actual fields unverified |
| VENDR | REQUIRED | Unspecified | Present | Blocked; actual fields unverified |

SPONCOMP's RR name is `Sponsor|Complimentary`. Creating or associating it requires a proven event-local route; creation of a reusable/global registration definition remains prohibited.

## Safety and measurements

- Two pre-hold trusted invocations: registration types `CONTROL_NOT_FOUND`, 17 records, **127.3366s**, 0 mutations; admission items `AMBIGUOUS`, 7 records, **4.1816s**, 0 mutations.
- Four audit entries are attempted/succeeded pairs for those two wrappers, **not four writes**.
- At checkpoint: `uncertain=0`; no mutation-uncertain marker and no pending write-readback marker. Diagnostic actions were reads/navigation, including opening the registration editor without changing or saving fields.
- No publishing, deletion, communications actions, attendee/contact changes, shared-definition changes or USER 2/3 actions were performed. Persistent USER 1 profile was retained. Draft status was not independently re-inventoried at the final checkpoint.
- 53 recorded model responses before hold, 916.1454s aggregate response time. These are whole-job failed-run measurements, not comparable section benchmarks. Login handoff wait was approximately 9m35s, separate from configuration timing.
- Original baselines remain registration types 29 calls / 259.1s and admission items 27 calls / 416.7s. Valid after measurements, internal operation/navigation counts, verified accuracy and model-time reduction are **not available**. Architecture validated: **NO**.

## Remaining work, in requested order

1. Build and test the trusted pricing reconciliation/editor/readback procedure using all 72 tier values plus three headers, retaining context that maps admission items and registration types to fee rows. Flat row presence is insufficient.
2. Run all seven admission items in one trusted mission only after pricing is resolved; route validation alone is not configuration verification.
3. Establish a safe, event-local group-registration mapping and independent active/code/name readback for all 17 types. Preserve null group requirements.
4. Resolve SPONCOMP through a proven event-local association/create flow, never global definition mutation.
5. Arrange a reviewed same-workflow rollout that accounts for the paused Pi process retaining the old extension in memory; do not hot-swap/restart over a leased job or blindly resume stale projections.
6. Continue remaining domains and final QA only after these blockers are resolved. Preserve validated RR provenance, original-workbook independence, bulk discount import, exact-event/runtime checks, auditing and uncertainty/readback gates.

End-to-end status: **incomplete; safely held, leases intentionally retained**.
