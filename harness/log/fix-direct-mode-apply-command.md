# Fix log: direct mode shares the command path, expires approvals, and says what it is (P1 B2-4, E-4, E-11, B2-6)

Spec: `harness/context/fix-direct-mode-apply-command-preflight.md`.
Programme: `harness/context/audit-remediation-decisions.md` decision 8. Branch
`fix/direct-mode-apply-command` from `main` @ `70c30c7`, rebased onto `a913733`. Origin: audit B2-4,
B2-6 (`harness/code_review/repo-audit-B2.md`), E-4, E-11
(`harness/code_review/repo-audit-E.md`).

## What changed

- `api/app.py`: one local `apply(command)` dispatches every POST. With a
  Temporal client it calls `temporal_client.apply_command` as before. Without
  one (direct mode) it reads the Runtime clock once, calls
  `service.apply_command(command.to_command(occurred_at))`, and hands the
  receipt to the expiry timer. Before an event or approval command it refuses
  a clock that is not after the latest visible event with 409 `clock time
  must advance event time` (review M1, below). All three POST routes now build the same
  `CaseCommandRequest` with `command_id=_command_id(request)` in both modes
  and end with `service.current_result(case_id, transition=transition)`. The
  `service.create_case/append_event/approve` branches are gone.
- `api/direct_expiry.py` (new): `DirectApprovalExpiry`. `observe(transition,
  observed_at=...)` arms one asyncio task per `(case_id, approval_id,
  approval_expires_at)`, at most once per process. The first delay is
  computed from the command time `apply` already read, so arming does not
  consume a tick of an injected clock. After each wake the task re-reads the
  Runtime clock and sleeps again if the deadline has not passed. At the
  deadline it issues `EXPIRE_APPROVAL` through `runtime.apply_command` with
  `expiry_command_id(case_id, transition)` (the Workflow's helper, imported
  from `proxyloop_workflow_worker`), `expected_revision =
  transition.after_revision`, and `to_command(expires_at)`, which is exactly
  the request `CaseWorkflow._expire_pending` builds. If the approval was
  decided meanwhile, the revision pin makes the Runtime refuse the expiry
  (`CaseConflictError`). That is logged at info and nothing is written. Any
  other exception is retried with the Workflow's backoff (15 s doubling, capped
  at 5 min, from `EXPIRY_RETRY_INITIAL_BACKOFF` and
  `EXPIRY_RETRY_MAXIMUM_BACKOFF` in `workflow_worker/workflow.py`). There are
  at most `EXPIRY_MAX_ATTEMPTS = 6` attempts; each failure is logged at
  warning with the exception type only, then the timer gives up and leaves the
  approval pending (review M2). The app keeps serving throughout. `aclose()`
  cancels the tasks, and the app lifespan calls it on shutdown. The sleep is
  injectable through `create_app(..., approval_expiry_sleep=...)`. The clock
  is the Runtime's public `ThinAgentRuntime.now()`.
- `api/app.py` readiness: a ready direct Runtime adds `orchestration_mode:
  "direct"` to `/health/ready`. The 503 payload and `/health/live` are
  unchanged.
- `api/app.py` projection (B2-6): `_browser_completion(snapshot)`. When
  `completion_decision is None`, `reason_codes` comes from the first approval:
  `rejected` gives `approval_rejected`, `expired` gives `approval_expired`,
  and anything else (pending, approved and still executing, or no approval)
  gives `approval_or_execution_pending` as before. `decision` stays
  `not_done`. The allow-list projection from #57 is otherwise untouched, and
  no field was added.
- `case_runtime/runtime.py`: one public `now()` that delegates to the clock
  (review M6), so the API no longer calls the private `_clock_now`.
  `_repeat_approved` is **not changed**. `apply_command` still reaches
  `_repeat_approved`, but always with a `command_id`, and in that case it
  already raises `approval is already terminal`, which is what Temporal mode
  returns. Its pin-less body is still reachable from direct Runtime callers
  that pass no `command_id` (`test_phase_04a` concurrency test,
  `test_phase_04c` repeat-after-completion). Deleting it would break those
  callers and serve no API route, so it stays.
