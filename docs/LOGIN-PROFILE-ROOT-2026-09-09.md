# USER 1 login and immutable-title checkpoint — September 9, 2026

The user confirmed login and reiterated: **no deleting and no modifying event titles**.

## Deployed repairs

- `3b7cad3e96a9fe1502dcd8916ef253d42b1b802e`: includes the prior exact-code/property-level/readback repairs and explicitly adds Event Title / EventTitle / event_title to immutable identity protection. 104 tests passed on staging.
- `71df1d00f7eab0be234ad2478953ebb6bb3f2aa0`: fixes the browser helper environment dropping `CVENT_DATA_ROOT`. The parent used `/var/lib/cvent-agent`, while the stripped helper environment defaulted to release-local `data/`, incorrectly reporting no persisted profile, profile mismatch and account-context mismatch. Forward only this non-secret server-controlled root; do not forward application/provider credentials. 105 tests passed on staging; health returned healthy with three workers.

USER 1 login was verified and persisted using the existing `/api/auth-settings` endpoint, without resuming stale code. The pre-write processes for jobs `job_5f0786e702674072a21513c01c28c2b0` and `job_837b10690ffe4f338c92d59db69bce4a` were stopped through the controller before deployment. Both stopped before configuration writes; leases were released before deployment. No saved profile reset, event deletion, event-title change, or USER 2/3 action was performed.

## Fresh active job at checkpoint

- ID: `job_03e7e3467f4244ea84bb39b72d9e19e9`.
- PID: `3747125`; worker 1, same persistent USER 1 profile.
- Original BDNY RR re-uploaded; independently compiled 658 writable fields.
- Exact authorized target lock confirmed for `(C+D) Medtrade Testing Clone 2`, `e712e34c-6117-4d13-bf4c-8ed54cf2b495`.
- Last inspected stage: `event_settings`, after a bounded section read.
- No uncertainty marker or pending readback marker at the checkpoint.
- This is running execution, not a completed or successful configuration benchmark. Recheck live state and leases before intervention.

## Additional rendering race

After correcting the root, the initial restored-page check reported all three binding flags true (`persistedProfile`, `profileMatch`, `accountContextMatch`) but `authenticated=false`; a fresh subsequent check returned authenticated=true. The page had not yet completed rendering. The existing verified Return-to-Agent endpoint was used only after fresh authentication proof; no additional credentials/SSO interaction were needed.

A further source patch adds bounded read-only settling (up to eight checks) only while all profile/account binding flags remain true. It never fabricates authentication, waives account checks, retries credentials or takes user control. 106 tests pass locally with this addition. This extra settling patch was not hot-deployed over the active job; deployed SHA was `71df1d00f7eab0be234ad2478953ebb6bb3f2aa0` at that checkpoint.

## Later stop — uncertain ATTED write

At 17:49:51 UTC, `configureRegistrationTypes` reported `Save control disappeared after registration-type mutation for ATTED`. The gateway retained `browser-mutation-uncertain.json`. No automatic replay was attempted. The operator stopped the process through `/api/stop-agent`; by 17:52:22 UTC the controller classified the job `failed_uncertain`, uncertainty 1, PID/slot cleared, both leases released.

The snapshot `browser-snapshots/f5ceda20-18d0-49bc-90d2-dab67b5a093e.txt`, captured at 17:49:58 UTC **after** the error, contains the unchanged selected-event banner `(C+D) Medtrade Testing Clone 2` twice. The detail page was `Attendee | Educator`. It showed Save/Cancel by then, and no visible registration Name textbox. This establishes title evidence, not a confirmed saved/read-back outcome for the attempted field change. No deletion operation was invoked.

Preventive source changes require the reviewed Save control after opening Edit, before any field planning/mutation, and exclude hidden, zero-size, invisible, disabled or read-only inputs from trusted control matching. Tests exercise both rejection of those controls and zero additional fills/saves when the Save preflight cannot be established. These safeguards do not resolve or clear the existing ATTED uncertainty. Do not start another configuration attempt against this event until that outcome is reviewed.
