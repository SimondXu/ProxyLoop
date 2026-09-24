# PR-6 (B2-8) synchronous Runtime calls off the event loop — independent review

Reviewer: project `reviewer` agent, read-only, not the session that wrote
the diff. Findings and decisions as relayed by the root orchestrator to the
implementer; the reviewer's reproduction script is
`rev-pr6/race_noapproval.py` in the session scratchpad (not committed).
Diff reviewed: `fix/b2-8-threadpool-runtime-calls` @ `67cdca10` vs `main`
@ `c73f6a7`.

**Verdict: Approve, with one Important finding.** All items addressed; see
disposition below.

## Findings and disposition

| # | Severity | Finding | Disposition |
|---|---|---|---|
| I1 | Important | Moving `apply_direct` into worker threads removed the in-process serialization the event loop gave direct commands. The clock guard (clock read, `repository.get`, `apply_command` with an explicit `occurred_at`) runs outside the Runtime lane, so two concurrent direct events on one Case, with no approval in between, can (a) carry a strictly earlier time into the snapshot validator, which ends in 500 `internal_error`, or (b) store two events with equal timestamps, which defeats the strict-advance guard. Reproduced by the reviewer with approval creation suppressed | Fixed (root decision): one `threading.Lock` per app guards the whole `apply_direct` body; lock order app lock, then Runtime lane; the expiry path takes the lane only. Regression test `test_concurrent_direct_events_keep_event_times_strictly_increasing` (`advancing`, `equal`) is red without the lock (500; equal times stored) and green with it |
| F2 | Follow-up (root decision) | `direct_expiry.py` `_expire` still called `runtime.apply_command` on the event loop | Fixed: `await run_in_threadpool(...)`. It needs no app lock: it never reads the API clock guard (time is `approval.expires_at`), pins `expected_revision`, and a later command finds the approval terminal (409 `case_conflict`) |
| F3 | Follow-up (root decision) | `BLOCK_TIMEOUT_SECONDS = 1.0` in `test_api_event_loop.py` is tight: on a slow runner the blocked call could time out and finish before the sibling request is checked (rationale as understood by the implementer) | Fixed: 10.0; the green path releases explicitly, so it costs nothing |
| F4 | Follow-up (root decision) | `health_live` was a `def` handler, so liveness competed for the 40-thread pool although `liveness_payload` does no I/O | Fixed: `async def` |
| F5 | Follow-up (root decision) | The log described the race as open and accepted | Fixed: the log's Known limits now record the in-process race as closed and keep the cross-process gap (several uvicorn workers on PostgreSQL: a strictly earlier time still fails closed with 500 `internal_error` and no write; an equal time is accepted) |

## Residual accepted

The cross-process gap above is accepted and documented. Implementer's note:
closing it would need the guard inside the Runtime lane or storage (a
`runtime.py` change, currently PR-7's file), not an API change.
