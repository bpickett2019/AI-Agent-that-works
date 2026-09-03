# Capability-only functional proof

Baseline requested: `e62fecdb36c517126725e887ea702d1bda3e6e29` plus the login/viewer recovery commits already on `azure-three-worker`.
Recorded: 2026-09-03. This is not Azure or three-event Cvent acceptance.

## Verdict

**CAPABILITY GAP FOUND.**

The capability boundary preserved the RR compiler, complete semantic observation, ordinary click/fill/navigation, state/reporting, event authorization, and guarded write path. Synthetic Steel/Ego execution also proved bounded select, checkbox, key, search, hover, modal, rich-text selection, drag, selector-inventory, and DOM activation operations.

A real authenticated Cvent read-only run nevertheless exposed a concrete target-discovery gap: `scanEventList` found the exact authorized row, but physical Ego clicks did not navigate and direct event URL navigation was correctly blocked before an authorization lock existed. The old agent had used arbitrary JS `element.click()` for this class of problem. The smallest bounded replacements are now implemented:

- `openAuthorizedEvent`: no model-supplied URL/name/key; opens exactly one server-authorized exact-name/canonical-key Cvent link.
- `activate`: executes only fixed DOM activation against one identified target.
- `controlInventory`: complete full-page interactive-control inventory for selector recovery; no model-supplied script.

These fixes have source/unit/synthetic coverage but `openAuthorizedEvent` has not yet been rerun against live Cvent. The current real job exited during read-only discovery, has no write audit, and is `failed_uncertain`; it must be reviewed/reset rather than auto-retried.

## Exact tool inventory

The implementation has **ten**, not nine, Pi tools. `cvent_snapshot_chunk` is a separately registered tool, which is the source of the count difference.

| Tool | Inputs | Outputs | Browser/runtime touched | Can mutate? | Lease required? | Event authorization required? | Timeout | Retry |
|---|---|---|---|---|---|---|---|---|
| `cvent_prepare_rr` | `{}` | Compiled RR summary/counts as JSON text | No browser; fixed job `input.xlsx`, verified Forge Intake workbook/manifest, fixed derived artifacts | Job files/log only; never Cvent | No capability-level lease check | Fixed job/manifest context; no browser event | `inspect_rr.py` 180 s plus `rr_compiler.py` 180 s; abort signal honored | None internally |
| `cvent_expectations` | `section`; optional `offset` 0–10000, `limit` 1–25 | Approved normalized section, with array pagination | No browser; fixed `expected-domains.json` | No | No | Section allowlist and confirmed-domain set | No explicit timeout; bounded local file read | None |
| `cvent_scope` | optional `scopeIds` (`scope-NNN`, max 100), optional section substring | Hash-verified authority/hash/counts/entries | No browser; fixed scope workbook + manifest | No | No | Scope IDs/statuses are server data | No explicit timeout | None |
| `cvent_job_read` | artifact enum by implementation; optional tail lines 1–500 | Fixed artifact text/JSON or `{exists:false}`; browser runtime is redacted to safe identity fields | No live browser; fixed job artifacts only | No | No | Job workspace fixed by server | No explicit timeout; 8 MiB artifact limit | None |
| `cvent_job_update` | bounded status/stage/action/completed/pending/review/log | `{ok,status,stage,action}` | No browser; fixed state/activity files | Job progress only | No capability-level check | Approved status/stage enums | No explicit timeout | None; atomic write |
| `cvent_record_domain` | domain enum, status enum, bounded result arrays | `{ok,domain,status}` | No browser; fixed domain-results file | Job evidence only | No capability-level check | Approved domain enum | No explicit timeout | None; atomic write |
| `cvent_login_handoff` | `{}` | Already-authenticated result, or resumed instruction after user return | Canonical runtime `pageInfo`; fixed subscriber-entry navigation only when blank; job state and gate | Browser navigation/gate/state, never Cvent event data | No explicit write-lease validation; only runs inside leased worker normally | Fixed Cvent login entry; no target event mutation | Browser probes 45 s, navigation 60 s; handoff waits up to 30 min | Polls gate every 1 s; no browser-action retry |
| `cvent_browser` | operation enum; `intent`; bounded scope IDs/selector/text/URL/option/boolean/key/destination/wait/scroll/time fields | Runtime ID, marker, target ID, timestamp/page info, operation result; complete snapshot or chunk descriptor/hash/identity | Exact job runtime, target tab, gate, Steel CDP endpoint via fixed Python/Node argv | **Yes**, for bounded browser interactions | Every declared write validates the active canonical event lease | Reads are Cvent-routed; event discovery/name/key are server-forced; writes require target lock + live key + runtime + lease + confirmed scope IDs | Caller 1–180 s, default 90; fixed helper receives same limit; outer process allows 10 s teardown margin | No tool retry. Declared writes are audited before execution; timeout or any post-attempt helper error becomes `uncertain_*`, creates an uncertainty marker, and cannot auto-replay |
| `cvent_snapshot_chunk` | active UUID and exact next chunk index | Chunk text plus hash/bytes/count/captured-at/job/workspace/worker/runtime/target/page binding | No live browser; fixed private snapshot file + runtime identity | Snapshot-consumption state only | No | Exact job/workspace/worker/runtime/target binding | No explicit timeout; 2 MiB snapshot cap | None; duplicate/out-of-order requests fail |
| `cvent_finish` | final status enum, bounded unresolved/read/write arrays, four integer guardrail counts | `{ok,status}`, terminates agent turn | No browser; fixed final report/state/activity | Job report only; never Cvent | No capability-level check | Fixed job | No explicit timeout | None; atomic writes |

