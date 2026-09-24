# Fix: a chained non-retryable expiry failure is abandoned, not retried (R-16)

Backlog item R-16 in `harness/context/audit-remediation-status.md` §4a
(build-plan PR-2). Branch `fix/r16-expiry-classifier` from `main` @ `d23aff9`
(includes #78, R-1).

## Defect (observed on main)

`_expire_pending` classifies a failed expiry with `_expiry_failure_category`,
which walks `__cause__` and keeps the innermost typed `ApplicationError`.
`activities.py` raises every category `from exc`, so through the default
failure converter a real failure arrives as
`ActivityError → ApplicationError('case_conflict', non_retryable=True) →
ApplicationError('CaseConflictError', non_retryable=False)` and is classified
`('CaseConflictError', False)`: retryable. The Workflow then re-arms a 15 s
backoff timer and retries an expiry the Runtime has already refused, instead
of abandoning it. The existing expiry tests miss it because their injected
faults carry no `__cause__`. Reproduced on `main` while recording the replay
fixture below: the worker logged `approval expiry attempt 1 failed:
CaseConflictError` and started the retry timer (history event 35).

## Decision: classify by the outermost cause (option A), behind a second patch

`runtime/services/workflow_worker/src/proxyloop_workflow_worker/workflow.py`
only:

1. New `_outermost_failure_category(error)`: the failure is `error.cause` for
   an `ActivityError`, else `error` itself (the Workflow-raised
   `state_invalid`). An `ApplicationError` is non-retryable when flagged
   `non_retryable` or its type is in `NON_RETRYABLE_ERROR_TYPES`; a
   `TimeoutError` is `activity_timeout`, retryable; anything else is
   `activity_failed`, retryable.
2. `_expire_pending` uses it when
   `workflow.patched("expiry-failure-outermost-cause")`, else the unchanged
   `_expiry_failure_category`. The patch call sits on the failure path only,
   so histories without an expiry failure gain no marker.
3. `apply_case_command`'s R-1 logic (`retry_state`, patch
   `retryable-update-failure-continues-as-new`) is unchanged.

Why A and not `ActivityError.retry_state` (the R-1 classifier): for an
activity failure the two agree, because the server's
`RETRY_STATE_NON_RETRYABLE_FAILURE` is decided by exactly the rule A applies
to the same outermost failure (flag or policy list); retryable exhaustion
(`MAXIMUM_ATTEMPTS_REACHED`, `TIMEOUT`) is retryable under both. But the
expiry path also catches the `ApplicationError` the Workflow raises itself
(`state_invalid` for a foreign Case id or an invalid activity result), which
has no `retry_state`, so B would need a second rule for it and a default for
an unset state. A is one rule for both paths and does not depend on a
server-populated field. R-1 uses `retry_state` because it must distinguish
"retries exhausted" from "non-retryable"; the expiry path only needs
"would the server retry this", which A answers directly.

## Tests (`tests/integration/test_phase_05a_temporal_workflow.py`)

`_ExpiryFaultingAdapter` gains `cause=` and raises its fault `from` it (the
production adapter's shape); `from None` keeps the old tests identical.

- `test_time_skipping_non_retryable_expiry_failure_does_not_spin[chained]`
  (`CaseConflictError` cause): one expiry attempt, then abandoned. Red on
  `main` expected (retried with backoff). Needs the Compose test DB.
- `test_time_skipping_expiry_retry_exhaustion_keeps_workflow_alive[chained]`
  (`StorageUnavailableError` cause): still backs off and later expires. Green
  on `main` and after. Needs the Compose test DB.
- `test_replay_pre_r16_history_keeps_the_expiry_patch_gate`: replays
  `tests/fixtures/temporal_history.case-workflow-expiry-chained-conflict.pre-r16.json`
  on the patched code; with only this patch forced on,
  `NondeterminismError` "No command scheduled for event HistoryEvent(id: 35,
  TimerStarted)". Red on `main` (DID NOT RAISE). Needs no DB; runs in
  `make test`.
- The R-1 replay test now shares a `_replay(path, runner)` helper; its
  assertions are unchanged.

The fixture was recorded on `main` @ `d23aff9` with the process-local
time-skipping test server and `InMemoryCaseRepository` behind the production
`CaseCommandActivityAdapter` (no shared DB or Compose Temporal): create; an
append leaving a pending approval; a rejection applied to the Runtime outside
the Workflow; the expiry fails once with `case_conflict` raised `from`
`CaseConflictError` (`RETRY_STATE_NON_RETRYABLE_FAILURE`) and the Workflow
starts a 15 s retry timer. Stack traces blanked, identities set to
`proxyloop-phase05a-recorder`; no local path or host name remains in the
plain text or the decoded payloads.

## Risks carried

- Runs in progress at deploy time: when a run replays an expiry failure
  recorded before the deploy, the SDK caches
  `patched("expiry-failure-outermost-cause") == False` for the rest of that
  run. A chained non-retryable expiry failure in that run is then classified
  retryable and retried indefinitely (there is no attempt limit), with the
  backoff capped at `EXPIRY_RETRY_MAXIMUM_BACKOFF` (5 minutes). It stops only
  when an Update adopts a newer transition (`_adopt_transition` →
  `_reset_expiry_backoff`) or the run rolls (command threshold or the R-1
  exhaustion roll; failed expiries do not count toward the threshold).
  Meanwhile the history grows by about one failed activity plus its retry
  timer every 5 minutes. That unbounded growth predates this fix: no
  history-size Continue-As-New exists.
- Unchanged: the expiry state is run-local, so any roll (threshold or R-1)
  resets `_expiry_abandoned_for` and the abandoned expiry is attempted once
  more in the new run.
