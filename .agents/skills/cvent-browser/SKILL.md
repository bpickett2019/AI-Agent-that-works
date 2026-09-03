---
name: cvent-browser
version: 1.1.0
description: Operate only the locked (C+D) Medtrade Clone 2 mock event in one persistent Cvent Chrome through Browser Use.
---

# Cvent Browser Operator

Run from `/Users/bp/cvent-one-shot`.

## 1. Find the one authorized mock event (read-only)

The uploaded RR is mock requirements data and never authorizes its real event. Search only for the exact literal event name `(C+D) Medtrade Clone 2`:

```bash
./browser_use_operator.py --discover --identity "(C+D) Medtrade Clone 2" \
  --mission "Find the one exact-name authorized mock event. Ignore RR identity. Read only." --max-steps 25
```

Discovery may search/filter the Cvent event list and open only the exact-name clone for identity verification. It cannot save/edit/create anything. Require exactly one exact-name match and a non-empty `discovered_target_url`. The operator writes `data/current/authorized-target.json`; all later operations are hard-blocked unless their event key matches this lock. Save that URL and the exact clone name in `state.json`. Zero, multiple, fuzzy, or uncertain matches means REVIEW REQUIRED and zero writes.

## 2. Operate only the locked clone target

```bash
./browser_use_operator.py --target "$DISCOVERED_TARGET_URL" \
  --mission "$BOUNDED_MISSION" --max-steps 35
```

- Preserve the clone's exact name, event code/ID, URL identity, and unpublished status. Never open or mutate the real event named in the RR.
- Browser Use always attaches to the one self-hosted Steel OSS browser at localhost CDP `127.0.0.1:9334`. Its Chrome profile persists at `data/steel-profile-local/`.
- You decide **what** from the RR; Browser Use determines **how** from the live UI.
- Keep invoking it section-by-section until done. It may restart, but never close/replace Chrome.
- Read `CVENT_BROWSER_RESULT=...`. Do not claim a write unless Browser Use re-read it.
- If the result says `LOGIN_REQUIRED` or `MFA REQUIRED`, update state to `login_required`, log `MFA REQUIRED`, and end the Pi turn. CONTINUE resumes this Pi session.
- On operator failure, keep Chrome alive, re-read RR/state and actual Cvent, then retry narrowly.
- Never create another Steel session yourself, release the active session, or use Playwright, ego-browser, raw CDP, curl, Cvent APIs, or another browser to operate Cvent. `steel_session.py` owns the one local Steel container/browser. Python/openpyxl is only for the workbook.
