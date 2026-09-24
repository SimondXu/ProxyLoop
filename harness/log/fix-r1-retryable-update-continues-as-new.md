# Fix log: a retryable Update failure rolls the run so its identical retry reaches the Runtime (R-1, R-1b)

Spec: `harness/context/fix-r1-retryable-update-continues-as-new-preflight.md`.
Branch `fix/r1-retryable-update-continues-as-new` from `main` @ `14d3fcf`,
merged with `origin/main` @ `8e1522a` (#76, fast-forward) before the gates.

## What changed

- `runtime/services/workflow_worker/src/proxyloop_workflow_worker/workflow.py`
  (the only source file):
  - `_can_continue_as_new()` (requested, no active handler, no activity in
    flight) drives `run()`'s Continue-As-New check and both `wake_changed`
    predicates (R-1b).
  - `apply_case_command`: on `ActivityError` with
    `error.retry_state in (RetryState.MAXIMUM_ATTEMPTS_REACHED,
    RetryState.TIMEOUT)` and
    `workflow.patched("retryable-update-failure-continues-as-new")`, set
    `_continue_requested`; re-raise.
  - Both success paths keep a pending request
    (`self._continue_requested = self._continue_requested or (...)`).
  - `update_id_for_command` docstring states the roll.
  - `_expiry_failure_category` and the expiry failure path are unchanged.
- `tests/integration/test_phase_05a_temporal_workflow.py`: T1–T5 (below),
  `_GatedCommandActivity`, helpers `_run_id`, `_start_queued`,
  `_failure_type`; `_ExhaustingAdapter.blocking` and
  `_FinalWriteOutageRepository(failures=1)` added with unchanged defaults. No
  existing test changed.
- `tests/fixtures/temporal_history.case-workflow-exhaustion-then-success.pre-r1.json`:
  a `CaseWorkflow` history recorded on `main` @ `14d3fcf` against the Compose
  Temporal (create; an append that exhausts five `storage_unavailable`
  attempts; a distinct append that succeeds in the same run). Stack traces
  blanked and identities set to `proxyloop-phase05a-recorder`; no local path
  remains in the plain text or the decoded payloads.

## Escalation and classifier choice

The design's step 2 classified the failure with `_expiry_failure_category`
(innermost typed `ApplicationError`). Implemented as written, `make
phase05a-check` gave 2 failed, 39 passed:
`test_live_temporal_identical_retry_keeps_cached_outcome` (#62 T2; outcomes
`['case_conflict', 'case_conflict']`) and
`test_time_skipping_non_retryable_expiry_failure_does_not_spin`
(`expiry_attempts` 2, expected 1). Cause: `activities.py` raises every
category `from exc`, so through the default failure converter the chain is
`[('ApplicationError','case_conflict',True), ('ApplicationError','CaseConflictError',False)]`
and the innermost classifier returns `('CaseConflictError', False)`: every
real non-retryable failure counted as retryable and rolled the run (the second
test failed because the roll reset `_expiry_abandoned_for`).

Root decision: option B, the server's `retry_state`, with option A (outermost
`error.cause`) as fallback. A probe of A passed `make phase05a-check` (41
passed) and was reverted. B was then implemented; `retry_state` is set in the
live environment (T1–T3 green) and the full 05A gate passes, so A was not
needed.

## Red → green

Red is `main`'s `workflow.py` with the new tests; each live test run alone.

| Test | Red | Green (option B) |
|---|---|---|
| T1 `test_live_temporal_identical_retry_after_exhaustion_reaches_runtime` | FAIL: identical retry raised the cached `temporal_unavailable` (16.1 s) | pass |
| T2 `test_live_temporal_identical_approval_retry_finishes_exhausted_claim` | FAIL: identical approval retry raised `temporal_unavailable` (16.2 s) | pass |
| T3 `test_live_temporal_exhaustion_with_queued_command_rolls_after_it` | FAIL: `'temporal_unavailable' == 'case_conflict'` (queued command succeeded) | pass |
| T4 `test_live_temporal_continue_as_new_waits_for_queued_command` | FAIL: `TMPRL1101 Potential deadlock` ×7, stuck Update timed out after 30 s; one earlier run hung past 180 s (killed, exit 142), apparently in worker shutdown | pass (~1 s) |
| T5 `test_replay_pre_r1_history_keeps_the_patch_gate` | FAIL: DID NOT RAISE | pass: replays; with `workflow.patched` forced True, `NondeterminismError` "Continue as new workflow machine does not handle this event" |

T6 (HTTP 503 then 200 with the same Idempotency-Key) was optional and not
added. Focused T1–T5 with option B: 5 passed in 49.4 s.

## Checks

Final diff (option B, on `8e1522a`):

- Passed: `make format-check lint typecheck` (exit 0).
- Passed: `make preflight-fast` (exit 0).
- Passed: `make test` (runtime 1200 passed, 51 skipped; ml 397 passed,
  1 skipped).
- Passed, one at a time against the Compose test DB and Temporal:
  `make phase05a-check` (42 passed), `make phase06b1-check` (35 passed),
  `make postgres-check` (27 passed).
- Passed: `make preflight` (exit 0; runtime 1200 passed, 51 skipped; ml 397
  passed, 1 skipped; web 99 passed).
- `git status --short data/`: empty.

## Known limits

- Delayed roll: the roll waits until no handler or activity is active, so any
  number of retries arriving before then receive the cached failure for as
  long as other handlers stay active (for example another handler exhausting
  its ~15 s of retries, or a continuous Update stream).
- Runs in progress at deploy time: a run that has replayed an exhaustion
  keeps `patched("retryable-update-failure-continues-as-new") == False` for
  the rest of that run, so further exhaustions in that run do not roll, and an
  approval stuck at `pending_execution` before the deploy recovers only after
  the run rolls at the command threshold (32) or through a retry with the same
  command id.
- `RetryState.TIMEOUT` (schedule-to-close exhaustion) is covered by code
  review only, not by a test. As before this change, the Workflow can see
  that timeout while the last attempt is still running, so the retry may run
  concurrently with it; the Runtime's revision CAS and execution claim bound
  that overlap.
- Every roll resets the run-local expiry state: the backoff
  (`_expiry_failures`, `_expiry_retry_at`) and `_expiry_abandoned_for`, so an
  abandoned expiry is attempted once more in the new run.
- One extra run per exhaustion.
- T4 bounds its red case with `asyncio.wait_for`; a regression can still hang
  the worker shutdown after the assertion fails.
- Separate pre-existing gap (backlog): a channel ingest whose delivery
  activity exhausts is not re-driven on redelivery.
- **New backlog item R-16** (pre-existing, not fixed here):
  `_expiry_failure_category` takes the innermost typed `ApplicationError`,
  which for every real activity failure is the converted Python cause
  (`[('ApplicationError','case_conflict',True), ('ApplicationError','CaseConflictError',False)]`
  → `('CaseConflictError', False)`). A real non-retryable expiry failure is
  therefore retried with backoff instead of abandoned; the expiry tests miss
  it because their injected faults carry no `__cause__`. The fix changes
  expiry-path commands for recorded histories, so it needs its own patch gate.
