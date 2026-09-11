# September 10 prewrite investigation — no live rerun

## Evidence and environment

All timestamps below are UTC on 2026-09-10. The supplied timestamps match **two local attempts of one job**, not two Azure jobs:

- Job: `job_36bf76f303194845879425cd12b1670b`
- Workspace: `ws_6c6efefc57835f688f8a354580cd2785` (`dev:local-operator`)
- Local controller PID: `87671`; UI: `http://127.0.0.1:8877/?worker=1`
- Attempt 1 Pi PID `87775`; session `2026-09-10T17-12-47-852Z_01a08c4e-c5ec-7da7-b2ec-85c5313d324c.jsonl`
- Attempt 2 Pi PID `88279`; session `2026-09-10T17-30-05-298Z_01a08c5e-9a72-7fe9-bef8-a5fb2588478c.jsonl`
- Local source base: `8d3d6693cf9ae792c85789be34024b1a466a8843`, with uncommitted action-heavy changes. It was not an immutable deployed SHA.
- Azure read-only inspection: current release is `8d3d6693cf9ae792c85789be34024b1a466a8843`; `/var/lib/cvent-agent/control.db` does not contain these attempts. Its most recent job is `job_0319072740ab4140a5aa0e6a48c72cb6`, finished at 03:48:49 UTC.

Primary evidence is in local `data/workspaces/<workspace>/jobs/<job>/`: both Pi session JSONLs, `performance-events.jsonl`, `activity.log`, `human-handoff-state.json`, `auth-settings.json`, and `browser-runtime.json`; SQLite `audit_log` independently records both finishes. The earlier operator session `~/.pi/agent/sessions/--Users-bp--/2026-09-10T03-48-47-829Z_01a0896e-b055-702c-a343-6869f5a3dbed.jsonl` preserves Docker diagnostics and the exact stop/kill commands. No browser was started to obtain this evidence.

## RUN 1 ROOT CAUSE

- Pi started **17:12:47.625**, PID **87775**.
- Login initially returned `authenticated:false`; human authentication was positively verified at **17:21:28.453** and returned to Pi at **17:21:29.283**. The same Pi session continued.
- Last successful browser operation: **`scanEventList`**, completed **17:21:37.341**. It found exactly `(C+D) Medtrade Testing Clone 2`, key `e712e34c-6117-4d13-bf4c-8ed54cf2b495`, code `NLNMYJD28PH`, lifecycle `Completed`.
- Last positively observed page: `https://app.cvent.com/Subscribers/Events2/EventSelection`, title `Events`, target ID `A5CEF34D3D06D6CA8F4C998AA6E552C6`.
- `openAuthorizedEvent` dispatched at **17:21:41.931** toward `https://app.cvent.com/subscribers/events2/Overview/Overview/Index/View?evtstub=e712e34c-6117-4d13-bf4c-8ed54cf2b495`.
- Steel independently recorded **`Page crashed!` at 17:22:18.418** for that target. Cvent modern-shell script requests show navigation reached the modern application, but successful exact-event entry/authorization was never returned.
- First Pi-visible tool error, **17:22:22.080**: **`ReferenceError: actionIndex is not defined`**, `ego_direct.mjs:257:96`, Node `v26.5.0`. This was an exception-handler scoping bug masking the original adapter exception. The underlying exception text is not recoverable from the saved output; do not invent it. The renderer crash is separately proven.
- Subsequent `navigate` and `probe`: **`TimeoutError:`**. Recovery began **17:22:48.710**.
- At **17:25:19.743**, the earlier operator agent ran **`kill 87999`**, killing the Python recovery helper. Its tool errored at **17:25:19.754**. The 151-second interval was **not a natural recovery timeout**.
- SIGTERM bypassed the gate context manager's `finally`. Subsequent `pageInfo` and `wait` failed **`RuntimeError: Browser action gate is occupied`**. The earlier operator manually cleared that gate at 17:26:12.729; this investigation does not repeat that unsafe ad-hoc recovery.
- Last successful Pi tool: **`cvent_job_read(artifact:"activity", tailLines:30)` at 17:25:54.652**. Last issued tool: another `recover` at **17:26:01.166**, without a terminal tool result.
- The earlier operator agent explicitly posted **`/api/stop-agent`** through the local Forge UI at approximately **17:27:38**. Pi exited **143** (SIGTERM convention). SQLite transitioned the job at **17:27:41.669243** to `failed_prewrite` with the exact message:

  `CVENT Agent exited with code 143; no Cvent write was attempted; a fresh preflight is required`

