# Fix log: deduplicated replay must not roll back the workflow's last transition (P0-3b)

Spec: `harness/context/fix-workflow-dedup-transition-guard-preflight.md`.
Programme: `harness/context/audit-remediation-decisions.md`. Branch
`fix/workflow-dedup-transition-guard` from `main` @ `2ad2b9a`. Origin:
reviewer finding I-1 on P0-3 (#40).

## What changed

- `workflow_worker/workflow.py`: `_adopt_transition(transition) -> bool`
  replaces `_last_transition` (and resets the expiry backoff) only when
  `transition.after_revision > current.after_revision`; both
  `apply_case_command` and `_expire_pending` use it and log a debug line
  when a receipt is not adopted. Revision order alone decides —
  `deduplicated` is **not** a rejection criterion (see review below).
- Tests (`tests/integration/test_phase_05a_temporal_workflow.py`):
  `test_time_skipping_deduplicated_replay_keeps_pending_expiry[create|append]`
  — after continue-as-new (Temporal dedups Update ids within one run
  server-side), re-send the original `CREATE_CASE` / `APPEND_EVENT`; the
  Update returns the stored receipt with `deduplicated=True`; the pending
  approval still expires exactly once. `[create]` fails on main
  (`'pending' == 'expired'`); `[append]` is a guard-only case (the dedup
  receipt equals the current transition) and passes pre-fix.
  `test_time_skipping_post_commit_retry_receipt_keeps_pending_expiry` (T3)
  — the first `APPEND_EVENT` faults once after commit
  (`_AppendPostCommitFaultingAdapter`), so the retry returns a
  `deduplicated=True` receipt with a **higher** revision; it must be
  adopted and the approval must still expire.

## Red → green

| Test | Pre-fix | Post-fix |
|---|---|---|
| T1 `[create]` | `assert 'pending' == 'expired'` (timer disarmed by the replayed create receipt) | expired once, RUNNING, 3 transitions |
| T3 | `assert 'pending' == 'expired'` against the first-cut guard that rejected `deduplicated` receipts | adopted; expired once |

## Review

Independent review (`reviewer`, Opus): first pass **Request Changes** with
a Blocking finding against the frozen design itself — the spec's
`deduplicated is False` clause would reject the receipt an activity retry
returns after its first attempt committed but failed to report
(`runtime.py:234-238`), which is strictly newer; rejecting it disarms the
expiry timer forever and strands the Case (reviewer probe: `deduplicated=True
after_revision=4` vs create 2 → approval never expires). Root revised the
spec to revision-only; implementer applied it and added T3 from the probe.
Re-review **Approve**: probe passes on the current diff, T3 fails against
the first-cut guard, Replayer test green, debug logging replay-safe.

## Checks

- Passed (Compose, torn down after): `phase05a-check` 31 (implementer and
  reviewer independently), `phase06b1-check` 32, `postgres-check` 27
  (implementer).
- Passed: `make lint`, `make typecheck`, `make format-check`.
- Passed: `make preflight` — runtime 316 / 42 gated skips (3 new gated
  tests), ML 318 / 1 skipped, web 51, all gates valid.

## Known limits

- T2 `[append]` is not a red-first regression; kept as the guard for the
  equal-revision branch.
- T3 relies on the activity retry's 1 s server backoff advancing on the
  wall clock under time skipping (same assumption as the P0-3 tests).
