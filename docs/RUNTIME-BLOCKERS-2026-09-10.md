# Runtime blockers — 2026-09-10

## Readiness: NO

No RR benchmark, Pi job, RR preparation, or Cvent configuration write was started.
No deployment, push, profile reset, Docker Desktop restart, unrelated-container
stop, shared-memory increase, or Azure resize was performed.

Offline fixes pass **147 tests**. The authorized Azure USER 1 read-only diagnostic
stopped at Cvent login, so authenticated heavy-page stability and three-worker
load remain **unproved**, not passed. Commit/push/deploy remain gated on that proof.

## ACTIONINDEX ROOT CAUSE / FIX

The earlier operator transcript preserves the exact old declaration:
`let writesAttempted=0,actionIndex=-1;` **inside `try`**, while the outer `catch`
read both variables as fallbacks. JavaScript block scope made both unavailable to
the catch. `actionIndex` was evaluated first, producing the observed
`ReferenceError: actionIndex is not defined` at `ego_direct.mjs:257:96` and masking
the underlying `openAuthorizedEvent` error. Fixing only its name would have left
`writesAttempted` with the same scope defect.

The scope relocation already present in the dirty tree was made by the earlier
operator at **17:23:05.053 UTC**; it is preserved, not claimed as a newly discovered
patch. This investigation adds executable regressions and corrects the remaining
failure-reporting behavior:

- Diagnostic counters and completed-action evidence live outside `try`.
- A local loop index is copied to the diagnostic index. Postflight errors no
  longer report an out-of-range `steps.length` index.
- Completed actions survive postflight failure as well as a middle-action error.
- The adapter no longer mutates the thrown object to attach counters; a thrown
  string retains its real cause instead of causing a secondary TypeError.
- The router trusts zero dispatch only in a structured coherent-action result.
  A killed adapter with no structured result remains conservatively uncertain.
- `mutation_outcome.py` cancels an admission audit only when the router records a
  proven `rejected_prewrite`; a zero-dispatch rejection is not a Cvent mutation.
- A read-helper timeout no longer falsely announces mutation uncertainty.

**Impact distinction:** the original scope bug did not inherently prohibit a
successful multi-action round. A nested action catch sometimes supplied diagnostic
properties and avoided the bad fallbacks. Neither failed live attempt dispatched
an `actions` round. The actual renderer failures occurred before coherent rounds;
the scope bug concealed their adapter errors and impaired recovery/diagnosis.

`tests/test_runtime_failure_regressions.py` runs the real adapter against fake Ego
I/O: four successful reads; multiple successful mock writes; startup, middle,
postflight, non-Error, pre-dispatch, and dispatched-write failures; exact indices,
prior successes, dispatch counts, and router mutation outcomes. No live writes or
network authentication occur in these tests.

## OOM ROOT CAUSE: Docker Desktop guest global exhaustion

These attempts were local, not Azure. New kernel evidence resolves the prior
"allocation cause unknown" finding in `PREWRITE-ROOT-CAUSE-2026-09-10.md`.

| Boundary | Evidence |
|---|---|
| Mac physical RAM | `38,654,705,664` bytes = 36 GiB |
| Docker Desktop usable guest RAM | `8,217,473,024` bytes = ~7.653 GiB; cgroup v2; 14 CPUs |
| Failed Steel memory limit | `HostConfig.Memory:0` — no per-container limit |
| Failed Steel shm | `2,147,483,648` bytes = 2 GiB |
| Kernel classification | `constraint=CONSTRAINT_NONE`, `global_oom`; **not** `CONSTRAINT_MEMCG` |
| Run 2 Docker state | `OOMKilled:true`, still `Running:true`, exit code 0 at inspect; killing Chromium need not kill container init |
| Azure existing host | `33,598,742,528` bytes (~31.29 GiB usable), 8 CPUs, no swap; ~28.59 GiB available at diagnostic admission |

