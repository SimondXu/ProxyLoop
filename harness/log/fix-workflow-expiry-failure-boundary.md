# Fix log: workflow expiry-timer failure boundary (P0-3)

Spec: `harness/context/fix-workflow-expiry-failure-boundary-preflight.md`.
Resolves audit finding C-3 (Important): an exhausted `EXPIRE_APPROVAL`
activity failed the whole `CaseWorkflow` run, and `REJECT_DUPLICATE` then
blocked every later command for that Case. Branch
`fix/workflow-expiry-failure-boundary` from `main` @ `fe3942a`.

## What changed

- `workflow_worker/workflow.py`: `_expire_pending` wraps the expiry
  activity (and the `case_id` result check) in
  `try/except (ActivityError, ApplicationError)`.
  `_expiry_failure_category` walks `__cause__` to the innermost
  `ApplicationError` and returns `(category, non_retryable)`;
  non-retryable = category in `NON_RETRYABLE_ERROR_TYPES` or the innermost
  error carries `non_retryable=True`. Non-retryable → the approval is
  recorded in `_expiry_abandoned_for` and the timer is not re-armed;
  retryable exhaustion → `_expiry_failures += 1`,
  `_expiry_retry_at = now + min(15s · 2^(n-1), 5min)`. `run()` skips an
  abandoned approval (plain `wait_condition`) and, while `_expiry_retry_at`
  is in the future, waits for it (`timeout_summary="case approval expiry
  retry"`) before re-attempting. `_reset_expiry_backoff()` runs whenever
  `_last_transition` is replaced by a successful Update or expiry. Logs
  carry only the category and attempt count. No change to `activities.py`,
  `client.py`, `models.py` (`CaseWorkflowInput` unchanged), `case_runtime`.
- Tests (`tests/integration/test_phase_05a_temporal_workflow.py`):
  `_ExpiryFaultingAdapter` (fails only inside `EXPIRE_APPROVAL`, counted,
  with a switch); T1 retryable exhaustion keeps the workflow RUNNING, a
  later distinct Update reaches the Runtime, and after the switch flips the
  expiry persists exactly once; T2 non-retryable (`case_conflict`) → one
  attempt, RUNNING, no spin after 1 h. The two existing expiry tests are
  unchanged.

## Red → green

| Test | Pre-fix (`main` `workflow.py`) | Post-fix |
|---|---|---|
| T1 | `assert <FAILED: 3> is <RUNNING: 1>` after 5 activity attempts | 5 attempts, RUNNING, 6th attempt succeeds after backoff; approval `expired` once, 3 transitions |
| T2 | `assert <FAILED: 3> is <RUNNING: 1>` after 1 attempt | 1 attempt, RUNNING, still 1 after `sleep(1h)` |

Deviations from the packet, accepted by root: (1) no `CaseWorkflowInput`
field — the CAN gate opens only after a successful command, which resets
the backoff state; the theoretical interleaving (handler holding the lock
across the 1-day expiry point) is unreachable under the 2-min
schedule-to-close, and its worst case is one extra attempt round, not a
spin. (2) "later distinct Update succeeds" is proven as "the Update is
executed by the Workflow and returns the Runtime's deterministic
`case_conflict`" because no non-expiry command is valid while an expired
approval is pending. (3) T1 skips to `approval_expires_at + 1 s` rather
than 2 h so the workflow-level retry timer does not fire a second round.

## Checks

- Passed: focused `-k expiry` 4; `test_phase_05a_temporal_workflow.py` +
  `test_phase_05a_temporal_api.py` 20; `make lint`, `make typecheck`,
  `make format-check`.
- Passed (Compose, torn down after), re-run by root after the review
  minors: `phase05a-check` 28 (incl. the Replayer test),
  `phase06b1-check` 32, `postgres-check` 27.
- Passed: `make preflight` on the stable diff — runtime 316 / 39 gated
  skips, ML 279, web 47, all artifact gates valid.
- Independent review (`reviewer`, Opus): **Approve**, no Blocking or
  Important findings in the diff. Adversarial checks: replay safety
  (Replayer test green; timeouts derived from deterministic state);
  `__cause__` chain verified against temporalio 1.32 failure converter;
  `CancelledError` not caught; an Update failing during the backoff wait
  re-waits the remaining backoff (no spin). Minors applied by root: M-1
  `case_id` result check moved inside the `try`; M-2 honour
  `ApplicationError.non_retryable`; M-3 wall-clock window comment in T1.

## Known limits and follow-ups

- Runs that already FAILED on `main` are not recovered (reset the local
  demo or terminate the run by hand).
- After continue-as-new the three fields restart at zero; the worst case
  is one extra attempt round for an abandoned or backing-off approval.
- `activity_timeout` classification has no test (needs an activity to
  exceed schedule-to-close under time skipping); it shares the retryable
  branch with `storage_unavailable`.
- **Reviewer I-1 (pre-existing, out of scope):** `apply_case_command`
  overwrites `_last_transition` with a deduplicated replay of an older
  command (e.g. a re-sent `CREATE_CASE` while an approval is pending), which
  drops the pending expiry timer. Candidate fix: do not replace
  `_last_transition` when `transition.deduplicated` or
  `transition.after_revision < current.after_revision`. Tracked as a
  Group 1 follow-up (P0-3b).
