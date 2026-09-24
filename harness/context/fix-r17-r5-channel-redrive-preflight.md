# Fix: a redelivered channel event re-drives an exhausted delivery (R-17); the channel route stops losing its first dispatch to a stale revision (R-5)

Backlog items R-17 and R-5 in `harness/context/audit-remediation-status.md`
§4a (build-plan PR-3). Branch `fix/r17-r5-channel-redrive` from `main` @
`5266b6d` (R-16), merged with `origin/main` @ `0eb3079` (#89, B2-8). Line
numbers below are on `0eb3079`, checked 2026-09-24. The defect sections are
observed (code and scratch probes); options and risks are proposals.

**Status: stopped after the spec.** R-17 has a recommended design that
changes no Workflow command. R-5 has no option free of trade-offs: the obvious
fix changes Update-ID dedup behaviour for channel events (§R-5). Root decides
R-5 (architect consult) before red tests and code.

## R-17: defect (reproduced on main)

Sequence for a Provider message:

1. `app.py:601` reserves the inbox (command id fixed per event), `app.py:661`
   dispatches `INGEST_CHANNEL_EVENT` through `TemporalCaseClient.apply_command`.
2. The Workflow runs the Case activity (`workflow.py:327-335`). The Runtime
   commits the Case transition, marks the inbox `applied`, and inserts the
   `pending` outbox in one transaction (`runtime.py:514`,
   `replace_with_channel_outbox`). The receipt carries
   `delivery_id` and `delivery_status="pending"` (`runtime.py:486-496`).
3. The Workflow then runs the delivery activity (`workflow.py:347-362`). When
   it exhausts its five retryable attempts (for example
   `channel_dependency_unavailable`), the Update fails. The client maps the
   failure to `channel_dependency_unavailable` (`client.py:129-151`), so the
   route answers 503. R-1 requests Continue-As-New because
   `retry_state == MAXIMUM_ATTEMPTS_REACHED` (`workflow.py:293-302`).
4. The sender redelivers the same event. `reserve` returns the applied inbox,
   the route finds the Case receipt for `inbox.command_id`, and returns it as
   `deduplicated` with HTTP 200 **without dispatching** (`app.py:606-618`).
   Nothing else ever schedules the delivery again, so the outbox stays
   `pending` indefinitely while the sender holds a 200.

The Workflow is not the gap. When an identical ingest Update reaches the
Workflow after the roll, the Runtime returns the stored receipt
(`runtime.py:236-240`, fingerprint checked), the receipt still carries
`delivery_id`, and `_execute_command` schedules the delivery activity again
(`workflow.py:347-362`). The delivery activity is idempotent over the stored
outbox (`activities.py:140-184`).

Evidence (scratch probes, not committed; no DB, no `PROXYLOOP_TEST_*`):

- Route, in-memory `_ChannelRepository` from
  `test_phase_06b1_channel_runtime.py` and a fake Temporal client that
  commits the ingest and then raises `channel_dependency_unavailable`: first
  POST `503 channel_dependency_unavailable`; redelivery `200`,
  `deduplicated: true`, `delivery_status: pending`; dispatches `1`; outbox
  `pending`.
- Workflow, time-skipping test server, the same in-memory repository with a
  `record_delivery_observation` that fails until switched on: first Update
  fails `channel_dependency_unavailable` after 15.0 s with 5 delivery
  attempts, outbox `pending`; the identical Update (same command id and body)
  then returns the deduplicated receipt, runs a 6th delivery attempt, and the
  outbox becomes `accepted`.

## R-17: options

- **A (recommended): the route re-dispatches the identical original request
  while the outbox is re-drivable.** In `local_mailbox_event`, when the
  prior receipt is an `INGEST_CHANNEL_EVENT` with a `delivery_id`, read the
  outbox (`get_outbox_record`, through `run_in_threadpool`). If its state is
  one the delivery activity would still send (`pending`, `failed_retryable`,
  `unknown`, the set at `activities.py:153`), rebuild the original request
  and dispatch it. Otherwise return the prior receipt as today. The original
  request is rebuilt from the event bytes, `inbox.command_id`, and the
  receipt. Its `expected_revision` is the candidate among
  `prior.before_revision` and `None` whose `semantic_fingerprint()` equals
  `prior.command_fingerprint`. If neither matches (not reachable today), the
  route returns the prior receipt as today. The Update ID therefore equals
  the failed one:
  - after the R-1 roll, the Update reaches the Workflow and re-drives
    delivery;
  - before the roll (another handler still active, or a run in flight at
    deploy time that replayed an exhaustion without the R-1 patch), the
    cached failure returns 503 again, and a later redelivery succeeds;
  - while the first dispatch is still running, the same Update ID attaches
    to the in-flight Update and returns its outcome.
  No `workflow.py`, client, model, Runtime, or repository change.
- **A′: re-dispatch every prior ingest receipt with a `delivery_id`**,
  without reading the outbox. It is simpler, but a duplicate of a
  `failed_terminal` delivery turns from 200 into 409 (the delivery activity
  raises `channel_conflict`), and every duplicate costs a Temporal round trip.
  Not recommended.
- **B: the Workflow owns delivery retry.** The ingest Update succeeds once
  the Case commits, and the Workflow retries delivery with its own backoff,
  carried across Continue-As-New in `CaseWorkflowInput`. The sender no longer
  needs to redeliver. This changes Workflow commands for recorded histories
  (a patch gate plus a replay fixture recorded on main, following R-1/R-16),
  adds carry state and a models change, and interacts with R-1's roll. It is
  larger than the finding asks ("re-driven on redelivery"). Not recommended
  for PR-3.

Replay and patch gate under A: none needed. No Workflow code changes, so no
recorded history can produce different commands. The existing replay tests
(`test_replay_pre_r1_history_keeps_the_patch_gate`,
`test_replay_pre_r16_history_keeps_the_expiry_patch_gate`, the 06B1 live
replay) must stay green.

Behaviour changes under A:

- A duplicate of an applied event whose delivery is still re-drivable now
  goes to Temporal. It can return 503 where it used to return a 200 claiming
  the event was deduplicated.
- `test_local_mailbox_api_duplicate_racing_first_dispatch_is_deduplicated`
  asserts one dispatch, and its fake client never runs a delivery, so its
  outbox stays `pending`. Under A its duplicate would be re-dispatched. Its
  fake must mark the outbox `accepted` (standing in for the delivery
  activity) so that it keeps testing what it was written for, the stale
  inbox-copy race. This is an existing-test edit and must be declared in
  the log.
- Reported `delivery_status` stays the receipt's stored value (`pending`), as
  on a first success today. The route does not report live outbox state.

## R-5: defect

`app.py:603` reads the Case and `app.py:628` puts `state.snapshot.revision`
into the channel command as `expected_revision`. No lock is held. If another
command commits in between, the Runtime's check under its lane
(`runtime.py:392-395` ingest, `runtime.py:569-572` and `611-614` delivery
callback) raises `CaseConflictError("case snapshot revision is stale")`. The
activity maps that to non-retryable `channel_conflict` (`activities.py:78-96`),
so the first delivery attempt returns 409. Redelivery recovers since #62: the
Case has moved, so the rebuilt request has a new revision, therefore a new
fingerprint and Update ID, and it reaches the Runtime.

The revision carries no meaning for a Provider-originated event. The route
makes no decision from the snapshot it reads, and every real precondition (no
pending approval, not complete, no pending execution, inbox still
`reserved`) is checked under the Runtime lane. The revision does one real
job, though: it is part of the Update ID. After a *non-retryable* channel
conflict that the Case later resolves (for example `case is awaiting
approval` → the approval is decided), the redelivery carries a new revision,
so its Update ID is not the cached failure. Any R-5 fix that removes the
revision from the command loses this unless it replaces it.

## R-5: options (root decision needed)

- **R5-1: send `expected_revision=None` on channel commands.** The Runtime
  then reads the revision under its lane and the repository CAS guards the
  write, which is exactly "read under the same lock/CAS as the write". It is
  a one-line route change. Trade-off, which is why I stopped: the channel
  command fingerprint, and so the Update ID, becomes constant per event.
  After a non-retryable conflict such as `case is awaiting approval`, every
  redelivery in the same run gets the cached 409 until the run rolls (32
  commands or an R-1 exhaustion). That regresses the recovery #62 provides.
  It also leaves the 06B1 contract's listed "expected Case revision" field
  always `None` on channel commands; the command model already allows that.
- **R5-2: R5-1 plus a client-side Update-ID salt for channel commands.**
  The command carries `None`, and the client derives the Update ID from
  (command id, fingerprint, the revision the route read). The salt is only a
  cache key and never a CAS: a stale read can at worst send one more Update
  to the Runtime, which deduplicates on the receipt. This keeps #62's
  recovery and removes the stale-revision failure entirely. Trade-off: it
  changes the Update-ID derivation (`update_id_for_command`,
  `client.py:68-70`), which is the dedup-semantics change the task packet
  names as a stop condition. It is client-only, so no replay impact, but the
  `update_id_for_command` docstring and #62's reasoning change.
- **R5-3 (recommended for PR-3): optimistic retry in the route.** Keep the
  revision in the command. On `TemporalDispatchError("channel_conflict")`,
  re-read the Case (threadpool):
  - if a receipt for `inbox.command_id` now exists, return it as
    `deduplicated`;
  - if the revision differs from the one dispatched, rebuild the command with
    the fresh revision and dispatch again (a new Update ID reaches the
    Runtime), at most 3 dispatches in total;
  - otherwise re-raise the 409.
  This does not change the Update ID, the Workflow, the Runtime, or the
  contract, and #62's recovery stays. Trade-offs: it is optimistic
  concurrency, not a lock, so sustained contention (more than 3 commits
  racing 3 dispatches) still yields 409, and redelivery recovers as today.
  Each retry adds one Update to the run's registry, bounded by 3. A genuine
  conflict that coincides with a revision change costs one extra dispatch
  before the 409.
- **R5-4: document only.** R-5 stays a known limit, as today.

Recommendation: A for R-17 and R5-3 for R-5, one PR, `app.py` only (plus
tests and docs). R5-2 is the principled end state if root prefers to remove
the stale-revision failure rather than retry it. R5-1 alone is not
recommended because of the #62 regression.

Interaction: A rebuilds the original request by fingerprint match over
`{prior.before_revision, None}`, so it works under every R-5 option,
including channel receipts stored before an R5-1/R5-2 deploy.

## Red tests (planned; written only after the R-5 decision)

DB-free, run by `make test`
(`tests/integration/test_phase_06b1_channel_runtime.py`, in-memory
`_ChannelRepository` and a fake Temporal client):

- R17-T1 `test_local_mailbox_redelivery_redrives_an_exhausted_delivery`: the
  first dispatch commits the ingest, then raises
  `channel_dependency_unavailable` (503). The redelivery must dispatch again
  with the identical request (same `command_id` and `semantic_fingerprint()`
  as the first), and the response is 200, `deduplicated: true`. Red on main:
  one dispatch.
- R17-T2 (guard, green on main): a duplicate of an applied event whose
  outbox is `accepted`, and one whose outbox is `failed_terminal`, is not
  re-dispatched.
- Racing-duplicate test edit (see above).
- R5-3-T1 `test_local_mailbox_stale_revision_is_retried_with_the_fresh_revision`:
  the fake client commits an `APPEND_EVENT` before applying the first
  dispatch, so the ingest conflicts on a stale revision. The route must
  dispatch again with the fresh revision and return 200. Red on main: 409.
- R5-3-T2 (guard): the Case awaits approval and the revision is unchanged. A
  single dispatch, then 409 `channel_conflict`.
- (Under R5-1/R5-2 the R-5 tests assert one dispatch with
  `expected_revision is None` instead; R5-2 adds a unit test of the salted
  Update ID.)

Live Temporal + Compose PostgreSQL, written but **not run** by the
implementer (the DB lane is held elsewhere; no `PROXYLOOP_TEST_*` set):

- R17-T3 `test_live_temporal_mailbox_redelivery_redrives_exhausted_delivery`
  (`test_phase_06b1_temporal.py`): the HTTP route with a real worker and
  `FaultInjectingLocalMailboxAdapter(fail_before_accept=5)`. The first POST
  returns 503 after about 15 s with the outbox `pending`. The redelivery
  returns 200, the outbox is `accepted`, with one outbox row, two
  transitions, one `provider_message` Evidence, and a new run id. The
  history replays. Red on main: the outbox stays `pending` and the run id is
  unchanged after the redelivery.

No replay fixture is needed under A with R5-1/2/3/4: no Workflow command
changes.

## Acceptance criteria

1. A redelivery of a Provider message whose ingest committed but whose
   delivery activity exhausted re-drives the delivery once the run has
   rolled. The outbox reaches `accepted`, with no second Case event, outbox,
   revision, or Evidence.
2. A duplicate whose outbox is `accepted`, `delivered`, `bounced`, or
   `failed_terminal` is answered from the receipt without a dispatch, as
   today.
3. Under R5-3: a channel dispatch that loses to a concurrent commit is retried
   with the fresh revision (at most 3 dispatches), and a genuine conflict is
   still 409 after one dispatch.
4. No change to `workflow.py`, the client, models, Runtime, or repository
   under the recommended options. Existing replay tests pass unchanged.
5. `make lint`, `make typecheck`, `make test`, and `make preflight` pass. The
   DB lane (`make postgres-check`, `make phase05a-check`,
   `make phase06b1-check`, serially) passes, R17-T3 included.
6. `docs/architecture.md` (the `local_mailbox` paragraph) states that an
   exact duplicate re-drives a still-pending delivery. §4a marks R-17 and
   R-5 done, or records their remaining limits.

## Risks carried (option A)

- The re-drive depends on the run having rolled. A redelivery that arrives
  while another handler holds the run gets the cached 503 again (R-1's
  delayed-roll limit). A run in flight at deploy time that replayed an
  exhaustion without the R-1 patch does not roll on exhaustion, so a
  re-drive waits for the command-threshold roll.
- The only re-drive trigger is a sender redelivery. A sender that stops after
  one 503 leaves the outbox `pending` (option B would close this).
- `failed_retryable` and `unknown` are listed for completeness. The local
  adapter never records them (it returns `accepted` or raises). If a future
  adapter records one on a *successful* Update, the identical Update is a
  cached success within the run and does not re-drive until a roll.