The kernel identifies the exact failed container cgroups:

- Run 1: `e9e58a55609d48e4bcf6eb67eb9d69d90ad7022c30df62a4f8607efd15af91cd`.
- Run 2: `40987ed5a79b76f613ef128ace567414249b928a94f0ad72df0420b8d7834ce0`.

At the correlated Run 1 OOM, two `beam.smp` processes had **2.144 GiB and
2.394 GiB RSS**, before the rest of Docker's workloads and kernel overhead.
At the late Run 2 Chromium OOM they had **2.298 GiB and 2.597 GiB RSS**.
The guest had approximately 7.3 GiB active+inactive anonymous memory and almost
no remaining swap: **164 KiB / 1,048,572 KiB** at the Run 1 record;
**84 KiB / 1,048,572 KiB** at the late Run 2 record.

Container identity evidence associates those processes with unrelated local
Supabase analytics workloads (`supabase_analytics_ODIC_V2`,
`supabase_analytics_Image_Gen`). PID 71549 was itself subsequently OOM-killed;
its cgroup is the Image_Gen analytics container
`085b7753787689c0df080b35652b245a65113beb84ff07d903120f4083ffaa9c`.
These were dominant competing consumers; this is **not proof of an application
memory leak** in either Supabase or Cvent.

Chromium's enormous `total-vm` address reservations in the kernel dump are **not
physical RSS**. The correlated Run 1 victim PID 42770 had 200,052 KiB anonymous
RSS; the late Run 2 victim PID 63355 had 19,004 KiB. Kernel policy selected victims
under global guest pressure; it does not imply the victim consumed all RAM.

Historical Steel samples were **352.5 MiB** at 17:24:33 and **359 MiB** at 17:31:45.
They were after crashes and **are not peak memory measurements**. The failed
containers were already removed; their historical cgroup `memory.peak`, full
process-memory series, and shm peak cannot be recovered. No values are invented.
The job's system-metrics file contains only two environment records.

## CRASH CORRELATION / CLOCKS

Docker's console contains both kernel-time-formatted lines and wall-clock
`init.oom-tracer` lines. Their timestamps differ; do not compare raw `kmsg` time
to Pi UTC as though they were one clock. Correlate **PID + cgroup + wall-clock
OOM tracer**:

| Attempt | Wall-clock OOM tracer | Victim | Steel `Page crashed!` |
|---|---|---|---|
| Run 1 | 17:22:18.263729721 UTC | Chromium PID 42770, Run 1 cgroup | 17:22:18.418 UTC |
| Run 2 | 17:30:31.647696458 UTC | Chromium PID 63355, Run 2 cgroup | 17:30:31.817 UTC |

The corresponding raw kernel records are stamped 17:07:07.275601875 and
17:15:17.423192875 respectively. There are additional Chromium kills in both
container cgroups. Image_Gen's PID 71549 is reported by the wall-clock tracer at
17:30:31.656811041. This establishes guest-wide OOM during both renderer incidents,
not Azure exhaustion. Azure's kernel query for the failed-run UTC interval found
no matching OOM messages.

## MEMORY / SHM / CPU PER WORKER

Candidate configuration, not a claimed measured steady-state requirement:

| Worker | Previous cap | Candidate RAM / swap-total cap | CPU cap | Shm |
|---|---|---|---|---|
| USER 1 | RAM/CPU unlimited | 6 GiB / 6 GiB (no extra swap) | 2 cores | 2 GiB, unchanged |
| USER 2 | RAM/CPU unlimited | 6 GiB / 6 GiB | 2 cores | 2 GiB, unchanged |
| USER 3 | RAM/CPU unlimited | 6 GiB / 6 GiB | 2 cores | 2 GiB, unchanged |

