# Fix log: a redelivered channel event re-drives an exhausted delivery (R-17); a stale route revision is retried once (R-5)

Spec and root decisions: `harness/context/fix-r17-r5-channel-redrive-preflight.md`.
Branch `fix/r17-r5-channel-redrive` from `main` @ `5266b6d`, fast-forwarded to
`origin/main` @ `0eb3079` (#89, B2-8) before any `app.py` edit.

## What changed

- `runtime/services/api/src/proxyloop_api/app.py` (`local_mailbox_event` and
  three module helpers):
  - `_channel_command_request(event, inbox, expected_revision)`: pure; the
    first dispatch and the re-drive both build the command here.
  - `_redrive_request(repository, event, inbox, prior)`: for an
    `INGEST_CHANNEL_EVENT` receipt with a `delivery_id` whose outbox state is
    in `REDRIVABLE_OUTBOX_STATES`, returns the candidate request (over
    `expected_revision` ∈ {`prior.before_revision`, `None`}) whose
    `semantic_fingerprint()` equals the receipt's; otherwise `None` (answer
    from the receipt, as before). Runs in the threadpool.
  - A re-drive is sent once; its response always carries
    `deduplicated=True`; its failure is returned as is.
  - R-5: on `TemporalDispatchError("channel_conflict")` the route re-reads the
    Case and re-sends once with the advanced revision only when
    `inbox.command_id` still has no receipt and the revision has advanced;
    otherwise it re-raises unchanged. At most 2 dispatches per request.
  - `_find_receipt` replaces the inline receipt lookup (used twice).
- `runtime/services/workflow_worker/src/proxyloop_workflow_worker/activities.py`:
  `REDRIVABLE_OUTBOX_STATES` (the set the delivery activity sends; the route
  imports it, no second copy). After review I-1 the activity always looks up
  before sending (every attempt and outbox state) and sends only when the
  lookup finds nothing; the first version looked up only when
  `activity_attempt > 1 or outbox.state != "pending"`.
  `__init__.py` exports the constant lazily.
- `workflow.py`, the Temporal client, models, the Runtime, the repository, and
  `update_id_for_command` are unchanged. No Workflow command changes, so no
  patch gate or replay fixture.
- `docs/architecture.md` (`local_mailbox` paragraph) and §4a of
  `harness/context/audit-remediation-status.md`: the re-drive, the R-5 retry,
  the always-lookup rule, and the residual `TIMEOUT` concurrency risk.

## Tests

`tests/integration/test_phase_06b1_channel_runtime.py` (no DB; `make test`
unless marked):

- `_ChannelRepository` gains `record_delivery_observation` (test seam).
- Racing-duplicate edit:
  `test_local_mailbox_api_duplicate_racing_first_dispatch_is_deduplicated`'s
  fake now runs the real `CaseCommandActivityAdapter.dispatch_channel_delivery`
  with `LocalMailboxAdapter` after the ingest, so the outbox is `accepted`
  and the duplicate has nothing to re-drive; it also asserts the outbox state.
