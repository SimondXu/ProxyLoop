# Fix log: callback events on a terminal Case are paired with their Evidence (R-18)

Spec: `harness/context/fix-r18-callback-evidence-pairing-preflight.md`.
Branch `fix/r18-callback-evidence-pairing` from `main` @ `d23aff9`.

## What changed

- `runtime/packages/case_runtime/src/proxyloop_case_runtime/postgres_repository.py`:
  new `_verify_delivery_callback_pairs`, called from the terminal branch of
  `_reconstruct_provider`. The events after the approval-decision cursor and
  the `PROVIDER_EVENT` Evidence after the confirmation Evidence must have the
  same count and pair in order with
  `observed_at == captured_at == occurred_at`.
- `tests/integration/test_r10_terminal_delivery_callback.py`: `_completed`
  now delegates to `_completed_with_replies` (several replies, optional
  callback before the approval); `_with_last_event` delegates to a new
  `_rebuilt` helper; eight new tests (below). No existing assertion changed.
- No runtime, contract or storage change.

## Red → green

Red is the codec on `main` @ `d23aff9` with the new tests.

| Test | Red | Green |
|---|---|---|
| `test_a_forged_callback_event_without_evidence_is_rejected` | FAIL: did not raise | pass |
| `test_a_forged_callback_event_on_a_completed_case_is_rejected` | FAIL: did not raise | pass |
| `test_a_deleted_callback_event_whose_evidence_remains_is_rejected` | FAIL: did not raise | pass |
| `test_provider_event_evidence_without_a_callback_event_is_rejected` | FAIL: did not raise | pass |
| `test_a_callback_evidence_at_another_time_is_rejected` | FAIL: did not raise | pass |
| `test_two_callbacks_after_complete_are_stored[delivered]`, `[bounced]` (control) | pass | pass |
| `test_a_callback_before_approval_and_one_after_complete_are_stored` (control) | pass | pass |

The nine R-10 tests in the file pass before and after.

## Checks

- Passed: focused `test_r10_terminal_delivery_callback.py`,
  `test_phase_06b1_channel_runtime.py`, `test_strategy_basis_binding.py`
  without DB (51 passed, 1 skipped: the DB-gated test).
- Passed: `make format-check lint typecheck` (exit 0).
- Passed: `make preflight-fast` (exit 0).
- Passed: `make test` (exit 0; runtime 1211 passed, 51 skipped; ml 397
  passed, 1 skipped).

After merging `origin/main` @ `e1c8371` (#81; one status-file conflict,
both sides kept):

- Passed: `make test` (exit 0; runtime 1231 passed, 51 skipped; ml 397
  passed, 1 skipped).
- Passed, one at a time against the Compose test DB and Temporal:
  `make postgres-check` (27 passed), `make phase05a-check` (42 passed),
  `make phase06b1-check` (35 passed, including R-10's DB-gated
  `test_postgres_delivery_callback_after_complete_is_stored`).
- Passed: `make preflight` (exit 0; runtime 1231 passed, 51 skipped; ml 397
  passed, 1 skipped; web 140 passed).

## Known limits

Recorded by the root as accepted limits (binding a pair to a real delivery
needs a storage change, out of scope):

- A consistent forged pair (a callback event and a `PROVIDER_EVENT` Evidence
  with equal times) is accepted, and a delivered/bounced text swap is not
  detected; binding needs the delivery id in the payload or a cross-check
  against `proxyloop_channel_delivery_receipts.evidence_id`.
- `source_ref` and `content_hash` are unchecked; the event does not carry
  them.
- Callbacks before the approval stay unpaired, and extra Evidence placed
  before the confirmation Evidence or of other types is not restricted.
