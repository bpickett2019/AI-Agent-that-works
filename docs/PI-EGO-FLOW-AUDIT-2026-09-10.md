# Pi → Ego → Cvent flow audit — 2026-09-10

## Verdict

**The architecture is substantially the requested single Pi agent using Ego.
The reliable read-RR → find-control → write → verify → continue contract is not
fully enforced.** This is not a need for another AI agent or a replacement browser.

I inspected local source, copied and byte-compared 16 deployed source files,
reviewed the stopped Azure session/tool results and workbook, reran all 147 local
tests, and exercised both real capability extensions with an entirely fake browser
helper. No Cvent run, browser action, login, profile change, restart, deployment,
or production-code edit was performed for this audit.

The stopped job is `job_af9780a5d0d041728f7a5e3e3cc1f411`, event
`(C+D) Medtrade Testing Clone 2`, event key
`e712e34c-6117-4d13-bf4c-8ed54cf2b495`. At audit start it was
`failed_recoverable`, PID null. The operator stop occurred at 21:46:26.984995 UTC;
canonical teardown finished at 21:46:37.677169 UTC. No restart was requested here.

## 1. What actually runs

```text
Uploaded input.xlsx
  → deterministic inspection/compiler/validator (not AI agents)
  → expected-domains.json + rr-validation.json + configuration-plan.json
  → one isolated Pi process with the job prompt and fixed cvent_* capabilities
  → capability extension (RR checks, bounded tools, progress, queues)
  → browser_tool.py (ownership/runtime/event/lease checks and audit)
  → ego_direct.mjs → vendored Ego helpers
  → the job's Steel-hosted Chromium → Cvent
```

Steel hosts Chromium; it is not a competing AI/browser planner. The Python/TypeScript
wrappers are application code, not additional agents. They are necessary places to
enforce boundaries; removing them to give Pi unrestricted shell/CDP would not fix
the observed correctness problems.

Pi is launched with built-in tools, arbitrary extensions, skills, prompt templates,
and context files disabled; only the configured `cvent_*` tools are enabled.
See `job_runner.py:561–586`. The model operates from compiled RR evidence, not a
free-form filesystem tool editing the workbook. The RR is input; Cvent is output.

There is a second **non-AI code path**: `cvent_execute_section` invokes hard-coded
Cvent procedures for registration types and admission items. These still use Ego,
but their fixed DOM assumptions can prevent adaptive progress.

## 2. Deployed and local are not the same implementation

Azure's release is **`8d3d6693cf9ae792c85789be34024b1a466a8843`**. All 16 retrieved
files byte-match that commit; this is not an unverified symlink-only conclusion.
The important local changes remain dirty/uncommitted and are not deployed.

| Capability | Deployed Azure | Local working tree |
|---|---|---|
| Single Pi using Ego | Yes | Yes |
| Model-planned grouped actions | `cvent_ego_actions`, loops through separate helper processes per step | `cvent_browser(operation:"actions")`, one Ego process per round |
| Screenshots/coordinate actions exposed to Pi | No | Yes |
| AX snapshot refs | Uses wrong AX property `backendNodeId` | Uses `backendDOMNodeId`; bracketed refs accepted |
| Context retention | Initial instruction + roughly 28 recent messages | Retains setup/mission/active plan/auth/target evidence |
| Old completed-domain result retained in context | No | Still no explicit retention |
| Killed-helper inherited gate lock | No | Offline-tested local fix |
| One bounded renderer recovery | Old 240–300 second loop | Local single-probe/budget fixes |
| Value-to-RR write binding | Missing | Still missing |
| Independently checked saved-value verification | Missing for generic actions | Still missing |
| Admission checkbox matching bug | Present | Present; trusted procedure file identical |

Azure's grouped-action tool is batching **model calls**, not one continuous Ego
execution: see deployed extension `1039–1090`, especially `1072–1083`. Local
`extensions/cvent-job-tools.ts:1254–1282` and `ego_direct.mjs:201–211` implement the
new one-process round. Calling both implementations simply “Ego rounds” hides this
difference.

## 3. Critical: proposed values are not bound to their RR evidence

`validateGeneralBrowserAction()` requires a nonempty `rrSource` string. It does
not resolve the cited cell, verify it belongs to the desired property, or compare
the requested value with that requirement.