Three RAM caps total 18 GiB; a 2 GiB minimum host reserve requires a 20 GiB Docker
host. Three CPU caps total 6 cores, leaving 2 on existing Azure. Shm is a demand-
allocated tmpfs charged to container memory, **not an extra preallocated 6 GiB**.
The 6 GiB caps are conservative isolation budgets, not extrapolated heavy-page
usage. They still require authenticated load/performance validation.

`steel_resources.py` checks **Docker host** totals, then samples Docker-host
`MemAvailable` through a 64 MiB, no-network, no-profile diagnostic shell. It rejects
less than 8 GiB available before browser startup. The actual failed ~8 GiB Desktop
VM is rejected before even that shell starts. `steel_session.py` applies the caps
when creating/restarting a stopped job container and checks admission before
runtime recovery. Healthy existing browsers are not restarted. The manual Compose
stack has matching caps. No global Docker configuration was changed.

This bounds project workers and rejects the demonstrated undersized runtime; it
cannot prevent unrelated unbounded host workloads from consuming memory later.
No shared-memory capacity failure was evidenced, so shm remains **2 GiB**.

## GATE CLEANUP / BOUNDED RECOVERY

The old gate relied on persisted `activeActor`; terminating its Python helper
could leave that state occupied forever. Clearing it merely because its PID died
would be unsafe: a dispatched Node child could still be mutating Cvent.

The new gate uses an inherited `flock` descriptor. Every browser subprocess
receives it through `pass_fds`. The lock remains held after the Python parent dies
until its browser child also exits. A subsequent automation action waits at most
2 seconds, then fails cleanly if the lock is still held. After acquiring the lock,
new-protocol abandoned metadata can be cleared deterministically. Legacy stale
gates fail closed because their children did not inherit this protocol.

If the abandoned action might have mutated Cvent, cleanup creates an uncertainty
marker before admitting further work; readback is required. It never silently
makes an interrupted write retryable. Normal errors release the gate in `finally`.

Real process tests kill parent helpers with SIGKILL, leave a real Node child alive,
prove concurrent entry is rejected, kill the child, and prove prompt safe cleanup.
Both read-only and potentially mutating cases are covered.

`recover_browser()` now makes **one** read-only canonical/probe attempt with a
30-second budget, not a 240–300 second retry loop. It preserves the original error
and never resets a profile, restarts Chromium, or swaps tabs. The extension caps
the recovery helper envelope at 35 seconds (its controller hook already reduces
requested recovery to 30 seconds). The existing recovery budget permits only one
recovery, terminates on repeated runtime failure, and now treats resource-admission
denial as immediately terminal. Dead-renderer/gate/ReferenceError regression tests
prove no sleep/retry loop and no repeated child invocation.

## READ-ONLY USER 1 STABILITY: BLOCKED AT AUTHENTICATION

Reviewed candidate source was copied to
`/opt/cvent-one-shot/diagnostics/runtime-20260910`; the service release symlink was
not changed. Candidate file-manifest digest:
`19f3d386e537d776cde02cf53c5d46aa578c4ba3213a300e71f0ca954e793d26`.
Later offline tightening of recovery/tests/final sampling remains local and has
not been live-tested; all final code must pass stability before release.

Diagnostic coordinator PID **253465**:

- Start **19:16:45.400364 UTC**.
- Container start **19:16:46.355938303 UTC**, host init PID **253675**.
- Inventory navigation succeeded **19:16:50.300257**, duration **0.913 s**, but
  landed on `https://app.cvent.com/Subscribers/Login.aspx`, title **Log In**.
- `authStatus` succeeded as an observation **19:16:53.458416**, duration **0.158 s**:
  `persistedProfile:true`, `profileMatch:true`, `accountContextMatch:true`,
  `workerSlot:1`, **`authenticated:false`, `loginRequired:true`**.
- Stopped without opening the event, attempting login, or resetting the profile.
- Cleanup/result completed **19:17:04.059396 UTC**.

Exact error: **`RuntimeError: Existing USER 1 authentication was not reused; no
login or profile reset attempted`**. The redirect proves login is required; it
does not establish the specific token-expiry/revocation mechanism.

