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
- New `tests/integration/test_r10_terminal_delivery_callback.py`; the
  callback test is parametrized over `delivered` and `bounced` and asserts the
  event text and the last Evidence.
- `tests/integration/test_phase_06b1_channel_runtime.py`: one added DB-gated
  test, `test_postgres_delivery_callback_after_complete_is_stored` (skips
  without `PROXYLOOP_TEST_DATABASE_URL`, via `test_phase_06b1_temporal`'s
  `_database_url` / `_truncate`; run by `make phase06b1-check`). No existing
  test changed.

## Red → green

Red is the codec and runtime on `main` @ `f818b61` with the new test file.

| Test | Red | Green |
|---|---|---|
| `test_first_delivered_callback_after_complete_is_stored` (now `test_first_callback_after_complete_is_stored[delivered]`) | FAIL: callback write raises "Case state failed storage validation" | pass |
| `test_a_stored_1_0_complete_case_stays_1_0_after_a_callback` | FAIL on `main` and with only the codec fix: the runtime's `_snapshot` raises the `CaseContextSnapshot` ValidationError "a 1.1 snapshot is complete exactly when it carries a completion receipt" before the codec is reached | pass |
| `test_a_tampered_source_pin_cursor_is_rejected[1]` | FAIL (setup: callback write) | pass |
| `test_a_tampered_source_pin_cursor_is_rejected[-1]` | FAIL (setup: callback write) | pass |
| `test_a_rebuilt_callback_event_is_still_accepted` | FAIL (setup: callback write) | pass |
| `test_a_non_delivery_event_after_the_approval_is_rejected[consumer-message]` | FAIL (setup: callback write) | pass |
| `...[provider-event-other-content]` | FAIL (setup: callback write) | pass |
| `...[provider-message]` | FAIL (setup: callback write) | pass |
| `test_first_callback_after_complete_is_stored[bounced]` (added after review) | not run on `main` | pass |
| `test_postgres_delivery_callback_after_complete_is_stored` (DB-gated, added after review) | FAIL on `main` sources against the Compose test DB | pass (in `make phase06b1-check`) |

Drift check: with runtime.py's bounce text changed to "The fictional Provider
bounced the reply." (scratch edit, reverted), `[bounced]` fails with "Case
state failed storage validation"; the other 8 tests in the file pass.

The tamper and forged-event tests are red on `main` only because their
fixture (a callback on a COMPLETE Case) cannot be stored there; they guard the
new rule rather than reproduce the defect. `[1]` is the value the old rule
required (source cursor == snapshot cursor) and is now rejected.

## Checks

Final diff (after the review follow-ups):

- Passed: focused `test_r10_terminal_delivery_callback.py` +
  `test_phase_06b1_channel_runtime.py` without DB (27 passed, 1 skipped).
- Passed: `make format-check lint typecheck` (exit 0).
- Passed: `make preflight-fast` (exit 0).
- Passed: `make test` (runtime 1183 passed, 47 skipped; ml 390 passed,
  1 skipped).
- Passed, run one at a time against the Compose test DB and Temporal:
  `make postgres-check` (27 passed), `make phase05a-check` (36 passed),
  `make phase06b1-check` (35 passed, including the new DB-gated test).
- Passed: `make preflight` (exit 0; runtime 1183 passed, 47 skipped; ml 390
  passed, 1 skipped; web 99 passed).
- `git status --short data/`: empty.

## Known limits

- The callback event texts are duplicated in the codec, as the codec already
  re-derives other runtime values (`_capability_proposal`, `_stable_uuid`).
  Changing the runtime text without the codec would reject callbacks; the new
  green test catches that.
- A callback event is recognized by type, actor and fixed text; the codec does
  not pair it with its Provider-event Evidence (the delivery id is not
  recoverable from the event). Two concrete forged forms are therefore
  accepted: any number of delivered/bounced `provider_event`s after the
  approval cursor without matching Provider-event Evidence, and a deleted
  callback event whose Evidence remains. Root decision: pairing is not in this
  PR. Extra Evidence of other types on a terminal Case was not restricted
  before this change and still is not.
- The 1.0 path is exercised through a 1.1 Case rewritten by
  `_as_stored_1_0`, not a row written by the pre-1.1 runtime.
