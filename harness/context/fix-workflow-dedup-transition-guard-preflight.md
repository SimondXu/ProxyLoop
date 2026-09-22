# Fix: deduplicated replay must not roll back the workflow's last transition (P0-3b)

Bounded change under `harness/context/audit-remediation-decisions.md`.
Branch `fix/workflow-dedup-transition-guard` from `main` @ `2ad2b9a`.
Found by the independent reviewer of P0-3 (#40), recorded in
`harness/log/fix-workflow-expiry-failure-boundary.md` "Reviewer I-1".

## Defect (observed on main)

`CaseWorkflow.apply_case_command`
(`runtime/services/workflow_worker/src/proxyloop_workflow_worker/workflow.py`,
the `self._last_transition = transition` after `_execute_command`)
overwrites the workflow's last transition unconditionally. The Runtime
returns the **stored** receipt for a repeated command id
(`runtime.py` `receipt.model_copy(update={"deduplicated": True})`), so a
client that re-sends an older command while an approval is pending — e.g.
the duplicate `CREATE_CASE` the existing replay test sends — makes
`_last_transition` the create receipt (no `approval_id`), `run()` takes the
plain `wait_condition` branch, and the pending approval's expiry timer is
silently disarmed. Continue-as-new then carries the rolled-back reference.

## Frozen design

All in `workflow.py`.

1. In `apply_case_command`, after `_execute_command` returns and the
   `case_id` check passes: replace `_last_transition` (and call
   `_reset_expiry_backoff()`) **only if** the transition is authoritative
   and newer:
   `current is None or transition.after_revision > current.after_revision`
   where `current = self._last_transition`. Otherwise keep
   `_last_transition` as is. **`deduplicated` is not a rejection
   criterion** (revised after review): the Runtime also marks the stored
   receipt `deduplicated` when an activity retries after its first attempt
   committed but failed to report, and that receipt is strictly newer and
   must be adopted. `after_revision` equals the snapshot revision written
   by the command, which is monotonic, so revision order alone decides. Still return `transition` to the caller, still bump
   `_commands_in_run`, `_continue_requested`, `_wake_version` (a dedup
   Update is a command the run served).
2. Same guard in `_expire_pending`'s success path (a deduplicated expiry
   receipt cannot be newer, but the rule must be one helper):
   `_adopt_transition(transition) -> bool`.
3. No change to `models.py`, `client.py`, `activities.py`, `case_runtime`.

## Regression tests (write first; must fail on the pre-fix code)

`tests/integration/test_phase_05a_temporal_workflow.py`, time-skipping
`WorkflowEnvironment` pattern as in the P0-3 tests:

- **T1**: create → event (pending approval with `approval_expires_at`) →
  re-send the **same `CREATE_CASE` request** (same command id) → assert the
  Update returns the stored create receipt with `deduplicated=True`; then
  `environment.sleep` past the approval expiry → assert the approval is
  persisted `expired` exactly once and the workflow is RUNNING. On main the
  expiry never fires (approval stays `pending`).
- **T2**: same setup, then a re-sent **older** `APPEND_EVENT` (the one that
  created the approval, same command id) → dedup receipt returned; expiry
  still fires once after the sleep.
- **T3** (added after review): the `APPEND_EVENT` that creates the pending
  approval fails once **after commit** inside the activity (the existing
  `_FaultingAdapter(after_commit=True)` shape), so the retry returns the
  stored receipt with `deduplicated=True` and a higher `after_revision`;
  assert the Workflow adopts it: after `environment.sleep` past the expiry
  the approval is persisted `expired` once and the run is RUNNING. Must
  fail against the first-cut guard that rejected `deduplicated`.
- Existing tests unchanged, including
  `test_live_temporal_postgres_duplicate_callback_continue_as_new_and_replay`
  (Replayer over real histories — the guard only skips a state write, adds
  no commands, so histories replay).

## Verification

Compose as in P0-3; `make phase05a-check`, `make phase06b1-check`,
`make postgres-check`; `make lint`, `make typecheck`, `make format-check`.
Root runs `make preflight` once.

## Escalate instead of deciding

Any existing test that must change semantics; any Replayer failure; any
need to touch `models.py` or the Runtime.