- Deployed primitive writes check artifact freshness, but not individual value
  provenance (`extensions/cvent-job-tools.ts:1116` in the deployed copy).
- Local primitive and grouped writes additionally require a domain whose evidence
  is VERIFIED. This is still domain-level, not proposed-value-to-item validation
  (`extensions/cvent-job-tools.ts:455–460,557–572,1254–1304`).
- `browser_tool.py` enforces event, lease, protected targets and action structure;
  it does not close that value-provenance gap.

**Offline reproduction on both versions:** a call to fill a planner-email target
with `invented-not-in-rr@example.invalid`, citing `Event Details!B9`, reaches the
fake browser dispatcher. The copied workbook's B9 contains **BDNY 2026**. No browser
was connected and no actual fill occurred in this reproduction.

The live stopped run supplied the same invalid citation pattern for the planner
email and cited venue cell B10 for additional address data. B10 is only
`Javits Convention Center, NYC`; B19 is `10 AM - 5 PM`, though an end-date fill
cited it. The end-date value itself is supported by B18, showing why wrong citation
and wrong value are related but different problems. Literal email/ZIP values used
were absent from the scanned workbook cell values. This proves missing traceability,
not that the address is necessarily geographically wrong.

The independent RR validator validates **compiler output**, not future model
writes. Its `independently_supported()` also allows bidirectional substring
containment (`rr_validator.py:106–119`): appending invented text to an otherwise
matching raw value can pass that predicate. This is an additional validation
weakness, not the sole cause of the live writes.

**Required behavior:** bind each change to an actual verified item/property,
object identity and desired value, permitting explicit reviewed transformations
such as dates/time-zone normalization. A plausible citation string is insufficient.

## 4. Critical: observing a page is treated as verifying a save

The generic primitive path creates a pending-readback marker after a write. A
successful `snapshotText`, `readTarget`, or `controlInventory` clears it, without
checking the desired value, confirming a Save, reopening the record, or comparing
the observed value. Consuming the last snapshot chunk can clear it too.

The grouped-action paths require a declared Save/readback sequence, but still do
not validate the readback's values. Local `validateActionRound()` recognizes Save
from strings and readback from operation names. A returned screenshot is an
observation, not a machine-checked value match.

References: local extension `574–589,1276,1289–1315,1357`; deployed extension
`1086,1109–1133,1175`.

**Offline reproduction on both versions:** after the fake write, the fake snapshot
explicitly says `saved value is WRONG; no save occurred`. The pending marker is
nevertheless removed.

`mutation_outcome.py` primarily balances attempted/succeeded audit entries and
checks markers. `job_runner.py:63` can therefore say “all attempted Cvent writes
were conclusively read back” without proving RR equality. `failed_recoverable`
means the current bookkeeping permits recovery; it is **not an RR-correctness
certificate**. A successful tool return is not a successful business outcome.

**Required behavior:** keep pending changes until a fresh, correctly scoped saved
state is compared with the authorized desired values. Separate dispatched action,
saved change, and verified requirement counts.

## 5. Critical: completion evidence can be supplied by the same model

`cvent_record_domain(status:"completed")` accepts the status and optional prose
without requiring item-level verification or reconciling known procedure failures.

`cvent_verify_domain` checks item IDs, uniqueness, VERIFIED RR status and nonempty
`cventEvidence` arrays. The evidence consists of model-supplied strings, not
references to trusted observations carrying observed values.

`cvent_finish` correctly accounts for missing items and rejects DRAFT_COMPLETE
while any item is not MATCH. **However, MATCH itself can be established from
unsupported model assertions.** Guardrail counts and real-read/write summaries are
also model-supplied; they are not independently recomputed there.

**Offline reproduction on both versions:**

1. Record a domain completed without any real Cvent evidence: accepted.
2. Supply all 798 real item IDs with explicitly fabricated evidence strings:
   accepted as MATCH.
3. Request DRAFT_COMPLETE with no real browser writes: accepted into the isolated
   fake job report.

This is a reproduction of a missing enforcement boundary, **not a claim that the
stopped live job produced DRAFT_COMPLETE**. It did not.

