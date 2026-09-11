# Pi INCOMPLETE forensic finding — September 11 UTC

## Primary evidence

Azure `/var/lib/cvent-agent/control.db`, job artifacts and Pi JSONL sessions were
copied privately to `/private/tmp/cvent-incomplete-audit/`. Raw session/browser
artifacts are not committed. The failed release was
`f48a8e74b11dca2f39da414d978dbd5841a3dd0a`; its prompt, runner and extension were
retrieved from Azure and byte-compared with the corresponding Git worktree.
Azure was subsequently rolled back to `8db63179c221857898cc50a04514a075bdfacb30`.
The patch is based on that current checkpoint; no UI/template changes are made.

## Exact cause

`job_runner.py:494-502` requested
`read,bash,cvent_job_update,cvent_login_handoff,cvent_finish`.
`extensions/cvent-job-tools.ts:44-48` defined ALLOWED_TOOLS without read/bash.
The extension called `pi.setActiveTools([...ALLOWED_TOOLS])` at lines 616 and
646 (session_start and before_agent_start). Its lines 648-650 additionally
blocked non-allowlisted tools with:

> Capability denied: this production agent has no shell or general filesystem tools

The CLI-selected three Cvent tools survived; the needed coding tools did not.
The explicit skill flag was present, but Pi could not read or execute the skill.
This was not a model refusal to write, missing Cvent adapter, Draft restriction,
RR/event mismatch, or uncertain historical mutation. No event was authorized.

The simplified failed runner also removed server RR preparation and instructed
Pi to parse the workbook with Bash while forbidding the compiler/validator.
No inspection, expected-domains.json, rr-validation.json or configuration-plan.json
existed in these failed attempts. Final accuracy contained four zero counts,
not evidence that there were no requirements.

## JOB: job_922b402e03a64e2f86a5742791c7e771

RR: `CGJWS 2026 (ANT264) FINAL NEW RR Doc_3.19.26 (1).xlsx`.
Exact target: `(C+D) Medtrade Testing Clone 2`, canonical key
`e712e34c-6117-4d13-bf4c-8ed54cf2b495`.
The reported timestamps are three attempts of ONE job and ONE resumed JSONL,
not three independently uploaded jobs:
`2026-09-11T04-02-16-637Z_01a08ea1-63bd-7a2b-bd2d-a69be85cc3ef.jsonl`.

### Attempt 1 — PID 493831

- WHY PI STOPPED: required read/Bash/browser capabilities removed at activation.
- MODEL MESSAGE THAT TRIGGERED STOP: line 10, 04:03:12.668:
  **“The system message indicates \"Available tools: (none)\" for standard coding tools (bash, file reading).”**
- TOOL RESULT THAT TRIGGERED STOP: no failed browser tool. Line 9,
  04:02:32.970, cvent_login_handoff returned `ok:true`, `loginRequired:false`,
  `persistedProfileReused:true` and instructed Pi to continue.
- LAST BROWSER ACTION: internal authStatus, completed 04:02:32.969. Last navigation
  was the fixed subscriber entry point `https://app.cvent.com/subscribers/default.aspx`.
- LAST CVENT PAGE: authenticated subscriber context; exact resulting URL was not
  retained in the login result/telemetry. It is not honest to invent a redirect
  destination. The selected event was never opened/bound.
- WRITES ATTEMPTED: 0; no write audit, no mutation marker, no target lock.
- EXACT FINAL CALL: line 12, 04:03:20.014, cvent_finish status INCOMPLETE,
  `realReads:[]`, `realWrites:[]`, with missing Pi coding tools/skill as the reason.
- WHY review_required WAS CHOSEN: extension finish mapped INCOMPLETE to
  state.status=review_required, returned terminate:true; controller accepted
  exit 0 + INCOMPLETE as review_required. No completion reason persisted in DB.

### Attempt 2 — PID 495926

- WHY PI STOPPED: identical capability set after resume, no fix applied.
- MODEL MESSAGE THAT TRIGGERED STOP: line 16, 04:07:02.515:
  **“My three available function calls are: cvent_job_update … cvent_login_handoff … cvent_finish.”**
  It also explicitly said Bash/read were **“not injected into this agent context.”**
- TOOL RESULT THAT TRIGGERED STOP: none; only cvent_finish was called in this attempt.
- LAST BROWSER ACTION / PAGE: none observed during this attempt. Previous successful
  login was session history, not a fresh authenticated current-event observation.
