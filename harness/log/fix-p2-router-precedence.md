# Fix log: the Router waits on approval state, not an event label (B1-12), and Router precedence is tested behaviourally

Spec: `harness/context/fix-p2-router-precedence-preflight.md`.
Branch `fix/p2-router-precedence` from `main` @ `74e2073`.

## What changed

- `runtime/packages/agent_core/src/proxyloop_agent_core/router.py`: removed
  `RouteRequest.trigger_is_approval_decision` and the `EventActor` import;
  `_select` returns `WAIT_FOR_APPROVAL` whenever a PENDING approval is current
  (`if approval_blocking:`). Precedence, reason codes, and every other branch
  are unchanged.
- `tests/integration/test_phase_03a1_agent_core.py`: B1-12 assertion flipped
  in `test_approval_trigger_must_be_the_latest_verified_visible_event`; three
  new tests (below).
- `tests/contract/test_phase_03a1_architecture.py`: grep router test deleted.
- `tests/contract/test_phase_03a0_architecture.py`: labelled docs-freeze; the
  ADR-order test reads `ROUTER_PRECEDENCE`.

## Red → green

| Test | main (`74e2073`) | this branch |
|---|---|---|
| `test_approval_trigger_must_be_the_latest_verified_visible_event` | FAIL: `FAST_NOW is not WAIT_FOR_APPROVAL` (the bypass) | pass |
| `test_a_recorded_approval_decision_releases_the_approval_wait` | pass | pass |
| `test_router_precedence_ladder_matches_the_frozen_table` | pass | pass |
| `test_stale_approval_and_expired_strategy_route_to_slow` | pass | pass |

Red run: `1 failed, 26 passed`; green: `27 passed`. The ladder test passes on
main because precedence itself was correct; it is a regression guard. A
mutation that evaluates the approval wait before `verify_only` fails it
(`1 failed`); the Router was restored in the same process.

## Grep tests → behavioural tests

| Grep-based test | Invariant | Replacement |
|---|---|---|
| `test_phase_03a1_architecture.py::test_phase_03a1_router_precedence_and_fast_action_boundary_are_executable` (deleted) | outcome literals ordered in `router.py` | `test_router_precedence_ladder_matches_the_frozen_table` (each row wins while all lower rows hold; outcomes == `ROUTER_PRECEDENCE`) |
| same test | words `action_intent`, `stale` in `coordinator.py` | existing `test_coordinator_rejects_stale_fast_and_forbidden_action_intent` (`stale_fast_result`, `fast_action_intent_forbidden`), `test_missing_slow_is_typed_and_slow_results_use_compare_and_swap` (`stale_slow_result`) |
| same test | word `planning_basis_fingerprint` in `coordinator.py` | new `test_slow_result_on_another_planning_basis_is_rejected` (`validate_slow_result` → `planning_basis_fingerprint_mismatch`); `test_each_material_snapshot_change_invalidates_the_planning_basis` covers only the fingerprint computation, not the coordinator check |

Kept, because they guard docs invariants no behaviour test can express: all
eleven tests in `test_phase_03a0_architecture.py` (ADR, build contract,
preflight, PLANS.md text). The file now says so in its docstring, and
`test_phase_03a0_freezes_router_precedence_and_single_outcome` iterates
`ROUTER_PRECEDENCE`, so ADR order → table → behaviour is one chain. The other
03A1 architecture tests (layout, dependency/import bans, Makefile wiring,
contract exports) are layout invariants and stay.

## Artifacts and reachability

No committed artifact changed (`git status` after `make test` shows only the
four source/test files). `ml/evaluation/.../runner_v2.py` routes an
`approval_decision` trigger only after setting the approval APPROVED, so its
route is unchanged. The product runtime never routes a pending approval with
an `approval_decision` trigger: public/durable commands accept only
`consumer_message`, `append_event` refuses while an approval is PENDING, and
the decision paths record APPROVED/REJECTED before routing.

## Checks

- Focused: 03A1 agent core, 03A1 harness, 04A, 05A, strategy-basis,
  model-trace, `tests/contract` → `231 passed, 24 skipped`
  (skips: `PROXYLOOP_TEST_DATABASE_URL is required`).
