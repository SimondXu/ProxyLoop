# Fix log: a chained non-retryable expiry failure is abandoned, not retried (R-16)

Spec: `harness/context/fix-r16-expiry-classifier-preflight.md`.
Branch `fix/r16-expiry-classifier` from `main` @ `d23aff9`.

## What changed

- `runtime/services/workflow_worker/src/proxyloop_workflow_worker/workflow.py`
  (the only source file): `_outermost_failure_category` (the activity's own
  typed `ApplicationError`, i.e. `ActivityError.cause`, or the
  Workflow-raised `ApplicationError`; non-retryable when flagged or its type
  is in `NON_RETRYABLE_ERROR_TYPES`), used by `_expire_pending` when
  `workflow.patched("expiry-failure-outermost-cause")`; otherwise the
  unchanged innermost `_expiry_failure_category`. `apply_case_command` (R-1)
  unchanged.
- `tests/integration/test_phase_05a_temporal_workflow.py`:
  `_ExpiryFaultingAdapter(cause=...)` raises its fault `from` the cause; the
  two time-skipping expiry tests are parametrized `unchained` / `chained`
  (`CaseConflictError`, `StorageUnavailableError`); new
  `test_replay_pre_r16_history_keeps_the_expiry_patch_gate`; the R-1 replay
  test shares a new `_replay` helper with unchanged assertions.
- `tests/fixtures/temporal_history.case-workflow-expiry-chained-conflict.pre-r16.json`:
  recorded on `main` @ `d23aff9` (process-local time-skipping server,
  `InMemoryCaseRepository`, production activity adapter; no shared DB or
  Compose Temporal). The recording reproduced the defect: the worker logged
  `approval expiry attempt 1 failed: CaseConflictError` for a failure whose
  outer category is `case_conflict`, `nonRetryable: true`,
  `RETRY_STATE_NON_RETRYABLE_FAILURE`, and started a 15 s retry timer
  (event 35). Stack traces blanked, identities `proxyloop-phase05a-recorder`;
  a scan of the plain text and decoded payloads found no local path or host
  name.

## Red → green

| Test | Red (`main`'s `workflow.py`) | Green |
|---|---|---|
| `test_replay_pre_r16_history_keeps_the_expiry_patch_gate` | FAIL: DID NOT RAISE `NondeterminismError` | pass: replays; with only this patch forced, `NondeterminismError` "No command scheduled for event HistoryEvent(id: 35, TimerStarted)" |
| `test_time_skipping_non_retryable_expiry_failure_does_not_spin[chained]` | not run (needs the Compose test DB) | not run |
| `test_time_skipping_expiry_retry_exhaustion_keeps_workflow_alive[chained]` | not run (needs the Compose test DB) | not run |

## Checks

Without the DB (no `PROXYLOOP_TEST_*` set):

- Passed: `make format-check lint typecheck` (exit 0, after a ruff import-order
  fix and a format fix in the test file).
- Passed: `make preflight-fast` (exit 0).
- Passed: `make test` (runtime 1204 passed, 53 skipped; ml 397 passed,
  1 skipped). The four new parametrized DB cases are among the skips.

Not run yet (need the Compose PostgreSQL test DB and Temporal, one at a time):
the red run of the two `[chained]` time-skipping tests on `main`'s
`workflow.py`, then `make phase05a-check`, `make phase06b1-check`,
`make postgres-check`, and the final `make preflight`.
