# Fix log: an append-only model-trace log at `storage_version` 3 (R-12, R-13b; PR-7)

Spec (frozen by the root, 2026-09-24): `harness/context/r12-model-trace-log-design.md`
(Option 3 + bootstrap backfill under an advisory lock, G8 required, I1–I11).
Branch `fix/r12-model-trace-log` from `main` @ `c73f6a7`.

Non-goals, per the spec: no change to `workflow.py`, `activities.py`, `app.py`,
the API shims, `contracts/`, or `agent_core/`; no pruning (retention stays
unbounded); an adapter that raises still produces no trace (coordinator gap,
spec §3.8 item 8); mixed code versions against one database are unsupported.

## What changed

- `repository.py`: `CaseRuntimeState.model_traces` removed. `CaseRepository`
  gains `append_model_traces(case_id, traces)` and `list_model_traces(case_id)`.
  `check_model_trace_case` refuses an append that has a foreign `case_id`
  (`ValueError`, before any write). `InMemoryCaseRepository` keeps a per-Case
  list under its existing lock. An empty append is a no-op.
- `postgres_repository.py`: the envelope is `storage_version` 3 with no
  `model_traces` field (`extra="forbid"` rejects a stray key). `_decode_state`
  accepts {3, 1} (v1 is still upgraded on read). `_bootstrap` takes
  `pg_advisory_xact_lock` first, creates `proxyloop_model_traces` (identity
  `log_id`, `case_id`, `trace` jsonb, no FK) plus the `(case_id, log_id)` index,
  and runs `_backfill_inline_traces`: each v2 row's inline traces are inserted
  in array order, and the row is rewritten as v3 at the same revision and
  `updated_at`. A non-array value is skipped and fails closed on read.
  `append_model_traces` uses one short transaction per call.
  `list_model_traces` returns `ORDER BY log_id`, raises
  `RuntimeError("stored model trace is invalid")` on an invalid or foreign
  trace, and maps `psycopg.Error` to `StorageUnavailableError`.
- `runtime.py`: `_advance` is the only `.advance(` call site. All 8 former
  sites route through it, and it appends `outcome.traces` before returning.
  `_refresh_strategy_if_required` returns the snapshot only. All 10
  `model_traces=` arguments are gone.