- WRITES ATTEMPTED: 0.
- WHY review_required WAS CHOSEN: cvent_finish(INCOMPLETE) at 04:07:02.541;
  same unconditional mapping, release at 04:07:13.136.

### Attempt 3 — PID 498324

- WHY PI STOPPED: still no callable execution tools.
- MODEL MESSAGE THAT TRIGGERED STOP: line 22, 04:10:18.548:
  **“These bash blocks are being written as text — the Pi coding tools (bash, read, write) are not executing in this session because they are not present in my function schema.”**
- TOOL RESULT THAT TRIGGERED STOP: none. cvent_job_update succeeded; text code blocks
  were not tool calls. cvent_finish then returned ok:true/INCOMPLETE at line 23.
- LAST BROWSER ACTION: none in this attempt.
- LAST CVENT PAGE: new runtime initialized at about:blank; no subsequent observation.
- WRITES ATTEMPTED: 0.
- WHY review_required WAS CHOSEN: same unconditional mapping; final release 04:10:29.

Pi stdout/stderr file was empty; structured sessions contain the calls/results
above. There was no ordinary post-tool final assistant message because finish
returned terminate:true. Resumes at 04:05:13 and 04:08:05 were HTTP POST
/api/continue requests, proven in systemd access logs, not spontaneous self-restarts.

## JOB: job_6c9f77f5ce454fe9ae53ad2f2b1d04c1 (preceding CGJWS upload)

- 03:51, 03:53:07, 03:53:24: pre-Pi launch failed with exact **KeyError: 'runtimeId'**.
  No model/browser configuration turn existed. Failed simple runner used the wrong
  runtime field; the later release fixed it to browserRuntimeId.
- PID 489226 started 03:56:03.491. Login handed to user at 03:56:16, returned 03:56:37.
- Model final call at session line 12, 03:56:45.469:
  **“Pi coding agent cannot execute bash commands or read files in this environment - the standard tool set (bash, read, write) is not available.”**
- Last browser work: successful login handoff verification; no exact-event binding.
  Exact page URL was not retained in the returned tool result. Writes: 0.
- INCOMPLETE → review_required at 03:56:56 for the same allowlist/mapping defect.
- Later retry PID 490792 was explicitly stopped through /api/stop-agent at 03:59:04;
  exit 143 → failed_prewrite at 03:59:15. Not another model INCOMPLETE decision.

## Prior BDNY job is not this failure

`job_af9780a5d0d041728f7a5e3e3cc1f411` (21:30–21:46 September 10) DID enter
Completed event `e712…`, edit Event Information, and perform writes/readback.
Its last browser result was Event Information snapshot at 21:45:18.116; last tool
was cvent_verify_domain at 21:46:25.311 (4 MATCH / 26 NOT_CONFIGURED).
Exit 143 at 21:46:37 → failed_recoverable. It did not emit an INCOMPLETE verdict.
Its desired BDNY values must not leak into this CGJWS run. Current Cvent state
must be inspected anew; historical snapshots are not present-state proof.

## Concurrent old-checkpoint retry during this investigation

Another /api/continue started PID 504814 at 04:18:36, after rollback. It loaded
CGJWS requirements and navigated to Event Information but repeatedly inspected
without writing. To avoid deploying over an active agent, this investigation
stopped it through the existing CSRF-authenticated controller API at
04:28:05.440818. Final state failed_prewrite, no write audit/uncertainty marker,
zero remaining event leases. This was not the fresh patched acceptance job.

## Fix and offline proof

- Register job-bound read and native Ego-heredoc bash in the same extension;
  retain them at both activation hooks. Load the Ego skill explicitly.
- Extend the existing Ego executor for coherent helper scripts, not a new
  browser/framework or per-section adapter. Same canonical target, gate/lease,
  protected controls, RR-source, Save/readback and uncertainty checks.
- Keep controller verified RR preparation. Actual CGJWS compilation: 16 reg types,
  3 admission items, 23 pricing records, 116 discounts, 23 questions. Validator:
  1789 VERIFIED evidence nodes (not 1789 distinct UI controls), no ambiguous nodes.
- Adaptive writes check their own exact VERIFIED sources, not every item in a
  domain. Independent work survives an ambiguous item.
- Missing-domain verification blocks early finish; INCOMPLETE requires an explicit
  job-wide reason. Controller no longer converts execution failure to item review;
  unresolved mutations take priority over any claimed final status.
