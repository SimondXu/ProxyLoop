# Fix: the Router waits on approval state, not an event label (B1-12), and Router precedence is tested behaviourally (audit §3, lane A)

P2 backlog items in `harness/context/audit-remediation-status.md` §4: B1-12
(`harness/code_review/repo-audit-B1.md`) and "grep-based architecture tests
replaced by Router precedence tests" (`harness/code_review/repo-audit-A.md` §3,
`harness/code_review/repo-audit-B1.md` N2, `docs/research/2026-09-21-repository-audit.md` §6).
Branch `fix/p2-router-precedence` from `main` @ `74e2073`.

## Defect (observed on main)

- **B1-12.** `DeterministicRouter._select` skipped `wait_for_approval`
  whenever the triggering event was a CONSUMER event labelled
  `approval_decision` (`RouteRequest.trigger_is_approval_decision`), even when
  the snapshot's approval was still PENDING and current.
  `test_approval_trigger_must_be_the_latest_verified_visible_event` asserted
  that bypass (`FAST_NOW`). Every public and durable command surface pins
  `event_type` to `Literal["consumer_message"]` (`proxyloop_api/app.py:83`,
  `case_runtime/commands.py:43`, `workflow_worker/models.py:62`), so the
  bypass was reachable only through the internal
  `CaseRuntime.append_event(event_type="approval_decision")` after a compliant
  offer builds a PENDING approval.
- **Lane A §3 / N2.** `tests/contract/test_phase_03a1_architecture.py::
  test_phase_03a1_router_precedence_and_fast_action_boundary_are_executable`
  checked the order of string literals in `router.py` and the presence of
  words in `coordinator.py`; `ROUTER_PRECEDENCE` is not read by the Router, so
  the test could not detect a precedence change. The 03A0 suite asserts ADR
  sentences and read as architecture enforcement.

## Decision

Approval state is the only authority for the wait (ADR "The transcript is
evidence-bearing event history, not the authoritative representation of ...
approvals"). The runtime records a decision (PENDING → APPROVED/REJECTED)
before it routes, so a decided approval never blocks and the label check adds
nothing except the bypass. Delete the bypass; no new condition.

## Exact change

1. `router.py`: remove `RouteRequest.trigger_is_approval_decision` and its now
   unused `EventActor` import; `if approval_blocking:` returns
   `WAIT_FOR_APPROVAL`. `triggering_event` and its latest-event validation stay.
2. `tests/integration/test_phase_03a1_agent_core.py`:
   - the existing approval-trigger test now expects `WAIT_FOR_APPROVAL` /
     `("current_approval_pending",)` (red on main);
   - `test_a_recorded_approval_decision_releases_the_approval_wait`
     (APPROVED and REJECTED, with and without the trigger → `FAST_NOW`);
   - `test_router_precedence_ladder_matches_the_frozen_table`: start with all
     six row conditions true, clear the highest one per step; the outcomes
     must equal `ROUTER_PRECEDENCE`;
   - `test_stale_approval_and_expired_strategy_route_to_slow`.
3. `tests/contract/test_phase_03a1_architecture.py`: delete the grep router
   test (replaced by 2).
4. `tests/contract/test_phase_03a0_architecture.py`: module docstring labels
   it a docs-freeze suite; the ADR-order test iterates `ROUTER_PRECEDENCE`
   instead of a duplicated literal, chaining ADR order → `ROUTER_PRECEDENCE` →
   Router behaviour (ladder).

## Non-goals

No contract, coordinator, runtime, `ml/`, `data/`, or ADR text change.

## Acceptance

- Red on main for the B1-12 assertion only; green after the fix.
- All 03A1/04A/05A non-DB tests and `make test` artifact gates pass with no
  committed artifact change.
- `make format-check lint typecheck`, `make preflight-fast`, `make test` pass.

## Open for the root

ADR `docs/decisions/2026-08-23-fast-slow-orchestration.md` row 3 still says
"... and the triggering event is not the Consumer's approval decision."
That clause described the removed bypass; it needs a wording decision (docs
are outside this change).