Pi-level retry is separate: transient model requests may retry at most three times with 2/4/8 s backoff; provider/SDK retries are zero and server-requested delay is capped at 60 s. A completed tool result is part of conversation state and is not re-executed by a model-request retry. Ambiguous browser-write timeouts now block further writes.

## Production capability mapping

| Required browser capability | Coverage | Capability/evidence |
|---|---|---|
| Observe complete current page | Covered | `snapshotText`; Ego requests `full_page`; real Cvent archived 134,367-byte snapshot and synthetic 53,410-byte page |
| Full text/accessibility context | Covered | Complete semantic snapshot; no viewport/element narrowing exposed |
| DOM/control attributes needed for recovery | Covered after discovered gap | Supplemental full-page `controlInventory`; excludes password values; synthetic inventory check passed |
| Identify controls | Covered | Snapshot refs/semantics, fixed full-page inventory, bounded selectors |
| Click | Covered | `click`; synthetic real Steel click passed |
| DOM activation when physical click fails | Covered after discovered gap | `activate`; fixed element `.click()`, synthetic passed |
| Fill/type | Covered | `fill`, `type`; synthetic fill and Pi readback passed |
| Select dropdown/options | Covered after audit | `selectOption` by exact label/value; Florida synthetic persisted |
| Checkbox/radio state | Covered after audit | `setChecked`; synthetic readback passed |
| Keyboard keys | Covered after audit | `press` allowlist only; destructive Backspace/Delete require write intent; Escape synthetic passed |
| Scroll | Covered | bounded `scroll`; down/up synthetic passed |
| Wait for render/navigation | Covered | bounded timeout, selector readiness, or load-state wait |
| Navigate allowed Cvent locations | Covered | Cvent-only `navigate`; keyed URLs require authorization lock |
| Open authorized event before lock | Covered after live gap, live recheck pending | `openAuthorizedEvent`, no model identity/URL input |
| Tabs | Not exposed; not required by known successful writes | Old evidence called `tabs` once but did not require `switchTab`; canonical single-target invariant remains. A future mandatory popup/tab flow would be a new gap |
| File upload | Not exposed; not required by current confirmed workflow | Header/logo is carry-over in current scope. A future RR-supplied asset requirement would need a fixed job-artifact upload capability |
| Modals | Covered | click/activate + wait + snapshot; synthetic modal passed |
| Dynamic controls | Covered | wait + snapshot/inventory + click/activate; synthetic dynamic modal control passed |
| Cvent list/table search | Covered | `scanEventList` and search-input-only `search`; synthetic `ROW-0077` readback passed |
| Hover controls | Covered after audit | `hover`; synthetic revealed-state readback passed |
| Site Designer | Partial pending live acceptance | Old Site Designer needs map to select/fill/check/activate/selectText/drag; synthetic primitives passed, but hardened live Site Designer has not run |
| HTML5/pointer drag/drop | Partial pending live Site Designer | Source-to-destination `drag` passed in Steel synthetic page; actual Cvent Countdown placement not yet accepted |
| Read post-action state | Covered | fresh `snapshotText`; Pi observed `Old Venue` → write → `Pi Reasoned Venue` |
| Evidence of success | Covered | timestamps/page/runtime identity + complete snapshot hash and exact readback |
| Selector/UI change recovery | Covered synthetically; live recheck pending | Pi rejected two stale selector forms, used probe/CSS attribute selector, then verified persistence; inventory/activate added for real Cvent failure |

