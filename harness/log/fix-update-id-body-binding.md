# Fix log: a corrected retry is not replayed a cached Update failure (P1 C-4)

Spec: `harness/context/fix-update-id-body-binding-preflight.md`.
Programme: `harness/context/audit-remediation-decisions.md`. Branch
`fix/update-id-body-binding` from `main` @ `383d1fa`. Origin: audit C-4
(`harness/code_review/repo-audit-C.md`).

## What changed

- `workflow_worker/models.py`: `CaseCommandRequest.semantic_fingerprint()`
  hashes (`canonical_fingerprint`) `model_dump(mode="json",
  exclude={"channel_occurred_at"})`, which is exactly the field set that
  `to_command` passes to `CaseCommand`. `semantic_command_fingerprint`
  excludes `occurred_at`, which is the only field `to_command` adds, so the
  value equals the Runtime receipt fingerprint without needing a Workflow
  time. It never raises, so an invalid request still reaches the Workflow and
  fails there as `invalid_command`, as before.
- `workflow_worker/workflow.py`: `update_id_for_command(command_id,
  request_fingerprint)` returns
  `case-command/<command id lower>:<fingerprint[:16] lower>`.
  `activity_id_for_command` returns the unchanged old string
  `case-command/<command id lower>`.
- `workflow_worker/client.py`: `TemporalCaseClient.apply_command` builds the
  Update ID from the request's fingerprint. The API and the channel route
  dispatch through this method. The only `app.py` change is the review fix M1
  (below).
- Tests: the time-skipping race test's explicit `start_update` uses the new
  signature.

## Determinism and Activity ID decision

- The Update ID is computed only on the client side. Workflow code never reads
  it, so no `workflow.patched` gate is needed.
- The Activity ID is left unchanged, byte for byte, so histories recorded
  before the fix still replay. A unit assertion freezes the format. A
  corrected retry now schedules a second activity with the same ID in one run.
  This is allowed because Temporal only rejects an Activity ID that is still
  pending, and every command activity (including expiry and channel delivery)
  runs under `_command_lock`, so two activities for one command id can never
  be pending at the same time. T1 and T4 exercise this against the Compose
  Temporal server.

## Tests

`tests/integration/test_phase_05a_temporal_workflow.py`:
- `test_update_id_binds_command_id_and_semantic_request` (unit): the ID is
  stable, lower-case and keeps the prefix. It differs when
  `expected_revision` differs. The Activity ID format is unchanged.
- `test_request_fingerprint_matches_runtime_receipt_fingerprint` (unit):
  equals `semantic_command_fingerprint(request.to_command(t))` for every
  command type at two different times, and `from_command` round trips (M3).
- T1 `test_live_temporal_corrected_retry_of_conflicted_command_executes`:
  a stale `expected_revision` returns `case_conflict`. The same command id
  with the correct revision is then applied (activity outcomes
  `[case_conflict, applied]`).
- T2 `test_live_temporal_identical_retry_keeps_cached_outcome`: an identical
  retry of a failed command returns the same failure, and an identical retry
  of a successful command returns the same receipt. Neither runs the activity
  again.
- T3 `test_live_temporal_changed_body_after_success_is_runtime_conflict`:
  the same id with a different body after success gets the Runtime
  fingerprint `case_conflict`. Nothing executes a second time.

`tests/integration/test_phase_06b1_temporal.py`:
- T4 `test_live_temporal_conflicted_mailbox_event_succeeds_on_redelivery`:
  under the inbox-reserved command id, a stale-revision dispatch returns
  `channel_conflict`. After the event is reserved again (same command id), the
  dispatch with the current revision is applied. This test goes through the
  client, not the HTTP route.

## Red → green

| Test | Pre-fix | Post-fix |
|---|---|---|
| T1 | corrected retry raises `TemporalDispatchError: case_conflict` (the cached Update failure) | applied, before revision = created |
| T3 | `DID NOT RAISE` (the cached success is returned for a different body) | `case_conflict`, 2 transitions |
| T4 | redelivery raises `TemporalDispatchError: channel_conflict` | applied with a delivery |
| unit ×2 | `AttributeError` (no `semantic_fingerprint`) | pass |
| T2 | passes (it guards behaviour that already worked) | pass |

## Review

Independent review (`reviewer`): **Approve**, with three minor findings.

- M1 (applied): the channel route in `api/app.py` treated a duplicate as
  already applied only when its inbox copy said `processing_state ==
  "applied"` **and** a Case receipt existed. The receipt is written in the
  same transaction that marks the inbox applied (`postgres_repository.py`
  `replace_with_channel_outbox` and the delivery-receipt write). So the extra
  condition added nothing, and a duplicate that raced the first dispatch got a
  false 409. The route now takes the early return when the receipt alone is
  present. Regression test
  `test_local_mailbox_api_duplicate_racing_first_dispatch_is_deduplicated`
  (`test_phase_06b1_channel_runtime.py`) uses a stale `reserved` inbox copy.
  Before the fix it fails with `assert 409 == 200`. After the fix the response
  is 200 with `deduplicated`, and there is one dispatch.
- M2 (accepted as is).
- M3 (applied): the fingerprint-equality unit test now also covers
  `EXPIRE_APPROVAL`, `INGEST_CHANNEL_EVENT` and `RECORD_CHANNEL_DELIVERY`
  (`phase-06b1-v1`), at two Workflow times. It adds a `from_command` round
  trip and shows that `channel_occurred_at` is outside the fingerprint.

## Checks (implementer)

- Passed: `test_phase_05a_temporal_workflow.py` + `test_phase_06b1_temporal.py`
  + `test_phase_05a_temporal_api.py` + `test_phase_06b1_workflow_worker.py`
  + `test_phase_06b1_channel_runtime.py` against the Compose Temporal and the
  PostgreSQL test database. The set includes the Replayer tests. Counts are in
  the final report.
- Passed: `make lint`, `make typecheck`, `make format-check`,
  `make preflight-fast`.
- Not run by the implementer (the root runs them serially): `phase05a-check`,
  `phase06b1-check`, `postgres-check`, `make preflight`.
- Root, final diff (serial, Compose profiles up, `PROXYLOOP_TEST_DATABASE_URL`
  and `PROXYLOOP_TEST_TEMPORAL_ADDRESS` set): `make preflight` exit 0 (runtime 754 passed incl. DB-gated tests, ML and web green);
  `postgres-check` 27, `phase05a-check` 36, `phase06b1-check` 34 — all passed.
  An earlier run failed intermittently (`case_not_found`, `state_invalid`)
  because another worktree's Temporal tests truncated the shared
  `proxyloop_test` database at the same time; rerun serially, all green.


## Known limits

- Behaviour change: before the fix, reusing a command id with a different
  body in the same run silently returned the cached success. It now gets the
  Runtime's fingerprint `case_conflict`, which is the intended receipt rule
  (T3).
- `channel_occurred_at` is outside the fingerprint, as it is in the Runtime
  fingerprint. A retry that changes only that field reuses the cached outcome.
- Remaining race (out of scope): the channel route reads `expected_revision`
  outside any lock. A concurrent command can still make the first dispatch
  conflict. Redelivery now recovers, but the first delivery attempt still
  fails.
- Pre-existing issue, reproduced by the reviewer and not fixed here: after
  the activity retries are exhausted (`temporal_unavailable`), an identical
  retry of the same command gets the cached failure until Continue-As-New.
  The Web copy "safe retry preserved" is therefore not true within one run.
  This is tracked as a separate backlog item.
- Temporal's per-run Update registry now holds one entry per distinct body
  instead of one per command id. The retry paths are bounded, so the growth
  is small.
