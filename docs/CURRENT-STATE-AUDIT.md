# Pre-refactor current-state audit

Audit baseline: branch `main`, commit
`5e286694168e1a33816d567d73d366a38a3eaa06`.

| Concern | Audited baseline |
|---|---|
| Frontend | One static HTML document with inline JavaScript and no application login. |
| Backend | One FastAPI process with process-global Pi, browser, and workbook locks. |
| Workspace | Shared mutable `data/current`; old runs moved to `data/runs`. |
| Process state | One `_proc`, PID, state, log, report, and Pi session directory. |
| Cvent target | One source-hard-coded name and event key. |
| Steel | One `latest` container (`cvent-one-shot-steel`), API `3005`, CDP `9334`. |
| Chromium | One persistent `data/steel-profile-local` profile and cache. |
| BrowserRuntime | One `data/current/browser-runtime.json`, marker, and target tab. |
| Ego | Fresh Node process per operation, but all operations share the one runtime. |
| BrowserActionGate | One host `fcntl` lock and one ownership JSON record. |
| Viewer | One unauthenticated `/steel-viewer`; rewritten to localhost URLs. |
| Files | RR, derived requirements, logs, reports, screenshots/evidence, target lock, and sessions share one current directory. |
| Cvent auth | Cookies/local storage in the one Chromium profile; metadata in `data/auth-settings.json`. |
| App auth | None: no users, roles, ownership, workspaces, or admin boundary. |
| Event concurrency | No canonical event-level mutation lease. |
| Shutdown | Kills one Pi process tree and stops one Steel container; profile persists. |
| Pi model | CLI did not pass provider/model and inherited ambient Pi defaults. |
| Secrets | No tracked secret values found; ignored local auth/profile data existed. |
| Browser Use | Removed; Ego direct was the only active Cvent router. |
| Tests | 23 Python tests plus Node syntax and diff checks passed at baseline. |

The baseline architecture could not safely support multiple users or simultaneous
jobs. In particular, changing only web route state would not isolate browser
ports, profiles, CDP targets, module-level Ego state, or Cvent mutations.