## Old working agent versus capability layer

Evidence source: `data/runs/20260903-062426`, status `COMPLETE_WITH_REVIEW`, five persisted save groups, 12 confirmed scope IDs written, 617 discounts read, 0 publishes/emails/deletes/global mutations. Its session made 352 detected browser-router calls: 121 JS, 89 snapshots, 65 waits, 42 clicks, 15 page-info reads, 13 fills, 3 scrolls, 2 CDP calls, 1 event scan, 1 target authorization.

| Old required capability/evidence | New mapping | Status |
|---|---|---|
| Shell-run openpyxl inspection/compiler | `cvent_prepare_rr` | Covered |
| Generic file reads of expected/scope/state/audits | `cvent_expectations`, `cvent_scope`, `cvent_job_read` | Covered |
| Generic writes of state/domain/final report | `cvent_job_update`, `cvent_record_domain`, `cvent_finish` | Covered |
| `snapshotText`, `pageInfo`, scroll, wait | same bounded `cvent_browser` operations + chunk tool | Covered |
| Event-list scan | `scanEventList` | Covered |
| JS exact authorized-link activation | `openAuthorizedEvent` | Covered after live gap; live recheck pending |
| Ordinary physical clicks/fills | `click`, `fill`, `type` | Covered |
| JS state `<select>` assignment (`scope-009`) | `selectOption` | Covered synthetically |
| JS exact option click (`scope-031`) | bounded `click`/`activate` against inventory target | Covered synthetically |
| JS row checkbox (`scope-040`) | `setChecked` against identified row checkbox | Covered synthetically; live pending |
| JS rich-text range selection | `selectText` | Covered synthetically |
| Raw CDP Backspace key events (`scope-027`) | bounded `press` after `selectText` | Covered synthetically; live pending |
| Read-only JS DOM/attribute/shadow-root inspection | complete snapshot + complete `controlInventory` | Covered after live gap; live pending |
| JS `.click()` used when physical click did not navigate | bounded `activate`; event entry uses stricter `openAuthorizedEvent` | Covered after live gap; event live recheck pending |
| Raw CDP mouse drag attempts for Countdown | source/destination `drag` | Partial until actual Site Designer acceptance |
| One `tabs` inventory call | No Pi tab capability | Not shown necessary to persisted successful writes |
| Snapshot `saveTo` arbitrary path | Server-owned opaque snapshots in fixed job directory | Covered without arbitrary path |

Security boundary audit: operation/intent are schema enums; key names are allowlisted; selectors/text/URLs are length-bounded; options are exact label/value; drag has only source/destination; no expression/method/command/path input exists. `execFile`, never a shell, launches only fixed helpers. Generic `js`, `cdp`, `tabs`, `switchTab`, and snapshot `saveTo` adapter operations were removed; fixed internal DOM functions implement only the named bounded capabilities.

## Snapshot integrity

`evidence/capability-functional.json` uses a 134,367-byte archived real Cvent discount-page snapshot, repeated into a 403,140-byte Unicode payload:

- 11 UTF-8 chunks; exact reconstruction and SHA-256 match.
- Declared, expected, and reconstructed SHA-256: `dcb9f3628bd0c2f667e5c0ffe4dcd83001b6c475501e8f8da9e4dd05c86c7690`.
- Out-of-order and duplicate reads rejected.
- Missing tail blocked the next browser operation.
- Runtime/target change blocked cross-browser delivery.
- Metadata binds job, workspace, worker slot, browser runtime, target, URL/title, capture timestamp, bytes, hash, and count.
- Creation: 32.556 ms; ten remaining chunk reads: 159.889 ms total.

`evidence/browser-reasoning-functional.json` proves the model loop in actual isolated Steel/Ego:

1. Pi read two snapshot chunks and the tail sentinel.
2. Pi observed Venue `Old Venue`.
3. Two selector forms failed; Pi took a fresh probe and recovered with a bounded CSS/ARIA selector.
4. Pi filled the field with `scope-007`.
5. Pi read both fresh post-action chunks.
6. Pi verified `Pi Reasoned Venue` and the tail sentinel.

No chunk can cross a job because files are private under the fixed job root and each read rechecks job/workspace/slot/runtime/target plus hash.

## Three-worker synthetic/process results

- `evidence/local-control-plane-acceptance.json`: three distinct synthetic events acquired slots 1/2/3 concurrently.
- `evidence/local-steel-3-worker.json`: three simultaneous real Steel containers, isolated profile mounts, unique localhost API/CDP pairs.
- `evidence/live-process-isolation.json`: while the authorized slot-1 Pi/browser was USER-owned and untouched, synthetic Pi/browser workers B/C occupied slots 2/3. Three Pi PIDs and all three CDP listeners were alive simultaneously. Killing worker B's process group left A and C Pi/browser checks alive.
- Unique PID/job/workspace/profile/session/CDP/runtime/target/gate/viewer values were recorded.
- Synthetic B/C did not have real Cvent authenticated sessions. Only filesystem/profile isolation—not three-session Cvent auth—has been proved.

The evidence proves process/container isolation, not three-event Cvent completion and not Azure deployment.

## Same-event lease result

The deterministic A(X), B(X), C(Y) test passed:

- A acquired event X.
- B remained waiting.
- C acquired event Y concurrently.
- Forced A lease expiry marked A `failed_uncertain`.
- B then acquired X while C's Y lease remained valid.
- A stale target lock from an older browser runtime could not authorize B's first write.
- B must produce a fresh complete observation and new `authorizeTarget` lock before writing.

Timed-out declared browser writes are now recorded before execution and become replay-blocking uncertainty, so model retries and browser mutation retries are separate.

## Anthropic concurrency

`evidence/anthropic-concurrency-functional.json`:

- Three simultaneous healthy Pi calls: all succeeded; wall 1.156 s; individual 1.032–1.153 s.
- Each recorded provider `anthropic`, model `claude-sonnet-4-6`, API `anthropic-messages`.
- 0 HTTP-429/rate-limit indications, 0 retries, 0 failures.
- Each used 465 input + 6 output tokens (471 total); aggregate 1,413 tokens.
- Failure-isolation phase used an intentionally invalid environment credential only for B: B failed in 0.368 s while A/C succeeded in 1.217/1.262 s; wall 1.263 s.
- Probe sessions had `--no-tools`; no browser operation could replay.

## Performance

- Deterministic production capability execution in real local Steel (`evidence/browser-operations-functional.json`): mean browser operation 774.269 ms; mean complete snapshot 766.110 ms; chunk-file read 7.059 ms. Fill/select/check/search/modal/key/hover/selectText/scroll/drag and readbacks all passed.
- Snapshot transport CPU/file overhead for 403,140 bytes: 192.445 ms including creation and ten chunk reads.
- Full Pi reasoning-loop wall time for two complete snapshots, selector recovery, one fill, and readback: 66.746 s. Session timestamps include model generation and therefore are not valid pure tool latency.
- Harmless Anthropic reasoning baseline: ~1.1 s.
- Old successful real Cvent run: ~2,086 s (34.8 min) of assistant activity and 352 browser-router operations; historic click baseline ~2.8 s.
- Hardened live run after login spent roughly ten minutes in target discovery, made 90 Anthropic responses/57 browser calls, and did not reach a write because of the now-fixed authorized-event opening gap.

The local chunk transport itself is not the dominant cost; model turns, selector recovery, per-operation process startup, and Cvent rendering dominate. No observation was reduced. Performance is functional but not yet acceptable as a production completion benchmark.

## Exact Azure RBAC blocker

Current deployment principal:

- UPN: `bpicket@EMERALDEXPO.NET`
- object ID: `4a6e7af6-72bb-4f11-8fb3-fb7842fcb2e6`
- tenant: `661c8d9b-e19e-4330-b412-75dce2d26154`
- subscription: `e7a6e33b-d0a8-4ab6-9aa0-114ac3ad9a88`
- required resource group: `/subscriptions/e7a6e33b-d0a8-4ab6-9aa0-114ac3ad9a88/resourceGroups/rg-cvent-agent-pilot`

