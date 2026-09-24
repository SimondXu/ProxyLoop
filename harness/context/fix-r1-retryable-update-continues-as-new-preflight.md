# Fix: a retryable Update failure rolls the run so its identical retry reaches the Runtime (R-1, R-1b)

Backlog items R-1 and R-1b in `harness/context/audit-remediation-status.md` §4a.
Branch `fix/r1-retryable-update-continues-as-new` from `main` @ `14d3fcf`.

## Defect (observed on main)

- **R-1.** Temporal caches an Update's outcome per Update ID for the rest of
  the run, and the Update ID binds the command id and the request
  fingerprint (#62). When the Runtime activity exhausts its five retryable
  attempts (`storage_unavailable` → client category `temporal_unavailable`,
  about 15 s), the identical retry is answered from that cache in ~0 s with no
  new activity until the run happens to Continue-As-New. The Web's "safe retry
  preserved" copy is therefore untrue within a run, and an approval whose final
  write exhausted stays `pending_execution` because its own identical retry
  never reaches the Runtime.
- **R-1b (pre-existing).** When the Continue-As-New threshold is reached while
  another Update is queued on the command lock, both `wake_changed`
  predicates in `run()` return True on `_continue_requested` while
  `_active_handlers > 0` forbids Continue-As-New, so the Workflow task spins
  (`TMPRL1101 Potential deadlock`) and both commands hang. R-1's fix would make
  this state common.

## Decision (root): option (f) plus the R-1b fix, one PR

On a retryable activity exhaustion the Update still fails with
`temporal_unavailable`, and the run requests Continue-As-New; the new run's
Update cache is empty, so the identical retry reaches the Runtime, whose
receipt and execution-claim rules decide. Non-retryable failures stay cached
(#62's T2 unchanged). Alternatives (a)–(e) and (g) stay rejected as recorded
in §4a, among them (a) keep the Update open and retry, (b) a non-failing
"retry later" result, (c) an attempt salt, (d) a larger retry budget, and (g)
a random Update ID per request (kept only as a fallback; it drops Update-level
dedup and reverses #62's T2).

## Exact change (`runtime/services/workflow_worker/src/proxyloop_workflow_worker/workflow.py` only)

Client, models, activities, API and Web are unchanged.

1. `_can_continue_as_new()` = `_continue_requested and _active_handlers == 0
   and not _activity_in_flight`; used by `run()`'s Continue-As-New check and by
   both `wake_changed` predicates (R-1b; no patch gate, since the old and new
   predicates differ only in states that spin).
2. `apply_case_command`, inside the lock: when `_execute_command` raises
   `ActivityError` whose server-reported `retry_state` is
   `MAXIMUM_ATTEMPTS_REACHED` or `TIMEOUT` and
   `workflow.patched("retryable-update-failure-continues-as-new")`,
   `_continue_requested = True`; the error is re-raised. Everything else
   (`NON_RETRYABLE_FAILURE`, cancellation, unset) does not roll.
   *Amended by root decision after the first implementation:* the design's
   original classifier, `_expiry_failure_category` (innermost typed
   `ApplicationError`), misclassifies every real activity failure, because
   `activities.py` raises `from exc` and the innermost error is the converted
   Python cause (`non_retryable=False`). It rolled on `case_conflict` and broke
   #62's T2 and the non-retryable expiry test. `_expiry_failure_category` and
   the expiry path are unchanged (the latent expiry misclassification is
   backlog R-16).
3. Both success paths (`apply_case_command`, `_expire_pending`) keep a pending
   request: `_continue_requested = _continue_requested or (_commands_in_run >=
   _continue_as_new_after)`. Without `or`, a queued command's success clears
   the flag and the retry still hits the cache.
4. The `update_id_for_command` docstring states that a retryable failure rolls
   the run.

## Tests (`tests/integration/test_phase_05a_temporal_workflow.py`)

Tests first, recorded red on `main`'s `workflow.py`. T1–T4 are live
(Compose PostgreSQL test DB + Temporal, ~16 s each where the backoff runs);
T5 needs neither and runs in `make test`.

- T1: identical append retry after exhaustion reaches the Runtime (6
  attempts, `applied`, run id changed).
- T2: identical approval retry finishes a claim whose final write exhausted
  (`pending_execution` before; `terminal`, `execution_count == 1`, one
  confirmation after).
- T3: exhaustion while another command is queued: the queued command
  succeeds, then A's identical retry reaches the Runtime (`case_conflict`).
- T4: `continue_as_new_after=2`, a held command X and a queued Y: both
  complete and the run rolls (hangs on `main`; bounded by `asyncio.wait_for`).
- T5: a Replayer test over a history recorded on `main` ("exhaustion, then a
  success in the same run"): it replays on the patched code, and with
  `workflow.patched` forced to True it fails with `NondeterminismError`
  ("Continue as new workflow machine does not handle this event").
- T6 (HTTP 503 then 200 with the same Idempotency-Key): optional, not added.

## Risks carried

- Delayed roll while other handlers run: the roll waits for every handler and
  activity to finish, so any number of retries arriving before then receive
  the cached failure for as long as other handlers stay active (for example
  another handler exhausting its ~15 s of retries, or a continuous Update
  stream).
- The expiry backoff (`_expiry_failures`, `_expiry_retry_at`) is run-local and
  resets on every roll (the P0-3 limit, now more frequent).
- Each roll also resets `_expiry_abandoned_for`, so an expiry abandoned after
  a non-retryable failure is attempted once more in the new run.
- One extra run per exhaustion (history and a new first Workflow task).
