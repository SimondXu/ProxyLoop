# PR-6 (B2-8) synchronous Runtime calls off the event loop — independent review

Reviewer: project `reviewer` agent, read-only, not the session that wrote
the diff. Findings and decisions as relayed by the root orchestrator to the
implementer; the reviewer's reproduction script is
`rev-pr6/race_noapproval.py` in the session scratchpad (not committed).

- First review: code at `e514754` (`fix/b2-8-threadpool-runtime-calls`) vs
  `main` @ `c73f6a7`.
- Re-review: `e514754..3c88fc2` (the follow-up fixes below).

**Verdict: Approve, with one Important finding (first review); Approve, no
Blocking or Important findings (re-review at `3c88fc2`).** All first-review
items addressed; see disposition below.

## First review (`e514754`): findings and disposition

| # | Severity | Finding | Disposition |
|---|---|---|---|
| I1 | Important | Moving `apply_direct` into worker threads removed the in-process serialization the event loop gave direct commands. The clock guard (clock read, `repository.get`, `apply_command` with an explicit `occurred_at`) runs outside the Runtime lane, so two concurrent direct events on one Case, with no approval in between, can carry a strictly earlier time into the snapshot validator, which ends in 500 `internal_error`. Reproduced by the reviewer with approval creation suppressed. Under the default scripted configuration the losing side is refused earlier, in the lane, with "case is awaiting approval" (409 `case_conflict`) and never reaches the timestamp check. The 500 comes from the catch-all `except Exception` in `app.py`'s `observe_operation` middleware, which logs no exception, so operators had no diagnostic beyond the correlation id and category. A separate Minor, "equal timestamps bypass the strict-advance guard" (two events stored with the same time), is folded into I1 | Fixed (root decision): one `threading.Lock` per app guards the whole `apply_direct` body; lock order app lock, then Runtime lane; the expiry path takes the lane only. Regression test `test_concurrent_direct_events_keep_event_times_strictly_increasing` (`advancing`, `equal`) is red without the lock (500; equal times stored) and green with it |
| F2 | Minor | `direct_expiry.py` `_expire` still called `runtime.apply_command` on the event loop | Fixed: `await run_in_threadpool(...)`. It needs no app lock: it never reads the API clock guard (time is `approval.expires_at`), pins `expected_revision`, and a later command finds the approval terminal (409 `case_conflict`) |
| F3 | Minor | `BLOCK_TIMEOUT_SECONDS = 1.0` in `test_api_event_loop.py` is tight: on a slow runner the blocked call could time out and finish before the sibling request is checked (rationale as understood by the implementer) | Fixed: 10.0; the green path releases explicitly, so it costs nothing |
| F4 | Minor | `health_live` was a `def` handler, so liveness competed for the 40-thread pool although `liveness_payload` does no I/O | Fixed: `async def` |
| F5 | Minor | The log misstated the race: it said out-of-order events could be appended, but a strictly earlier time was rejected with 500 `internal_error` (nothing written) and only equal timestamps got in | Fixed: the log's Known limits now state those facts, record the in-process race as closed, and keep the cross-process gap (several uvicorn workers on PostgreSQL: a strictly earlier time still fails closed with 500 `internal_error` and no write; an equal time is accepted) |

Reviewer's checks (first review): `make lint`, `make typecheck`, 36 focused
tests passed, the event-loop test red on `main`, race reproduction scripts.

## Re-review (`e514754..3c88fc2`)

**Verdict: Approve.** No Blocking or Important findings. Two Minors, both
accepted and recorded as known limits in the log:

| # | Severity | Finding | Disposition |
|---|---|---|---|
| M1 | Minor | The direct-command lock is process-wide, not per Case: a slow model call on Case X delays commands on Case Y, and each queued command holds one of the 40 threadpool slots. Command throughput equals `main`'s (where the event loop serialized every command); reads and liveness are strictly better | Accepted; a per-Case lock is not needed now |
| M2 | Minor | `_settle` in `tests/integration/test_direct_mode_command_path.py:100-105` polls its condition for at most 200 `sleep(0)` iterations, a count bound rather than a time bound; with the expiry now in a worker thread, settling depends on thread scheduling. Passed 25/25 idle and 25/25 under load | Accepted; switch to a time-based wait if it ever flakes |

Reviewer's checks (re-review): `make lint`, `make typecheck`, 38 focused
tests passed; the race test 10/10 on the branch and red on the pre-lock
`app.py`; the expiry tests 50 runs, half under full CPU load.

Not run by the reviewer: full `make test` / `make preflight` and the DB
gates. The implementer ran them: `make test` and `make preflight` exit 0 on
the follow-up diff; `make postgres-check` 27, `make phase05a-check` 42,
`make phase06b1-check` 35 passed at `3c88fc2`.

## Residual accepted

The cross-process gap above is accepted and documented. Implementer's note:
closing it would need the guard inside the Runtime lane or storage (a
`runtime.py` change, currently PR-7's file), not an API change.
