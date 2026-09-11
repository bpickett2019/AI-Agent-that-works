# Atomic Ego execution repair — 2026-09-11

## Inspected reality

- Azure/current and remote `fix/pi-upstream-ego`: `4774289811a14fada75eff42dc14d2003febf991`.
- The default local checkout is the older, dirty `azure-three-worker` worktree. It was not changed. Work continued in `/private/tmp/cvent-pi-native-fix` at the deployed baseline.
- Azure `/healthz`: `{"ok":true,"workers":3}`; `cvent-one-shot.service` active.
- A newer operator job, `job_835953e57c46499dbd0291bef7cc61fe`, was already running. Stopped through Forge's CSRF-protected stop API before writes. Terminal state `failed_prewrite`; worker/event leases released. This was not a new acceptance launch.
- That job again proved authentication, 75-event authenticated inventory, exact canonical key/code, runtime binding and authorized opening. The circular bootstrap bug has not recurred.
- USER 1 retained its existing workspace/slot Chromium profile and authenticated account context. No profile/cookies/SSO reset.
- Live Pi capabilities include read, bash and all 14 Cvent tools; none missing. Its system prompt loads `skills/ego-browser/SKILL.md`.
- Skill is byte-identical to `https://github.com/citrolabs/ego-lite.git`, commit `d01be93325c7ea59d41c2ca9f4c59b58b4be4046`, metadata version 2.0.0. No `.agents/skills` override. Vendor skill/browser code was not changed.

## Prior Venue attempt

`job_72a268177cac4525add1fea9b1e4c68a` dispatched one Venue fill, no Save, at 07:26:38–39 UTC. Audit source: `Event Details!B10`. Its round ended dirty and subsequent writes were contained.

The old editor/browser was already gone after a later job replaced that BrowserRuntime. A separately leased, read-only Azure reconciliation reused USER 1's profile, refreshed inventory, bound the exact event and opened the previously observed **read-only** Event Information URL. Fresh snapshot at 07:42:59 UTC shows:

- canonical event name `(C+D) Medtrade Testing Clone 2`, code `NLNMYJD28PH`;
- persisted Venue **Javits Convention Center**, not **The Hangar at Regatta Harbour**;
- read-only details, Edit button and no Save/editor controls.

Evidence lives in the original job's `reconciliation/venue-20260911/`. No configuration writes or Save were dispatched by reconciliation. Original audit and uncertainty evidence must be retained. The exact attempted round can be resolved as NOT_PERSISTED using an operator-only resolution tied to the original attempt timestamp/source and hashed readback evidence; unrelated attempts and historical ATTED holds remain untouched.

## Root cause and repair

Native scripts previously checked sources one action at a time and tested `dirty` only **after** script execution. A valid field fill could therefore run in a script that never contained Save. Source fallback also depended on a single header source or the last written source, so multi-source rounds failed before the first field or incorrectly attributed control actions.

`ego_round_validation.mjs` is a pure pre-dispatch validator, not another browser/runtime/controller. Pi and the existing Ego wrapper both validate planned sequential awaited actions. Actual live targets and Save are resolved before the first mutation. Sources must belong to the verified domain/header; desired values are checked against compiled evidence (including date display formatting). No previous-field provenance fallback. Save/Tab/Edit are control flow, not independent spreadsheet values.

A mutating script must have a fresh snapshot, known targets, RR-backed data actions, an unconditional commit, wait and fresh snapshot for verification. Dynamic/conditional discovery remains read-only; Pi repairs an unresolved write plan rather than dispatching a fragment. Legacy individual writes are rejected in favor of atomic rounds. The actions-array path receives the same commit preflight. No arbitrary page.evaluate/CDP is exposed.

Save/readback runtime failures still contain genuinely dispatched writes. Zero-dispatch errors do not create uncertainty. The extension no longer creates an actions-array pending mutation marker before preflight. Existing stale-ref refresh and durable domain checkpoints remain; stalled rounds require a changed strategy. Final domain verification remains item-accounted and cannot be replaced by narration.

## Regression coverage

Real wrapper with fake Ego I/O: later invalid source rejects before first fill; Venue-only fill rejects with zero writes/no hold; valid fill/Tab/Save/wait/readback succeeds without fake control cells; missing/conditional/comment-only Save and missing wait reject; target binding checked; runtime failure after dispatch remains uncertain. Existing killed-runtime, stale-ref recovery, three-round progress guard, exact bootstrap and Pi CLI active-tool tests retained. Resolution test proves exact attempt scoping, evidence integrity and preservation of unrelated uncertainty.

No UI, target bootstrap, local Docker, vendored skill, or new orchestration architecture changes.