- **Why that state:** `_monitor` observed process exit 143 and no attempted/unresolved Cvent configuration mutation. The renderer exception did not itself transition the job; the explicit stop did.
- Authentication: **verified after handoff**, not freshly reverified after the crash. Exact event opened: **not conclusively proven**; `authorizeTarget` was never called and no target lock was created. Current live URL: **unavailable** after teardown; the inventory URL above is the last successful observation, not a claim about a crashed page.
- Coherent round attempted: **no**. Configuration mutation dispatched: **no**. Read-intent navigation was dispatched; that must not be confused with a saved configuration mutation.

## RUN 2 ROOT CAUSE

- Same job, fresh Pi session, PID **88279**, started **17:30:05.105661** after `/api/continue` was issued by the earlier operator at 17:29:33.
- First browser request: `authStatus`, **17:30:14.535**. First error returned **17:30:19.841**: **`BROWSER_ROUTER_RESULT={"ok":false,"error":"timeout: timed out"}`**.
- The model **did call `cvent_login_handoff`**, at **17:30:21.515**. Its initial `pageInfo` timed out at **17:30:26.793**, before it could hand control to the user. Thus the absent SSO prompt is not evidence of successful auth reuse.
- Steel recorded **`Page crashed!` at 17:30:31.817** for target `0456DBEE6CF8A86AF0ED83F2EE0B2B13`.
- Docker inspect, captured at **17:31:33.878** and **17:32:02.524**, reported **`OOMKilled:true`**, `RestartCount:0`, `HostConfig.Memory:0`, container start `17:29:39.430614508Z`. Container remained running although the page renderer had crashed. This proves a runtime/OOM problem; it does not establish which allocation caused it. Shared memory was 2 GiB and empty at later inspection, not proven to be the failing resource. Docker VM budget shown by stats was 7.653 GiB.
- `probe` also failed **`TimeoutError:`**, returned **17:30:41.875**. Final `recover` issued **17:30:44.071** never returned before stop.
- Last successful Pi tool: `cvent_plan(section:"mission")`, **17:30:11.013** (summary returned in the same batch). **No successful model-requested browser operation**.
- Read-only operator target inventory at **17:31:11.559** still showed `about:blank`, title `about:blank`, on the crashed target. Exact authorized event was never opened or bound. Authenticated: **unknown**, not false and not proven true.
- The earlier operator explicitly posted `/api/stop-agent` at approximately **17:32:36**. SQLite transition: **17:32:46.996688**, same exact exit-143 message as Run 1. No attempted configuration mutations meant `failed_prewrite` rather than recoverable/uncertain.
- Coherent round attempted: **no**. Configuration mutation dispatched: **no**.

## LOGIN REUSE

**FAIL — acceptance not demonstrated**, not a finding that stored credentials were lost.

Run 1's handoff did persist a verified USER 1 profile; metadata has `lastVerifiedAt:17:21:28.453312`, `authenticated:true`, `microsoftSsoPersistent:true`, and `accountContextVerified:true`. Both attempts use the same workspace/slot profile directory. Run 2's runtime failed before authentication could be observed. No profile/cookies were reset or copied during this investigation.

## MODEL RESPONSES BEFORE FAILURE

Primary classification describes the requested work; `Z` means no completed browser progress, new required evidence, or successful handoff. Incomplete final recovery responses are separately marked interrupted, but count as zero achieved progress in the forensic totals.

### Run 1 — all 20 responses

