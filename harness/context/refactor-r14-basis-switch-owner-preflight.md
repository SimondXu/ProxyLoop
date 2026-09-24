# Refactor: one owner for the 1.0/1.1 planning-basis switch (R-14)

Backlog item R-14 in `harness/context/audit-remediation-status.md` §4a.
Branch `refactor/r14-basis-switch-owner` from `main` @ `74e2073`.
Background: `harness/context/schema-1.1-design.md` (A-1, A-10 narrowing; PR2
added the runtime copy in `_basis`).

## Duplication (observed on main)

The eight planning-basis components, including the version switch on the
offer and approval components, are computed twice:

- `runtime/packages/case_runtime/src/proxyloop_case_runtime/runtime.py`
  `_basis(...)`: builds the `PlanningBasis` a runtime snapshot carries.
- `runtime/packages/contracts/src/proxyloop_contracts/contracts.py`
  `CaseContextSnapshot.snapshot_references_must_match`: recomputes the same
  components and rejects a snapshot whose `planning_basis` differs.

Both are semantically identical today: at `"1.1"` the offer/approval
components are `material_offers_fingerprint` / `approval_state_fingerprint`;
otherwise (`"1.0"`) they are `canonical_fingerprint` of the offers/approvals
sorted by id. Goal, constraints (sorted by id), delegated authority,
verified facts (status VERIFIED, sorted by id), provider config and
capability manifest are hashed the same way. The one textual difference is
the provider config input: the runtime hashes `RUNTIME_PROVIDER_CONFIG`, the
validator hashes `self.provider_config_ref`; `_snapshot` is `_basis`'s only
caller and sets `provider_config_ref=RUNTIME_PROVIDER_CONFIG`, so the values
are equal.

## Change

1. `contracts.py`: new public `planning_basis_components(*, schema_version,
   case, fact_ledger, offers, approval_requests, provider_config_ref,
   capability_manifest) -> dict[str, str]`, the verbatim validator
   computation. The validator calls it.
2. `__init__.py`: export it (added to `__all__`).
3. `runtime.py` `_basis`: calls it with `provider_config_ref=
   RUNTIME_PROVIDER_CONFIG`, then builds `PlanningBasis` as before. Imports
   that become unused (`approval_state_fingerprint`,
   `material_offers_fingerprint`) are removed from the runtime only if no
   other runtime use remains.

Kept: every existing public name (`planning_basis_fingerprint`,
`material_offers_fingerprint`, `approval_state_fingerprint`,
`strategy_basis_binding`); `_basis` keeps its signature.

## Non-goals

No behaviour change, no contract schema change, no generated
JSON Schema/TypeScript or fixture byte change. The test/fixture builders
that assemble a `PlanningBasis` by hand (`tests/`, `ml/`, `scripts/`) are
left alone: they are independent oracles or frozen evaluation code.

## Trade-off

The validator was an independent re-computation of the runtime's basis;
after the change both use one function, so that cross-check no longer
catches a formula error in the shared function itself. It still catches a
runtime that passes the wrong inputs (for example a provider config or
manifest that differs from the snapshot's). Before this change nothing else
pinned the full formula: no committed JSON fixture carries component
fingerprints (the contracts drift gate checks schema shape only), and
`tests/contract/test_contract_set_1_1.py` `_components` pins only the
version switch and the provider config (empty verified facts, constraints
in fixture order). The change therefore adds an independent reference test,
`runtime/packages/contracts/tests/test_planning_basis_components.py`
(added after independent review): hand-ordered expectations for mixed-status
facts, constraints and 1.0 offers/approvals that arrive out of id order, a
non-default provider config, both versions, and snapshot rejection of a
basis built without the filter or a sort.

## Acceptance

- Focused tests unchanged in count and outcome: contracts package tests,
  `tests/contract`, `test_strategy_basis_binding.py`,
  `test_phase_04a_agent_runtime.py`, `test_phase_05a_case_runtime.py`
  (non-DB). Baseline on main: 172 passed, 2 skipped (DB-gated).
- `make contracts-check`: no generated-artifact drift.
- A scratch equivalence probe (verbatim copy of the pre-change `_basis`
  formula) reproduces the post-change basis of runtime-built snapshots at
  1.0 and 1.1.
- `make format-check lint typecheck`, `make preflight-fast`, `make test`.
- Not run here (root schedules): `postgres-check`, `phase05a-check`,
  `phase06b1-check`.
