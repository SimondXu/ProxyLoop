# PR-7 Review: append-only model-trace log at `storage_version` 3 (R-12, R-13b)

**Target**: `fix/r12-model-trace-log` @ `068225f` (base `main` @ `c73f6a7`, not
yet merged with PR-4)

**Spec**: `harness/context/r12-model-trace-log-design.md`

**Reviewer**: independent read-only `reviewer` subagent. The root orchestrator
relayed the findings, and the implementer wrote this artifact.

**Decision**: Approve. There are no Blocking or Important findings. The root
accepted Minors M1–M6 for this PR and deferred M7 to PR-8.

## Findings and disposition

### M1: a version 2 row with no `model_traces` key was stranded

**Severity**: Minor. **Disposition**: fixed.

`_backfill_inline_traces` skipped a version 2 row whose `payload->'model_traces'`
was SQL NULL, so the row stayed "unsupported" forever. The version 2 envelope
on `main` defaulted a missing key to `()`. The backfill now selects
`COALESCE(payload->'model_traces', '[]'::jsonb)`: a missing key migrates with
no traces, and the row is rewritten as version 3. A present non-array value,
including JSON `null`, is still left as version 2 and fails closed on read.
The new DB-gated test is
`test_postgres_bootstrap_migrates_a_v2_row_without_a_traces_key`.

### M2: the backfill moves the tamper signal from the Case read to the log read

**Severity**: Minor. **Disposition**: documented.

The backfill copies inline traces without validating them. A version 2 row that
used to fail closed only because an inline trace was invalid or foreign now
reads as a Case, while `list_model_traces` fails closed on that trace. This is
what the spec intends. It is recorded in `docs/architecture.md` and in the
execution log.

### M3: the G8 source guard was too narrow

**Severity**: Minor. **Disposition**: fixed.

`test_the_runtime_calls_the_coordinator_only_through_advance` now also requires
exactly one `.advance`, one `._coordinator(`, and one `CaseCoordinator(`, and
zero `.decide(` and `.reason(` in `runtime.py`. A comment states that this is a
text guard.

### M4: storage-error mapping of the log methods was untested

**Severity**: Minor. **Disposition**: fixed.

`test_postgres_trace_log_error_suppresses_driver_cause[append|list]` is DB-free
and uses the `__new__` plus failing `_connect` pattern. It checks that a
`psycopg.OperationalError` surfaces as `StorageUnavailableError("PostgreSQL
model trace operation failed")`, with no driver cause and no secret.

### M5: reject and expire coverage was lost with the replaced tests

**Severity**: Minor. **Disposition**: fixed.

`test_an_approval_that_does_not_execute_leaves_the_log_as_issued[rejected|expired]`
restores the deleted `test_traces_survive_an_approval_that_does_not_execute`
cases against the log.

### M6: the R2 assertion on the refused refresh trace was weak

**Severity**: Minor. **Disposition**: fixed.

`reason_codes is not None` is replaced by an assertion on `result`.
`_SameRevisionSlow` passes the coordinator and is refused by the Runtime, so it
must be `SUCCEEDED` (I11). `_ExpiredStrategySlow` must be `REJECTED`.

### M7: a re-create on an existing Case logs a Slow trace

**Severity**: Minor. **Disposition**: deferred to PR-8.

`create_case` on an existing Case runs Slow, appends a `SUCCEEDED` Slow trace,
and only then fails with `CaseConflictError`. This follows from I6 (log before
acting). PR-8's per-turn Fast/Slow split must not count it as a turn. The note
is in the execution log.

## Final gate

After M1–M6, `make lint`, `make typecheck`, `make test`, and `make preflight`
passed locally. Results are in `harness/log/fix-r12-model-trace-log.md`. The DB
gates run again after `origin/main` (with PR-4) is merged in.