- Web: `runtime-client.ts` `statusMessage("case_conflict")` no longer claims
  a read ("I read the current state"). The create-409 path never read, so the
  copy changed; the component still reads in its event, approval and restore
  409 paths. The copy is mode-neutral and promises no read or reconnect
  (review M5): "Retry only if the action is still offered; to start over,
  restart the Runtime process (or reset the durable demo), then choose New
  task." `conversation-workspace.tsx` `restorePersisted`: readiness with
  `orchestration_mode: "direct"` **and** `storage_mode: "memory"` shows the
  one-Case-per-process limit and "Restart the Runtime process to start over"
  instead of the durable-profile recovery block (review M4). Any other
  non-durable profile, including direct with PostgreSQL storage, keeps the
  existing block.
- Docs: `apps/README.md` (the direct-mode paragraph), `docs/ui/user-flows.md`
  (the key is honoured in both modes; create-409 performs no read),
  `docs/ui/state-matrix.md` rows Restoring Case, Authoritative approval
  expired, and HTTP/network/malformed failure.

## Root decision: a non-v4 path id is 422 in both modes

A path `case_id` or `approval_id` that parses as a UUID but is not version 4
fails `CaseCommandRequest` validation. On `main` this already returned 500
`internal_error` in Temporal mode (the pydantic `ValidationError` escaped
the route); direct mode returned 404 because it never built the request.
The first cut of this change made direct mode 500 as well. The root decided
that this is API request validation on the shared command path, not a
Temporal orchestration change, and that 500 for bad input is a defect.
`app.py` `_command_request(**values)` now builds the request for all three
POST routes and maps a `ValidationError` to `TemporalDispatchError(
"invalid_command")`, which is 422 `{"code": "invalid_command", "message":
"command rejected"}`, the same response as a malformed key, in both modes. The
channel route builds its request from server-owned values and is unchanged.
The matrix test covers a non-v4 case id on `/events` and a non-v4 case id or
approval id on `/approvals`. On the first cut both modes failed with `assert
500 == 422`, and now both pass.

## Intended behaviour change

`test_phase_04a_agent_runtime.py::_test_thin_runtime_completes_multiturn_approval_flow`
asserted that direct mode returns 200 (via `_repeat_approved`) for a pin-less
approval re-POST after completion. Direct mode now returns 409 `approval is
already terminal`, the same as Temporal mode, and the Provider is still
confirmed exactly once. The assertion was updated.

## Tests

`tests/integration/test_direct_mode_command_path.py` (new; the matrix is
parametrised over `direct` and the `FakeTemporalCaseClient` from
`test_phase_05a_temporal_api.py`). The modes match on status codes and
deduplication behaviour. The fake calls the Runtime directly, so its error
`detail` equals direct mode's. Under a real Temporal server the activity
error is classified (for example `{"detail": "case_conflict"}`), a
pre-existing difference not changed here (review M3).

- Key/body matrix on `POST /cases`, `/events`, and `/approvals`: a malformed
  key (`not-a-uuid`, upper-case UUID) or a non-v4 path id gets 422
  `invalid_command` and stores nothing. The same key with the same body returns a byte-identical payload
  (201 or 200). The same key with a different body gets 409 `command id was
  reused for a different command`. No key applies a fresh command (409 `case
  already exists` or `case snapshot revision is stale`). A pin-less approval
  after terminal gets 409 `approval is already terminal`. Provider confirmed
  once.
- `/health/ready` direct payload includes `orchestration_mode: "direct"`, and
  live is unchanged.
- Expiry: event opens an approval, then one sleep of at most 3600 s is
  armed. An early wake re-sleeps and does not expire. With the clock past
  `expires_at` the approval is persisted `expired` with exactly one
  `EXPIRE_APPROVAL` receipt whose id equals `expiry_command_id(case,
  opening receipt)`. A deduplicated replay of the opening command arms no
  second timer. The projection reports `approval_expired`, and a late approve
  gets 409.
- A decision before the deadline leaves the timer a no-op (no revision
  change, no expiry receipt, still `complete`).
- A rejection projects `approval_rejected`.
- Lifespan shutdown cancels a sleeping timer.
- Expiry retry: one transient failure, then success, gives exactly one
  `EXPIRE_APPROVAL` receipt after a 15 s backoff. Persistent failure backs off
  15/30/60/120/240 s, logs `approval expiry abandoned after 6 attempts:
  RuntimeError` (never the exception message), leaves the approval pending,
  and the app keeps serving. The backoff function matches the Workflow policy
  (15 s up to a 300 s cap).