| # | Response UTC | Classification | Work/result | Z |
|---:|---|---|---|:---:|
| 1 | 17:12:51.673 | PREFLIGHT | Job update + prepare existing RR | |
| 2 | 17:12:53.780 | PLAN_READ | Summary + mission, first delivery | |
| 3 | 17:12:56.688 | OBSERVE | authStatus completed | |
| 4 | 17:12:58.533 | RECOVERY | Login handoff; 12 internal browser operations and human login | |
| 5 | 17:21:31.825 | OBSERVE | Successful exact event inventory scan | |
| 6 | 17:21:41.931 | ACTION | Open event; page crashed / ReferenceError | Z |
| 7 | 17:22:24.921 | RECOVERY | Navigate; timeout | Z |
| 8 | 17:22:36.796 | RECOVERY | Probe; timeout | Z |
| 9 | 17:22:48.710 | RECOVERY | Recovery helper killed externally | Z |
| 10 | 17:25:27.118 | OBSERVE | pageInfo; occupied gate | Z |
| 11 | 17:25:29.676 | RECOVERY | Wait; occupied gate | Z |
| 12 | 17:25:32.204 | ZERO_PROGRESS | Read runtime artifact, no fresh browser evidence | Z |
| 13 | 17:25:36.012 | PREFLIGHT | Unnecessary repeat prepare | Z |
| 14 | 17:25:40.046 | PLAN_READ | Summary suppressed as already delivered | Z |
| 15 | 17:25:42.021 | PLAN_READ | Mission suppressed as already delivered | Z |
| 16 | 17:25:43.720 | PLAN_READ | Expectations summary suppressed by shared key | Z |
| 17 | 17:25:46.038 | ZERO_PROGRESS | Read already-known job state | Z |
| 18 | 17:25:50.878 | ZERO_PROGRESS | Status/log update only | Z |
| 19 | 17:25:54.651 | ZERO_PROGRESS | Read activity history | Z |
| 20 | 17:26:01.166 | RECOVERY | Interrupted recovery; no terminal result | Z |

### Run 2 — all 6 responses

| # | Response UTC | Classification | Work/result | Z |
|---:|---|---|---|:---:|
| 1 | 17:30:09.241 | PREFLIGHT | Job update + prepare existing RR | |
| 2 | 17:30:10.995 | PLAN_READ | Summary + mission, first delivery in fresh session | |
| 3 | 17:30:14.535 | OBSERVE | authStatus timeout | Z |
| 4 | 17:30:21.515 | RECOVERY | Handoff's pageInfo timeout; no handoff | Z |
| 5 | 17:30:28.361 | RECOVERY | Probe timeout | Z |
| 6 | 17:30:44.071 | RECOVERY | Interrupted recovery; no terminal result | Z |

### Counts

| Measure | Run 1 | Run 2 |
|---|---:|---:|
| Model responses | 20 | 6 |
| Responses causing completed browser operations | 3 | 0 |
| Completed browser operations | 14 | 0 |
| Responses without a completed browser operation | 17 | 6 |
| Forensic zero-achieved-progress responses | 15 | 4 |
| Existing ZERO_PROGRESS telemetry flags | 13 | 3 |
| Additional forensic flags | Duplicate prepare + interrupted recovery | Interrupted recovery |
| Initial plan reads | Summary + mission | Summary + mission |
| Repeated plan requests within session | 2 plan + 1 expectations alias | 0 |
| Prepare calls within session | 2 (1 repeat) | 1 (0 repeats) |
| Full controller RR compiles | 1 | 1 |
| `cvent_browser(operation:"actions")` calls | 0 | 0 |
| Coherent Ego rounds, requested/completed | 0 / 0 | 0 / 0 |
| Actions requested per coherent round | None | None |
| Actions completed in coherent rounds | 0 | 0 |
| Configuration writes/saves dispatched | 0 | 0 |

The original telemetry counted every prepare as required verification and omitted unfinished turns. That is why 13/3 flags understate 15/4 zero-achieved-progress responses. Run 1's 14 successful primitive operations include 10 authStatus, 2 pageInfo, 1 login navigation, and 1 scanEventList. The action-heavy round executor was never requested; Ego **was** invoked for primitive work. Zero coherent rounds is not proof that all faults were above Ego: a real renderer crash and adapter exception are proven.

## DUPLICATE PLAN/PREFLIGHT CAUSE

The required-start prompt mandated two setup turns: prepare, then summary/mission. The extension additionally:

1. Reopened the workbook and verified compiled JSON on every prepare/plan/evidence call.
2. Applied a sliding window after 24 messages, retaining the original controlling prompt and only about 20 recent messages.
3. Kept a separate process-lifetime `deliveredPlanReads` set, not synchronized with what the pruner removed. Summary and mission were dropped, yet rerequests got only `alreadyDelivered:true`. The plan/expectations tools also shared the same section/offset/limit key.
4. Did not distinguish dead browser transport from a missing RR plan. The model reread runtime/state and restarted setup after recovery failures.

At 17:25:29.929 the first context prune removed setup; the repeated prepare followed at 17:25:36.012. Further pruning removed the initial plan responses. This was **not** an SSO controller restart: PID/session were unchanged, and no compiler was invoked after the handoff. The repeated prepare took about **12 ms**, not four minutes. The activity message was misleadingly broad.

