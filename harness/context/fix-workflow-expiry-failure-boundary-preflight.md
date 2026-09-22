# Fix: workflow expiry-timer failure boundary (P0-3)

Bounded repository change approved by the user on 2026-09-21 (Group 1).
Branch `fix/workflow-expiry-failure-boundary` from `main` after P0-2
merges. Resolves audit finding **C-3** (Important); see
`harness/code_review/repo-audit-C.md` and
`docs/research/2026-09-21-repository-audit.md` §6 P0 row 3.

## Defect (observed on main)

`CaseWorkflow.run` (`workflow.py:153-171`) awaits `_expire_pending`
(`:262-308`), which awaits `_execute_command` with no failure boundary.
When the `EXPIRE_APPROVAL` activity exhausts `ACTIVITY_RETRY_POLICY`
(PostgreSQL outage, 5 attempts / 2 min schedule-to-close) the
`ActivityError` propagates out of `run()`; the workflow run is **FAILED**;
`client.py:81` uses `REJECT_DUPLICATE`, so Update-with-Start cannot recreate
it. Observed (`c3_expiry_exhaustion.py`): `expiry activity attempts: 5`,
`workflow status FAILED`, approval still `pending` in the DB, later Update
→ `temporal_unavailable` (update not found), create → `ALREADY_EXISTS`.
Contract violated: `phase-05a` fault row "PostgreSQL unavailable through
retry exhaustion → Workflow remains available for a later distinct
command"; AC7 (approval expiry persists once).

## Frozen design

All changes in
`runtime/services/workflow_worker/src/proxyloop_workflow_worker/workflow.py`.

1. **Failure boundary.** In `_expire_pending`, wrap the
   `await self._execute_command(expiry_command)` in `try/except`:
   - `except ActivityError as error` (from `temporalio.exceptions`;
     also catch `ApplicationError` raised directly by `_execute_command`'s
     result validation):
     - Determine `category`: the innermost `ApplicationError.type` when
       present (the activity taxonomy: `storage_unavailable`,
       `case_conflict`, `case_not_found`, `state_invalid`,
       `invalid_command`, …), else `"activity_timeout"` for timeouts, else
       `"activity_failed"`.
     - **Retryable exhaustion** (`storage_unavailable`, timeouts,
       `activity_failed`): increment `self._expiry_failures`, set
       `self._expiry_retry_at = workflow.now() + backoff` with
       `backoff = min(timedelta(seconds=15 * 2 ** (failures - 1)),
       timedelta(minutes=5))`, `workflow.logger.warning(...)` with the
       category only (no exception text), and return. The run stays alive.
     - **Non-retryable** (`case_conflict`, `case_not_found`,
       `state_invalid`, `invalid_command`): record
       `self._expiry_abandoned_for = (current.approval_id,
       current.approval_expires_at)`, log the category, and return; the
       loop must not re-arm the timer for that approval (a conflict means
       the aggregate moved without this workflow — e.g. a direct-mode
       writer — and the next Update will carry the truth).
   - On success, behaviour unchanged (`_last_transition`, counters,
     `_wake_version`).
2. **Run loop.** In `run()`'s expiry branch, before calling
   `_expire_pending` on `remaining <= 0`: if `self._expiry_abandoned_for`
   equals `(pending.approval_id, pending.approval_expires_at)`, treat the
   transition as having no pending approval (fall through to the plain
   `wait_condition`); if `self._expiry_retry_at` is in the future, wait with
   `timeout = self._expiry_retry_at - workflow.now()` (wake on Updates as
   today) before re-attempting. Reset `_expiry_failures`, `_expiry_retry_at`
   and `_expiry_abandoned_for` whenever `_last_transition` changes through
   an Update or a successful expiry.
3. **Continue-as-new carry.** The three new fields are workflow-run state;
   if `_continue_as_new` carries state through `CaseWorkflowInput`, carry
   `expiry_failures` only (retry time and abandonment are recomputed; an
   abandoned approval id may be carried to avoid a spin after CAN). If the
   input model must gain a field, it is optional with a default so replay of
   existing histories is unaffected; state so in the report.
4. **Workflow-id reuse policy**: unchanged (`REJECT_DUPLICATE`). Recovery of
   runs that already FAILED on main is out of scope (documented limit: reset
   the local demo or terminate the failed run by hand).
5. No change to `activities.py` taxonomy, `client.py`, `models.py`
   (unless item 3 requires the optional field), `case_runtime`.

## Out of scope

Activity taxonomy and API category mapping (`_failure_category` "update not
found" → `temporal_unavailable`, C-N8), C-4 Update-ID replay, `case_runtime`,
`api`, docs other than this file.

## Regression tests (write first; must fail on the pre-fix code)

In `tests/integration/test_phase_05a_temporal_workflow.py`, using the
existing time-skipping `WorkflowEnvironment` pattern and a faulting adapter
that can fail **inside the `EXPIRE_APPROVAL` activity** (extend
`_FaultingAdapter` or add a sibling; failures must be raised as the
activity's own `ApplicationError` types so the real retry policy runs):

- **T1 retryable exhaustion**: adapter raises `storage_unavailable` for
  every `EXPIRE_APPROVAL` attempt until a switch flips. Create → event
  (pending approval) → `env.sleep(2h)`. Assert: the activity was attempted
  5 times, the workflow is still **RUNNING**, a later distinct `APPEND_EVENT`
  Update (or another valid command) succeeds; then flip the switch,
  advance time past the backoff, and assert the approval transition is
  persisted **once** (`expired`), and the workflow is still running.
- **T2 non-retryable**: adapter raises `case_conflict` on
  `EXPIRE_APPROVAL`. Assert exactly one attempt, workflow RUNNING, a later
  distinct Update succeeds, and no further expiry attempts occur after
  `env.sleep(1h)` (no spin).
- **T3 unchanged happy path**: the existing expiry tests
  (`test_..._expiry_...`, the race test) still pass unchanged.

## Verification

Focused: `uv run --project runtime --all-packages pytest -c runtime/pyproject.toml -q runtime/services/workflow_worker tests/integration/test_phase_05a_temporal_api.py`
Gated (Compose as in P0-1): `make phase05a-check`, `make phase06b1-check`,
`make postgres-check`. Static: `make lint`, `make typecheck`,
`make format-check`. Root runs `make preflight` once.

## Escalate instead of deciding

Any need to change the activity taxonomy, the Update contract, the
workflow id reuse policy, or `CaseWorkflowInput` beyond one optional field;
any existing test that must change semantics.
