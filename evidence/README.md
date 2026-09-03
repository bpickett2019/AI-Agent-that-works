# Acceptance evidence

## Completed locally

| Probe | Result | Evidence |
|---|---|---|
| Unit safety/auth/lease/workbook tests | Pass | `npm test` output; 39 tests after V1 additions |
| Pi capability boundary | Pass: explicit extension loaded, exact ten `cvent_*` tools active, builtin `read`/`bash` absent, fixed RR preparation executed | `pi-capability-extension.json` |
| 1/2/3 concurrent control-plane acquisitions on different canonical events | Pass | `local-control-plane-acceptance.json` |
| Three same-event acquisition race | Pass: exactly one holder; successor acquired only after release | `local-control-plane-acceptance.json` |
| Controller restart recovery | Pass: active job became `failed_uncertain`; all leases cleared | `local-control-plane-acceptance.json` |
| Three simultaneous Steel containers/profiles/API/CDP pairs | Pass; 2.086 s local wall time; all removed afterward | `local-steel-3-worker.json` |
| Anthropic model/provider smoke | Pass | `anthropic-smoke.json` |
| 1/2/3 simultaneous Pi calls using `anthropic/claude-sonnet-4-6` | Pass; no tools/browser/session | `anthropic-concurrency.json` |
| Authenticated UI load and full-page semantic review | Pass using ego-browser | Operator identity, allowlisted target, 65/33/18 scope counts, and three-worker wording rendered |
| Terraform static validation | Pass with Terraform 1.16.0 and pinned provider lock | Local command output |
| Complete snapshot reconstruction/integrity | Pass on 403,140-byte payload derived from archived real Cvent DOM | `capability-functional.json` |
| Bounded browser primitives in real isolated Steel/Ego | Pass for snapshot/inventory/fill/select/check/search/activate/modal/key/hover/rich-text selection/scroll/drag/readback | `browser-operations-functional.json` |
| Browser target preflight and bounded renderer recovery | Pass in real isolated Steel/Ego: exact role locator, pre-dispatch target resolution, one bounded recovery call, and all readbacks | `browser-recovery-functional.json` |
| Capability-only Pi reasoning loop | Pass: complete chunks → reason → recover selector → scoped fill → complete chunks → verify | `browser-reasoning-functional.json` |
| Authorized live Cvent read-only discovery | Auth/login, 47,098-byte complete snapshot, 70-row scan, one exact event match; exposed bounded event-opening gap; zero writes | `live-cvent-capability-discovery.json` |
| Live OS process kill isolation | Pass locally with authorized USER-owned slot 1 untouched and synthetic slots 2/3 | `live-process-isolation.json` |
| Anthropic functional concurrency/failure isolation | Pass: 3 healthy concurrent calls, 0 429; isolated B auth failure did not block A/C | `anthropic-concurrency-functional.json` |
| Azure target/identity inventory | Read-only confirmation of subscription, tenant, two ChartDarts RGs, effective Contributor role, account aliases, and existing Entra app/SP configuration | `azure-target-inventory.json` |

These are real measurements but are not substitutes for Azure/Cvent acceptance.
Synthetic acceptance probes did not navigate to or mutate Cvent. The authorized live job performed read-only Cvent login/event-list discovery and made no Cvent writes. That run exposed an authorized-event opening gap; bounded `openAuthorizedEvent`, `activate`, and full-page `controlInventory` replacements were added but have not yet been rerun live. See `docs/FUNCTIONAL-PROOF.md`.

## Blocked acceptance

The following required tests have **not** been run and must not be inferred from
the local evidence:

1. Azure deployment and managed-identity/Key Vault startup.
2. Fresh Azure Cvent SSO/MFA for each isolated job profile.
3. One-worker real Cvent build baseline.
4. Two simultaneous real builds against two different explicitly authorized
   test events.
5. Three simultaneous real builds against three different explicitly authorized
   test events.
6. Same-real-event queueing followed by fresh Cvent preflight/readback.
7. Kill-and-recover during a real Cvent mutation.
8. Azure CPU/RAM/disk/network measurements and comparison against the existing
   baseline build time.

Current blockers are Azure `AuthorizationFailed` for even resource-group read,
only one explicitly authorized Cvent event, and no fresh Azure Cvent login
profiles. Two additional event names, canonical IDs/keys, codes, and explicit
authorization are required before different-event concurrency tests.
