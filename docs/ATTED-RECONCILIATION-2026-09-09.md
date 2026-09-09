# Fresh ATTED reconciliation — September 9, 2026

## Exact scope and evidence

Read-only inspection completed against event
`e712e34c-6117-4d13-bf4c-8ed54cf2b495`, unchanged banner
`(C+D) Medtrade Testing Clone 2`. Original verified RR SHA-256:
`da7ea1d56616357080ba4a69eea74aa11266478bc13c3581cd6b3fdd7cd1bb51`.
The exact inventory row currently says **Completed**, not Draft. No lifecycle
status was modified. Read-only inspection of the same explicitly authorized
canonical event did not waive any write eligibility or uncertainty gate.

Server evidence under original job `job_03e7e3467f4244ea84bb39b72d9e19e9`:

`reconciliation/atted-e430f6805c09/`
- `fresh-reconciliation-result.json`
- `fresh-registration-grid.json`
- `fresh-atted-snapshot.json`
- `human-review-classification.json` (21:41:16 UTC)

The earlier `atted-readback.json` is the coordinator's failed Draft preflight,
not the subsequent successful current-state readback. Do not conflate them.

## ATTED CURRENT STATE / RR MATCH

| Property | RR | Fresh Cvent observation | Classification |
|---|---|---|---|
| Code | ATTED | ATTED; one exact Code-column row and one exact parent/detail route | MATCH |
| Name | `Attendee|Educator` | `Attendee | Educator` in grid, detail title, and hidden `#Name` | MISMATCH (literal pipe spacing) |
| Active | ACTIVATE | No independently proven active property | NOT_READABLE |
| Group registration | Y | No explicit group-registration property in the detail | NOT_READABLE |

Detail registration-type key: `e4422872-c916-40e8-94b9-6850e15adb1e`.
Open for registration is Yes, but equivalence to RR ACTIVATE is not proven.
An Active column in the page belongs to badge reprint fees; it is not evidence
of registration-type activation. Overall outcome remains
`MATCH_UNCERTAIN_HUMAN_REVIEW`, not full MATCH or successful configuration.

## PREVIOUS WRITE ACTUALLY APPLIED / RETRY REQUIRED

The intended literal name change is **not persisted** in current Cvent state.
The overall original mutation remains UNPROVEN; its uncertainty marker is
retained. No automatic retry is permitted. The observed Name control is hidden,
not a proven editable event-local Name property. Do not modify a shared
registration-type definition to compensate.

## UNCERTAINTY ROOT CAUSE / 355e8eb PREVENTION

The original `71df1d0` editor routine waited a fixed 650 ms after Edit, then
returned success without proving Save was present. Its control matcher accepted
connected, enabled hidden inputs. Fresh ATTED has precisely such a hidden
`#Name` input containing `Attendee | Educator`.

The original failure occurred when Save-target resolution returned no unique
eligible target after the field attempt, before any Save click. It was not a
Save timeout or failed post-Save readback. The post-error historical snapshot
showed Save later. These facts support an edit-readiness/hidden-input defect;
the original run did not record the chosen selector and exact DOM transition,
so the precise historical timing cannot be conclusively reconstructed.

The unchanged `355e8eb` procedures now require a Save target before planning,
and reject hidden, zero-size, read-only, disabled, and invisible inputs. Tests
using the freshly observed hidden Name shape confirm the retired predicate
accepts it and the current matcher rejects it. This proves prevention of that
observed invalid-target condition, not a successful Cvent mutation or universal
immunity to subsequent UI changes.

## REMAINING REGISTRATION-TYPE DELTA

17 requested codes: 16 exact identities, 9 matching names, 7 literal pipe-spacing
name mismatches, and missing SPONCOMP.

Mismatch codes: ATTED, ATTSTU, ATTFLXTO, EXCOMP, EXPAID, PRESSED, PRESSNED.
SPONCOMP remains a creation candidate only through a proven event-local path;
never repurpose a similar code/name. Active/group coverage is still incomplete,
so these name counts are not whole-record accuracy or completion counts.

## SAFE TO CONTINUE

Independent read-only inventory work succeeded. ATTED writes and the full RR
write run remain held; no uncertainty marker was cleared, no retry occurred,
and no new Pi process or RR run started. No Cvent configuration mutation,
Save, deletion, title change, publish action, communication, or attendee/contact
operation was invoked.

A successful write benchmark cannot be reported from this read-only execution.
Pricing (72 values), admission-item write verification, safe SPONCOMP creation,
remaining event domains, and site configuration remain unfinished.

## Additional reader findings

The Draft-only check was the real inventory stop: the exact canonical row was
present but labelled Completed. Read-only continuation now preserves that fact.
Event opening redirects to `events.app.cvent.com/events/home?evtstub=<same-key>`.
The existing auth helper only recognizes `app.cvent.com`, so it reports false on
this newer origin despite matching profile/account context. The successful
reader revalidated authentication on the known inventory origin, then separately
proved the exact key and visible banner after the redirect. No auth check was
fabricated or disabled. Modern-origin auth support remains a product gap.

The live continuation used an operator-only script and the existing leased
read-only runtime; it did not restart the browser after the second login.
Application deployment remains `71224a5`, with the mutation procedures byte-for-
byte unchanged from `355e8eb`. No service deployment occurred over active leases.

At 21:43:30 UTC the read-only coordinator stopped cleanly. Worker/event leases
are both zero; the original job is still `failed_uncertain`, uncertainty 1,
PID/slot null. Cleanup confirmed original evidence unchanged and no read-session
write audit. The original uncertainty marker still exactly matches its retained
copy. USER 1 profile files were preserved; USER 2/3 were untouched. Local tests
pass: 117. No new application deployment is claimed from those local results.
