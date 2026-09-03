# Production Azure V1

## Scope and design

V1 is deliberately one Azure VM, not AKS. One FastAPI control plane owns a
SQLite/WAL lease database on an attached Premium SSD and schedules at most three
job workers. Each active job has a separate:

- Entra-bound workspace and job directory;
- RR, derived files, state, evidence, logs, report, and Pi session/config;
- Pi process explicitly pinned to `anthropic/claude-sonnet-4-6`;
- Steel container, API port, CDP port, Chromium profile, cache, BrowserRuntime,
  authorized target, BrowserActionGate, scope-write audit, and authenticated
  viewer route.

Static slots use loopback-only Steel API/CDP pairs `3005/9334`, `3006/9335`, and
`3007/9336`. Only Caddy HTTPS on port 443 is public. The app binds to loopback.
SSH has no Internet NSG rule and is available through Azure Bastion.

SQLite is the correct V1 lease authority because all workers are on one host.
`BEGIN IMMEDIATE` atomically acquires both a free slot and an event row keyed by
canonical server-configured Cvent event ID. A heartbeat and expiration survive
worker failure. Every browser write rechecks the live unexpired database lease,
job token, runtime event ID, authorized-target event key, live page event key,
and confirmed Forge Intake scope IDs. A controller restart or expired active
lease marks the job `failed_uncertain`; it is never replayed automatically.

## Microsoft Entra authorization

Terraform creates one single-tenant application with assignment required and two
app roles:

- `Cvent.Agent.User`: own workspace/jobs only;
- `Cvent.Agent.Admin`: all-job and active-lease overview.

MSAL authorization-code flow runs server-side. The signed, HttpOnly, Secure,
SameSite=Lax cookie stores only identity/role claims and a CSRF token—not Entra
access or refresh tokens. Every mutating API requires the CSRF header. Every job,
file, viewer, browser ownership, and workbook route checks ownership server-side;
a non-admin receives 404 for another user's job ID.

Local development auth exists only when `CVENT_ENV=development` and an operator
explicitly sets `CVENT_DEV_AUTH_SUBJECT`. It cannot activate in production.

## Secrets

The VM uses a user-assigned managed identity with Key Vault Secrets User. The
systemd process starts through `run_with_keyvault.py`, which reads these names
into process memory/environment without printing or writing their values:

- `anthropic-api-key` -> `ANTHROPIC_API_KEY`
- `entra-client-secret` -> `ENTRA_CLIENT_SECRET`
- `cvent-session-secret` -> `CVENT_SESSION_SECRET`

Terraform generates and stores the latter two. Set the Anthropic key outside
Terraform so it never enters Terraform state, source, command arguments, or chat:

```bash
read -s ANTHROPIC_API_KEY
az keyvault secret set \
  --vault-name "$(terraform output -raw key_vault_name)" \
  --name anthropic-api-key \
  --value "$ANTHROPIC_API_KEY" >/dev/null
unset ANTHROPIC_API_KEY
```

The value is still supplied to Azure CLI over its process boundary. Run this
only from a trusted admin shell with history disabled if required by policy.
Never copy local Cvent profile/cookies to Azure; each job profile must complete
fresh Microsoft SSO/MFA.

### Pi capability boundary

Production Pi starts with `--no-builtin-tools`; neither `read` nor `bash` is
available. An explicitly loaded project extension exposes only fixed `cvent_*`
capabilities for verified RR preparation, approved job artifacts, structured
state/report updates, and validated Ego operations through `browser_tool.py`.
The extension blocks every unregistered tool call and accepts no executable or
arbitrary path from the model. Helper subprocesses receive an allowlisted
environment; the RR helpers receive no lease token and no helper receives the
Anthropic, Entra, or session secret. Pi itself receives `ANTHROPIC_API_KEY` only
because the Anthropic provider requires it, but the model has no environment,
shell, process, or generic file-read capability with which to retrieve it.