The retry at 17:29:34 was a real fresh launch, which ran the three controller RR helpers again (2.952 seconds). That is distinct from the same-process SSO duplicate.

## 658 → 724 FIELD EXPLANATION

Old artifact: Azure `job_5f0786e702674072a21513c01c28c2b0/expected-domains.json` (658). New artifact: local job above (724). Both workbook byte hashes are exactly:

`da7ea1d56616357080ba4a69eea74aa11266478bc13c3581cd6b3fdd7cd1bb51`

Commit **`e12a732`**, `Generalize event targeting and enforce lifecycle write policy`, changed `choose_registration_layout` from one-row `header_map` to `layered_header_map`. BDNY puts relevant headers in row 3, with registration-code headers in row 4. The newly detected columns are J3 (registration path), K3 (admission description), and M3 (registration method). No RR edits caused this delta.

All 66 added `{value, source}` nodes were independently checked against their actual source cells/ranges using openpyxl: **66 exact matches**, **0 removed evidence nodes**, **0 changed pre-existing evidence nodes**. They are genuine RR evidence, not fabricated policy defaults. However, `count_fields()` counts every `{value,source}` node, including repeated sourceEvidence rows; it does **not** count distinct supported UI controls.

All references below are on sheet **`NEW Reg Types & Pricing`**.

### Registration types: +34 (17 paths + 17 methods)

For each row, path source is `J<row>` and method source is `M<row>`.

| Reg code | RR row | registration_path | registration_method |
|---|---:|---|---|
| ATT | 5 | Attendee | Web & Staff |
| MANREP | 9 | Attendee | Web & Staff |
| NONEX | 10 | Attendee | Web & Staff |
| ATTED | 12 | Student/Educator | Web & Staff |
| ATTSTU | 14 | Student/Educator | Web & Staff |
| ATTFLXTO | 16 | Tickets Only | Web & Staff |
| EXCOMP | 17 | Exhibitor | Web & Staff |
| EXPAID | 19 | Exhibitor | Web & Staff |
| PRESSED | 21 | Press/Media | Web & Staff |
| PRESSNED | 22 | Press/Media | Web & Staff |
| ATTGUE | 23 | Internal | Staff Only |
| SPKR | 24 | Internal | Staff Only |
| SPONCOMP | 25 | Internal | Staff Only |
| EAC | 26 | Internal | Staff Only |
| SHOWGUE | 27 | Internal | Staff Only |
| STAFF | 28 | Internal | Staff Only |
| VENDR | 29 | Internal | Staff Only |

### Admission items: +7 admission_description fields

| Source | Value |
|---|---|
| K5 | Trade Fair Only Pass |
| K6 | Full Conference Pass |
| K7 | Conference Pass - Sunday |
| K8 | Conference Pass - Monday |
| K11 | Non-Exhibitor Full Conference Pass |
| K16 | Ticket Only: Platinum Circle or Gold Key Awards |
| K21 | All Access Press Pass |

### Registration paths: +25 sourceEvidence entries across 6 paths

Each listed row contributes one source `C<row>:J<row>` and value `{path, registrationType}`.

| Path | Rows and registration types | Added evidence nodes |
|---|---|---:|
| Attendee | 5 ATT; 6 ATT; 7 ATT; 8 ATT; 9 MANREP; 10 NONEX; 11 NONEX | 7 |
| Student/Educator | 12 ATTED; 13 ATTED; 14 ATTSTU; 15 ATTSTU | 4 |
| Tickets Only | 16 ATTFLXTO | 1 |
| Exhibitor | 17 EXCOMP; 18 EXCOMP; 19 EXPAID; 20 EXPAID | 4 |
| Press/Media | 21 PRESSED; 22 PRESSNED | 2 |
| Internal | 23 ATTGUE; 24 SPKR; 25 SPONCOMP; 26 EAC; 27 SHOWGUE; 28 STAFF; 29 VENDR | 7 |
| **Total** | **17 unique path/type pairs, 8 repeat evidence rows** | **25** |

Thus **34 + 7 + 25 = 66**, not 66 newly proven Cvent controls. Path relationships are also represented on registration-type records. Live editability/capability remains to be established per property. Parser and RR remain unchanged in this fix.

## TIME LOST BEFORE FIRST REAL ACTION

No configuration action occurred in either attempt. Telemetry's `first_browser_action` means request dispatch, not a successful configuration edit.