- A backwards clock on `/events` gets 409 `clock time must advance event
  time` and leaves the snapshot and receipts unchanged.

Web: `runtime-client.test.ts` (new case_conflict copy; direct readiness
parse; "does not promise a Case read"), `conversation-workspace.test.tsx`
(direct plus memory readiness shows the one-Case/restart copy and not the
durable block; direct with PostgreSQL storage and "no orchestration_mode"
keep the durable block).

## Red → green

| Test | Pre-fix | Post-fix |
|---|---|---|
| matrix ×3 `[direct]` | `assert 201 == 422` / `assert 200 == 422` (malformed key accepted) | pass |
| matrix ×3 `[temporal]` | pass (the reference behaviour) | pass |
| direct readiness | missing `orchestration_mode: "direct"` | pass |
| rejection projection | `approval_or_execution_pending != approval_rejected` | pass |
| expiry ×4 | `TypeError` (no `approval_expiry_sleep`; direct mode had no timer) | pass |
| Web ×3 | old copy; durable block for direct | pass |
| M1 backwards clock | 500 `internal_error` without the guard | 409 |
| M2 transient failure | `assert [] == [15.0]` without retry | pass |

One intermediate failure is worth recording.
`test_late_pin_less_recovery_verifies_at_claim_time` broke when the timer
read the Runtime clock at arming time, because the extra read consumed one
value of its `SequenceClock` (the B2-9 fragility). Arming now uses the
command time already read, and the test passes unchanged.

## Review

Independent review (`reviewer`): **Approve**, with six minor findings, all
applied.

- M1: the direct path now passes an explicit command time, which skips the
  Runtime's own event-time guard. With a backwards clock, `main` returned 409
  `clock time must advance event time`; this diff without the guard returned
  500. `apply` now refuses such a clock before dispatch for event and
  approval commands, and nothing is written. The earlier statement that
  dropping the guard "matches Temporal mode" was wrong and is withdrawn: in
  Temporal mode the Workflow supplies the command time, and a command the
  Runtime rejects with a `ValueError` there is mapped to 422
  `invalid_command`.
- M2: a non-conflict expiry failure is retried with bounded backoff that
  mirrors the Workflow's policy, then the timer gives up. Conflicts are still
  a no-op.
- M3: the log and the test docstring now say the modes match on status codes
  and deduplication, and that `detail` differs under real Temporal.
- M4: the direct restart copy is shown only for memory storage.
- M5: the `case_conflict` copy no longer promises "Reconnect to read the
  Case".
- M6: `ThinAgentRuntime.now()` replaces the API's use of `_clock_now`.

## Checks (implementer)

- Passed: the Python suite without DB/Temporal
  (`tests/integration tests/contract` plus the package tests), the new module,
  `test_phase_04a_agent_runtime.py`, and `test_phase_05a_temporal_api.py`.
  Counts are in the final report.
- Passed: `make web-check`, `make lint`, `make typecheck`,
  `make format-check`, `make preflight-fast`. `make phase04d-profile-check`
  passed on the pre-review diff.
- Not run by the implementer (the root runs them serially): `postgres-check`,
  `phase05a-check`, `phase06b1-check`, `make preflight`.

## Known limits

- Direct mode is in-process. A restart loses the timer, and with memory
  storage the Case as well. With direct plus PostgreSQL storage a restarted
  process does not re-arm the timer until a command replays a receipt that
  names the approval.
- The timer and the handlers still call the synchronous Runtime on the event
  loop (B2-8, unchanged).
- The API's clock guard (M1) covers event and approval commands. It runs
  before the receipt lookup, so replaying a deduplicated event or approval
  under a backwards clock gets the 409 rather than the stored receipt. With a
  real clock this does not happen.
- After `EXPIRY_MAX_ATTEMPTS` failed attempts an in-process timer gives up.
  The Workflow instead keeps retrying, because its timer is durable.

## Root gate (2026-09-23)

Run serially with the Compose profiles up and `PROXYLOOP_TEST_DATABASE_URL`
/ `PROXYLOOP_TEST_TEMPORAL_ADDRESS` set, on the final diff rebased onto
`a913733`: `make preflight` exit 0 (runtime 962 passed incl. DB-gated tests;
ML and web green); `postgres-check` 27, `phase05a-check` 36,
`phase06b1-check` 34 — all passed. Not run: a Browser smoke pass of the
direct-mode copy.
