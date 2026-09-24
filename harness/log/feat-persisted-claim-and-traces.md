# Log: the canonical execution claim and model traces are persisted (1.1 PR4)

Spec: `harness/context/feat-persisted-claim-and-traces-preflight.md`; design
`harness/context/schema-1.1-design.md` (PR4 row, decision 2). Resolves P1
B2-1 (contract half) and A-2 (storage). Branch
`feat/persisted-claim-and-traces` from `main` @ `6932596` (after PR2 #68).

## What changed

- `case_runtime/commands.py`: the runtime-local `ExecutionClaimRecord` is
  deleted.
- `case_runtime/repository.py`: `CaseRuntimeState.execution_claim` is the
  canonical `ExecutionClaim` (1.1); new `model_traces: tuple[ModelTrace, ...]
  = ()`. The claim/pending invariant is unchanged.
- `case_runtime/postgres_repository.py`: envelope `storage_version` 2 carries
  the canonical claim and `model_traces`; every write is version 2. Version 1
  rows are parsed by a private legacy envelope and upgraded on read: the
  claim's `case_id`, `action_intent_id` and `idempotency_key` come from the
  stored `execution_intent`, every other claim field is carried over, and
  `model_traces=()`. No table schema change. The pending-row check now also
  binds the claim's Case, intent id and idempotency key to the stored intent;
  a stored trace must reference the row's Case.
- `case_runtime/runtime.py`: the claim write builds the canonical
  `ExecutionClaim`. Every state write that follows a coordinator run appends
  that run's `outcome.traces` (create, event, channel event including the
  Slow refresh, rejection, expiry, final execution write); the other writes
  carry `model_traces` forward. `_refresh_strategy_if_required` returns its
  traces to the caller's write. The final route of `_execute_claim` is now
  computed before the final write so its traces ride in it (route-only, no
  adapter: behaviour unchanged). Traces never enter the snapshot, events,
  transitions, `RuntimeResult` or the API projection.

## Test edits (intended consequences)

- `tests/integration/test_phase_04c_persistent_case_store.py`
  `test_postgres_conflicts_and_strict_payload_fail_closed`: the
  "unsupported version" probe writes `storage_version` 3 (2 is now the
  supported version). DB-gated; not run here.

No existing test referenced `ExecutionClaimRecord` by name; tests reading
`execution_claim.command_id` / `.before_revision` keep working unchanged.

## Red -> green

New `tests/integration/test_persisted_claim_and_traces.py` (12 tests; the
PostgreSQL codec is exercised through `_encode_state`/`_decode_state` without
a database). On `main`: 8 failed, 4 passed. The four that passed on `main`
are the tamper probes of a v2 claim's `case_id`, `action_intent_id`,
`idempotency_key`, `approval_id`: the v1 record rejected the first three as
unknown keys and already checked the approval id, so their red is vacuous;
they guard the new binding checks.

| Test | Red on `main` | Green |
|---|---|---|
| v1 row with a pending claim upgrades, completes, writes v2 (1.1 and 1.0 snapshot) | upgraded claim != canonical `ExecutionClaim` | pass |
| v1 rows without a claim load and rewrite as v2 | no `model_traces` | pass |
| rows fail closed on shapes they never had | DID NOT RAISE (v2 payload shape) | pass |
| claim present exactly while pending | claim is not `ExecutionClaim` | pass |
| traces in the same write, survive completion | no `model_traces` | pass |
| channel event writes refresh + fast traces once | no `model_traces` | pass |
| browser projection never carries a trace | no `model_traces` | pass |