- Persist actual system prompt/tool activation and JSON stdout for later diagnosis.
- Preserve source checkpoint UI, leases, profiles and Azure topology unchanged.

153 offline tests passed, including real Pi CLI startup/skill activation without
any model call; actual Ego-executor multi-action fake-browser Save/readback;
nonverified item and protected-action rejections; final-state/uncertain precedence;
existing lease/runtime/recovery/compiler regressions. Python compilation, Node
syntax and diff whitespace checks passed. Offline passes are not live acceptance.

## Live follow-up before the fresh acceptance job

Release eae56b3 was pushed, passed 151 tests on Azure, deployed and health-checked.
A user-initiated retry of the historical job started PID 513171 at 04:32:32,
using a NEW Pi session on that release. Its pi-capabilities.json proves read/bash
and the RR/browser tools active, missing:[]. It executed native Ego scripts,
loaded CGJWS, bound the exact event, and resumed after an SSO handoff.
Our new upload `job_fe2a7f0078b24cf09819395d30ec511e` was created but its /api/start
returned 409 because PID 513171 already held the event lease. It did not launch
an extra agent.

At 04:35:53.316 that concurrent run proved another exact policy problem:
`Write blocked: selected event lifecycle status upcoming is not writable under approved product policy`.
Inventory now says Upcoming, not historical Completed. The default product
allowlist omitted this ordinary editable state. No configuration mutation was
dispatched (write audit and pending/uncertain markers absent). We stopped that
blocked attempt through the existing controller rather than let it repeat denied
writes. Follow-up adds Upcoming to the existing defaults, tests it, treats an
observed Edit button as navigation even when the caller overstates write intent,
and forbids guessed Cvent navigation URLs in the prompt. Native snapshot results
are no longer duplicated in both action metadata and cliLog output. No UI change.

## Fresh acceptance — INCOMPLETE, not a successful end-to-end build

`job_fe2a7f0078b24cf09819395d30ec511e`, PID 518510, new session
`2026-09-11T04-39-33-500Z_01a08ec3-857c-7627-bb23-6cf46de38ff8.jsonl`, ran release
`a2aa4c41bd11732ef5267188f5cb8813c393f17c`. Started 04:39:32.626, login reused,
exact Upcoming event authorized, Ego navigated via real Details UI and opened Edit.
Original uploaded workbook SHA256:
`6b1fe61fb47c6dc5dfce1aa5b392f5924889f46812b44124c1b7c0403ebb84b4`.

At 04:42:02.588 Pi submitted a coherent date/venue/Save/readback script. The first
fill changed Start Date to 11/13/2026. At 04:42:03.324 the NEXT command,
`await pressKey('Tab', {intent:'write'})`, failed because the header contained two
VERIFIED sources but the keyboard helper did not inherit the preceding field's
source. Exact error: `Item held: this action needs an exact VERIFIED rrSource from the round header`.
This redundant annotation requirement was an implementation defect introduced
by the native helper round, not a missing Cvent capability or missing RR evidence.

Counts: **1 configuration field fill, 0 Save clicks, 1 fresh unsaved-editor
readback, 0 saved-configuration verifications**. Session line 38 at
04:43:06.518 shows `textbox M/D/YYYY [ref=12842]` containing `11/13/2026`.
The save was never reached. Persisted Cvent outcome was not verified.

The router contained the partial round with browser-mutation-uncertain.json;
subsequent mutation requests were rejected before dispatch. An old generic
error incorrectly described every hold as a timeout, so the recovery circuit
breaker then terminated Pi at 04:45:34.980 and released it as failed_uncertain
at 04:45:45.601. cvent_finish was never called; the initial final-report.json still
said Build not started, while state/SQLite correctly reflected failed_uncertain.

Follow-up fixes: keyboard/blur/Save inherit the last successful field's VERIFIED
source; preserve structured partial-dispatch evidence; report holds as holds,
not imaginary renderer timeouts; keep final-report capability available during
runtime failure; controller-generated failure reports cannot retain the initial
Build not started placeholder. Also explicitly preserve unspecified RR fields
rather than clearing old phone/address/ZIP values. Regression reproduces a
multi-source fill → Tab → Save → readback sequence.

The uncertainty marker is NOT cleared, no mutation is replayed, and no second
fresh acceptance job is launched. The follow-up fix has offline tests, not a
successful live acceptance result. Human review of the partial event edit is
required before any additional live mutation. End-to-end objective remains unmet.
