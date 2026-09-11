# Live model-turn audit — September 10, 2026

Job: `job_e405c8574bcf4f5fb210c8c594b94cba`

This is a response-by-response audit of all 51 recorded Anthropic responses. A
"browser op" is a completed `browser_operation` telemetry event. An Ego
`actions` call is one browser operation even when it contains multiple actions.

Flags:

- `Z`: qualifies as `MODEL_RESPONSE_WITH_ZERO_PROGRESS` under the new rule.
- `R`: reread information already available in live context.
- `W`: existed because of wrapper/schema/locator syntax friction or its recovery fallout.
- `U`: unnecessary in the action-heavy ideal flow.

| # | Classification | Browser ops / contained actions | Flags | What the response did |
|---:|---|---:|---|---|
| 1 | PLAN | 0 | — | Set running state and prepared the RR. Required initial setup. |
| 2 | PLAN | 0 | — | Read summary through both plan and expectations tools. One source would have sufficed, but this established initial mission context. |
| 3 | PLAN | 0 | — | Read mission. |
| 4 | PLAN | 0 | — | Read Event Settings plan before login. |
| 5 | OBSERVE | 1 / 1 | — | Checked authentication. |
| 6 | AUTH_HANDOFF | 4 / 4 | — | Page checks/navigation/auth checks and required human SSO handoff. |
| 7 | OBSERVE | 1 / 1 | — | Scanned event inventory. |
| 8 | NAVIGATION_DECISION | 1 / 1 | — | Opened the exact authorized event. |
| 9 | VERIFICATION | 1 / 1 | — | Bound and authorized exact event identity/lifecycle. |
| 10 | OBSERVE | 0 | ZRU | Reread fresh-job state to prove no prior work, although that was already known. |
| 11 | PLAN | 0 | ZRU | Reread Event Settings plan/expectations already obtained in turn 4. |
| 12 | PLAN | 0 | ZU | Spent a model response only updating stage text. |
| 13 | ACTION_GENERATION | 0 | ZWU | Generated a two-action read round without required `commitMode`; wrapper rejected it. |
| 14 | NAVIGATION_DECISION | 1 / 2 | — | Corrected syntax; one coherent navigate + snapshot round. |
| 15 | NAVIGATION_DECISION | 1 / 2 | — | One coherent navigate + snapshot round to classic event Home. |
| 16 | NAVIGATION_DECISION | 1 / 2 | — | One coherent click Details + snapshot round. |
| 17 | OBSERVE | 1 / 1 | — | Screenshot because semantic result was sparse. |
| 18 | PLAN | 0 | ZRU | Reread Event Settings requirements already in context. |
| 19 | ACTION_GENERATION | 0 | ZWU | Tried write-declared Edit + screenshot without a Save/readback group; wrapper rejected it. |
| 20 | OBSERVE | 1 / 1 | RU | Took another broad screenshot of substantially the same view. |
| 21 | ACTION_GENERATION | 0 | ZWU | Repeated the same incomplete write round; rejected again. |
| 22 | ACTION_GENERATION | 0 | ZWU | Repeated incomplete Edit/wait/screenshot round; rejected again. |
| 23 | ACTION_GENERATION | 1 / 1 | — | Opened Edit with one primitive click. This visibly advanced UI state but should have been paired with the subsequent observation in one read round. |
| 24 | OBSERVE | 1 / 1 | — | Screenshot of newly opened editor. |
| 25 | OBSERVE | 1 / 1 | — | Full semantic editor snapshot. Legitimate material-state observation. |
| 26 | OBSERVE | 0 | — | Consumed required second snapshot transport chunk and extracted live controls. |
| 27 | PLAN | 0 | ZRU | Repeated job update and RR preparation despite already validated RR. |
| 28 | ACTION_GENERATION | 0 | ZWU | Invented unsupported `triple_click_fill`; schema rejected entire round. |
| 29 | ERROR_CORRECTION | 0 | ZWU | Expanded one fill into click/selectText/type and omitted RR evidence on writes. |
| 30 | ERROR_CORRECTION | 0 | ZWU | Added evidence but incorrectly declared `selectText` as a write. |
| 31 | ERROR_CORRECTION | 0 | ZW | Finally used fill, but stale/non-native role locator resolution failed before a completed browser operation. This response alone took about 74 seconds. |
| 32 | RECOVERY | 1 / 1 | WU | Scrolled the wrong page surface trying to recover locator failure. |
| 33 | OBSERVE | 1 / 1 | WU | Screenshot of the resulting blank viewport. |
| 34 | OBSERVE | 1 / 1 | RWU | Requested a 198 KB all-control inventory instead of using recent semantic state. |
| 35 | OBSERVE | 0 | ZRWU | Consumed mostly irrelevant inventory chunk 1. |
| 36 | OBSERVE | 0 | ZRWU | Consumed mostly irrelevant inventory chunk 2. |
| 37 | OBSERVE | 0 | ZRWU | Consumed mostly irrelevant inventory chunk 3. |
| 38 | OBSERVE | 0 | RWU | Consumed chunk 4 and finally found useful field IDs. |
| 39 | OBSERVE | 0 | RWU | Consumed chunk 5 for remaining selectors. |
| 40 | ACTION_GENERATION | 0 | ZWU | Generated a substantial round, but a conservative earlier uncertainty marker blocked dispatch. |
| 41 | RECOVERY | 1 / 1 | W | Recovered renderer responsiveness; incorrectly treated this as mutation resolution. |
| 42 | RECOVERY | 0 | WU | Attempted navigation while pending write readback correctly blocked leaving the page. |
| 43 | RECOVERY | 1 / 1 | W | Screenshot for uncertainty recovery. |
| 44 | VERIFICATION | 1 / 1 | W | Targeted timezone readback showed original value. |
| 45 | VERIFICATION | 1 / 1 | W | Targeted start-date readback showed original value. |
| 46 | ACTION_GENERATION | 0 | ZW | Generated substantial round but omitted exact RR evidence on keyboard steps and used incorrect B12/B13 sources; rejected. |
| 47 | ERROR_CORRECTION | 0 | ZWU | Misdiagnosed provenance rejection as missing initial setup and only updated job state. |
| 48 | ERROR_CORRECTION | 0 | ZRWU | Repeated RR preparation. |
| 49 | ERROR_CORRECTION | 0 | ZRWU | Reread summary. |
| 50 | ERROR_CORRECTION | 0 | ZRWU | Reread Event Settings plan. |
| 51 | PLAN | 0 | ZU | Restated already-known Event Settings mission; provider then stopped for insufficient credit. |

