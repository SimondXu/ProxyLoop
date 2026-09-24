# R-12 + R-13b: append-only model-trace log (PR-7) — frozen spec

Status: frozen by the root orchestrator on 2026-09-24 from the `architect`
proposal below (decision 16 authority). Root decisions:

1. **Option 3 with bootstrap backfill (a)** for `storage_version` 2 rows.
   Reason: keeps the v1→v2 precedent that no stored row is stranded and
   keeps committed A-2 evidence readable; the steady-state cost is a
   filtered scan. Option (b) "reject v2 / reset the demo" is the recorded
   fallback only if the backfill proves unsound in review.
2. **G8 is required**: a source guard asserting `runtime.py` has exactly one
   `.advance(` call (`_advance`), so PR-8, PR-13 and PR-14 cannot add an
   untraced path (invariant I6).
3. Sequencing change to the build plan: PR-7 starts before PR-5. PR-7 owns
   `runtime.py` and `postgres_repository.py` until it merges; PR-5 must not
   touch either (if R-6 needs `runtime.py`, R-6 moves after PR-7). PR-7
   merges `origin/main` after PR-4 lands and before its DB gates.
4. Known limit recorded, not fixed: an adapter that raises produces no
   `CoordinatorOutcome` and so no trace (coordinator gap, §3.8 item 8).
5. Unsupported: mixed code versions against one database (§3.8 item 3);
   document "stop all processes before upgrading".

---

# PR-7 design proposal: R-12 + R-13b, an append-only model-trace log at `storage_version` 3

Architect proposal, propose mode. Baseline `main` @ `c73f6a7`. No repository file was edited.
Tags: **[O]** observed in code or docs (with file:line), **[I]** inferred, **[P]** proposed.

---

## 1. Current state

### 1.1 Where traces live [O]

