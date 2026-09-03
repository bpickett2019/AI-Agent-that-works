# Post-demo Ego performance notes

## Demo decision

Keep the current Ego + Steel architecture unchanged for the demo. Do not refactor the browser execution path, migrate it to Azure, restart InstantView, or alter the persistent Steel profile before the demo.

The two stale `cvent-steel-worker-*` containers were stopped. The canonical `cvent-one-shot-steel` container, browser runtime, login profile, and active CVENT Agent were preserved.

## Non-negotiable observation policy

**Never optimize performance by making DOM reads smaller.** Full-page/full-context DOM reads remain required so the agent can understand the complete interface, detect related controls, and verify state without losing context.

Post-demo optimization must not introduce partial-widget snapshots, reduced DOM scopes, truncated semantic reads, or selector-only observation as substitutes for complete reads. Targeted readiness checks may supplement full DOM reads, but may never replace or shrink them.

Also preserve:

- fresh readback after every meaningful write;
- the browser action gate;
- canonical runtime marker and target-ID verification;
- authorized event-key verification;
- confirmed Forge Intake `scopeIds` on every write;
- unpublished-state and protected-identity safeguards;
- the existing local Steel profile and authentication boundary.

## Why this runtime feels slower than desktop Ego Lite

Desktop Ego Lite keeps its native browser, task space, helper runtime, and CDP connection alive. The current CVENT Agent path repeats substantial setup for individual operations:

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

## Post-demo optimization backlog

### 1. Persistent Ego worker — highest priority

Run one long-lived local Ego worker that retains:

- the Node process;
- imported Ego helpers;
- the browser-level CDP WebSocket;
- the canonical target selection;
- task-local ref/session state.

Route commands to it over a local Unix socket or localhost-only API. The Python safety router remains authoritative and must fail closed if the worker, marker, target ID, event key, or browser gate differs.

### 2. Safe multi-action transactions

Allow related operations to execute within one worker transaction rather than launching a process for each step. Examples include observe → click → wait → full readback.

Each mutating sub-action must still carry and validate exact confirmed Forge Intake `scopeIds`. Never batch across ownership changes, event-key changes, navigation to another event, or uncertain UI state.

### 3. Event-driven stabilization

Replace arbitrary fixed sleeps with readiness signals such as:

- document/load lifecycle state;
- a specific expected control becoming available;
- Cvent save confirmation appearing;
- spinners or busy indicators disappearing;
- relevant network activity settling.

After readiness is reached, still perform the required complete DOM read. Readiness checks improve waiting behavior; they do not reduce observation coverage.

### 4. Combine duplicate CDP handshakes

Today the Python live probe and Ego helper may establish separate CDP connections for one action. Have the persistent worker return verified marker, target ID, URL, title, and event key with each operation so redundant connection setup can be removed without weakening checks.

### 5. Cache static policy data safely

Keep the compiled Forge Intake manifest in memory inside the long-lived router/worker. Revalidate its file identity and SHA-256 whenever its mtime, size, inode, or configured path changes. Never cache authorization lock or live browser identity without a fresh check at mutation time.

### 6. Reduce orchestration overhead, not DOM coverage

Possible reductions include:

- fewer Python/Node process launches;
- fewer repeated helper imports;
- less repeated tab enumeration when target identity is unchanged and freshly verified;
- combining adjacent safe operations;
- reducing unnecessary status subprocesses and UI polling work.

Do not reduce full DOM reads or post-write verification.

### 7. Improve selector recovery

Record action timing and failure categories. When a selector fails, take one complete fresh DOM read and re-resolve from current state rather than repeating stale selectors or fixed waits. Preserve semantic-first interaction and bounded JS/CDP escape hatches.

### 8. Steel container lifecycle cleanup

Automatically identify and stop stale `cvent-steel-worker-*` containers without touching the canonical `cvent-one-shot-steel` container. Require explicit identity checks before cleanup. Consider a startup reconciliation step and a graceful shutdown policy.

### 9. Review unrelated workloads safely

Inventory unused Docker/Supabase projects and other heavy local processes after the demo. Stop only workloads the user explicitly confirms are unused. Never stop InstantView, WindowServer, the canonical Steel container, the active CVENT Agent, or the persistent login profile as a performance shortcut.

### 10. Add performance telemetry

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

## Azure evaluation after the demo

Azure may improve stability by isolating Steel and Ego from desktop display and local development workloads. It will not by itself fix process-per-action overhead.

If evaluated, run the app, router, persistent Ego worker, and Steel on the same dedicated VM so CDP remains local to that machine. Start with at least 4–8 vCPUs and 16 GB RAM, preserve localhost-only control boundaries, and plan explicitly for browser-profile migration, Microsoft SSO/MFA, secure remote viewing, backups, and operating cost.

Benchmark local optimized execution before deciding to migrate. Compare the same full-DOM workflow and safety settings; do not make Azure appear faster by weakening observation or verification.

## Recommended order after the demo

1. Add timing telemetry.
2. Implement the persistent Ego worker.
3. Add safe multi-action transactions.
4. Replace fixed sleeps with event-driven readiness checks.
5. Optimize duplicate probes and static policy loading.
6. Add stale Steel lifecycle cleanup.
7. Benchmark the optimized local system.
8. Run an equivalent Azure proof of concept only if local results remain insufficient.