- R17-T1 `test_local_mailbox_redelivery_redrives_an_exhausted_delivery`
  (identical request, fingerprint equals the receipt's).
- `test_local_mailbox_redrive_response_is_always_deduplicated`.
- `test_local_mailbox_redrive_failure_is_not_retried_in_route`.
- R17-T2 `test_local_mailbox_duplicate_of_settled_delivery_is_not_redriven`
  [accepted, delivered, bounced, failed_terminal].
- `test_local_mailbox_redrive_falls_back_when_no_fingerprint_matches`.
- R5-T1 `test_local_mailbox_stale_revision_is_retried_with_the_fresh_revision`;
  `test_local_mailbox_stale_revision_retry_is_bounded` (2 dispatches, 409).
- R5-T2 `test_local_mailbox_conflict_without_revision_change_is_not_retried`.
- R5-T3 `test_local_mailbox_delivery_conflict_after_ingest_commit_is_not_retried`.
- M-2 `test_local_mailbox_unavailable_dispatch_is_not_retried_after_case_moved`
  (1 dispatch, 503).
- `test_time_skipping_identical_ingest_redrives_exhausted_delivery`
  (**gated** on `PROXYLOOP_TEST_TEMPORAL_ADDRESS`, runs in `phase06b1-check`;
  review I-3): the scratch probe as a test (process-local time-skipping
  server, in-memory repository whose observation write fails until switched
  on; about 15 s of real activity backoff). `_CountingMailboxAdapter` counts
  `send` and `lookup`; the test asserts the outbox ends `accepted` after
  exactly one `send` (review I-2).

`tests/integration/test_phase_06b1_workflow_worker.py` (no DB):
`test_outbox_looks_up_before_sending_on_first_attempt`
[pending, unknown, failed_retryable] and
`test_redrivable_outbox_states_are_the_ones_the_activity_sends`.

`tests/integration/test_phase_06b1_temporal.py` (DB + Temporal): R17-T3
`test_live_temporal_mailbox_redelivery_redrives_exhausted_delivery`.

`scripts/check_gated_skips.py` pin and `docs/development.md`: channel
runtime 1 → 2, 06B1 temporal 3 → 4, total 53 → 55.

## Red → green

First pass (no DB, no `PROXYLOOP_TEST_*`): new tests with `main`'s `app.py`
and `activities.py` (before any source edit): 8 failed, 34 passed, 5 skipped.

| Test | Red | Green |
|---|---|---|
| R17-T1 | `assert 1 == 2` dispatches | pass |
| re-drive `deduplicated=True` | `assert 1 == 2` dispatches | pass |
| re-drive failure not retried | `assert 200 == 503` (answered from the receipt) | pass |
| R5-T1 | `assert 409 == 200` | pass |
| R5 retry bounded | `assert 1 == 2` dispatches | pass |
| lookup-first [unknown], [failed_retryable] | `assert 0 == 1` lookups | pass |
| constant | `ImportError` (no `REDRIVABLE_OUTBOX_STATES`) | pass |
| R17-T2 ×4, fingerprint fallback, R5-T2, R5-T3, racing edit | pass (guards) | pass |

Review round (I-1/I-2): the time-skipping test with separate counters, run
against the first-pass `activities.py` (`PROXYLOOP_TEST_TEMPORAL_ADDRESS` set
on the command line, DB lane held): FAIL `assert 2 == 1` (`send_calls`): the
re-drive's attempt 1 on the still-`pending` outbox sent again although
attempt 1 of the first activity had sent and failed to record. After the
always-lookup change: pass (non-DB 06B1 files plus that test: 48 passed,
1 skipped). M-2's test passes on both (guard).

## Checks

First pass, on `64ace73` + merge `3343609` (`main` @ `74fb993`, #88):

- Passed: `make test` (runtime 1291 passed, 54 skipped; ml 397 passed,
  1 skipped).
- Passed, serially, variables on the make command line only
  (`127.0.0.1:55432/proxyloop_test`, Temporal `127.0.0.1:7233`):
  `make postgres-check` 27 passed; `make phase05a-check` 53 passed;
  `make phase06b1-check` 52 passed, 0 skipped (includes R17-T3).

Final, after the review changes and merge `8a883ed` (`main` @ `f4a2487`,
#90):

- Passed: `make format-check`, `make lint`, `make typecheck` (exit 0).
- `make preflight` first failed only on the gated-skip pin (expected 53,
  found 55: channel runtime 1 → 2, 06B1 temporal 3 → 4); pin and
  `docs/development.md` updated. Then passed (exit 0; runtime 1301 passed,
  55 skipped; ml 397 passed, 1 skipped; vitest 140 passed; gated skips 55).
- Passed: `make test` (runtime 1301 passed, 55 skipped; ml 397 passed,
  1 skipped).
- Passed, serially: `make postgres-check` 27 passed; `make phase05a-check`
  53 passed; `make phase06b1-check` 54 passed, 0 skipped (includes R17-T3 and
  the time-skipping re-drive test).

After merging `main` @ `1573a42` (#91, v3 trace log; merge `6a4abce`; pin
kept from both sides: 04c 29, channel runtime 2, 06B1 temporal 4, total 61):

- Passed: `make test` (runtime 1311 passed, 61 skipped; ml 397 passed,
  1 skipped).
- Passed: `make preflight` (exit 0; runtime 1311 passed, 61 skipped; ml 397
  passed, 1 skipped; vitest 140 passed; gated skips 61).
- Passed, serially: `make postgres-check` 35 passed; `make phase05a-check`
  53 passed; `make phase06b1-check` 54 passed, 0 skipped (includes R17-T3
  and the time-skipping re-drive test).

Review: `harness/code_review/fix-r17-r5-channel-redrive.md` (Request
Changes, no Blocking; all findings applied).

## Known limits and risks

- The re-drive depends on the R-1 roll. A redelivery that arrives before the
  run rolls (another handler still active) gets the cached 503 again; a run
  in flight at deploy time that replayed an exhaustion without the R-1 patch
  does not roll on exhaustion, so a re-drive waits for the command-threshold
  roll.
- The only re-drive trigger is a sender redelivery. A sender that stops after
  one 503 leaves the outbox `pending`.
- The response's `delivery_status` is the stored receipt value (`pending`),
  not live outbox state, as on a first success.
- `unknown` / `failed_retryable` after a *successful* Update: the local
  adapter never records them, but if a future adapter does, the identical
  re-drive Update is a cached success within the run and re-drives nothing
  until the run rolls.
- Duplicate sends: the activity looks up before every send, so the residual
  is a send whose effect is not yet visible to `lookup`, e.g. a
  schedule-to-close `TIMEOUT` letting a retry or re-drive run while the
  timed-out attempt is still in flight (pre-existing, R-1 known limit).
- M-3: a known race still returns 409 for an event that did apply (the
  conflict and the receipt race; same as `main`); its redelivery gets 200.
- M-4: a duplicate now reads the outbox, so an outbox-read storage fault
  returns 503 where `main` returned 200; and a duplicate of an event whose
  first Update is still running waits on that in-flight Update instead of
  returning 200 at once.
