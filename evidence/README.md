# Acceptance evidence

## Completed locally

| Probe | Result | Evidence |
|---|---|---|
| Unit safety/auth/lease/workbook tests | Pass | `npm test` output; 39 tests after V1 additions |
| Pi capability boundary | Pass: explicit extension loaded, exact nine `cvent_*` tools active, builtin `read`/`bash` absent, fixed RR preparation executed | `pi-capability-extension.json` |
| 1/2/3 concurrent control-plane acquisitions on different canonical events | Pass | `local-control-plane-acceptance.json` |
| Three same-event acquisition race | Pass: exactly one holder; successor acquired only after release | `local-control-plane-acceptance.json` |
| Controller restart recovery | Pass: active job became `failed_uncertain`; all leases cleared | `local-control-plane-acceptance.json` |
| Three simultaneous Steel containers/profiles/API/CDP pairs | Pass; 2.086 s local wall time; all removed afterward | `local-steel-3-worker.json` |
| Anthropic model/provider smoke | Pass | `anthropic-smoke.json` |
| 1/2/3 simultaneous Pi calls using `anthropic/claude-sonnet-4-6` | Pass; no tools/browser/session | `anthropic-concurrency.json` |
| Authenticated UI load and full-page semantic review | Pass using ego-browser | Operator identity, allowlisted target, 65/33/18 scope counts, and three-worker wording rendered |
| Terraform static validation | Pass with Terraform 1.16.0 and pinned provider lock | Local command output |

These are real measurements but are not substitutes for Azure/Cvent acceptance.
No local acceptance probe navigated to or mutated Cvent.

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