References: local extension `432–453,1006–1080,1370–1434`. `completion_state.py`
adds a useful UI check for full explicit item coverage, but it consumes those same
unvalidated evidence strings. It does not repair the underlying trust gap.

**Required behavior:** derive completion from a trusted per-field change/readback
ledger, preserve known blocked outcomes, and generate product progress from it.
Keep model narration distinct from verified progress.

## 6. Exact explanation of the missing admission controls

The controls were present. The captured EXONLY snapshot at **21:43:51.253 UTC**
shows the availability table with rows such as:

```text
cell "Select/Unselect" → checkbox
cell "Attendee [ATT]"

cell "Select/Unselect" → checkbox
cell "Attendee | Educator [ATTED]"
```

The preceding inventory contains 24 checkbox elements, including header/select-all
controls; many row checkboxes have no ID, name, or aria-label. The record identity
is in the neighboring cell. Thus 24 checkboxes does not mean 24 RR records.

`configureAdmissionAvailability()` (`trusted_cvent_procedures.mjs:197–222`) tries
to identify each checkbox by a direct/wrapping/ARIA label equal to the RR name or
code. Actual checkbox labels are `Select/Unselect` or empty, and displayed row
names include `[CODE]`. It never resolves the checkbox via its exact row identity.
This explains `control:"registration type checkboxes", found:[]` for all seven
items despite the controls being present.

The routine **already tries to set the limiter to Yes** before searching; my
earlier possibility that it merely failed to reveal the controls was incomplete.
The concrete defect is checkbox-to-record association. It also demands that every
known RR registration type appear, including types missing from the live event,
which can block an independently actionable admission item.

**Required behavior:** locate the exact availability table and unique row using
its exact code/verified identity, then operate on that row's checkbox. Verify the
whole resulting association set, not just a similar name or an incidental match.
Handle missing/extra/held identities explicitly.

A separate problem in this run: the agent first sent unsupported selector syntax
`combobox[name="Time Zone:"]` instead of `role:combobox[...]`. Azure snapshots also
omit usable refs because `vendor/.../cdp-snapshot.js:43–45,70` reads the wrong AX
property. Local changes correct that property and expose screenshot/visual
fallback, but neither is deployed. The local role fallback also differs from the
old shadow-root/implicit-role fallback; it needs real fixture coverage, not an
assumption that the new code handles every control better.

### Additional local-only regression: event-key query casing

The new coherent-round parser in `ego_direct.mjs:43` uses case-sensitive
`URLSearchParams.get('evtstub')`. Actual saved Cvent URLs in this run use
`evtStub`. An offline evaluation of the real parser returns the expected key for
`evtstub` and **null** for the otherwise identical `evtStub` URL. Python's router
and the trusted procedure already normalize parameter names, but the new local
adapter does not. A coherent write/navigation can therefore reject the correct
event as if identity had been lost. The local changes are not deployment-ready
merely because their existing tests pass.

## 7. Registration-type “configuration” is presently mostly inspection/holds

`configureRegistrationTypes()` (`trusted_cvent_procedures.mjs:422–471`) has no
configuration-write branch: `mutationCount` starts at zero and is never incremented.
It reads exact existing records, reports already-correct fields, and produces gaps.
Missing creation, shared-name editing, path-level group registration, and unproven
fee mapping do not become executable actions through this routine.

Observed result: **6 already correct, 11 failures, 17 property gaps, 0 updates**.
The agent then announced “Registration types complete.” That announcement was not
supported by the procedure's result.

Some blocks are correct: shared Contact Type definitions must not be renamed to
force an event-local name match. Missing SPONCOMP identity must not be substituted
with a similar record. Group-registration configuration needs the correct Cvent
registration path. The compiler already extracts RR type-to-path associations;
the helper does not connect those associations to a proven Cvent path editor.

The generic Ego path can theoretically perform other supported event-local work,
but there is no guaranteed fallback workflow that resolves each gap. Only two
named specialized procedures exist; declaring 13 populated domains does not prove
all 13 have end-to-end tested UI implementations.

**Required behavior:** describe this helper honestly as inspection/delta planning
until it has executable safe updates; route actionable gaps to the correct event-
local controls and preserve legitimate prohibited/missing-identity holds.

## 8. State loss and misclassified read-only actions

