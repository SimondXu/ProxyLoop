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

## Update to origin/main

Merged (not rebased) `origin/main` @ `c914c1b` (#70, #71, #72, #73) into
the branch. No textual conflicts, and main touched none of this branch's
files. #72 leaves `_browser_case` unchanged, so the projection stays an
explicit allow-list: it carries no `model_traces` and no claim data, and
the one addition is still `bill_snapshot.usage.data_megabytes`
(`NonNegativeInt` in contracts).

Rerun on the merged tree (no `PROXYLOOP_TEST_*` set):

- `make format-check lint typecheck`: pass.
- `make web-check`: pass (2 files, 114 vitest tests, build).
- `make preflight-fast`: pass.
- `make test`: pass (1184 passed, 46 skipped; 390 passed, 1 skipped;
  V2 ceiling report current).
- `git status --short data/`: empty.
- Still not run: `make preflight`, real-dependency gates
  (`postgres-check`, `phase05a-check`, `phase06b1-check`), Browser/manual
  smoke.

## Review round 1 (Request Changes): root decisions applied

All in `apps/web/app/components/conversation-workspace.tsx` and its test
file unless noted. Red was observed before each change.

| Item | Change | Red → green |
|---|---|---|
| I-2 / E-10 | `parseUsdMoney`: step 1 counts loose candidates `\$\s*[\d.,]+` or `[\d.,]+\s*USD`, rejecting unless exactly one; step 2 validates that one strictly (`^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?$`) after removing one trailing period or a trailing comma before whitespace/end | 8 new cases red (accept `$92, thanks`, `$1,500, please`, `92 USD, thanks`; reject `$1,50 or $70`, `$92, $93`, `$12,34 then $5`, `92,5 USD and $4`, `$92.5 and $1,5`) → green |
| M-2 / E-10 | Only a bare `$` or `USD` counts as USD. Rejected: a letter directly before the candidate (`A$`, `C$`, `HK$`, `NZ$`, `R$`, and also `US$`, by decision), an uppercase non-USD 3-letter code after a `$` amount (`$92 AUD`, `$92 MXN`), a dash next to the candidate (`$92–95`, `$5-`), or a letter glued to it | 9 new cases red → green; `$92-95` was already rejected by the negative-number rule and is kept as a pin. Prompt copy unchanged (it states no grammar); `docs/ui/state-matrix.md` intake row updated |
| I-3 | The event and approval POST failure paths fall back to `confirm`/`approval` only when `phaseForPayload(payloadRef.current)` is that phase | New vitest "I-3: a failed event POST keeps the approval a poll already read…": red (approval card gone after the network reject) → green. The approval path has the same guard but no dedicated test |
| M-1 | A poll read that `acceptPayload` rejects for the same Case (so the only possible cause is a lower revision) is dropped without `setError`. `stalePollTick` re-arms both poll effects so that polling still does not stop silently; it stays bounded by the 5-read budget | New vitest "M-1: a stale (lower-revision) poll read is dropped silently and polling continues": red (alert shown) → green |
| M-4 / E-8 | Finalizing title: "Finalizing the approved fictional transition" only when `payload.approval.decision === "approved"`, else "Finalizing the fictional transition"; the working title "Comparing fictional Provider options" (no payload backs it) becomes "Waiting for the Runtime decision" | The two E-8 tests, updated, were red → green. New M-4 approved-title test passes on both sides (pin). 13 existing assertions whose fixtures carry no approved approval now use the neutral titles |
| M-5 | `tests/integration/test_browser_projection_allowlist.py` `EXCLUDED_KEYS` gains `model_traces`, `execution_claim`, `trace_id`, `claimed_at` | Guard only: the allow-list already kept them out, so it cannot be red first |
| M-3 | No code change | n/a |
| spec | "No runtime-package change" now names the `runtime/services/api` `app.py` projection change | n/a |
| I-1 | **Not applied, escalated.** "Skip the poll timer while in flight" (prototyped) turns the I-1 regression test green but reds 4 tests: #63's `B1` and `sticky I1`, the E-7 test, and the item-4 I-3 test. All four need a poll during the in-flight event POST. Keeping the polls but not charging the budget passes everything except the I-1 assertion "`getCase` called 0 times" (7 reads in 10.5 s) | root decided Option B; applied below |

Limits (M-3): no local upper bound on amounts; the server `Money` has none
either.

Checks on this tree (no `PROXYLOOP_TEST_*` set):

- `make web-check`: pass (2 files, 136 vitest tests, build).
- `uv run --project runtime --all-packages pytest -q tests/integration/test_browser_projection_allowlist.py`: 1 passed.
- `make format-check lint typecheck`: pass.
- `make preflight-fast`: pass.
- `make test`: pass (1174 passed, 46 skipped; 390 passed, 1 skipped;
  V2 ceiling report current). The first suite collected 1230 at the merge
  run and 1220 now. A clean detached worktree at `49a10a3` also collects
  1220 with an identical per-file count, so this diff did not change it.
  Correction (re-review): the extra 10 are #75
  (`test_r10_terminal_delivery_callback.py`, 9 parametrised cases, plus 1
  in `test_phase_06b1_channel_runtime.py`), which was present on the tree
  where the merge-time run happened. No test file was lost. After merging
  #75 (below) the suite collects 1230 again, and those two files add 9
  and 1.
- `git status --short data/`: empty.
- Not run: `make preflight`, real-dependency gates, Browser/manual smoke.

## Review round 1, item I-1: root decision Option B

- `countPollRead()` (`conversation-workspace.tsx`, used by the deadline and
  the working/finalizing poll timers): a read made while
  `commandInFlightRef.current === sessionId.current` does not count against
  the 5-read budget. Polling continues during the command, so #63 `B1` /
  `sticky I1`, E-7 and I-3 keep their poll-during-POST behaviour.
- `clearPollBudgetError()`, called from `readAuthoritativeCase` for every
  successful non-poll (command, restore or reconnect) read: when the budget
  error was reported, restart the budget and clear the error only if it is
  still `POLL_BUDGET_MESSAGE`.
- A direct confirm/approve cannot start with the budget error showing: both
  already `clearFailure()` at start, and no command button is enabled while
  it shows. The reachable case is a Reconnect whose readiness check stalls
  while restoring-phase polls exhaust the budget.
- `docs/ui/state-matrix.md` finalizing row documents the accounting.

| Test | Before | After |
|---|---|---|
| "I-1: polls during a long in-flight event POST continue without exhausting the poll budget" | red (reads stop at 5, "Still waiting" shown) | green |
| "I-1: a budget error from a stalled reconnect is cleared once its authoritative reads and replay succeed" | red (error left after the approval card appears) | green |
| "M-1: stale poll reads re-arm polling but still stop at the 5-read budget" | green (guard: the `stalePollTick` re-arm cannot bypass the budget; stale reads outside a command count) | green |

Checks on this tree (no `PROXYLOOP_TEST_*` set):

- `make web-check`: pass (2 files, 139 vitest tests, build).
- allow-list pytest: 1 passed.
- `make format-check lint typecheck`: pass.
- `make preflight-fast`: pass.
- `make test`: pass (1174 passed, 46 skipped; 390 passed, 1 skipped;
  V2 ceiling report current).
- `git status --short data/`: empty.
- Not run: `make preflight`, real-dependency gates, Browser/manual smoke.

Known limit: reads made during a command are unbounded for as long as the
POST stays pending (one per 1500 ms); the budget cannot bound them.

## Re-review @ db154b2 (Request Changes: N-1) and update to origin/main

- Merged `origin/main` @ `14d3fcf` (#74, #75): no conflicts; main touched
  none of this branch's files.
- N-1: while an approval POST is in flight, the deadline effect detected
  its first read with `pollCount.current === 0`. Under option B the count
  stays 0, so the delay stayed `max(0, expiresAt - now) = 0` and GETs fired
  back to back. Fix: `deadlineReadStartedRef` holds
  `approval_id|expires_at` once the first deadline read fires, and the
  delay is 1500 ms for that same key, otherwise the time to expiry. A new
  approval or deadline starts over, and `restart()` clears the ref.
  Vitest "N-1: deadline reads during an in-flight approval POST stay
  1500 ms apart" (expires_at = now + 5 s, `decideApproval` held pending,
  Approve, +5001 ms, 30 zero-duration flushes, then +1499/+1): red, getCase
  2 → 32 (matches the reviewer repro) → green (no read on zero-duration
  flushes; next read exactly at +1500 ms).
- M-a: `docs/ui/state-matrix.md` states that only an uppercase ISO code
  after the amount marks it non-USD (`$92 aud` is read as USD; the Draft
  Task Brief echoes the amount). No code change.

Checks on this tree (no `PROXYLOOP_TEST_*` set):

- `make web-check`: pass (2 files, 140 vitest tests, build).
- allow-list pytest: 1 passed.
- `make format-check lint typecheck`: pass.
- `make preflight-fast`: pass.
- `make test`: pass (1183 passed, 47 skipped; 397 passed, 1 skipped;
  V2 ceiling report current).
- `git status --short data/`: empty.
- Not run: `make preflight`, real-dependency gates, Browser/manual smoke.

## Final integration: update to origin/main @ 8e1522a (#76)

Merged `origin/main` @ `8e1522a` (#76): no conflicts. With the shared
test DB held exclusively, the variables were set on the make command line
only, and the gates ran one at a time:

- `make test`: pass (1199 passed, 47 skipped; 397 passed, 1 skipped;
  V2 ceiling report current).
- `make postgres-check PROXYLOOP_TEST_DATABASE_URL=…/proxyloop_test`: 27 passed.
- `make phase05a-check` (+ `PROXYLOOP_TEST_TEMPORAL_ADDRESS=localhost:7233`): 37 passed.
- `make phase06b1-check` (same variables): 35 passed.
- `make preflight`: pass (1199 passed, 47 skipped; 397 passed, 1 skipped;
  140 vitest tests; V2 ceiling report current).
- `git status --short data/`: empty.
- Not run: Browser/manual smoke.
