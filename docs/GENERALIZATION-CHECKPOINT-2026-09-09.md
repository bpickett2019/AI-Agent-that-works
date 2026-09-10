# Generalization and current-event checkpoint — September 9, 2026

## Current live result

The reusable read-only registration capability mission ran against the current
job using its compiled RR identities. It did not contain event-specific codes,
names, counts, or workbook positions. It reused the authenticated USER 1
browser, performed no login restart, made no configuration write or Save, and
left the original uncertain job and evidence unchanged. The coordinator then
released both canonical leases.

Current event findings are test evidence, not defaults:

- 16/17 requested registration codes are exact event identities.
- Seven names differ literally; Cvent documents name changes as shared Contact
  Type/Admin edits, so those properties are prohibited.
- The event-local detail editor has no visible Name or Group Registration field.
- Add from Contact Types exists, but its chooser did not expose a trusted unique
  Code column. SPONCOMP cannot be exactly matched there and is blocked.
- Create Contact Type exists but creates a shared definition and is prohibited.
- The selected event lifecycle status is Completed.

## Product generalization changes

- Runtime development defaults no longer name or key the current staging event.
  Staging and production require an explicit server-side event allowlist.
- RR compilation now requires the job's explicit selected event name, ID, and
  canonical key instead of falling back to the current diagnostic event.
- The active read-only capability continuation takes a job ID and derives every
  registration identity and count from that job's independently validated RR.
- Registration activation is preserved as the RR enum (`ACTIVATE` or
  `REQUIRED`) and is not guessed to mean Cvent Open for registration.
- Registration names and Group Registration are held at property level when
  their authoritative scope/mapping is not event-local and proven.
- Candidate inventories without one unique Code and Name column return
  `SECTION_STATE_UNTRUSTED`; they do not turn every requested item into absent.
- Modern-origin auth is limited to HTTPS `events.app.cvent.com` with the exact
  runtime-authorized event key, account/profile binding, authenticated UI, and
  visible authorized event name.

## Lifecycle policy

Event inventory status is now application evidence. `openAuthorizedEvent`
retains the exact row's status; `authorizeTarget` binds that status into the
runtime target lock; every write checks it against
`CVENT_WRITABLE_EVENT_STATUSES`. The initial checkpoint defaulted to `draft`.
The subsequent product decision explicitly allows `draft`, `active`, `open`,
and `completed`, provided each trusted procedure independently proves its
requested event-local controls are currently editable. Cancelled, canceled,
archived, and unknown labels fail closed. No procedure may change lifecycle to
proceed.

## Remaining capability gaps

No safe write was attempted because both independent gates remain decisive:

1. the original mutation uncertainty is retained; and
2. Completed is not writable under current approved policy.

Admission Items have a trusted exact-update/readback procedure but no live
benchmark on this event. Pricing still has no trusted 24-combination/72-value
editor/readback procedure. Remaining RR and Site Designer domains likewise lack
complete trusted write adapters. They remain `NOT_CONFIGURED`, never implicit
matches.