Azure's context hook (`deployed extension:619–629`) drops earlier messages and
retains the initial “start” instruction plus about 28 recent messages. In this
session it pruned context **59 times**. No Pi compaction event occurred.

At **21:44:30** the model said “the job needs to start fresh”; at **21:44:40** it
restarted from event settings after earlier reporting that domain completed.
The durable domain artifact existed; `cvent_record_domain` does not automatically
synchronize `state.completed`, and retained context did not preserve the earlier
completion record. Context loss is a supported contributing explanation, not
proof of the model's internal cause.

The local retention fix keeps setup/mission/active evidence, but an offline message
fixture confirms it still drops an old `cvent_record_domain` result. Durable
per-item progress must remain available and authoritative after context pruning.

The model also classified clicking `#LimitRegistration__True` as a `read_only`
mission at **21:43:38**, after write-mode attempts were rejected for lacking Save.
That click changes draft form state. It later clicked Cancel at **21:44:11**; this
is not evidence of a saved admission change. Nonetheless, the application accepts
caller-declared read clicks on configuration radios. This could be unsafe on an
autosaving screen. It must classify actual target/effect, not just trust intent.

## 9. What already works / do not remove

- Deterministic RR extraction, workbook hash and exact authorized-event binding.
- Single isolated Pi, fixed capabilities, no model shell/arbitrary JS/network.
- Canonical browser identity, gate and event lease checks.
- Protected event identity and destructive/global/communications action denials.
- Exact-code matching in reviewed inventory/detail procedures.
- Per-item final coverage: omitted items are not silently MATCH.
- Human-owned SSO/MFA and persistent per-worker profiles.
- Actual saved event-settings reads exist; this is not a fake browser demo.

These are meaningful safeguards, but they do not substitute for value-level
provenance and outcome verification. Protected-action checks are code rules, not a
proof that every possible Cvent control or autosave behavior is classified.

## 10. Measurement and test findings

Stopped run: **73 assistant responses**; 28 primitive `cvent_browser` calls,
9 `cvent_ego_actions` calls (including rejected plans), 10 plan reads, 9 snapshot
chunk calls, 2 specialized procedures. Registration inspection performed 132 Ego
operations; admission procedure performed 165, both with zero reported saved
mutations. This is not the desired short decision → substantial reliable action
cadence.

The 724 extracted `{value,source}` fields and 798 validator evidence items count
different structures, including row/association evidence. Neither is a count of
798 independently implemented writable controls. The RR bytes did not change.

**147 existing local tests pass.** The new offline diagnostic reproductions still
show the gaps above in both deployed and local extensions. Passing existing tests
therefore does not establish end-to-end correctness. The diagnostic used fake
process output and local temporary job artifacts only; no live Cvent or provider
calls were made.

## Minimal repair order — keep Pi → Ego

1. **Stop unsupported values:** actual item/property/value/identity authorization
   before dispatch, with explicit supported normalizations.
2. **Stop unsupported success:** trusted saved-value comparisons determine MATCH,
   readback completion, progress and final status—not model prose alone.
3. **Fix the demonstrated selectors:** admission row-to-checkbox mapping; deployed
   AX-ref issue and local `evtStub` parser regression; fixture-test Edit/Save,
   rerenders, duplicate labels and frame cases.
4. **Preserve the mission:** durable requirement outcomes in context and after
   pruning; no unexplained fresh start, no unsupported completed flags.
5. **Make effect classification honest:** changing a radio is not read-only;
   uncertain/interrupted/unsaved changes stay distinguishable from verified saves.
6. Review existing saved unsupported values without guessing rollback values.
   Then prove one approved small RR-backed write group plus reopen/readback before
   accepting a full run. Release only one reviewed, tested exact commit; do not
   silently equate local fixes with Azure deployment.

## Evidence

Private audit directory: `/private/tmp/cvent-flow-audit/`.

- `azure-code/`: retrieved deployed source; `source-comparison.json`: byte/hash comparison.
- `run/`: stopped session, RR, plans, activity and audit artifacts.
- `probe.mjs`, `probe-azure.json`, `probe-local.json`: executable offline reproductions.
- `tests.log`: 147-test result.

Raw session/browser records remain private rather than being committed. This
report is the only repository file added by this audit; application code and
existing dirty work were not changed.