- Run 1 first auth dispatch: ~9.08 s after Pi spawn. Total spawn → failed state: **894.04 s**, including **501.879 s human handoff**. Completed Anthropic responses total **63.972 s**; successful browser operations total **10.649 s**.
- Run 1 human return → next *actual browser request*: **2.54 s**; scan result arrived **8.06 s** after return. The activity list omitted this work.
- Run 1 human return → repeated prepare log: **246.742 s**.
- Run 1 human return → failed state: **372.387 s**.
- Run 2 Pi spawn → failed state: **161.891 s**; first auth dispatch ~9.44 s after spawn.

### Non-overlapping wall-time breakdowns (seconds, rounded)

| Interval | Anthropic response time | RR/job reads or setup | Successful browser helper | Failed browser calls/recovery | Unfinished recovery + stop/teardown | Other scheduling/wrapper overhead |
|---|---:|---:|---:|---:|---:|---:|
| Run 1 return → 17:25:36.024 | 28.797 | 0.013 | 5.516 | 212.402 | 0 | 0.014 |
| Run 1 return → failed state | 53.907 | 0.039 | 5.516 | 212.402 | 100.503 | 0.020 |
| Run 2 spawn → failed state | 14.596 | 0.035 | 0 | 24.098 | 122.926 | 0.236 |

Failed Run 1 calls comprise open-event 40.149 s, navigation 10.357 s, probe 10.322 s, externally killed recovery 151.044 s, gate rejections 0.530 s. Run 2's first three failing helpers consumed 5.306 + 5.278 + 13.514 s.

The final unfinished tool has no completion timestamp. Its interval includes the explicit stop and Steel teardown; those components cannot honestly be split exactly from the saved telemetry. There is **no evidence of a four-minute controller queue wait or four-minute model response**. The dead-renderer polling and external intervention dominate. Before Run 2's Pi spawn, controller setup additionally consumed 30.632 s (provider probe 1.745 s, RR helpers 2.952 s, and approximately 25.9 s Steel/runtime startup and overhead).

## FIX

Controller-only changes, independently isolated from existing uncommitted Ego/adapter work:

- Keep successful RR setup, summary/mission, active-domain plan and authentication/target tool-call/result pairs when pruning; do not drop the plan while leaving the original start instruction.
- Cache validated RR per job/process and artifact revision (inode/size/mtime/ctime plus authorized target). Changed files invalidate and reverify; symlinks and concurrent artifact changes fail closed. Authentication, live event identity, event lease, and all write gates remain separate and mandatory.
- Prepare returns a compact mission and first-domain evidence in the initial setup response. Repeated prepare neither reprocesses the workbook nor repeats the preflight activity message while unchanged.
- Stop immediately on adapter programming errors or occupied gate. Runtime timeouts permit one bounded read-only recovery (30-second requested budget, existing 45-second subprocess grace); further failure stops execution instead of entering plan rereads or SSO loops. No browser/profile restart is performed by this circuit breaker.
- Persist the first browser error and terminal recovery reason by Pi PID, log failed browser-operation durations, and retain the actual reason when a terminating tool exits Pi cleanly.
- Audit explicit stop requests before signalling Pi, preserving actor, timestamp and PID. This avoids disguising operator stops as unexplained generic prewrite failures.

The earlier operator already edited `ego_direct.mjs` at 17:23:05 to move the `actionIndex` declaration outside the try block and at 17:28:51 to change event landing observation. Those are **pre-existing, uncommitted changes**, not fixes made or independently live-validated by this investigation. No Ego, Steel profile, compiler, RR, or vendor source is changed by this scoped commit.

## Validation / deployment boundary

Offline tests exercise the actual extension against fake browser helpers (no model or Cvent), including setup caching, changed-workbook rejection, context retention, recovery termination, preserved failure reasons and pre-signal stop audit. `npm test`: **126 tests passed** in the isolated orchestration-only worktree, **131 passed** in the existing action-heavy working tree. Python compile checks, Ego syntax checks, `git diff --check`, and manual Docker Compose configuration validation also passed. These are not live Cvent acceptance results.

**Deployment and the benchmark remain blocked.** Neither fixing lost plan context nor shortening recovery repairs the demonstrated renderer/OOM failure. The reported runs were local, while the requested deployment target is Azure; merging/deploying the existing uncommitted action-heavy adapter changes would exceed an orchestration-only patch. The single fresh benchmark remains unspent until the runtime blocker and intended benchmark environment are explicitly resolved. No full RR continuation occurred.