During this short startup/login-only check:

- Two resource samples; last observed cgroup `memory.peak` **682,881,024 bytes
  (651.246 MiB)** at 19:16:51.539577. This is not a full-run or heavy-page peak.
  The sampler was subsequently improved to capture the final cgroup peak as well.
- Largest observed Chromium RSS: **357,150,720 bytes** (PID 107 inside container);
  Steel Node RSS **272,252,928 bytes** (PID 7). Shared RSS must not be summed as
  unique physical memory. Resource sampling itself briefly uses a Node process.
- Shm observed **0 / 2,147,483,648 bytes**. This is not heavy-page shm evidence.
- Sampled CPU interval **1.323 cores**; `cpu.max = 200000 100000`.
  CPU throttling occurred; the proposed cap's heavy-page latency is unproved.
- `memory.events`: `max=0`, `oom=0`, `oom_kill=0`; Docker `OOMKilled:false`.
- No `Page crashed!`, browser-router timeout, or stuck gate. Initial nginx
  upstream connection refusals occurred while Chromium was starting; readiness
  subsequently succeeded. They were not router-operation timeouts.
- Final gate: `activeActor:NONE`, `activePid:null`.
- Container removed, **zero worker/event leases**, **zero leftover browser-tool,
  Ego-adapter, or diagnostic coordinator processes** in the post-check.
- Original job remains `failed_uncertain`, `pid:null`, `uncertain:1`.
  Protected original artifacts hash-match; diagnostic write audit absent.
- **0 model calls, 0 configuration writes, 0 RR benchmarks.**

No second or third worker was started. The planned repeated heavy-page navigation,
snapshots, screenshots, and coherent read rounds did **not run**. A short healthy
login page cannot satisfy the user's stability acceptance criteria.

## TESTS / SHA / NEXT GATE

Final offline checks: **147 tests passed**, Python compilation, Ego syntax,
`git diff --check`, and Docker Compose configuration validation passed. Tests
include the existing action-heavy Ego/RR changes; those dirty changes were not
reverted. Unrelated untracked `build_expected.py` was not executed or packaged.

- Current branch/HEAD: `azure-three-worker` /
  `8d3d6693cf9ae792c85789be34024b1a466a8843`, with preserved dirty work plus fixes.
- Earlier isolated orchestration commit remains
  `b9961fa56af8374ab858f9aa53dc141f7816aa5a`.
- **No new release SHA committed, pushed, or deployed**, because authenticated
  runtime acceptance is blocked.
- Azure still runs **`8d3d6693cf9ae792c85789be34024b1a466a8843`**;
  `/healthz` returned `{"ok":true,"workers":3}` after cleanup.
- USER 1 profile exists and matches its saved account context, but its live Cvent
  login is **not currently reusable**.

Required next step: USER 1 authenticates through the approved staging handoff,
without resetting/replacing the persistent profile and without starting an RR
build. Then rerun the read-only stability diagnostic against final reviewed code,
measure the heavy-page resource profile, validate capacity for three workers,
run all tests, commit the complete required release, push, deploy/verify the exact
SHA and profile, and only then reconsider spending the one RR benchmark.

## Evidence locations

Private local preservation: `/private/tmp/cvent-runtime-audit/`:
`kmsg.log`, `console.log*`, `oom-summary.json`,
`prior-operator-runtime-evidence.json`, `docker-info.json`,
`candidate-manifest.json`, `tests-final.log`, `azure-readonly-evidence.tar.gz`.
Raw browser logs may contain session identifiers and are deliberately not committed.

Azure diagnostic evidence:
`/var/lib/cvent-agent/workspaces/ws_eaa61faba6345e488b4c0d0b65bfe782/jobs/job_03e7e3467f4244ea84bb39b72d9e19e9/reconciliation/runtime-73c6fa40b449/`.
