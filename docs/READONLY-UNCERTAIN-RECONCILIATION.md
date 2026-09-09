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