- Docs: the `docs/architecture.md` trace-storage paragraph (I1–I11, "stop all
  processes before upgrading", retention unbounded) and the R-12/R-13 bullets
  plus the §0 in-flight row in `harness/context/audit-remediation-status.md`.

## Red (on `main` sources, before any production edit)

The helpers read "persisted" traces the only way `main` has them, from
`repository.get(case_id).model_traces`, with `()` when there is no Case row.
Once the log existed, the same assertions were ported to `list_model_traces`.
Result: `9 failed, 54 deselected`.

| Test | Red failure |
|---|---|
| R1 `test_a_rejected_fast_result_is_traced` | `test_persisted_claim_and_traces.py:638` `assert _logged(...) == tuple(issued)`: "Right contains one more item" (the REJECTED Fast trace). The earlier assertions (issued roles `["slow","fast"]`, last `REJECTED` with reason codes) passed. |
| R4 `test_a_channel_refusal_keeps_its_accepted_traces[response_text]` | `:694` same assertion: "Right contains 2 more items" (refresh Slow and Fast, both `SUCCEEDED`) |
| R4 `[unauthorized_send]` | `:694`: "Right contains 2 more items" |
| R3 `test_a_rejected_create_is_traced_without_a_case` | `test_phase_04b_model_runtime.py:392` `(trace,) = _logged(...)`: `ValueError: not enough values to unpack (expected 1, got 0)` |
| R2 `test_t5_rejected_slow_refresh_persists_no_case_state[_SameRevisionSlow]` and `[_ExpiredStrategySlow]` | `test_slow_refresh_strategy_expiry.py:356` `assert ['slow'] == ['slow', 'slow']` |
| R2 (channel) `test_t5_channel_rejected_slow_refresh_persists_no_case_state[x2]` and `test_t5_channel_rejects_a_same_id_revision_regression` | `:263` `assert [] == ['slow']` |

## Tests (spec §3.5)

- R1–R4 as above. R2 renames the two "persists nothing" tests to "…persists
  no Case state" and keeps their Case-state assertions.
- G1: `test_the_log_holds_every_issued_trace_across_the_direct_flow` and
  `…_channel_flow` replace the four "same write" and "carry forward" tests.
- G2: `test_a_trace_append_is_for_one_case_and_empty_is_a_no_op[memory|postgres]`.
  The Postgres case runs without a database: `_connect` fails the test if it is
  called, which proves that neither a foreign append nor an empty one opens a
  connection.
- G3: `test_the_append_event_rollback_keeps_its_traces`.
  `test_a_compare_and_swap_loser_keeps_its_traces` also covers the CAS-loser
  case of AC 1.
- G4: codec. A v3 row with a `model_traces` key is invalid; v2 and v4 are
  "unsupported"; v1 rows load and are rewritten as v3.
- G5: browser projection, adapted to the log.
- G6 (DB-gated, `test_phase_04c_persistent_case_store.py`): append/list order
  and duplicate rows; an append leaves revision, payload bytes, and
  `updated_at` unchanged; an append without a Case row; `TRUNCATE` of the Case
  table alone; tampered traces (consistently foreign `case_id`, invalid shape)
  fail closed; the `storage_version` garbage row moves from 3 to 4. The fixture
  now truncates `proxyloop_model_traces` with the Case table.
- G7 (DB-gated): a raw v2 row with inline traces becomes v3 at the same
  revision and `updated_at`, and its traces land in the log in order. A second
  bootstrap adds no rows. A v2 row with non-array traces is skipped and stays
  unsupported on read.
- G8: `test_the_runtime_calls_the_coordinator_only_through_advance`, which
  requires exactly one `.advance(` in `runtime.py`.
- `test_phase_06b1_temporal.py` `_truncate` also truncates the log.

## Checks (non-DB; no `PROXYLOOP_TEST_*` set)

- Passed: focused `test_persisted_claim_and_traces.py`,
  `test_phase_04b_model_runtime.py`, and `test_slow_refresh_strategy_expiry.py`
  (65 passed).
- Passed: `tests/integration tests/contract` (849 passed, 56 skipped). The
  skips are 51 before plus the 5 new DB-gated items.
- Passed: `make lint`, `make typecheck` (66 and 59 source files, no issues),
  and `make format-check`.
- Passed: `make test` (exit 0: runtime 1257 passed, 56 skipped; ml 397 passed,
  1 skipped; negotiation gate current).
- No committed `*-check` artifact changed bytes (`git status` shows only the
  owned files).
- Passed: `make preflight` (exit 0: runtime 1257 passed, 56 skipped; ml 397
  passed, 1 skipped; web 140 passed; lock, compileall, and compose config
  clean). This branch has no gated-skip pin (PR-1 has not merged). With PR-1's
  pin, the count is +5 over the pinned 51.

## Real-dependency gates, early run (branch @ `5e483db`, base `c73f6a7`, before the PR-4 merge)

The root granted the DB lane exclusively. The gates ran serially against the
Compose `postgres-test` (`localhost:55432/proxyloop_test`) and Temporal
`127.0.0.1:7233`, with the variables on the make command line only:

- Passed: `make postgres-check` (32 passed, 0 skipped; includes G6 and G7).
- Passed: `make phase05a-check` (42 passed; replay tests unchanged).
- Passed: `make phase06b1-check` (35 passed).

No fixes were needed. These gates run again after `git merge origin/main`
once PR-4 has landed.

## Review follow-ups (independent review: Approve; root accepted M1–M6)

The artifact is `harness/code_review/fix-r12-model-trace-log.md`. These
follow-ups were made without the DB.

- M1: the backfill reads `COALESCE(payload->'model_traces', '[]'::jsonb)`, so
  a version 2 row with no traces key migrates with no traces. A present
  non-array value, including JSON `null`, still stays version 2. New DB-gated
  test `test_postgres_bootstrap_migrates_a_v2_row_without_a_traces_key`
  (written, not run).
- M2: the backfill copies inline traces without validating them. A version 2
  row that used to fail closed only because an inline trace was invalid or
  foreign now reads as a Case, while `list_model_traces` fails closed on that
  trace. The tamper signal moves from the Case read to the log read, as the
  spec intends. Also recorded in `docs/architecture.md`.
- M3: the G8 text guard also requires one `.advance`, one `._coordinator(`,
  and one `CaseCoordinator(`, and no `.decide(` or `.reason(` in `runtime.py`.
- M4: `test_postgres_trace_log_error_suppresses_driver_cause[append|list]`
  (DB-free) covers the mapping of `psycopg.Error` to `StorageUnavailableError`.
- M5: `test_an_approval_that_does_not_execute_leaves_the_log_as_issued[rejected|expired]`.
- M6: the R2 refresh trace asserts `result`: `SUCCEEDED` for
  `_SameRevisionSlow` (the coordinator accepts it and the Runtime refuses it,
  I11) and `REJECTED` for `_ExpiredStrategySlow`.

Checks after the follow-ups (no `PROXYLOOP_TEST_*` set):

- Passed: `make lint`, and `make typecheck` (66 and 59 files).
- Passed: `make test` (exit 0: runtime 1261 passed, 57 skipped; ml 397 passed,
  1 skipped; negotiation gate current).
- Passed: `make preflight` (exit 0: the same counts, plus web 140 passed).
- There are now 6 new DB-gated items (57 skipped = 51 + 6), so PR-1's
  gated-skip pin moves by +6.
- Not run: the DB gates. The early run above predates M1; all three gates run
  again after the PR-4 merge.

## Notes for PR-8

- M7: `create_case` on an existing Case runs Slow and appends a `SUCCEEDED`
  Slow trace before it fails with `CaseConflictError` (I6: log before acting).
  A per-turn Fast/Slow split read from `list_model_traces` must not count it
  as a turn.

## Merge with `main` @ `74fb993` (PR-4 R-18, #87, #89) and final gates

Merge commit `03a6ca9`. `postgres_repository.py` merged cleanly. R-18's
`_verify_delivery_callback_pairs` (called from `_reconstruct_provider`) and
this branch's v3 envelope, bootstrap lock, backfill, and log methods touch
separate regions. Both behaviours are kept. The status file conflicted only
in the §0 in-flight table: both rows are kept (PR-6 from `main`, PR-7 here).

Checks on the merged tree, run serially with the DB lane held exclusively and
the variables on the make command line only:

- Passed: `make test` (exit 0: runtime 1285 passed, 59 skipped; ml 397 passed,
  1 skipped; negotiation gate current).
- Passed: `make postgres-check` (35 passed, 0 skipped). This includes G6, G7,
  the M1 no-key backfill, and the M4 error mapping.
- Passed: `make phase05a-check` (53 passed).
- Passed: `make phase06b1-check` (35 passed).
- Passed: `make preflight` (exit 0, variables unset: runtime 1285 passed, 59
  skipped; ml 397 passed, 1 skipped; web 140 passed). Six of the 59 skips are
  this branch's new DB-gated items.
