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

A further source patch adds bounded read-only settling (up to eight checks) only while all profile/account binding flags remain true. It never fabricates authentication, waives account checks, retries credentials or takes user control. 106 tests pass locally with this addition. This extra settling patch is not hot-deployed over the active job; deployed SHA remains `71df1d00f7eab0be234ad2478953ebb6bb3f2aa0` at this checkpoint.