A live read-only recheck failed with `AuthorizationFailed` for both `Microsoft.Resources/subscriptions/resourcegroups/read` and `Microsoft.Authorization/roleAssignments/read` at that RG scope.

Minimum practical built-in assignments (all resource roles RG/resource scoped, never subscription-wide):

| Resource/scope | Principal | Role/permission | Why |
|---|---|---|---|
| `rg-cvent-agent-pilot` | object ID above | `Contributor` at this RG only | Read RG and create/update the VM, identity, network, Bastion, disk, backup, monitor, Key Vault, public IP, and extensions in Terraform |
| `rg-cvent-agent-pilot` | object ID above | `User Access Administrator` at this RG only | Create the two Key Vault role assignments and storage data-plane assignment; Contributor excludes role assignments |
| future state account `cvagenttf82cf39cf49` | object ID above | `Storage Blob Data Contributor` at that account only | Terraform AzureAD backend container/blob read/write/lease; management-plane Contributor does not grant blob data access |
| Entra tenant `661c…6154` | object ID above | `Application Administrator`, or admin-consented delegated Graph permissions `Application.ReadWrite.All`, `AppRoleAssignment.ReadWrite.All`, and required principal reads | Create application, service principal, secret, app roles, and user/group app-role assignments |
| generated app Key Vault | generated VM user-assigned managed identity | `Key Vault Secrets User` at that vault only | VM startup reads Anthropic, Entra client, and session secrets; Terraform creates this assignment |
| generated app Key Vault | deployment object ID above | `Key Vault Secrets Officer` at that vault only | Terraform writes/updates application secrets; Terraform creates this assignment after vault creation |

A custom RG role could replace Contributor with only the exact resource-provider actions used by `main.tf`, but that role itself must be created/assigned by an administrator and offers no acceptance benefit. No subscription-wide Owner/Contributor is required.

## Exact Cvent event blocker

Exactly **two additional** explicitly authorized disposable Draft/unpublished events are needed, because one is already authorized and three unique targets are required concurrently. The final allowlist must contain three unique entries, each with:

- exact unique event name;
- canonical event ID/key (same UUID in this implementation);
- event code;
- explicit authorization for controlled mutation;
- Draft/Pending/unpublished state;
- same test organization and feature set/template needed by the RR;
- permission for the Cvent SSO user to edit Event Details, Registration, Pricing, Questions, and Site Designer;
- no production attendees/contacts/communications;
- disposable test data and permission to reset between tests.

Each worker profile needs one completed Microsoft SSO/MFA login, `SAVE LOGIN INFO`, authenticated organization cookie, and returned agent control. Three concurrent acceptance jobs require three independently persisted job profiles. CAPTCHA/conditional-access prompts remain human-only.

## Ready-to-run live acceptance plan

1. **Preflight**: deploy immutable tested commit; install the three-event server allowlist; verify three logins/profiles; verify Draft/unpublished status; verify zero pending uncertainty; preserve event identities; record baseline readbacks.
2. **Test A — one full build**: RR → compile → Pi → exact event discovery/open/authorization → all confirmed mutations → fresh readback after every save → final QA/report. No publish/communications/delete/global data.
3. **Test B — idempotent rerun**: same RR/event; compare baseline and final object counts/values; require zero duplicates and zero writes for already-correct values.
4. **Test C — three concurrent builds**: submit RR A/B/C to Event A/B/C in one window; capture three Pi/browser/helper process trees, leases, distinct profiles/endpoints/viewers, overlapping browser progress timestamps, readbacks, and reports.
5. **Test D — same event**: submit two jobs for X; first runs, second remains queued; after clean completion second performs fresh snapshot/authorization and idempotent readback before any write.
6. **Test E — crash**: kill worker B after a controlled scoped write attempt; require B `failed_uncertain`, A/C uninterrupted, no automatic replay, admin readback, new runtime authorization, then explicit recovery.
7. **Azure evidence**: record deployment plan/apply, managed-identity Key Vault reads, health, CPU/RAM/disk/network, three process/container trees, 429/retries/tokens, per-operation and end-to-end times.

Do not promote the verdict until `openAuthorizedEvent`, Site Designer primitives, one full real build, idempotent rerun, three real concurrent events, same-event serialization, and crash recovery all pass on Azure.
