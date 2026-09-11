# Post-demo Ego performance notes

## Demo decision

Keep the current Ego + Steel architecture unchanged for the demo. Do not refactor the browser execution path, migrate it to Azure, restart InstantView, or alter the persistent Steel profile before the demo.

The two stale `cvent-steel-worker-*` containers were stopped. The canonical `cvent-one-shot-steel` container, browser runtime, login profile, and active CVENT Agent were preserved.

## Observation policy

Use Ego's default full-page `snapshotText` when entering an unknown ordinary DOM page or when the layout materially changed. That snapshot exists to enable action; it is not the deliverable. Do not repeat the same full snapshot after every primitive. Targeted reads and screenshots are appropriate for meaningful post-save verification, and screenshots plus mouse/keyboard operations are required for visual or virtualized surfaces.

Never reduce a snapshot so far that Ego cannot understand the relevant interface, but optimize primarily by taking fewer snapshots and performing more useful actions per coherent execution round.

Also preserve:

- fresh readback after every meaningful write;
- the browser action gate;
- canonical runtime marker and target-ID verification;
- authorized event-key verification;
- independently validated RR provenance on every write;
- unpublished-state and protected-identity safeguards;
- the existing local Steel profile and authentication boundary.

## Why this runtime feels slower than desktop Ego Lite

Desktop Ego Lite keeps its native browser, task space, helper runtime, and CDP connection alive. The regressed CVENT Agent path repeated substantial setup for individual operations:

1. Start the Python browser router.
2. Acquire and verify the cross-process browser gate.
3. Probe the live Steel target and event lock.
4. Start a Node process.
5. Import the vendored Ego helpers.
6. Establish a browser-level CDP connection through Docker.
7. Find and activate the canonical tab.
8. Verify the runtime marker.
9. Perform the action.
10. Verify the marker again and terminate the process.

Cvent's dynamic UI, full DOM reads, deliberate stabilization waits, fresh post-write reads, and model reasoning add additional latency. The Forge Intake hash/scope check is small and is not the primary bottleneck.

Observed baseline during the demo run:

- one scoped click: approximately 2.8 seconds;
- a click/navigation/read sequence: approximately 4.9 seconds;
- a failed selector and recovery cycle: approximately 10 seconds;
- InstantView often consumed 70–100% of one CPU core;
- WindowServer and Docker virtualization also had substantial CPU usage.

InstantView is Silicon Motion software driving the two external monitors. Do not stop it or disrupt the monitor setup.

## Restored execution architecture

`cvent_browser(operation: actions)` now sends one model-planned sequence to one Python safety-gateway invocation and one Ego Node process. Ego imports its helpers, attaches to the canonical target, then continuously executes up to 80 navigation, semantic or visual actions, Saves, and readbacks. It no longer launches Python and Node once per step.

Each mutating sub-action still carries verified RR provenance. The action executor rechecks the active lease and exact event context immediately before each write, blocks permanent protected controls, and returns all action/readback evidence together. Navigation after a write is accepted only after the prior saved/autosaved group has a meaningful readback.

### Remaining: event-driven stabilization

Replace arbitrary fixed sleeps with readiness signals such as:

- document/load lifecycle state;
- a specific expected control becoming available;
- Cvent save confirmation appearing;
- spinners or busy indicators disappearing;
- relevant network activity settling.

After readiness is reached, still perform the required complete DOM read. Readiness checks improve waiting behavior; they do not reduce observation coverage.

### Remaining: combine duplicate CDP handshakes

Today the Python live probe and Ego helper may establish separate CDP connections for one action. Have the persistent worker return verified marker, target ID, URL, title, and event key with each operation so redundant connection setup can be removed without weakening checks.

### Remaining: cache static policy data safely

Keep the compiled Forge Intake manifest in memory inside the long-lived router/worker. Revalidate its file identity and SHA-256 whenever its mtime, size, inode, or configured path changes. Never cache authorization lock or live browser identity without a fresh check at mutation time.

### Remaining: reduce orchestration overhead, not observation quality

Possible reductions include:

- fewer Python/Node process launches;
- fewer repeated helper imports;
- less repeated tab enumeration when target identity is unchanged and freshly verified;
- combining adjacent safe operations;
- reducing unnecessary status subprocesses and UI polling work.

Do not reduce the first sufficient observation on a materially changed page or any required post-write verification.

### Remaining: improve selector recovery

Record action timing and failure categories. When a selector fails, take one complete fresh DOM read and re-resolve from current state rather than repeating stale selectors or fixed waits. Preserve semantic-first interaction and bounded JS/CDP escape hatches.

