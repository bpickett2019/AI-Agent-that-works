# cvent-one-shot

One user, one mock RR workbook, one Pi session, one persistent **open-source Steel Browser**, and one authorized unpublished test event: **`(C+D) Medtrade Clone 2`**.

```bash
cd /Users/bp/cvent-one-shot
python3 -m uvicorn app:app --host 127.0.0.1 --port 8877
```

Open <http://127.0.0.1:8877>. The Emerald-style workspace includes drag-and-drop intake, workflow/status cards, an embedded Steel browser, and an in-UI Excel viewer with worksheet selection and row paging. Upload the RR and click **START BUILD**. This starts the one local Steel browser and Pi job. **STOP BUILD** immediately stops Pi and Steel while preserving the local Steel login profile and keeping the control UI online. The uploaded RR supplies mock requirements only—it never selects the target. Pi searches read-only for the exact literal event name `(C+D) Medtrade Clone 2`, creates a run-local event-key lock, and blocks every write outside that locked clone.

Browser Use defaults to **FAST mode** (`claude-haiku-4-5`, flash prompts, low-detail automatic vision, up to 8 actions per model step). Set `BROWSER_USE_FAST=0` and optionally `BROWSER_USE_MODEL=claude-sonnet-4-5` before starting the UI for slower balanced mode. Target/event-key enforcement remains deterministic and independent of the model.

Steel OSS runs locally in Docker only:

- API/UI: `127.0.0.1:3005`
- localhost-only CDP: `127.0.0.1:9334`
- persistent browser profile: `data/steel-profile-local/`
- 2 GB shared memory with Chrome's slower `/tmp` shared-memory fallback disabled
- no Steel Cloud API or API key

Browser Use connects to that local Steel CDP. The localhost app embeds the interactive Steel viewer directly below Status for login, MFA, and watching the agent. **OPEN BROWSER** refreshes and scrolls to the embedded viewer; **OPEN IN NEW TAB** is also available.

If the UI shows **LOGIN REQUIRED**, click **OPEN BROWSER**, choose Cvent Microsoft Single Sign-On, complete MFA, and accept **Stay signed in** manually. Cvent and Microsoft authentication cookies/local storage are retained in `data/steel-profile-local/` across container restarts. Passwords are never automated or copied. Then click **CONTINUE**. Never publish the event.
