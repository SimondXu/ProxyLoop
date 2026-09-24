# Fix log: a delivery callback on a COMPLETE Case survives the PostgreSQL codec (R-10)

Spec: `harness/context/fix-r10-terminal-delivery-callback-preflight.md`.
Branch `fix/r10-terminal-delivery-callback` from `main` @ `f818b61`.

## What changed

- `runtime/packages/case_runtime/src/proxyloop_case_runtime/postgres_repository.py`:
  the terminal branch of `_reconstruct_provider` compares the execution source
  pins with the snapshot pins at the approval-decision cursor
  (`_approval_decision_cursor`: the one event with the deterministic
  approval event id, type `approval_decision`, time `approval.decided_at`)
  and rejects any event after that cursor that is not a delivery-callback
  `provider_event` (`_is_delivery_callback_event`, `_DELIVERY_CALLBACK_CONTENT`).
- `runtime/packages/case_runtime/src/proxyloop_case_runtime/runtime.py`:
  `record_channel_delivery` builds the next snapshot in the stored
  `schema_version` when `completion_decision` is set (otherwise `"1.1"`, as
  before).
- New `tests/integration/test_r10_terminal_delivery_callback.py`.
  No existing test changed.

## Red → green

Red is the codec and runtime on `main` @ `f818b61` with the new test file.

| Test | Red | Green |
|---|---|---|
| `test_first_delivered_callback_after_complete_is_stored` | FAIL: callback write raises "Case state failed storage validation" | pass |
| `test_a_stored_1_0_complete_case_stays_1_0_after_a_callback` | FAIL: same codec error; after the codec fix alone, `CaseContextSnapshot` validation error (1.1 without receipt) | pass |
| `test_a_tampered_source_pin_cursor_is_rejected[1]` | FAIL (setup: callback write) | pass |
| `test_a_tampered_source_pin_cursor_is_rejected[-1]` | FAIL (setup: callback write) | pass |
| `test_a_rebuilt_callback_event_is_still_accepted` | FAIL (setup: callback write) | pass |
| `test_a_non_delivery_event_after_the_approval_is_rejected[consumer-message]` | FAIL (setup: callback write) | pass |
| `...[provider-event-other-content]` | FAIL (setup: callback write) | pass |
| `...[provider-message]` | FAIL (setup: callback write) | pass |

The tamper and forged-event tests are red on `main` only because their
fixture (a callback on a COMPLETE Case) cannot be stored there; they guard the
new rule rather than reproduce the defect. `[1]` is the value the old rule
required (source cursor == snapshot cursor) and is now rejected.

## Checks

- Passed: focused `pytest tests/integration/test_r10_terminal_delivery_callback.py`
  plus `test_phase_06b1_channel_runtime.py`, `test_persisted_claim_and_traces.py`,
  `test_strategy_basis_binding.py`, `test_phase_05a_case_runtime.py`,
  `test_phase_04c_persistent_case_store.py` (68 passed, 25 skipped: DB-gated).
- Passed: `make format-check lint typecheck` (exit 0).
- Passed: `make preflight-fast` (exit 0).
- Passed: `make test` (exit 0; runtime 1182 passed, 46 skipped; ml 390 passed,
  1 skipped).
- `git status --short data/`: empty.
- Unrun (root runs them serially on the shared test DB): `make postgres-check`,
  `make phase05a-check`, `make phase06b1-check`, `make preflight`.

## Known limits

- The callback event texts are duplicated in the codec, as the codec already
  re-derives other runtime values (`_capability_proposal`, `_stable_uuid`).
  Changing the runtime text without the codec would reject callbacks; the new
  green test catches that.
- A callback event is recognized by type, actor and fixed text; the codec does
  not pair it with its Provider-event Evidence (the delivery id is not
  recoverable from the event). Extra Evidence of other types on a terminal
  Case was not restricted before this change and still is not.
- The 1.0 path is exercised through a 1.1 Case rewritten by
  `_as_stored_1_0`, not a row written by the pre-1.1 runtime.