### Remaining: Steel container lifecycle cleanup

Automatically identify and stop stale `cvent-steel-worker-*` containers without touching the canonical `cvent-one-shot-steel` container. Require explicit identity checks before cleanup. Consider a startup reconciliation step and a graceful shutdown policy.

### Remaining: review unrelated workloads safely

Inventory unused Docker/Supabase projects and other heavy local processes after the demo. Stop only workloads the user explicitly confirms are unused. Never stop InstantView, WindowServer, the canonical Steel container, the active CVENT Agent, or the persistent login profile as a performance shortcut.

### Completed/continuing: performance telemetry

Measure and log, without sensitive payloads:

- router startup time;
- gate wait time;
- CDP connection/attachment time;
- Ego helper import time;
- action duration;
- readiness wait duration;
- full DOM read duration and output size;
- Cvent navigation duration;
- retry/failure reason;
- end-to-end domain duration.

Use these measurements to compare the existing process-per-action implementation with the persistent worker.

## September 10 live measurement

The RR-to-existing-event run `job_e405c8574bcf4f5fb210c8c594b94cba`
reached the exact authorized event and exercised native semantic and screenshot
workflows before Anthropic rejected further calls for insufficient credit. Its
performance summary recorded 51 model responses (486.9 seconds) and 23 browser
operations (23.5 seconds). Three coherent read rounds performed six actions in
three Ego launches, a 50% launch reduction for those steps. Their average round
latency was 2.35 seconds, or about 1.18 seconds per contained action, versus the
older observed 2.8-second scoped-click baseline. Only one full semantic snapshot
was taken; later evidence used screenshots, a control inventory, and targeted
reads.

The consistent end-to-end denominator is total automation minus measured human
handoff: 834.6 − 281.0 = 553.6 seconds. Model response time was therefore about
486.9 / 553.6 ≈ 87.9% using the rounded benchmark values (88.0% from exact
telemetry) of non-human automation time, not 95%. The earlier 95%
figure mixed the narrower Pi event span with the wider end-to-end total and was
incorrect. This is above the prior approximately 82% benchmark, but it is not a
completion-speed result: the run spent too many model turns
recovering from invalid action syntax, exact-locator mismatch, and a large
control inventory, then stopped before any saved write. Browser execution was
not the dominant measured cost.

The live run also demonstrated visible navigation from Cvent inventory to the
bound event Home page and classic Event Information editor. The browser remained
responsive while rendering event details and edit controls. Final status was
`failed_uncertain`, with zero successful writes and all protected-action counts
zero; no complete end-to-end duration can honestly be reported.

### Before/after benchmark status

| Metric | September 10 baseline | Fresh action-heavy run |
|---|---:|---:|
| Model responses | 51 | Pending provider credit and hold review |
| Responses with completed browser operation | 20 | Pending |
| Zero-progress responses (retrospective rule) | 23 | Pending |
| Ego rounds | 3 | Pending |
| Actions per Ego round | 2.0 | Pending |
| Model response time | 486.9 s | Pending |
| Browser operation time | 23.5 s | Pending |
| Human handoff | 281.5 s | Pending |
| Non-human automation | 553.1 s | Pending |
| Model share of non-human automation | 88.0% exact | Pending |
| Successful saved writes | 0 | Pending |
| End-to-end RR completion | No | Pending |

The new summary schema adds, for every observed section: total model turns,
turns with browser action, zero-progress turns, Ego rounds, actions per round,
browser operations, model time, browser time, total wall span, and 1–3-turn
budget overruns. A valid "after" column requires a new job; it cannot be inferred
from unit tests or from the incomplete baseline.

## Azure evaluation after the demo

Azure may improve stability by isolating Steel and Ego from desktop display and local development workloads. It will not by itself fix process-per-action overhead.

If evaluated, run the app, router, persistent Ego worker, and Steel on the same dedicated VM so CDP remains local to that machine. Start with at least 4–8 vCPUs and 16 GB RAM, preserve localhost-only control boundaries, and plan explicitly for browser-profile migration, Microsoft SSO/MFA, secure remote viewing, backups, and operating cost.

Benchmark local optimized execution before deciding to migrate. Compare the same full-DOM workflow and safety settings; do not make Azure appear faster by weakening observation or verification.

## Recommended order after the demo

1. Repeat the live RR run after Anthropic credit is restored; the September 10 run stopped in `event_settings` before a saved write.
2. Replace remaining fixed sleeps with event-driven readiness checks.
3. Optimize duplicate probes and static policy loading.
4. Add stale Steel lifecycle cleanup.
5. Consider a persistent worker only if per-round process startup remains material after model round trips are reduced.
