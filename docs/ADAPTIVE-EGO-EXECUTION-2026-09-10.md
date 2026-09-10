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

`cvent_ego_actions` executes up to 80 model-planned actions for one currently
inspected editor/coherent configuration group. Every step still passes through
the canonical Python safety gateway. A mutating batch requires:

- one independently validated RR domain;
- RR source evidence for every write;
- an exact target preflight on the page where the action occurs;
- an explicit Save action, or an explicit autosave mode;
- a post-write snapshot/control/target/section readback;
- no navigation away after mutation before the model evaluates readback.

This changes the normal interaction from one model response per primitive to
one model response/tool call per coherent editor. When intermediate UI state is
not predictable, the model can inspect again and continue; changed layouts no
longer require an application release.

## Safety retained outside UI interpretation

Every write still requires the selected event's canonical identity, bound
lifecycle, current page event key, matching BrowserRuntime, agent-owned browser
gate, and active canonical event lease. Every attempted/succeeded/uncertain
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