Before PR3 landed, traces were injected by a stub coordinator. After the
rebase onto `main` @ `f989613` (PR3 #70 merged) the fixture only records the
traces the real coordinator returns; the stub is gone.

## After the rebase onto PR3 (`f989613`)

- `runtime.py`: all eight `CaseCoordinator(...)` constructions go through
  `ThinAgentRuntime._coordinator`, which passes `monotonic=time.perf_counter`.
  Without it every persisted trace had `latency_ms=0` and
  `completed_at == started_at` (the scripted adapters report no latency).
- Decision (root): the Runtime clock is **not** passed as the coordinator's
  `clock`, although the handoff said `clock=self.now`. That was tried: the
  coordinator reads a clock twice per model call, so an injected sequence
  clock (`SequenceClock` in `test_phase_04a_agent_runtime.py`) had its later
  operation times shifted and two 04a tests failed (an approval no longer
  expired; a late recovery lost its claim time). Every model-calling route
  (create, event, channel) already carries `created_at` = the Case event's
  time, which is the trace start without a clock; the monotonic measurement
  supplies the duration. The Runtime clock stays the single time base and
  keeps one read per operation.
- New `test_persisted_traces_share_the_case_time_base`: each persisted trace
  starts at a stored Case event's `occurred_at`, `latency_ms` is the
  (patched) perf-counter measurement, and `completed_at = started_at +
  latency`. Red with the helper reverted to `CaseCoordinator(snapshot=...)`:
  `latency_ms` 0 != 250.
- From the PR3 review: `trace_id` is not an idempotency key; a replayed
  command is deduplicated by command id before any coordinator run, so no
  trace is appended twice.

## Review

Independent review (`reviewer`, on `126df56`): **Approve**, no Critical.
It confirmed the root's clock decision (only `monotonic` is passed).

1. I1, carry-forward untested on delivery, expiry, rejection. Applied:
   `test_traces_survive_an_approval_that_does_not_execute` (rejected,
   expired) and `test_delivery_callbacks_carry_the_traces_forward` (first
   and exact-duplicate callback). Mutation check: deleting any
   `model_traces` line in `runtime.py` now fails a test in this file.
2. I2, a rejected model result is never persisted, so every stored trace
   has `result=SUCCEEDED`; the channel path also drops accepted traces on a
   `response_text` mismatch or an unauthorized send. Recorded below as the
   remaining A-2 gap (needs a trace-only write or a side table: a new
   decision, outside PR4's frozen "no separate write").
3. M1, trace times are the Case operation time plus measured latency, not a
   wall-clock call window: a Slow refresh and the Fast call in the same
   event share `started_at`; after a Temporal retry `started_at` is the
   workflow-assigned time; `trace_id` hashes `latency_ms`, so it is as stable
   as that measurement. Documented here, not changed.
4. M6, the timing test patched the process-wide `time.perf_counter`.
   Applied: it now replaces only the runtime module's `time`.
5. Not applied, recorded: M2 (the in-memory state checks claim presence, not
   its Case/intent binding or a trace's Case; the Postgres codec enforces
   both), M3 (the v2 envelope accepts duplicate `trace_id`s), M4 (the version
   tag accepts `true`/`1.0`/`2.0` by equality, pre-existing), M5 (direct
   `approve(command_id=X)` without a fingerprint fails with a pydantic error;
   no caller), M8 (every write re-validates and rewrites all traces).
   M7 (WIP commit title) is resolved by the squash-merge message.

## Checks (on the final diff)

- Passed: `tests/integration/test_persisted_claim_and_traces.py` 16/16;
  `test_phase_04a_agent_runtime.py` 29/29 (two of its `SequenceClock` tests
  had failed with `clock=self.now`); `make format-check`, `make lint`,
  `make typecheck`; `make test` (runtime 1171 / 46 skipped, ML 390 / 1
  skipped, all artifact gates); `make preflight` (exit 0; runtime 1171 / 46,
  ML 390 / 1, web 99); `data/` clean.
- Passed, Compose, run one at a time, before the review's test-only
  additions: `make postgres-check` 27, `make phase05a-check` 36,
  `make phase06b1-check` 34.
- Earlier, on `6932596` before the rebase: new file 12/12, focused suite 85
  passed / 25 gated skips, runtime unit suite 1120 / 46.

## Known limits

- `model_traces` retention is unbounded.
- Traces of a coordinator run that raises `ModelRuntimeError` (rejected
  model result) are not persisted: that path has no state write, and this PR
  adds no separate write. Same for the append-event rollback after a failed
  `await_approval`, which restores the prior state.
- A version 1 pending claim that cannot become a canonical claim (command id
  without fingerprint, or a non-SHA-256 fingerprint) fails closed as an
  invalid row. No production path wrote one: every command-bearing approval
  goes through `apply_command`, which always fingerprints.
- A direct `runtime.approve(..., command_id=X)` without a fingerprint now
  fails at the claim write (canonical contract: both or neither), before any
  write. No caller does this.
- Remaining A-2 gap (review I2): traces of a rejected model result, and
  accepted traces on a channel `response_text` mismatch or unauthorized
  send, are never persisted, so stored traces are all `SUCCEEDED`.
- A trace's `started_at` is the Case operation time, not a wall-clock call
  start (review M1).
