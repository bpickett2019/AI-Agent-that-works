# Local recovery of the Monday September 14 run

## Identified run

- Local timezone: America/Los_Angeles (PDT, UTC−7).
- Model process: September 14, 2026 **08:48:00–09:16:20 PDT**.
- Login returned: 08:52:47 PDT. Explicit stop requested: 09:16:09 PDT.
- Job: `job_b475daaf9d3242c5b8c1c37b679b8ceb`.
- Original checkout: `/Users/bp/cvent-local-dynamic`.
- Event: `(C+D) Medtrade Testing Clone 2`, canonical key `e712e34c-6117-4d13-bf4c-8ed54cf2b495`.
- Workbook: `BDNY 2026 (BDE261) FINAL RR Doc_NEW_2.26.26 (1).xlsx`.
- Provider/model: `openai-codex/gpt-6-astra`, local OAuth subscription, high thinking.
- Execution mode: `simple` (Pi-owned mission), not the controlled-mode Sonnet run of September 17.

The original job directory is under
`/Users/bp/cvent-local-dynamic/data/local-preview/isolated-data/workspaces/ws_bdf4e73d80d258df9eb436b8cac20c53/jobs/`.
Its activity log, persisted session, settings, provider probe, browser runtime, write audit and state identify the run.

## What the historical run achieved

The saved checkpoint reports admission eligibility reconciled for 14 registration
types and an event-local Sponsor | Complimentary registration type (`SPONCOMP`)
created and read back. It also verified existing event dates/location/custom fields
and the BD NY user-group association. Locked legacy eligibility and conflicting RR
instructions remained unresolved. **This was a partial run stopped by the user,
not proof of complete end-to-end RR execution.**

The historical telemetry summaries disagree about action totals; they must not
be treated as unique-field counts. The persisted session records 47 model responses
and an SDK estimate of $10.399066. That is an API-equivalent estimate, not a
ChatGPT/Codex subscription invoice or evidence of that amount being charged.

## Source recovery

The original Git base was `86014fe430dedf10dbd019d3b9341f7efec733ef`, already the base
of the user's fork. A Git-only rollback would therefore NOT restore the working
Monday configuration. The essential local changes were uncommitted.

Recovered 44 successful write/edit operations across 25 source/test/documentation
files from the September 11 and September 14 coding-session logs. Recovery uses
only literal file contents and exact text substitutions; no historical shell
commands were executed. Cutoff: September 14, 16:00 UTC (09:00 PDT). This includes
the upload UI fix made during the run but excludes later token optimization and
benchmark-controller changes. The recovered Simple Mode prompt matches the
historical rendered job prompt after allowing for its expanded placeholders.

- Exact recovered source: branch `restore/monday-2026-09-14`, commit
  `5d747edeaf385f01788d753e5e5d03004fde3a3b`.
- Separate unchanged recovery checkout: `/Users/bp/AI-Agent-that-works-monday`.
- Active local checkout: branch `local/monday-restored` in `/Users/bp/AI-Agent-that-works`.
- Replay manifest, recovered-file SHA-256 values, test output and reconstruction
  script: `data/monday-recovery/` in the active checkout.
- Offline recovered-source suite: 231 tests passed.

This recovers the source and execution settings, not an immutable image of all
Monday dependencies/provider services. The installed Pi runtime and provider
availability can have changed; no paid model probe or live build is part of recovery.

## Intentional local isolation differences

Only the restored application's host isolation differs from the recovered source:
configurable Steel container prefix/port offset and a distinct session-cookie name.
These prevent collisions with other local Cvent instances. They do not change the
model mission, browser tools, prompts or mutation checks.

The local server uses port 8880, Simple Mode, Astra OAuth, and an explicit
server-side target allowlist for the same event. That allowlist permits intake
before login; it does not replace live canonical-event verification before writes.
A fresh data root, `data/monday-restored`, prevents automatic continuation/replay of
old jobs. No Cvent data, workbook, profile or historical evidence was rolled back.
No model/build is started automatically. No GitHub or Azure deployment was changed.

## Preserved September 17 version

- Tracked/untracked source changes: Git stash labelled
  `before Monday Sep14 rollback: upload bootstrap and isolated local runtime`.
- Additional patch, old local environment file and SQLite backup:
  `data/monday-recovery/before-rollback/` (private local files; do not commit).
- September 17 run data remains at its original `data/workspaces/` paths.

Do not blindly resume the Monday job: its verified Cvent changes may still exist.
Any future build must inspect current state and reconcile the remaining work.