## Totals

### Classification

| Classification | Responses |
|---|---:|
| PLAN | 9 |
| OBSERVE | 15 |
| NAVIGATION_DECISION | 4 |
| ACTION_GENERATION | 8 |
| VERIFICATION | 3 |
| RECOVERY | 4 |
| ERROR_CORRECTION | 7 |
| AUTH_HANDOFF | 1 |
| OTHER | 0 |
| **Total** | **51** |

### Productivity findings

- Responses causing at least one completed browser operation: **20**.
- Responses causing zero completed browser operations: **31**.
- Responses that visibly changed page/control state rather than only observing it: **7**.
- Responses qualifying as `MODEL_RESPONSE_WITH_ZERO_PROGRESS`: **23**.
- Responses that reread information already available: **14**.
- Responses caused by wrapper/tool syntax friction or its recovery chain: **27**.
- Responses unnecessary in the action-heavy ideal flow: **29**.
- Completed coherent rounds: **3**, all read-only, with **6 contained actions**.
- Successful saved write rounds: **0**.

The central failure was not browser latency. Pi spent turns rediscovering mission
state, satisfying wrapper syntax incrementally, consuming oversized observations,
and recovering from those failures. Once a trustworthy editor snapshot existed
at turn 25, the expected next response was one valid multi-field Save/readback
round. Instead turns 27–51 contained 18 zero-browser responses, one oversized
inventory operation, and recovery reads, with no saved write.