The browser capability forces the server-authorized event name for discovery
and authorization, strips snapshot path parameters, exposes neither arbitrary
JavaScript nor raw CDP, and still delegates all writes to the existing
runtime/event-lease/scope checks. Complete DOM
captures larger than one tool result are captured once and transported through
job-scoped opaque chunks; the agent must consume every chunk before acting. If
the browser reaches Cvent SSO/MFA, `cvent_login_handoff` transfers the existing
viewer to the user and blocks the Pi tool turn until control is returned, so the
worker, profile, process, and lease remain alive without automated credential
access or URL probing.

## Prerequisites and RBAC

The deployment identity currently needs all of the following:

1. Resource-group `Contributor` on `rg-cvent-agent-pilot`.
2. `User Access Administrator` or `Owner` on that RG to create managed-identity
   and Key Vault role assignments.
3. Microsoft Entra `Application Administrator` (or equivalent delegated Graph
   permissions) to create the app/service principal, credentials, app roles, and
   assignments.
4. Storage Blob Data Contributor for the Terraform state account/container.

The current authenticated Azure identity failed even RG read with
`AuthorizationFailed`; provisioning cannot proceed until RBAC is granted.

## Deploy

Use Terraform >= 1.8 and Azure CLI. Do not put secrets in `.tfvars`.

```bash
cd infra/terraform
export SUBSCRIPTION_ID='<subscription-id>'
./bootstrap-state.sh
# Run the printed terraform init command.
cp terraform.tfvars.example terraform.tfvars
# Fill non-secret IDs, FQDN label, alert email, SSH public key, full tested commit.
terraform fmt -recursive
terraform validate
terraform plan -out production-v1.tfplan
terraform apply production-v1.tfplan
```

Then set `anthropic-api-key`, wait for systemd's restart, and inspect:

```bash
az network bastion ssh --name cvent-agent-pilot-bastion \
  --resource-group rg-cvent-agent-pilot \
  --target-resource-id "$(az vm show -g rg-cvent-agent-pilot -n cvent-agent-pilot-vm --query id -o tsv)" \
  --auth-type ssh-key --username azureadmin --ssh-key ~/.ssh/id_ed25519

sudo systemctl status cvent-agent caddy docker
sudo journalctl -u cvent-agent -n 200 --no-pager
curl -fsS http://127.0.0.1:8877/healthz
```

## Recovery and operations

- **Pi/Anthropic transient failure:** Pi performs at most three agent-level
  retries (2/4/8-second base backoff), no hidden provider retries, and refuses a
  server delay above 60 seconds. The application does not replay a browser job.
- **Worker/Steel failure:** lease heartbeat expires, job becomes
  `failed_uncertain`, named container is removed on controller restart, and the
  next job starts with a fresh preflight/readback.
- **Application restart:** active jobs fail closed as uncertain; queued jobs are
  retained and may schedule after restart.
- **VM restart:** SQLite, profiles, and artifacts persist on the managed data
  disk. Azure Backup protects OS and data disks daily for 14 days.
- **Capacity:** a fourth different-event job queues. Jobs for the same canonical
  event serialize even when slots are free.
- **Human control:** explicit takeover pauses that job's process group only after
  acquiring its gate; return shields first and requires fresh Ego/runtime/event
  verification before resume.

Never resume `failed_uncertain` automatically. An administrator must review the
scope-write audit and live Cvent state before choosing a new idempotent job.

## Monitoring

Azure Monitor Agent sends warning-and-higher syslog to Log Analytics. An Azure
Monitor availability alert emails the configured operations address. A systemd
timer checks `/healthz` each minute; failures appear in the journal. Primary
operational checks are:

- `systemctl is-active cvent-agent caddy docker`
- `journalctl -u cvent-agent`
- `/healthz`
- admin-only `/api/admin/jobs` and `/api/admin/leases`
- disk usage under `/var/lib/cvent-agent`
- named containers `cvent-agent-steel-1..3`

## Scale-out trigger

Do not adopt AKS, Service Bus, PostgreSQL, or distributed leases for the pilot.
Revisit only when measurements show the single D8as_v5 VM cannot safely support
three workers, VM recovery objectives are insufficient, or active demand
requires more than three isolated browsers. At that point, replace SQLite leases
with a transactional shared database and move immutable artifacts to Blob before
adding hosts.
