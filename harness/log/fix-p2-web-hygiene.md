# Fix log: Web P2 hygiene batch (P2 E-7, E-8, E-9/R-3, E-10, R-8)

Spec: `harness/context/fix-p2-web-hygiene-preflight.md`. Branch
`fix/p2-web-hygiene` from `origin/main` @ `5bedcce`.

## What changed

- `apps/web/app/components/conversation-workspace.tsx`
  - E-7: `commandInFlightRef` holds the session id of the event or approval
    `POST` in flight. `readAuthoritativeCase` takes `{ poll }`; both poll
    timers pass `poll: true`. A poll that maps to `confirm` while that
    command is in flight keeps the phase (payload still accepted). The
    blocked checks run first, so #63's sticky blocked is unchanged.
  - E-8: `ProgressArtifact` takes the payload and shows one done step
    "Case revision N read" plus one active step ("Runtime decision" or,
    when finalizing, "Execution pending"). "Guardrails checked" is gone.
  - E-9: the Usage row renders `usage.data_megabytes` as "N MB data",
    else "Unavailable" (no more "Runtime fact" literal).
  - E-10: `parseUsdMoney` grammar rewritten (see spec item 4).
- `runtime/services/api/src/proxyloop_api/app.py` `_browser_case`: E-9
  explicit `bill_snapshot.usage = {"data_megabytes": ...}`.
- `tests/integration/test_browser_projection_allowlist.py`: `BILL_KEYS`
  gains `usage`; new `USAGE_KEYS = {"data_megabytes"}` exact set.
- `docs/ui/state-matrix.md`: intake-row USD grammar, working-row Progress
  and poll rule, and the R-8 projection note (synthetic `not_done`
  `completion` from `_browser_completion` when the Runtime has no
  `CompletionDecision`; the Web never treats it as completion).

## Red → green

| Item | Test | Red on `5bedcce` | Green |
|---|---|---|---|
| E-7 | vitest "E-7: an unchanged poll during the in-flight event POST keeps Working…" | yes (`Working` gone after the 1500 ms poll) | yes; removing the guard line re-fails it |
| E-8 | vitest "E-8: the working Progress…", "E-8: the finalizing Progress…" | yes | yes |
| E-9 | vitest "E-9: the Usage row renders…", "…says Unavailable…"; `test_browser_projection_allowlist.py` | yes (both) | yes |
| E-10 | vitest `it.each` accepts `$92.00.`, `$92.`, `$12345`; rejects `$1,50`, `$1,500,00`, `12.345 USD` | those 6 red; `$1,500`, `92 USD.`, `$92.00.5`, `$.50` already behaved (kept as pins) | yes |
| R-8 | docs only | n/a | n/a |

## Verification

- `make web-check`: pass (lint, typecheck, 114 vitest tests, build).
- `uv run --project runtime --all-packages pytest -q tests/integration/test_browser_projection_allowlist.py tests/integration/test_phase_04a_agent_runtime.py`: 30 passed.
- `make lint`, `make typecheck`, `make format-check`, `make preflight-fast`: pass.
- No `PROXYLOOP_TEST_*` variables set.
- Not run: `make preflight`, `make test`, real-dependency gates
  (`postgres-check`, `phase05a-check`, `phase06b1-check`) although `api`
  changed; Browser/manual smoke.
