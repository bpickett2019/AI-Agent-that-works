# Local dynamic Excel → Pi → Ego

Worktree: `/Users/bp/cvent-local-dynamic`, branch `local/dynamic-excel-ego`.
This work is local-only: no deployment, SSH, remote job, or live Cvent test is part
of the regression command below. No frontend changes or domain executors were added.

## Architecture

1. Select the authorized existing target, then upload the Excel workbook. When
   `CVENT_AUTHORIZED_EVENTS_JSON` (or `_B64`) is configured, intake uses that explicit
   server-side allowlist without requiring Cvent login or an inventory refresh.
   It does not manufacture an authenticated inventory or grant browser write proof.
   START BUILD acquires the worker/lease and starts the existing Steel + Pi path;
   Pi hands the browser over for login, verifies the live exact event, then executes.
2. Preserve literal workbook evidence: all sheets, cell addresses, values,
   formulas, hyperlinks, comments, number formats, and merged ranges. Hidden
   sheets remain visible in the evidence. The summary is an index, not a substitute
   for reading the complete requirements. The inspection records the workbook hash.
3. Optional compilation supplies hints and a minimum domain coverage list. In
   Simple Mode, failure, timeout, unavailable helper, malformed output, or a
   workbook/event mismatch cannot make those hints mandatory. Invalid hints are
   moved into `compiler-diagnostics/<unique-id>/`; they are not used by the agent.
   Failure to read the original workbook still stops preflight.
4. One Pi agent reads the original evidence and chooses its own categories,
   checklist, navigation, browser scripts, edits, and recovery using generic Ego
   operations. The compiler cannot reject additional workbook requirements.
5. Keep exact-event identity, one-writer leases, browser ownership, protected-action
   blocks, append-only mutation audit, and persisted readback. Nothing here relaxes
   uncertain-write reconciliation or permits global/account changes.
6. Final assessment covers every populated compiled domain plus all additional
   domains discovered by Pi. `allSafeWorkAttempted` is explicit agent-reported
   state, not a word/regex heuristic. Pending safe work prevents completion;
   exact blocked items can require review after other safe work is attempted.
   A genuine job-wide blocker may end incomplete without discarding pending work.

The completion fields are **agent assessments**, not independent proof that all
UI details are correct. Audit/readback checks remain necessary. There is no claim
of deterministic UI reasoning or full-RR readiness from these tests.

## Run offline checks

With the repository's existing Python/Node dependencies available:

```bash
cd /Users/bp/cvent-local-dynamic
bash scripts/test_local_dynamic.sh
```

The command strips inherited Cvent/deployment/provider settings for the test
process and runs the local unit and integration fixtures. It does not launch an
agent or connect to an external browser. No API key or SSO is needed.

Regression coverage includes:

- Real `.xlsx` literal extraction, including hyperlinks, comments and hidden sheets.
- An unfamiliar workbook layout driving a generic simulated 125-object form flow
  through the actual Ego wrapper: edit, Save, reopen, compare. A second pass verifies
  the same objects with zero edits/Saves. This is a scripted wrapper test, **not a
  live model or Cvent acceptance run**.
- Large agent-owned checklists, extra domains beyond the compiler, and completion
  with no compiler hints.
- Rejection of pending work, omitted mandatory domains, duplicate assessments,
  empty evidence, missing attempt attestation, and false complete outcomes.
- Honest item-level review evidence is accepted even if it says “not verified”;
  wording alone is not the completion decision.
- Optional-compiler fallback while retaining diagnostics; original-file failures
  and controlled-mode failures remain blocking.
- Existing ownership, event identity, protected actions, readback, replay and
  uncertainty regressions.

## Worker reservation errors

The backend now returns the actual reserved worker and phase (starting,
agent running, waiting for Cvent sign-in, waiting for browser control, or stopping).
The wording survives the unchanged frontend error formatter rather than being
rewritten to the hardcoded “USER 1 is busy” message. Same-event conflicts identify
the holding slot even when a different slot was requested.

`job.start_rejected` audit records include the requested slot and each blocking
job's ID, slot, state, phase, PID, heartbeat, and lease expiry. Tokens and other
operators' identities are not exposed in the public error. Gate/progress files
are used only to explain the reservation; they never authorize releasing it.
Only existing lease expiration/teardown rules decide availability. A stopped
`login_required` row with no leases does not occupy a slot.

Tests exercise both real reservation logic and the actual unchanged frontend
formatter, including a live handoff lease and successful admission after release.
This fixes misleading errors; it does not establish the source of an earlier
message for which this local instance has no rejection record, or resolve
provider credit failures.

### Login wait teardown

The 60-minute login handoff deadline now returns a terminating tool result instead
of a retryable error. Calling the login tool again while the browser remains
USER-owned also ends the run without dispatching browser reads. Pending/completed
checklists and mutation evidence remain intact; the tool never force-unlocks a
lease or takes browser control. Normal controller teardown releases the browser,
worker, and event reservation. Unresolved mutations still become `failed_uncertain`,
not a retryable login state. The stopped job explains that Continue reopens its
browser for sign-in, rather than displaying a generic “Review required” action.

Offline tests simulate timeout and normal Return-to-Agent, verify zero browser
calls on a repeated USER-owned handoff, and drive the real monitor/store finish
path to prove the next job can reserve the same worker and event.

## Live execution is separate

A locally hosted Forge server can still make external provider/Cvent requests.
Do not confuse “server on localhost” with “offline.” The regression command does
not start a server or live job. The local preview on port 8878 can be configured
with the existing local provider credentials and explicit target allowlist so
intake works before login. Clicking START BUILD begins real provider/browser work.
Any live test needs explicit approval of its target, credentials, and scope. Keep `CVENT_EXECUTION_MODE=simple` for that execution;
legacy mode remains available for compatibility, not as the dynamic path.
