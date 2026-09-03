# CVENT Agent

One user, one mock RR workbook, one CVENT Agent session, one persistent **open-source Steel Browser**, and one authorized unpublished test event: **`(C+D) Medtrade Testing Clone 2`**.

```bash
cd /Users/bp/cvent-one-shot
python3 -m uvicorn app:app --host 127.0.0.1 --port 8877
```

Open <http://127.0.0.1:8877>. The Emerald-style workspace includes drag-and-drop intake, workflow/status cards, an embedded Steel browser, and an in-UI Excel viewer with worksheet selection and row paging. Upload the RR and click **START BUILD**. This starts the one local Steel browser and CVENT Agent job. **STOP BUILD** immediately stops CVENT Agent and Steel while preserving the local Steel login profile and keeping the control UI online. The uploaded RR supplies mock requirements only—it never selects the target. CVENT Agent uses Ego to physically scroll normal event-list views for the exact literal name `(C+D) Medtrade Testing Clone 2` without defaulting to Advanced Search, creates a run-local event-key lock only after one exact match, and blocks every write outside that locked clone.

CVENT Agent interprets the RR and uses **Ego inside the canonical Steel Chromium** for event discovery, domain building, and verification. Ego observes and scrolls unfamiliar pages before interacting, then uses semantic controls or bounded DOM/JS/CDP escape hatches and fresh readback. Every call receives `data/current/browser-runtime.json`, passes through one cross-process BrowserActionGate, and proves the same marker, target ID, and locked event key before writes proceed.

Ego direct uses the MIT-licensed CDP build from `fango19961106-dotcom/ego-browser-linux` pinned in `vendor/ego-browser-linux/` (upstream commit recorded in `UPSTREAM.json`) so it can attach to Steel rather than creating Ego's separate Chromium.

Steel OSS runs locally in Docker only:

- API/UI: `127.0.0.1:3005`
- localhost-only CDP: `127.0.0.1:9334`
- persistent browser profile: `data/steel-profile-local/`
- 2 GB shared memory with Chrome's slower `/tmp` shared-memory fallback disabled
- no Steel Cloud API or API key

Ego connects directly to that local Steel CDP and operates the same page displayed by the embedded viewer. The embedded Steel viewer is display-only by default: a hard overlay captures pointer, wheel, touch, and click input while the iframe has pointer events and keyboard focus disabled. Only **TAKE CONTROL** pauses CVENT Agent at the action gate before enabling input. **RETURN TO AGENT** shields the iframe first, performs fresh Ego identity/state reads, verifies the event lock, and only then resumes CVENT Agent. Raw new-tab viewer access is hidden unless USER owns the gate.

If the UI shows **LOGIN REQUIRED**, click **OPEN BROWSER**, choose Cvent Microsoft Single Sign-On, complete MFA, and accept **Stay signed in** manually. Cvent and Microsoft authentication cookies/local storage are retained in `data/steel-profile-local/` across container restarts. Passwords are never automated or copied. Then click **CONTINUE**. Never publish the event.
