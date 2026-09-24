# Fix log: synchronous Runtime calls leave the event loop (B2-8, PR-6)

Finding: `harness/code_review/repo-audit-B2.md` B2-8. Plan row:
`harness/context/build-plan-to-complete.md` PR-6.
Branch `fix/b2-8-threadpool-runtime-calls` from `main` @ `c73f6a7`.

## What changed

`runtime/services/api/src/proxyloop_api/app.py` only. Every synchronous
Runtime, storage, or model call inside an `async def` handler now runs via
`fastapi.concurrency.run_in_threadpool` (FastAPI's re-export of Starlette's;
Starlette is not a declared direct dependency of the API package):

- `apply` (direct mode): the clock read, the direct-mode clock guard, and
  `service.apply_command` run in one worker-thread call (`apply_direct`);
  `DirectApprovalExpiry.observe` stays on the loop because it creates an
  asyncio task. The Temporal branch still awaits the async Temporal client
  on the loop.
- `create_case`, `append_event`, `decide_approval`: `service.current_result`
  (a repository read, PostgreSQL in postgres mode).
- `health_ready`: `check_readiness` (the PostgreSQL probe);
  `temporal_client.check_readiness()` stays awaited on the loop.
- `local_mailbox_event`: `reserve_channel_event` and `repository.get`
  (PostgreSQL); `temporal_client.apply_command` stays on the loop.

`get_case` and `health_live` were already `def` handlers (FastAPI runs them
in the threadpool). Status codes, error bodies, correlation-id logging, and
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

New `tests/integration/test_api_event_loop.py`: a repository whose `create`
blocks (up to 1 s) until released; `POST /cases` is started, and once the
call is inside the repository `GET /health/live` must be served while the
call is still blocked.

- Red on `main` (`app.py` unchanged): `AssertionError: the event loop
  waited for the blocking call`; the operation log shows `create_case`
  latency 1009 ms and `health_live` recorded after it.
- Green on the branch: 1 passed.

## Checks

- `make lint`: exit 0 ("All checks passed!", `git diff --check` clean).
- `make typecheck`: exit 0 (mypy "Success: no issues found").
- `make test`: exit 0. Runtime tests 1252 passed, 51 skipped (DB and
  Temporal gated); ML tests 397 passed, 1 skipped; every artifact gate
  through `negotiation-check` green.
- `make preflight`: exit 0 (same Python counts; Web 140 passed).
- DB lane (held exclusively, serial, variables on the make command line
  only: `PROXYLOOP_TEST_DATABASE_URL` = the Compose `postgres-test`
  database on `127.0.0.1:55432/proxyloop_test`,
  `PROXYLOOP_TEST_TEMPORAL_ADDRESS=127.0.0.1:7233`):
  `make postgres-check` exit 0, 27 passed; `make phase05a-check` exit 0,
  42 passed; `make phase06b1-check` exit 0, 35 passed.
- Not done here: independent review.

## Known limits

Root decision (option (a)): accepted and documented, not changed.

1. **Direct-mode clock-guard race.** `apply_direct` reads the clock, reads
   the Case (`repository.get`), and then calls `apply_command` with that
   explicit `occurred_at`; the guard runs outside the Runtime's per-Case
   lane. Before this change the sequence was atomic only because every
   direct command ran synchronously on the one event loop. Now a command
   whose guard read is stale can carry an `occurred_at` earlier than an event
   another command appended in between. The same window already exists
   across processes (several uvicorn workers on PostgreSQL).
2. **It fails closed.** Building the next snapshot runs the
   `CaseContextSnapshot` validator, which rejects a timestamp earlier than
   its predecessor (`contracts.py:1211-1213`, "visible event timestamps
   must be ordered"; equal timestamps pass). The Runtime raises before any
   repository write, so nothing out of order is stored (scratch probe:
   revision and event list unchanged).
3. **What the client gets** (scratch probes against this branch, not
   committed; the `app.py` mapping is unchanged):
   - When the race reaches the validator, the Runtime raises
     `pydantic_core.ValidationError` (a `ValueError`). No exception handler
     maps it, so `observe_operation`'s catch-all answers
     **500 `{"detail": {"code": "internal_error", "message": "internal
     operation failed safely"}}`**, with operation `error_category`
     `internal_error` and the correlation-id header. Reproduced by an
     event whose guard read ran before `POST /cases` (guard saw no Case,
     event time 12:00:10 < creation 12:00:20).
   - With the scripted adapters the two-event form of the race does not
     reach the validator: the first event leaves an approval pending, so the
     late command is refused in the lane with "case is awaiting approval"
     and gets **409 `{"detail": "case_conflict"}`** (reproduced). With a
     model Fast turn that does not gate the Case, the two-event form would
     take the 500 path above (inferred, not reproduced).
   - A command that pins `expected_revision` gets 409
     `{"detail": "stale_cas"}` as before.
4. **Out of scope:** `direct_expiry.py` `_expire` still calls
   `runtime.apply_command` on the event loop when a direct-mode approval
   timer fires (not an `app.py` call), so an expiry blocks the loop for one
   Runtime call.