- `make format-check lint typecheck` → exit 0 (`116`/`90 files already
  formatted`, ruff `All checks passed!` ×2, mypy `no issues found in 66` and
  `59 source files`).
- `make preflight-fast` → exit 0.
- `make test` (after `pnpm install --frozen-lockfile`) → exit 0; runtime
  `1200 passed, 51 skipped`, ml `397 passed, 1 skipped`; all artifact gates
  passed. The `drifted_since_r1` / `drifted_since_03b` / `drifted_since_bundle`
  lines are the gates' documented historical states, not changes here.
- Not run in the first commit: `make postgres-check`, `make phase05a-check`, `make
  phase06b1-check` (root schedules the shared DB), `make preflight`.

## Root decisions applied (second commit)

- ADR row 3 amended in place, plus a dated `## Amendment 2026-09-24 — Approval
  wait keyed on approval state` section (style of the 2026-09-21 amendment in
  `2026-08-22-implementation-defaults.md`). No test pins the removed clause
  (`grep "triggering event is not" tests scripts ml` is empty); the 03A0
  docs-freeze tests only pin outcome names and order within `### Routing`, so
  no pin changed. `tests/contract` → `106 passed`.
- `grep -rn trigger_is_approval_decision ml scripts` plus every
  `_R4_EXECUTION_PATHS` file → no match (exit 1); no `ml/` or `scripts/` file
  differs from `origin/main`.
- `make phase05a-check` (shared Compose PostgreSQL + Temporal, variables on the
  command line only) → exit 0, `42 passed in 97.93s`, 0 skipped.
- `make preflight-fast` → exit 0. `make test` not rerun: only the ADR and
  harness docs changed after the run recorded above.

## Independent review: Approve, four Minors applied (third commit)

1. `test_stale_approval_and_expired_strategy_route_to_slow` now also covers a
   PENDING approval with `expires_at <= created_at` and one whose
   `offer_ref.offer_revision` no longer matches the current offer; both route
   `SLOW_REFRESH` with `stale_approval`.
2. Ladder docstring (and the expired-strategy comment) no longer calls rows 4
   and 5 a precedence: they are mutually exclusive on whether a bounded
   acknowledgement is allowed under a current strategy.
3. ADR amendment quotes the removed clause verbatim and the mandatory-Slow
   list names `stale_approval` (a Router-internal reason code in
   `_mandatory_slow_reasons`). `slow_work_pending` is not added: it has no
   producer (audit A-8).
4. Mapping row corrected (above); new
   `test_slow_result_on_another_planning_basis_is_rejected`.

Mutation checks (scratch edit, run, restore in the same process; `runtime/`
matches HEAD afterwards):

| Mutation | Test | Result |
|---|---|---|
| delete `and approval.expires_at > created_at` (`router.py` `_approval_is_current`) | `test_stale_approval_and_expired_strategy_route_to_slow` | `1 failed` (`AssertionError: expired`) |
| delete `and offer_current` | same | `1 failed` (`AssertionError: offer_revision`) |
| drop `planning_basis_fingerprint_mismatch` append (`coordinator.py`) | `test_slow_result_on_another_planning_basis_is_rejected` | `1 failed` (reasons `('stale_slow_result',)`) |

Unmutated: `tests/integration/test_phase_03a1_agent_core.py` → `28 passed`.

Merged `origin/main` @ `ff35dca` (#79, docs only; no conflict). Checks on the
merged tree:

- Focused (03A1 agent core/harness, 04A, 05A, strategy-basis, model-trace,
  `tests/contract`) → `232 passed, 24 skipped` (DB-URL skips).
- `make format-check lint typecheck` → exit 0 (`116`/`90 files already
  formatted`, ruff `All checks passed!` ×2, mypy `66` and `59 source files`
  clean).
- `make preflight-fast` → exit 0.
- `make test` → exit 0; runtime `1203 passed, 51 skipped`, ml `397 passed, 1
  skipped`.
- `make preflight` → exit 0; runtime `1220 passed, 51 skipped`, ml `397
  passed, 1 skipped`, Web `140 passed (140)`.
- Not rerun: DB gates (`make phase05a-check` passed on this change above;
  `postgres-check`, `phase06b1-check` not run).
