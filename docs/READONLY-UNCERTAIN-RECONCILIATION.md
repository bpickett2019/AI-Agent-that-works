# Read-only ATTED reconciliation

This operator-only path inspects the existing uncertain job without uploading,
recompiling or restarting its RR, without starting Pi, and without clearing its
uncertainty. Normal configuration agents remain writable; only this explicitly
requested reconciliation runtime is read-only.

`scripts/reconcile_registration_readonly.py` is fixed to the authorized ATTED
job/event and USER 1. It checks the original RR/validation/plan hashes, acquires
the original job's canonical event and worker leases transactionally, renews
them, and releases them in `finally`. It does not change the job's
`failed_uncertain` classification. Evidence and the fresh BrowserRuntime are
written to a separate `reconciliation/atted-<id>` directory. The original RR,
prior BrowserRuntime, uncertainty marker and write audit must retain their
hashes. Existing USER 1 profile/cache paths are reused; USER 2/3 are prohibited.

Only fixed read operations are available. Save, fill, click, checkbox/option
changes and trusted configuration missions are absent from the reader's
operation allowlist. The browser gateway independently denies all writes and
mutation operations for `accessMode=read_only_reconciliation`, even if the
copied uncertainty marker were missing.

A viewer is exposed through the existing authenticated, ownership-gated staging
UI only while an exact matching worker/event lease is live and its fingerprint,
job, event, slot, and fresh runtime match the private readback descriptor.
There is no generic new browser capability or model tool.

If Cvent requires login, the reader hands USER 1 control to the human and waits.
The normal Return-to-Agent endpoint performs fresh account/profile/login checks,
but its read-only branch never resumes a process or enables configuration
writes. The uncertainty remains. The reader then inventories the registration
types once, follows ATTED's unique exact-code/event-local detail link, and saves
fresh readback evidence. A missing/ambiguous identity or auth failure is not a
license to write. The handoff is bounded to 30 minutes; the normal stop endpoint
can signal it to end without starting or resuming Pi.

Two initial live attempts found the preserved profile and account binding but
were redirected to `/subscribers/Login.aspx`. They made no Cvent configuration
writes and released their leases. This is fresh evidence of expired application
authentication, not proof that ATTED currently matches or differs from its RR.
No ATTED value should be reported as current until authenticated live readback
succeeds.

The deployed `355e8eb` trusted-procedure bytes are pinned by SHA-256 in the
reader. New read-only viewer plumbing does not change those mutation procedures.
Their visibility/editability and Save-readiness protections are still in place.

## September 9 live login handoff

Staging `71224a5477ae99520ec7de660e927b53d15297fb` passed 114 tests and is
healthy. Read-only coordinator PID `3837520` is waiting in
`reconciliation/atted-f5ef44c71a58` under the original job. No Pi process was
started. One fresh event lease and one USER 1 lease are held only for this
bounded read-only browser; the original job remains `failed_uncertain`.

The first viewer lookup failed because operator-created private files were
root-owned while the app runs as the existing workspace owner `cvent` (UID
994). Only the new reconciliation directory/files and its private descriptor
were assigned to that existing owner; contents and original evidence were not
changed. The authenticated staging UI then verified `readOnly=true`,
`browserRunning=true`, `agentRunning=false`, `ownership=USER`, and the viewer
reported `Session Online`. A source follow-up now assigns private atomic JSON
and gate files to the workspace owner at creation time. It must not be deployed
over this active read-only lease.

The local Ego task space is 17. It is being handed to the user solely to refresh
Cvent login and select Return to Agent. Current ATTED values and the remaining
registration-type delta are still unverified. Do not report stored snapshots as
fresh readback or retry the earlier mutation.

## Login verified, inventory preflight stopped

The user completed the handoff. At 21:19:51 UTC the first reader ended after
fresh authentication passed, but its exact Draft inventory check did not. It
never reached ATTED. Its result confirms original evidence unchanged and no
write audit; both leases released. The first reader did not retain enough
inventory diagnostics to distinguish a wrong landing page from a missing row.

A subsequent fresh browser again required Cvent login despite the preserved
profile/account binding. Do not call that successful session persistence.
The reader now explicitly navigates to the known EventSelection route both at
startup and after login, records selected-event inventory diagnostics before
checking them, and retains an authenticated read-only browser on read errors
for bounded diagnosis instead of forcing another browser restart.

Current operator reader PID `3850235`, directory
`reconciliation/atted-e430f6805c09`, is waiting for login. The staging UI confirms
read-only mode, USER ownership, Session Online, and no agent process. The reader
is the reviewed updated operator script in `/tmp/cvent_atted_reconcile_readonly.py`;
the application deployment remains `71224a5`. No deployment may replace the
active leased runtime. No ATTED retry or RR restart occurred.
