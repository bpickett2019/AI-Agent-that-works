# Adaptive Ego execution — September 10, 2026

## Audit: restrictions that prevented general operation

The browser router already implemented bounded Ego navigation, click, activate,
fill, type, select, check, keyboard, scroll, wait, drag, upload, snapshots,
control inventories, and targeted reads. The Pi-facing extension intentionally
hid almost all of them:

- `cvent_browser` accepted read intent only and its schema exposed no selector,
  URL, input value, option, checkbox state, key, or destination.
- Only Registration Types and Admission Items were registered in
  `TRUSTED_SECTION_PROCEDURES`.
- The controlling prompt required those bespoke procedures and ordered the
  model to report `NO_PROVEN_ROUTE`/missing-procedure for every other domain.
- Fixed menu paths and four fixed routes were treated as prerequisites rather
  than optional shortcuts.
- A write/readback marker forced another model/tool exchange after each
  primitive when no section procedure existed.

Consequently Ego could understand an unfamiliar page but could not act on it.
Site Designer, Pricing, Questions, Paths, Optional Items, and most event settings
were structurally read-only regardless of what Cvent exposed.

## Simplified execution model

`cvent_browser` is now the general semantic Ego interface. It exposes the
existing bounded operations and typed action inputs to Pi. It still does not
expose JavaScript, CDP, browser storage, cookies, credentials, shell, arbitrary
network access, or arbitrary local files.

The separate `cvent_ego_actions` wrapper has been removed. `cvent_browser` now
accepts `operation: actions` and executes up to 80 model-planned actions for a
currently inspected editor or sequence of saved records. One round uses one
Python safety-gateway invocation and one Ego Node process rather than relaunching
both processes for every step. A mutating round requires:

- one independently validated RR domain;
- RR source evidence for every write;
- an exact target preflight on the page where the action occurs;
- an explicit Save action, or an explicit autosave mode;
- a post-write snapshot/control/target/section readback;
- meaningful readback after each saved/autosaved group before later navigation.

This changes the normal interaction from one model response and process pair per
primitive to one model response and one Ego process per coherent round. When
intermediate UI state is not predictable, the model can inspect again and
continue; changed layouts no longer require an application release. Ordinary DOM
pages use `snapshotText → locators → actions → readback`; visual/virtualized
surfaces use `screenshot → coordinate mouse/keyboard actions → screenshot/readback`.

## Safety retained outside UI interpretation

Every write still requires the selected event's canonical identity, bound
lifecycle, current page event key, matching BrowserRuntime, agent-owned browser
gate, and active canonical event lease. The coherent executor rechecks lease and
live event context immediately before each write. Every attempted/succeeded/uncertain
write is audited. Timeout or post-dispatch failure creates a job-local uncertainty
marker and blocks replay.

Preflight now runs for interactive read-declared clicks as well as writes. Save,
Create, Add, Update, Apply, Confirm, and Submit controls cannot be disguised as
reads. Publish/Go Live, communication send/test/schedule, delete/archive,
attendee/contact, event identity, Create Event, and Create Contact Type controls
remain permanently blocked. Account/global routes and non-Cvent navigation
remain blocked.

## Optional adapters

The Registration Types and Admission Items procedures remain available as
optional accelerators because they can process many rows in one call. They are
no longer the only write path and no longer block dynamic fallback. The discount
bulk-import artifact remains appropriate for genuinely large discount sets.
Fixed section routes/menu paths remain cache/bootstrap hints only.

No code, route, count, or decision branches on ATTED, SPONCOMP, BDNY, or
Medtrade. Those identities occur only in test evidence/job data.

## Live validation

Run `job_e405c8574bcf4f5fb210c8c594b94cba` exercised the current RR against the
existing authorized event `(C+D) Medtrade Testing Clone 2` on September 10.
After human SSO/MFA, Ego found exactly one inventory match, bound event key
`e712e34c-6117-4d13-bf4c-8ed54cf2b495`, preserved observed lifecycle status
`Completed`, opened the event, navigated between the new and classic Cvent
surfaces, opened Event Information edit mode, and read live controls and values.
Screenshots show the browser responding and rendering each page transition.

Telemetry before the provider stopped the run:

- 51 model responses, 486.9 seconds total;
- 23 completed browser operations, 23.5 seconds total;
- one full semantic snapshot rather than a snapshot after every primitive;
- three completed coherent Ego rounds, each carrying two actions in one Node
  process (six actions in three process launches rather than six);
- 19.97 seconds to first browser action;
- 2.35 seconds average per completed two-action coherent round;
- 0 successful saved writes and 0 protected actions.

The run did not complete. Anthropic stopped it for insufficient API credit while
it was still in `event_settings`. A conservative uncertainty marker from an
earlier write-declared round remained unresolved: target resolution failed, and
fresh reads showed the time zone and start date were still at their original
values. Because the agent then exited, the job correctly ended
`failed_uncertain` rather than claiming completion.

The response-by-response classification is in
[`LIVE-MODEL-TURN-AUDIT-2026-09-10.md`](LIVE-MODEL-TURN-AUDIT-2026-09-10.md).
Only 20 of 51 responses caused a completed browser operation, 23 qualified as
zero-progress, 14 reread available information, and 27 belonged to wrapper or
selector-error fallout. The three successful coherent rounds averaged only two
actions; they proved capability but not effective orchestration.

The default contract is now action-heavy: one domain plan read, one sufficient
semantic or visual observation, then one substantial action/Save/readback round.
Event Settings, Registration Types, Admission Items, and Pricing target 1–3
model turns. Telemetry records model turns with action, zero-progress turns,
coherent-round density, budget overruns, and complete per-section model/browser
wall times. Repeated plan pages return only a compact already-delivered notice,
and `controlInventory` now excludes hidden and irrelevant page-wide controls.

The vendored native snapshot implementation also used the wrong CDP AX property
(`backendNodeId` instead of `backendDOMNodeId`), so its advertised refs were
missing. It now emits `[ref=N]`, accepts the normal ref spellings, and enables the
intended snapshot → fresh ref → many actions path.

The live failure exposed one additional dispatch-accounting issue. The Ego
adapter counted a write as attempted when safety checks passed, before the
low-level browser helper was actually dispatched. The adapter now validates a
native select option before dispatch and increments `writesAttempted` only when
a mutating helper is actually dispatched. Selector and native-option failures
that occur before dispatch therefore remain pre-write failures; failures during
or after a dispatched action still create the existing uncertainty hold. The
prompt also now tells the model to use `fill` directly, use only declared action
names, prefer compact `sectionState` over a 198 KB control inventory, and never
mistake renderer `recover` for mutation verification.
