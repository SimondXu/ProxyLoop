# Feat log: runtime produces contract set 1.1 (PR2: A-1, A-10, A-6 producer)

Spec: `harness/context/feat-runtime-1-1-preflight.md`. Design and root
decisions: `harness/context/schema-1.1-design.md`. Branch `feat/runtime-1-1`
from `main` @ `69924fe` (PR1 #65), rebased onto `812ba54` (#66, direct mode
through `apply_command`) and then onto `db95033` (#67, simulator). Neither
rebase had conflicts. #66 added
`ThinAgentRuntime.now()` in `runtime.py`, which this slice does not touch.

## What changed

- `case_runtime/runtime.py`:
  - `_snapshot` writes 1.1 by default. `manifest` is now required, as
    deferred from the A-11 review. Two keyword arguments are new: `receipt`
    and `schema_version`.
  - `_basis` takes `schema_version`. At 1.1 it uses the contracts helpers
    `material_offers_fingerprint` and `approval_state_fingerprint`. The 1.0
    formula is kept, with a code comment, only for root decision 1 below.
  - `_execute_claim` builds a `CompletionReceipt` when the verifier returns
    COMPLETE on a 1.1 claim. The new helper `_completion_receipt` copies
    every field of the Provider's `AppliedOfferConfirmation`. It adds the
    approved approval's revision and the CONFIRMATION Evidence id and
    `content_hash`. The hash is not recomputed; the contract validator
    re-derives it.
  - `_record_rejection` and `expire_approval` record the Router's decision
    (`CaseCoordinator.advance(...).route`) in both the transition and the
    result, instead of a hard-coded `fast_now`.
  - `record_channel_delivery` and `_refresh_strategy_if_required` carry
    `completion_receipt` forward.
- `agent_core/router.py`:
  - One helper, `_strategy_basis_incompatible`, is true when a 1.1
    snapshot's strategy binding differs from
    `pins.planning_basis_fingerprint`. A 1.0 strategy has no binding, so it
    is incompatible inside a 1.1 snapshot. The helper reads the snapshot's
    `schema_version`, never the pins.
  - It is used twice:
    - `_mandatory_slow_reasons` adds `strategy_basis_incompatible`;
    - `current_strategy_allows_fast` (the FAST_NOW_AND_SLOW_REFRESH
      branch) also requires a compatible binding.
- `agent_core/coordinator.py`:
  - `validate_slow_result` adds `slow_strategy_basis_mismatch` at 1.1.
  - `CoordinatorOutcome.traces: tuple[ModelTrace, ...] = ()` is added as
    the PR3 seam. Nothing populates it.
- `agent_core/scripted.py` and `openai_adapter/outputs.py`: strategies are
  stamped with `**strategy_basis_binding(request.planning_basis)` at
  construction. A 1.0 basis (ML/evaluation) still produces a 1.0 strategy
  with no new key.
- `docs/architecture.md` (Router section, planning-basis paragraph) and the
  Planning Basis entry in `CONTEXT.md` describe the 1.1 materiality and the
  binding.
- New `tests/integration/test_strategy_basis_binding.py` (16 tests).

## Red → green

- Red, on `69924fe` sources with only the first 11 tests: 10 failed and 1
  passed.
  - A-1: `fast_now` was returned where `slow_refresh` was expected.
  - The runtime wrote `1.0` snapshots.
  - Rejection recorded `fast_now`.
  - There was no stored-1.0 refresh.
  - No receipt was built.
  - The producers stamped `1.0`.
  - The one test that passed is
    `test_a_stored_1_0_pending_claim_completes_in_its_claim_version`, a
    regression guard: `main` writes only 1.0, so it trivially passes there.
    It was confirmed to fail when the final snapshot is built at 1.1 (the
    `schema_version=snapshot.schema_version` argument removed). The
    ValidationError was: "a 1.1 snapshot is complete exactly when it
    carries a completion receipt".
- The two tests added after the root decisions were checked against the old
  behaviour:
  - `test_a_bounded_acknowledgement_requires_a_compatible_strategy` fails
    without the new router condition. It gets `fast_now_and_slow_refresh`
    where `slow_refresh` is expected.
  - `test_an_approval_expiring_after_its_strategy_records_the_router_route`
    could not pass against the hard-coded `"fast_now"` string, because it
    asserts a `RoutingDecision` of `slow_refresh(strategy_expired)`.
- Green: 13 passed; 16 after the review additions.

Acceptance mapping:

| Acceptance | Test |
|---|---|
| A-1: offer revision change under a valid strategy → `slow_refresh(strategy_basis_incompatible)`; Slow's new strategy is bound | `test_a1_offer_revision_change_under_a_valid_strategy_routes_slow_refresh` |
| Coordinator rejects a strategy bound to another basis | `test_the_coordinator_rejects_a_strategy_bound_to_another_basis` |
| Expired approval → `fast_now`, no Slow call (Router, expiry transition == Router, a channel event after expiry) | `test_an_expired_approval_is_not_material_and_makes_no_slow_call` |
| `expire_approval` records the Router's route: an approval expiring after its strategy → `slow_refresh(strategy_expired)`, no adapter call | `test_an_approval_expiring_after_its_strategy_records_the_router_route` |
| A bounded acknowledgement requires a compatible 1.1 binding (router unit) | `test_a_bounded_acknowledgement_requires_a_compatible_strategy` |
| Rejected approval → `slow_refresh`; `_record_rejection` route == Router; one Slow refresh on the next (channel) event, outbox pinned to the refreshed strategy | `test_a_rejected_approval_routes_slow_refresh_and_refreshes_once` |
| Full approved flow → 1.1 COMPLETE with a bound receipt; strict JSON round-trip; PostgreSQL envelope encode/decode | `test_a_full_approved_flow_ends_in_a_bound_1_1_completion_receipt` |
| Stored 1.0 Case (through the PostgreSQL envelope codec, no DB) refreshes on the next event and completes at 1.1 | `test_a_stored_1_0_case_refreshes_its_strategy_on_the_next_event` |
| Stored 1.0 Case awaiting approval completes at 1.1 | `test_a_stored_1_0_case_awaiting_approval_completes_at_1_1` |
| Stored 1.0 pending claim completes at 1.0; the PostgreSQL envelope codec accepts the terminal write | `test_a_stored_1_0_pending_claim_completes_in_its_claim_version` |
| Coordinator rejects a 1.0 strategy on a 1.1 snapshot (the frozen `ml/slow_output.py` shape) | `test_the_coordinator_rejects_a_1_0_strategy_on_a_1_1_snapshot` |
| Router does not flag a 1.0 snapshot carrying a 1.0 strategy | `test_the_router_does_not_flag_a_1_0_snapshot_with_a_1_0_strategy` |
| Stored 1.0 Case refreshes exactly once through channel ingest; outbox pinned to the refreshed strategy; a second event makes no Slow call | `test_a_stored_1_0_case_refreshes_exactly_once_through_channel_ingest` |
| Producers stamp the basis version (scripted and OpenAI compiler, 1.0 and 1.1) | `test_strategy_producers_stamp_the_version_of_their_planning_basis[_scripted, _compiled]` |

The stored-1.0 states are built by `_as_stored_1_0`. It rewrites a runtime
state with the 1.0 strategy, 1.0 basis formula, and pins the pre-1.1
runtime wrote. The strict 1.0 snapshot validator accepts the result, and it
is then passed through `PostgresCaseRepository._encode_state` /
`_decode_state`, the same codec a real row goes through.

## Existing tests

No existing test needed an edit. No committed test asserted any of these:

- a 1.0 runtime snapshot;
- a `fast_now` route after a rejection or an expiry.

The DB-gated tests were scanned (04c, 05a, 06b1). They assert neither
`schema_version` nor routes. The workflow worker and the direct-mode
expiry timer from #66 never read `route`. The Web treats `route` as an
opaque string.

## Root decisions (2026-09-23)

1. **Accepted: an in-flight 1.0 claim completes at its own version.**
   - Why: the PostgreSQL envelope requires
     `execution_source_pins == snapshot.pins` for a terminal Case. A claim
     written by the 1.0 runtime pins the 1.0 basis, so finishing it at 1.1
     would make `_encode_state` reject the terminal write.
   - What the code does:
     - `_execute_claim` passes `schema_version=snapshot.schema_version`;
     - only a 1.1 claim produces a receipt;
     - `_basis` keeps the 1.0 formula for this path only, and a code
       comment says so.
   - Every new claim is taken at 1.1.
2. **`expire_approval` records the Router's decision**, like
   `_record_rejection`. An approval that expires after its strategy now
   records `slow_refresh(strategy_expired)`. Previously it recorded a
   hard-coded `fast_now`. The route is recorded only; no adapter is called.
3. **`current_strategy_allows_fast` requires a compatible binding at 1.1.**
   This keeps the Router rules consistent. The branch is unreachable today:
   only `create_case` sets `bounded_acknowledgement_allowed`, and it has no
   strategy at that point.

Also in this slice: `record_channel_delivery` passes
`receipt=snapshot.completion_receipt`, so that a delivery callback on a 1.1
COMPLETE Case keeps a valid snapshot.

## Review

Independent review (`reviewer`): **Approve**. Findings handled:

1. Fixed: the preflight's non-goal about `expire_approval` was stale. It
   now records the Router's decision (root decision 2).
2. Applied: `_refresh_strategy_if_required` passes
   `receipt=event_snapshot.completion_receipt`, like
   `record_channel_delivery`.
3. Deferred, see Known limits: the duplicated 1.0/1.1 basis switch.
4. Applied, three tests added:
   - a 1.0 strategy on a 1.1 snapshot is rejected by `validate_slow_result`;
   - the Router does not flag a 1.0 snapshot carrying a 1.0 strategy;
   - a stored 1.0 Case refreshes exactly once through channel ingest.

## Checks (after the review, on `db95033`)

| Check | Result |
|---|---|
| `tests/integration/test_strategy_basis_binding.py` | 16 passed |
| runtime unit suite (`make unit-test` runtime half) | 1108 passed, 46 skipped (DB/Temporal-gated) |
| `make lint` | pass |
| `make typecheck` | pass (63 + 59 files) |
| `make format-check` | pass |
| `make preflight-fast` | pass |
| `make test` | exit 0: runtime 1108 passed, 46 skipped; ml 388 passed, 1 skipped |
| harness-check | manifest, episodes, and ceiling gate valid |
| hosted-rescore-check | r4 execution contract unchanged `6b50437f…`; rescored artifact equals derivation |
| validity-smoke-check | valid |
| phase03c-prompt-set-check | consistent |
| phase03c-rescore-check | heldout and dev checked, 0 cloud disagreements |
| `git status --porcelain data/` | empty |

- The drift lines `drifted_since_r1`, `drifted_since_03b`, and
  `drifted_since_bundle` are pre-existing informational states; PR1
  recorded them on `main`.
- Earlier runs:
  - on `69924fe`: runtime 961 passed;
  - on `812ba54` after the root decisions: runtime 978 passed.

  Both had `make test` exit 0 with the same gate lines. The larger count on
  `db95033` comes from #67's simulator tests.

Not run: `make preflight`, and the Compose gates (`postgres-check`,
`phase05a-check`, `phase06b1-check`), which the root runs serially. No
`PROXYLOOP_TEST_*` variable was set. The web check (`make web-check`) was
not run separately; `make test` includes the contracts `tsc` check.

## Known limits

- **Backlog (pre-existing defect on `main`, not fixed here):** a channel
  delivery callback on a COMPLETE Case fails under PostgreSQL.
  - `record_channel_delivery` appends an event, which advances the event
    cursor.
  - The pins then no longer equal `execution_source_pins`.
  - `_reconstruct_provider`'s terminal check ("terminal execution pins do
    not match snapshot identity") rejects the write in `_encode_state`.
  - For a stored 1.0 COMPLETE Case the same write would also fail the 1.1
    receipt rule.
- After the upgrade, the scripted Slow adapter derives a new `strategy_id`,
  because its id hashes the pins fingerprint, which changes with the
  formula.
- **Follow-up (review finding 3, deferred):** the 1.0/1.1 basis switch is
  duplicated. `runtime.py` has `SnapshotVersion` and the version branch in
  `_basis`; `contracts.py` has its own branch in the snapshot validator. In
  addition, `_snapshot` defaults to 1.1. A later PR should consolidate this
  into one contracts-level basis builder; PR2 does not touch contracts.

## Root gate (2026-09-23)

Final diff on `db95033`, run serially with the Compose profiles up and
`PROXYLOOP_TEST_DATABASE_URL` / `PROXYLOOP_TEST_TEMPORAL_ADDRESS` set:
`make preflight` exit 0 (runtime 1154 passed incl. DB-gated tests; ML and
web green; evidence gates unchanged, `data/` clean); `postgres-check` 27,
`phase05a-check` 36, `phase06b1-check` 34 — all passed.
