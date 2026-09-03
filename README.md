# cvent-one-shot

One user, one mock RR workbook, one Pi session, one persistent **open-source Steel Browser**, and one authorized unpublished test event: **`(C+D) Medtrade Clone 2`**.

```bash
cd /Users/bp/cvent-one-shot
python3 -m uvicorn app:app --host 127.0.0.1 --port 8877
```

Open <http://127.0.0.1:8877>. The Emerald-style workspace includes drag-and-drop intake, workflow/status cards, an embedded Steel browser, and an in-UI Excel viewer with worksheet selection and row paging. Upload the RR and click **START BUILD**. This starts the one local Steel browser and Pi job. **STOP BUILD** immediately stops Pi and Steel while preserving the local Steel login profile and keeping the control UI online. The uploaded RR supplies mock requirements only—it never selects the target. Pi searches read-only for the exact literal event name `(C+D) Medtrade Clone 2`, creates a run-local event-key lock, and blocks every write outside that locked clone.

Pi remains the only reasoning agent. Its browser hierarchy is: **Ego direct** → **Browser Use direct** → tightly bounded **Browser Use autonomous fallback**. Every call receives `data/current/browser-runtime.json`, passes through one cross-process BrowserActionGate, and proves the same marker/target ID is visible through Ego, Browser Use, and Steel before work proceeds.

Ego direct uses the MIT-licensed CDP build from `fango19961106-dotcom/ego-browser-linux` pinned in `vendor/ego-browser-linux/` (upstream commit recorded in `UPSTREAM.json`) so it can attach to Steel rather than creating Ego's separate Chromium. Browser Use OSS 0.9.5 attaches to that exact same explicit CDP endpoint. The autonomous fallback defaults to FAST mode (`claude-haiku-4-5`, flash prompts, low-detail automatic vision, up to 8 actions per model step).

Steel OSS runs locally in Docker only:

- API/UI: `127.0.0.1:3005`
- localhost-only CDP: `127.0.0.1:9334`
- persistent browser profile: `data/steel-profile-local/`
- 2 GB shared memory with Chrome's slower `/tmp` shared-memory fallback disabled
- no Steel Cloud API or API key

Both direct toolsets and Browser Use fallback connect to that local Steel CDP. The embedded Steel viewer is display-only by default: a hard overlay captures pointer, wheel, touch, and click input while the iframe has pointer events and keyboard focus disabled. Only **TAKE CONTROL** pauses Pi at the action gate before enabling input. **RETURN TO AGENT** shields the iframe first, performs fresh Ego and Browser Use identity/state reads, verifies the event lock, and only then resumes Pi. Raw new-tab viewer access is hidden unless USER owns the gate.

If the UI shows **LOGIN REQUIRED**, click **OPEN BROWSER**, choose Cvent Microsoft Single Sign-On, complete MFA, and accept **Stay signed in** manually. Cvent and Microsoft authentication cookies/local storage are retained in `data/steel-profile-local/` across container restarts. Passwords are never automated or copied. Then click **CONTINUE**. Never publish the event.
