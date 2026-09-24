# Fix log: synchronous Runtime calls leave the event loop (B2-8, PR-6)

Finding: `harness/code_review/repo-audit-B2.md` B2-8. Plan row:
`harness/context/build-plan-to-complete.md` PR-6.
Branch `fix/b2-8-threadpool-runtime-calls` from `main` @ `c73f6a7`.

## What changed

`runtime/services/api/src/proxyloop_api/app.py` and `direct_expiry.py`.
Every synchronous Runtime, storage, or model call inside an `async def`
handler or the direct-mode expiry timer now runs via
`fastapi.concurrency.run_in_threadpool` (FastAPI's re-export of Starlette's;
Starlette is not a declared direct dependency of the API package):

- `apply` (direct mode): the clock read, the direct-mode clock guard, and
  `service.apply_command` run in one worker-thread call (`apply_direct`)
  under one per-app `threading.Lock` (review follow-up I1, below), so direct
  commands stay serialized in the process as they were on the loop; the
  lock is taken inside the worker thread, so the loop stays free. Lock
  order: this lock, then the Runtime's per-Case lane.
  `DirectApprovalExpiry.observe` stays on the loop because it creates an
  asyncio task. The Temporal branch still awaits the async Temporal client
  on the loop.
- `create_case`, `append_event`, `decide_approval`: `service.current_result`
  (a repository read, PostgreSQL in postgres mode).
- `health_ready`: `check_readiness` (the PostgreSQL probe);
  `temporal_client.check_readiness()` stays awaited on the loop.
- `local_mailbox_event`: `reserve_channel_event` and `repository.get`
  (PostgreSQL); `temporal_client.apply_command` stays on the loop.
- `direct_expiry.py` `_expire`: `runtime.apply_command` for
  `EXPIRE_APPROVAL`. It takes only the Runtime lane, not the app lock: it
  never reads the API clock guard (the time is `approval.expires_at`), and
  it pins `expected_revision` to the receipt that armed it, so it cannot
  land between another command's guard read and write without failing its
  pin; a command that lands after it finds the approval terminal
  (`runtime.py:1115-1116`, 409 `case_conflict`). No lock-order inversion.
- `health_live` is now `async def`: `liveness_payload` does no I/O, so
  liveness no longer needs a threadpool slot.

`get_case` stays a `def` handler (FastAPI runs it in the threadpool). Status codes, error bodies, correlation-id logging, and
`Idempotency-Key` handling are unchanged: `run_in_threadpool` re-raises the
original exception object, so the same exception handlers map it.

## Thread safety of the shared objects

- `InMemoryCaseRepository` guards every method with an `RLock`
  (`repository.py:153-188`, docstring "Thread-safe").
- `PostgresCaseRepository` opens a fresh connection per operation
  (`postgres_repository.py:202-207`, `_connect` at `:880`); no connection is
  shared across threads.
- `ThinAgentRuntime` serializes each Case through a per-Case `RLock` lane
  (`runtime.py:218-219`, `_lane` at `:1677`; used by every mutating path);
  the coordinator and capability executor hold their own `RLock`s.
- The Temporal worker already calls `adapter.apply_command` through
  `asyncio.to_thread` (`workflow_worker/activities.py:277, 289, 312, 317`),
  so the same Runtime is already driven from worker threads in production
  shape.

## Red / green

New `tests/integration/test_api_event_loop.py`.

Event loop: a repository whose `create` blocks (bounded at 10 s) until
released; `POST /cases` is started, and once the
call is inside the repository `GET /health/live` must be served while the
call is still blocked.

- Red on `main` (`app.py` unchanged): `AssertionError: the event loop
  waited for the blocking call`; the operation log shows `create_case`
  latency 1009 ms and `health_live` recorded after it.
- Green on the branch: 1 passed.

Direct-command race (review follow-up I1), parametrized `advancing` and
`equal` clock: after `POST /cases`, with approval creation suppressed
(`offer_compliance_violations_for_case` patched to report a violation, so a
second event reaches the time path), event A parks right after its guard's
repository read; event B runs for up to 1 s; then A is released. Asserts:
every response is 200 or 409 `{"detail": "case_conflict"}`, at least one is
200, and stored event times are strictly increasing.

- Red with the lock-free `app.py` (`e514754`): `advancing` fails with 500
  `internal_error` (A's earlier time reaches the snapshot validator);
  `equal` fails with two stored events at 13:00:00 (equal times accepted).
- Green with the lock: 3 passed, five consecutive runs.

## Checks

After the review follow-ups (current diff):

- `make lint`: exit 0. `make typecheck`: exit 0.
- `make test`: exit 0. Runtime tests 1254 passed, 51 skipped (DB and
  Temporal gated); ML tests 397 passed, 1 skipped; every artifact gate
  green.
- `make preflight`: exit 0 (same Python counts; Web 140 passed).
- DB gates at `3c88fc2` (lane held exclusively, serial, variables on the
  make command line only, same values as below): `make postgres-check`
  exit 0, 27 passed; `make phase05a-check` exit 0, 42 passed;
  `make phase06b1-check` exit 0, 35 passed.

Before the review, on `e514754`: `make lint`, `typecheck`, `test`,
`preflight` exit 0; DB lane held exclusively, serial, variables on the make
command line only (`PROXYLOOP_TEST_DATABASE_URL` = the Compose
`postgres-test` database on `127.0.0.1:55432/proxyloop_test`,
`PROXYLOOP_TEST_TEMPORAL_ADDRESS=127.0.0.1:7233`): `make postgres-check`
27 passed, `make phase05a-check` 42 passed, `make phase06b1-check` 35
passed.

Independent review: `harness/code_review/fix-b2-8-threadpool-runtime-calls.md`.

## Known limits

1. **In-process race: closed.** Before the lock, `apply_direct` (clock
   read, guard read, `apply_command` with that explicit `occurred_at`) ran
   outside the Runtime lane in worker threads, so a stale guard read let a
   strictly earlier time reach the `CaseContextSnapshot` validator
   (`contracts.py:1211-1213`) and end in 500 `internal_error`, and let an
   equal time through (the validator only rejects strictly earlier times).
   The per-app lock restores the serialization the single event loop gave
   on `main`; the regression test above pins both cases.
2. **Cross-process gap: remains, documented.** With several uvicorn workers
   (or API replicas) in direct mode on PostgreSQL, each process has its own
   lock, so two processes can still interleave the guard for one Case, as
   they could on `main`. A strictly earlier time then fails closed: the
   Runtime raises `pydantic_core.ValidationError` (a `ValueError`) before
   any repository write, no exception handler maps it, and the middleware
   catch-all answers **500 `{"detail": {"code": "internal_error",
   "message": "internal operation failed safely"}}`** with the
   correlation-id header; nothing is stored. An equal time across processes
   is accepted. A command pinning `expected_revision` gets 409
   `{"detail": "stale_cas"}` instead. Temporal mode serializes commands per
   Case in the Workflow and is not affected.
3. **Process-wide lock (re-review M1).** The direct-command lock is not
   per Case: a slow model call on Case X delays commands on Case Y, and each
   queued command holds one of the 40 threadpool slots. Command throughput
   equals `main`'s (where the event loop serialized every command); reads
   and liveness are strictly better. A per-Case lock is not needed now.
4. **Count-bounded settle (re-review M2).** `_settle` in
   `tests/integration/test_direct_mode_command_path.py:100-105` polls for at
   most 200 `sleep(0)` iterations; with the expiry in a worker thread it
   depends on thread scheduling. It passed 25/25 idle and 25/25 under load;
   switch to a time-based wait if it ever flakes.