- The coordinator issues one 1.1 `ModelTrace` per adapter call on a 1.1 snapshot, **including rejected calls** (`result=REJECTED`, with the audit's reason codes). They go into `CoordinatorOutcome.traces` in call order:
  `runtime/packages/agent_core/src/proxyloop_agent_core/coordinator.py:67-74` (outcome), `:198-299` (collection), `:548-613` (`_model_trace`).
- `trace_id` is derived from all other fields, including `latency_ms`, `started_at`, and `input_pins` (`coordinator.py:610-613`). It is **not** an idempotency key. Two calls with identical content and latency, for example a scripted retry at 0 ms, get the same id (`harness/log/feat-persisted-claim-and-traces.md:88-90,108-111`).
- Runtime state: `CaseRuntimeState.model_traces: tuple[ModelTrace, ...]` (`runtime/packages/case_runtime/src/proxyloop_case_runtime/repository.py:47-50`). The dataclass is shared by both adapters.
- PostgreSQL: traces sit **inside the Case aggregate's jsonb payload**, `_CaseStorageEnvelope.model_traces` (`postgres_repository.py:83-99`), in table `proxyloop_case_runtime_states(case_id PK, revision, payload jsonb, updated_at)` (`:890-899`). There is no trace table. Every `replace*` re-encodes and rewrites the whole envelope, all traces included (`:993-1012`). That rewrite is R-13's O(n) cost.
- In memory: `InMemoryCaseRepository` stores the whole `CaseRuntimeState` value (`repository.py:155-189`).
- The API package copies are pure re-export shims, with no logic of their own: `runtime/services/api/src/proxyloop_api/{runtime,repository,postgres_repository}.py`. Nothing needs to change there.
- The runtime writes traces by carrying them forward. Every `CaseRuntimeState(...)` construction passes `model_traces=(*state.model_traces, *new)` or `state.model_traces`. There are 10 such sites (`runtime.py:508-512, 596, 694, 824, 985-990, 1187, 1278, 1453, 1530`). `_refresh_strategy_if_required` returns its traces so the caller can include them in its write (`runtime.py:1588-1647`).

### 1.2 Where R-12 happens [O]

`ModelRuntimeError` is raised after `outcome.traces` exist but before any write, so those traces are dropped:

| Path | Raise | Traces lost |
|---|---|---|
| `ingest_channel_event` | `runtime.py:463` (`ModelRuntimeError("fast")`: rejected **or** accepted with `response_text != BOUNDED_FAST_STATUS_TEXT`) | `refresh_traces` + fast trace |
| `ingest_channel_event` | `runtime.py:467` (`ChannelConflictError("channel send is not authorized")`) | accepted refresh + fast traces |
| `create_case` | `runtime.py:788` (`ModelRuntimeError("slow")`) | slow trace; no Case row exists at all |
| `_append_event_serialized` | `runtime.py:926` (`ModelRuntimeError("fast")`) | `refresh_traces` + fast trace |
| `_refresh_strategy_if_required` | `runtime.py:1630` (`ModelRuntimeError("slow")`) | slow trace |
| `_append_event_serialized` rollback | `runtime.py:1005-1010` (the `await_approval` failure restores the prior state) | the traces already written are *removed* by the compensating write |

The approval, expiry, execution and rejection paths advance the coordinator without adapters (`runtime.py:1260, 1440, 1506`), so they never produce traces. [O] (`coordinator.py:207-260`: without an adapter the result is `*_UNAVAILABLE` with no traces.)

The consequence was recorded in the PR4 review, finding I2: every stored trace is `SUCCEEDED` (`harness/log/feat-persisted-claim-and-traces.md:102-106,150-152`).

### 1.3 `storage_version` today [O]

- `_STORAGE_VERSION = 2` and `_LEGACY_STORAGE_VERSION = 1` (`postgres_repository.py:64-67`).
- `_decode_state` accepts exactly 1 and 2. Anything else raises `RuntimeError("unsupported Case storage version")` (`:1022-1024`).
- Version 1 is upgraded **on read** by `_LegacyCaseStorageEnvelope.upgrade()` (`:139-196`, "a version 1 row has no model traces") and **rewritten as the current version on the next write**. Every write is v2 (`:993-1012`).
- There are no migration files. `_bootstrap` runs idempotent DDL (`CREATE TABLE/INDEX IF NOT EXISTS`, one `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) inside the `PostgresCaseRepository.__init__` of every process (`:207-211, 883-990`). It takes no lock.
- Tests pin the version gate. `tests/integration/test_persisted_claim_and_traces.py:295` expects `storage_version: 3` to be rejected, and `tests/integration/test_phase_04c_persistent_case_store.py:634` writes `{"storage_version": 3}` and expects "unsupported". Both have to move to 4.

### 1.4 Who reads traces [O]

No product code reads traces. The only readers are the codec round trip and the tests (`test_persisted_claim_and_traces.py`, 23 references). `test_browser_projection_allowlist.py:93` asserts they never reach the browser. Planned readers [I from the build plan]: the PR-8 `make fast-slow-split-report` (per-turn Fast/Slow share), the PR-14 `role=judge` traces, and possibly PR-16 `make ops-report`. The Web must never read them.

### 1.5 Temporal [O]

- `workflow.py` never touches the repository. The activity `CaseCommandActivityAdapter.apply_command` (`activities.py:46-117`) maps `ModelRuntimeError` to the non-retryable `model_path` and `StorageUnavailableError` to the retryable `storage_unavailable`.
- Replay tests exist in `test_phase_05a_temporal_workflow.py` and `test_phase_06b1_temporal.py`.
- Test databases are reset with `TRUNCATE` on `proxyloop_case_runtime_states` and on the channel tables (`test_phase_04c...:142`, `test_phase_05a_case_runtime.py:385`, `test_phase_05a_temporal_workflow.py:255`, `test_phase_06b1_temporal.py:74`). The 07A demo reset removes the whole named volume (`scripts/run_phase_07a_portfolio_demo.py:688-743`).
- Every Case has the same id, `SCRIPTED_CASE_ID` (`runtime.py:104`, `create_case` at `:731-734`).

---

## 2. Options

### Option 1: keep traces in the v2 envelope and add a revision-neutral traces-only envelope update. Rejected.

- *Append:* `UPDATE ... SET payload = jsonb_set(payload,'{model_traces}', ...)` without bumping the revision.
- *Why rejected:*
  - **Lost update.** Every other writer CAS-compares only `revision` and then rewrites the whole payload. A writer that read revision r before the append overwrites the appended traces. [I, follows from `postgres_repository.py:302-317`]
  - Fixing that needs a revision bump. A bump turns a rejected model output into a Case transition, which breaks "stale/rejected output causes no state mutation" (`docs/architecture.md:191`). It also moves the `expected_revision` the next command and workflow carry, which is a Temporal behaviour change.
  - The `create_case` rejection has no row to update.
  - R-13's O(n) write cost is not addressed.

### Option 2: a side table, appended **inside the Case write transaction**, plus a traces-only append at each raise site. Rejected.

- *Shape:* `create`, `replace`, `replace_with_channel_outbox` and `replace_with_delivery_receipt` gain a `traces=` keyword and insert trace rows in the same transaction as the CAS. Each of the six raise sites in §1.2 calls `append_model_traces` before raising.
- *Pros:* traces are atomic with the transition.
- *Why rejected:*
  - Four write signatures change, and about 12 test fakes override `create`/`replace` with the exact current signature (`test_phase_04a...:333-360`, `test_phase_05a_case_runtime.py:170`, `test_phase_05a_temporal_workflow.py:159`, `test_phase_04c...:49`, `test_strategy_basis_binding.py:586`, `test_phase_06b1_channel_runtime.py:50,528`, `test_r10...:60-63`, `test_persisted_claim_and_traces.py:73-100,360-370`). [O]
  - **R-12 recurs by construction.** Every new raise site must remember its own append, and PR-8, PR-13 and PR-14 each add new rejection or retry sites.
  - A CAS-losing attempt's model call is still unlogged.
  - The atomicity it buys is worth nothing to any reader. A Model Trace is "the operational record of a model invocation" (`CONTEXT.md:99-101`), not a record of applied state. Applied state is recorded by the Case transitions.

### Option 3 (recommended): a side table, **appended once per coordinator run, before the runtime acts on the outcome**. The envelope moves to v3 without traces, and v2 rows are backfilled at bootstrap.

- **Storage shape.** New table `proxyloop_model_traces(log_id identity PK, case_id, trace jsonb)`. There is no FK to the Case table, for three reasons: the `create_case` rejection has no Case row, every existing `TRUNCATE proxyloop_case_runtime_states` would fail against an FK, and the log must outlive a compensating rollback. There is no unique constraint on `trace_id` (§1.1).
- **Append semantics.**
  - One `append_model_traces(case_id, traces)` per coordinator run that issued traces. It runs in its own short transaction, immediately after `advance()` and before the outcome is checked. That is before any raise, any CAS, and any rollback.
  - It neither reads nor writes the Case row, does not change the revision, and does not need the Case to exist.
  - *Idempotency:* no key is needed. A command already applied is deduplicated by command id before any coordinator run (`runtime.py:237-241`). A failed command's retry is a **new model call** and correctly gets a new record. If the append commits but its acknowledgement is lost, the command fails with `StorageUnavailableError` and a retry again makes a new call, so no call is recorded twice.
  - *Ordering:* ascending `log_id`. Per case, that equals call order within a runtime, because appends are synchronous and sequential.
- **Rejected outcomes.** Handled by construction, with no per-site code: the traces are durable before `ModelRuntimeError` is raised.
- **Read path.** `list_model_traces(case_id) -> tuple[ModelTrace, ...]` in append order. It fails closed on an invalid or foreign trace. Consumers are tests, PR-8's report, and PR-14's tests. Nothing on the runtime's decision path reads it; see invariant I8.
- **v2 rows.** `_bootstrap` runs a one-time backfill under a PostgreSQL advisory lock:
  1. Move each v2 row's inline `model_traces`, in order, into the log.
  2. Rewrite the payload as v3 (`payload - 'model_traces'`, `storage_version: 3`) at the **same revision**.

  The backfill is idempotent because only v2 rows match. After it runs, `_decode_state` accepts v3 and v1 (v1 is still upgraded on read and rewritten as v3 on write) and rejects v2 and everything else.
- **In-memory parity.** `InMemoryCaseRepository` keeps a `dict[UUID, list[ModelTrace]]` under its existing lock, with the same validation and ordering. Every test fake subclasses `InMemoryCaseRepository` or `PostgresCaseRepository` [O], so all of them inherit the log with no edits.
- **Temporal.** `workflow.py` and `activities.py` are unchanged, and so are the activity input and result types and every `ApplicationError` type. The rejection path still ends in `ModelRuntimeError`, which maps to `model_path` (non-retryable). The only new live behaviour is one extra INSERT inside activities that already do DB I/O. If that INSERT fails, the error is `storage_unavailable` (retryable), the same category any Case write failure has today. Replay is unaffected, because activities are not re-executed on replay and no workflow code or history shape changes. [I; proven by the existing replay tests passing unchanged]
- **Cost.** At most two extra INSERT transactions per model-calling command (Slow refresh + Fast), and zero for commands that make no model call. In exchange, Case writes and reads no longer grow with the trace count (R-13b).

#### Sub-choice for v2 rows

| | Behaviour | Verdict |
|---|---|---|
| (a) bootstrap backfill | One place, no steady-state cost, keeps the A-2 evidence | **recommended** |
| (b) reject v2 at read ("reset the demo") | Zero migration code. Local v2 rows exist only in dev/demo databases, and the demo already requires `make portfolio-demo-reset` for fresh state. | acceptable fallback if the root prefers the smallest diff. It breaks the v1→v2 precedent of never stranding a row. |
| (c) lazy (v2 decoded; inline traces moved on the next write; `list` unions inline + log) | Needs the mover at three UPDATE sites. **Ordering breaks**: a traces-only append made while the row is still v2 would be logged before the older inline traces. Sorting by `started_at` is not total, because a channel event may reuse the previous event time (`runtime.py:407-409`). | rejected |

---

## 3. Recommendation: Option 3 with backfill (a)

### 3.1 Frozen interface [P]

`repository.py`:

```python
@dataclass(frozen=True, slots=True)
class CaseRuntimeState:
    ...                      # unchanged fields
    # REMOVED: model_traces. Traces live only in the repository's trace log.

class CaseRepository(Protocol):
    def create(self, state: CaseRuntimeState) -> CaseRuntimeState: ...
    def get(self, case_id: UUID) -> CaseRuntimeState | None: ...
    def replace(self, case_id: UUID, *, expected_revision: int,
                state: CaseRuntimeState) -> CaseRuntimeState: ...
    def append_model_traces(self, case_id: UUID,
                            traces: tuple[ModelTrace, ...]) -> None: ...
    def list_model_traces(self, case_id: UUID) -> tuple[ModelTrace, ...]: ...
```

`runtime.py` gets a single private call site. All 8 `self._coordinator(x).advance(RouteRequest(snapshot=x, ...))` sites (`:450, 774, 914, 955, 1260, 1440, 1506, 1602`) are routed through it:

```python
def _advance(self, request: RouteRequest, *, fast: FastAdapter | None = None,
             slow: SlowAdapter | None = None) -> CoordinatorOutcome:
    outcome = self._coordinator(request.snapshot).advance(request, fast=fast, slow=slow)
    if outcome.traces:
        self.repository.append_model_traces(request.snapshot.case.case_id, outcome.traces)
    return outcome
```

Also in `runtime.py`:

- `_refresh_strategy_if_required(...) -> CaseContextSnapshot`. It no longer returns traces.
- Every `model_traces=` argument is deleted.
- `_coordinator` still resolves `CaseCoordinator` from the module namespace, so the tests' `_RecordingCoordinator` monkeypatch keeps working.

PostgreSQL DDL, added to `_bootstrap` in its existing single transaction:

```sql
SELECT pg_advisory_xact_lock(<fixed bigint, e.g. hashtext('proxyloop_case_storage_bootstrap')>);
-- existing DDL unchanged ...
CREATE TABLE IF NOT EXISTS proxyloop_model_traces (
    log_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_id  uuid  NOT NULL,
    trace    jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS proxyloop_model_traces_case_idx
    ON proxyloop_model_traces (case_id, log_id);
```

Backfill, in Python inside the same locked transaction, so the insert order is explicit:

```text
SELECT case_id, payload->'model_traces' FROM proxyloop_case_runtime_states
 WHERE payload->'storage_version' = '2'::jsonb ORDER BY case_id FOR UPDATE
for each row whose model_traces is a JSON array:
    INSERT ... (case_id, trace) VALUES (%s, %s)   -- executemany, array order
    UPDATE proxyloop_case_runtime_states
       SET payload = (payload - 'model_traces') || '{"storage_version": 3}'::jsonb
     WHERE case_id = %s                            -- revision and updated_at untouched
(a non-array value is left as v2 and fails closed at read, per Case)
```

The advisory lock is required. Without it, two processes bootstrapping concurrently can both run the `INSERT ... SELECT` over the same uncommitted v2 rows and double-copy the traces. [I] The lock also serializes the existing `CREATE ... IF NOT EXISTS` DDL, which is a known PostgreSQL race. That is a side benefit, not a goal.

Envelope changes:

- `_CaseStorageEnvelope.storage_version: Literal[3]`, and the `model_traces` field is removed (`extra="forbid"` then rejects a stray `model_traces` key).
- `_STORAGE_VERSION = 3`.
- `_LegacyCaseStorageEnvelope.upgrade()` builds the v3 envelope.
- `_decode_state` accepts `{3, 1}`.
- The trace `case_id` check moves from the envelope validator to the log reader.

The `append_model_traces` and `list_model_traces` methods follow the repository's existing pattern: one connection per operation, `psycopg.Error` mapped to `StorageUnavailableError(...) from None`. Each trace is written as `trace.model_dump(mode="json")` and read with `ModelTrace.model_validate_json(json.dumps(value))`, mirroring the envelope's strict JSON validation.

### 3.2 Invariants to freeze [P]

- **I1 append-only.** There is no product API that updates or deletes a log row. Only test `TRUNCATE`s and the demo volume reset remove rows.
- **I2 one Case per append.** Every `trace.case_id == case_id`, otherwise `ValueError` before any write. The append is all-or-nothing, in one transaction.
- **I3 empty is a no-op.** An empty tuple opens no connection.
- **I4 order.** `list_model_traces` returns traces in append order. Per runtime, the log equals the concatenation of every `CoordinatorOutcome.traces` in call order.
- **I5 independence.** An append reads and writes no Case row, never changes a revision, does not need the Case to exist, and never joins a Case CAS transaction.
- **I6 before acting.** Exactly one append per coordinator run that issued traces, performed before the runtime inspects the outcome, and therefore before any raise, write, or rollback. `_advance` is the only `advance(` call in `runtime.py`.
- **I7 never projected.** Traces never enter `CaseRuntimeState`, the snapshot, the v3 envelope, views, receipts, or the API.
- **I8 observability only.** Nothing on the runtime's decision path reads the log. This binds PR-14: Judge feedback to the Slow retry is passed in-process, not through the log (decision 20 keeps it off the contract; this keeps it off the log too).
- **I9 fail closed.** A storage failure raises `StorageUnavailableError` and is never swallowed. A stored trace that is invalid or belongs to another Case makes `list_model_traces` raise `RuntimeError("stored model trace is invalid")`.
- **I10 identity.** `trace_id` is not unique in the log. Two indistinguishable calls are two rows.
- **I11 meaning of `result`.** `result` is the coordinator's validation verdict, not delivery or application. A `SUCCEEDED` Fast trace from the channel path that raised at `:463`/`:467` was never delivered. Delivery and application are recorded by the Case transitions. Document this in `docs/architecture.md`.

### 3.3 Forward compatibility

- **PR-8** reads `list_model_traces(case_id)` and groups by `trace.input_pins.event_cursor` and `trace.role` to get the per-turn Fast/Slow split. This works identically on the in-memory adapter the scripted report is likely to use. [P] If a join key to `CaseTransitionRef.command_id` is ever needed, add a nullable `command_id` column with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, following the precedent at `postgres_repository.py:932-937`. Not now (YAGNI).
- **PR-14.** `ModelTrace.role` already admits `"judge"` (`contracts.py:588-590`), so no contract change is needed. The Judge seam's traces and the retry's second Slow trace must go through `repository.append_model_traces`, either via `_advance` or a sibling private helper that shares the same single append line. PR-14's import-boundary test is unaffected.

### 3.4 Acceptance criteria

1. Every trace the coordinator issues on any runtime path, including rejected results, CAS losers, and the append-event rollback, is in `list_model_traces` in call order. Both adapters.
2. A rejected result leaves the Case exactly as before: same revision, snapshot, events, transitions, inbox `reserved`, no outbox. On `create`, no Case row exists.
3. The PostgreSQL envelope is v3 and has no traces. The size of a Case write no longer depends on the number of traces.
4. After bootstrap, a v2 row is v3 at the same revision, and its traces are in the log in their original order. A second bootstrap changes nothing.
5. Decoding rejects v2 and v4. v1 still loads and is rewritten as v3.
6. `workflow.py`, `activities.py`, `app.py`, contracts and `agent_core` are unchanged. The phase05a and phase06b1 suites, including their replay tests, pass unchanged.
7. `docs/architecture.md:56` is rewritten to describe the implemented log: where it lives, I1–I11 in prose, retention still unbounded. `harness/context/audit-remediation-status.md` marks R-12 and R-13b done.

### 3.5 Tests, red first

**Red: reproduce R-12 on `main` before any production edit.** Use the existing `issued` recording-coordinator fixture (`test_persisted_claim_and_traces.py` ~`:330-350`) and assert "persisted traces == issued". On `main`, "persisted" means `repository.get(case_id).model_traces`. Record the failing output in the log, then port the assertion to `list_model_traces`.

- R1 `test_a_rejected_fast_result_is_traced`. The Fast adapter echoes stale pins, so `append_event` raises `ModelRuntimeError("fast")`. The log ends with `role="fast", result=REJECTED` plus reason codes. The Case is unchanged. On `main` it fails: the REJECTED trace is missing.
- R2 `test_a_rejected_slow_refresh_is_traced`. Reuse `_SameRevisionSlow`/`_ExpiredStrategySlow` from `test_slow_refresh_strategy_expiry.py:320-340`. Rename the existing `test_t5_rejected_slow_refresh_persists_nothing` to "…persists no Case state" and add the log assertion.
- R3 `test_a_rejected_create_is_traced_without_a_case`. `StaleSlow` as in `test_phase_04b_model_runtime.py:357-372`. `get()` returns `None` and the log holds the REJECTED Slow trace.
- R4 `test_a_channel_refusal_keeps_its_accepted_traces`. Covers the `:463` response-text mismatch and the `:467` unauthorized send. The log holds the SUCCEEDED refresh and Fast traces, the inbox stays `reserved`, and there is no outbox.

**Green and invariant tests:**

- G1: the log equals `issued` across the full direct flow (create → event → approve → complete) and the channel flow (create → refresh + Fast → delivery callbacks). This replaces the three "same write" and "carry forward" tests (`:390, 461, 509, 533`).
- G2: an append with a foreign `case_id` raises `ValueError` and writes nothing (both adapters). An empty append is a no-op.
- G3: the append-event rollback (`await_approval` raises) keeps the first write's traces while the state rolls back.
- G4: codec. A v3 envelope with a `model_traces` key is invalid. `_decode_state` rejects v2 and v4 as "unsupported". The v1 row loads and is rewritten as v3 (update `:201, 252, 295`).
- G5: browser projection and allow-list. No trace or `trace_id` appears in the snapshot, transitions, events, or API body (adapt `:581`).
- G6 (Postgres, `test_phase_04c_persistent_case_store.py`, in `make postgres-check`):
  - append/list round trip, order preserved;
  - an append without a Case row succeeds;
  - an append leaves the row's revision and payload bytes unchanged;
  - `TRUNCATE proxyloop_case_runtime_states` still works (no FK);
  - a tampered stored trace (foreign `case_id`, invalid JSON shape) makes `list` fail closed;
  - the `{"storage_version": 3}` garbage test at `:634` changes to `4`.
- G7 (Postgres): insert a raw v2 row with two inline traces, then construct a new `PostgresCaseRepository`. The row is v3 at the same revision, has no `model_traces`, `get()` decodes it, and the log holds both traces in order. Construct a third repository and check that no log rows are duplicated.
- G8 (optional; the root decides): a source guard asserting that `runtime.py` contains exactly one `.advance(` call. It keeps I6 true as PR-8, PR-13 and PR-14 add paths.

Test hygiene: tests that read the log `TRUNCATE proxyloop_model_traces` together with the Case table. Add it to the all-tables `_truncate` in `test_phase_06b1_temporal.py:70-79`. Leave other `TRUNCATE`s alone.

### 3.6 Owned files for the `implementer`

- `runtime/packages/case_runtime/src/proxyloop_case_runtime/repository.py` (Protocol, dataclass field removal, in-memory log)
- `runtime/packages/case_runtime/src/proxyloop_case_runtime/postgres_repository.py` (v3 envelope, DDL, lock, backfill, append/list)
- `runtime/packages/case_runtime/src/proxyloop_case_runtime/runtime.py` (`_advance`, removing the `model_traces` plumbing, the `_refresh_strategy_if_required` return type)
- `tests/integration/test_persisted_claim_and_traces.py` (rewrite around the log)
- `tests/integration/test_phase_04c_persistent_case_store.py` (G6, G7, version 3→4)
- `tests/integration/test_slow_refresh_strategy_expiry.py` and `tests/integration/test_phase_04b_model_runtime.py` (R2, R3, the rename)
- `tests/integration/test_phase_06b1_temporal.py` (`_truncate` only)
- `docs/architecture.md` (the `:56` paragraph), `harness/context/audit-remediation-status.md`, `harness/log/<branch>.md`

**Not owned** (escalate if a change there seems necessary): `workflow.py`, `activities.py`, `app.py`, the API shims, `contracts/`, `agent_core/` (the coordinator and the `trace_id` derivation), and every committed `*-check` artifact.

The root freezes this as a spec under `harness/context/` (for example `r12-model-trace-log-design.md`) before the implementer starts, per the plan's "architect first" rule.

### 3.7 Gates

- Focused: the files above, plus `test_phase_04a_agent_runtime.py`, `test_strategy_basis_binding.py`, `test_phase_06b1_channel_runtime.py`, `test_r10_terminal_delivery_callback.py` and `test_browser_projection_allowlist.py` (these use the fakes or the codec).
- `make lint`, `make typecheck`, `make test`, then `make preflight` once on the stable diff.
- DB lane, serially, after PR-4 and PR-5 have merged and `origin/main` has been merged in: `make postgres-check` → `make phase05a-check` → `make phase06b1-check`.
- An independent `reviewer` pass, because this is a storage-format and concurrency change.

### 3.8 Risks

1. **Hot-file serialization.** PR-4 (R-18) adds `_verify_delivery_callback_pairs` near `_reconstruct_provider` in `postgres_repository.py` [O, branch `fix/r18-callback-evidence-pairing`]. The textual overlap with PR-7 is small (envelope, bootstrap, codec), but PR-7 must merge `origin/main` after PR-4 and PR-5. PR-5's R-6 may touch `runtime.py`.
2. **Gated-skip pin.** If PR-1 (G-1 strong form) pins the `make preflight` gated-skip count, the new DB-gated tests in `test_phase_04c...` change it. Update the pin in PR-7. [I]
3. **Mixed code versions against one database.** An old-code process fails closed on v3 rows (good). If it writes a v2 row after the new bootstrap, the new code rejects that row until a restart re-runs the backfill, and the backfilled traces then sort after newer log rows. This setup is unsupported: stop all processes before upgrading. The 07A launcher starts everything from one checkout. Document it.
4. **Bootstrap does data work.** A one-time row rewrite now runs at process start in every process that constructs the repository (API, worker, demo script, tests). After the first run it is a filtered scan. A non-array `model_traces` is skipped rather than aborting startup.
5. **Stale traces under a reused Case id.** Every Case uses `SCRIPTED_CASE_ID`. A Case re-created after only the Case table is truncated inherits old log rows. The product never does this (the demo reset drops the volume). Tests must truncate both tables.
6. **Retention stays unbounded.** R-13b removes the per-write O(n) cost and removes traces from Case reads. It does not prune. Pruning is a separate policy decision, stated as such in the docs.
7. **Latency.** Up to two extra short transactions per model-calling command. This is negligible against the 30 s activity limit, but it is real. Batching the appends per command would reintroduce per-site discipline (Option 2's weakness), so it is not proposed.
8. **Out of scope, stated.** An adapter that *raises* (transport or timeout, for example `test_phase_04b...:345-352`) produces no `CoordinatorOutcome` and so no trace. `ModelResult.FAILED` is never emitted today. That is a coordinator gap, not R-12. Record it as a known limit, or as a follow-up in the `agent_core` coordinator.
9. **Semantics change visible in tests.** Traces from a CAS loser and from a rolled-back write are now kept. That is intended (I11), but two existing test names say "persists nothing" and must be renamed rather than weakened.
