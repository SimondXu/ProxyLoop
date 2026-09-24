# Refactor log: one owner for the 1.0/1.1 planning-basis switch (R-14)

Spec: `harness/context/refactor-r14-basis-switch-owner-preflight.md`.
Branch `refactor/r14-basis-switch-owner` from `main` @ `74e2073`.

## What changed

- `runtime/packages/contracts/src/proxyloop_contracts/contracts.py`: new
  public `planning_basis_components(*, schema_version, case, fact_ledger,
  offers, approval_requests, provider_config_ref, capability_manifest)`
  holding the component formula and the 1.0/1.1 switch, moved verbatim from
  `CaseContextSnapshot.snapshot_references_must_match`, which now calls it.
- `runtime/packages/contracts/src/proxyloop_contracts/__init__.py`: exports
  it.
- `runtime/packages/case_runtime/src/proxyloop_case_runtime/runtime.py`:
  `_basis` calls it with `provider_config_ref=RUNTIME_PROVIDER_CONFIG`;
  imports it orphaned (`FactStatus`, `canonical_fingerprint`,
  `material_offers_fingerprint`, `approval_state_fingerprint`) removed from
  the runtime. All public names are kept.

No contract schema, generated artifact or fixture change.

## Equivalence

- Pre-change copies were semantically identical (spec, "Duplication").
- Scratch probe (not committed): a pytest plugin loads `runtime.py` at
  `74e2073` as a separate module and wraps the new `_basis` so every call
  also runs the old `_basis` and asserts equal models and equal JSON. Over
  `tests/integration tests/contract runtime/packages/contracts/tests`: 836
  passed, 51 skipped (DB and Temporal gated), 578 cross-checks (1.1: 575,
  1.0: 3), zero mismatches. Negative control (reference 1.1 offer component
  mutated): `test_strategy_basis_binding.py` 16 failed, so the probe bites.
- Focused suite (contracts package tests, `tests/contract`,
  `test_strategy_basis_binding.py`, `test_phase_04a_agent_runtime.py`,
  `test_phase_05a_case_runtime.py`): 172 passed, 2 skipped before and after.

## Checks

- `make test`: exit 0. Runtime unit tests 1200 passed, 51 skipped (DB and
  Temporal gated); ML tests 397 passed, 1 skipped (`yaml` not installed,
  pre-existing); contracts drift check "Contract artifacts match the
  canonical Pydantic source"; every artifact `--check` gate through
  `negotiation-check` green.
- `make format-check lint typecheck`: exit 0 (ruff format 116 + 90 files
  formatted, ruff "All checks passed!" twice, mypy 66 + 59 files clean).
- `make contracts-check`: exit 0, "Contract artifacts match the canonical
  Pydantic source", `tsc --noEmit` clean.
- `make preflight-fast`: exit 0.
- Not run (root schedules): `make postgres-check`, `make phase05a-check`,
  `make phase06b1-check`, `make preflight`.

## Independent review follow-up

Reviewer verdict: Approve with two Important items, both applied.

1. New `runtime/packages/contracts/tests/test_planning_basis_components.py`
   (12 tests). A hand-ordered reference that never calls
   `planning_basis_components` or relies on the snapshot validator:
   mixed-status ledger (VERIFIED facts in reverse `fact_id` order plus a
   CANDIDATE and a REJECTED fact), two constraints in reverse id order, two
   offers and two approvals in reverse id order, provider config
   `carrier-b:custom-config-7`, both versions. Asserts dict equality with
   `planning_basis_components`, that `CaseContextSnapshot` accepts the
   reference basis, and that it rejects a basis built without the VERIFIED
   filter (id-sorted), without the fact sort, without the constraint sort,
   or (1.0) without the offer/approval sort. 1.1 offer/approval components
   use `material_offers_fingerprint` / `approval_state_fingerprint`, which
   `tests/contract/test_contract_set_1_1.py` pins separately.
   Reviewer mutation plugin (`r14mutant.py`, copied unchanged, same
   SHA-256), new test file only: unmutated 12 passed; `nofilter` 6 failed;
   `nofactsort` 6 failed; `no10sort` 3 failed (1.0 only, as expected);
   `noconsort` 6 failed; also `swap` 4 failed and `provconst` 4 failed.
2. Spec corrected: no committed JSON fixture carries component fingerprints
   (the drift gate checks schema shape only), and `test_contract_set_1_1.py`
   `_components` pins only the version switch and provider config.

Merged `origin/main` @ `ff35dca` (docs only, no overlap), then reran:

- Focused suite: 184 passed, 2 skipped (172 before plus the 12 new).
- `make format-check lint typecheck`: exit 0 (ruff format 117 + 90 files,
  ruff "All checks passed!" twice, mypy 66 + 59 files clean).
- `make contracts-check`: exit 0, "Contract artifacts match the canonical
  Pydantic source".
- `make preflight-fast`: exit 0.
- `make test`: exit 0; runtime 1212 passed, 51 skipped (DB/Temporal gated);
  ML 397 passed, 1 skipped (`yaml`); every artifact `--check` gate green.
- Still not run (root schedules): `postgres-check`, `phase05a-check`,
  `phase06b1-check`, `make preflight`.

## Residual risk and known limits

- The snapshot validator no longer independently re-derives the runtime's
  basis formula; it still checks the runtime's inputs. The formula is now
  pinned by `test_planning_basis_components.py`.
- Pre-existing, out of scope: `scripts/run_phase_03a1_harness.py`,
  `tests/integration/test_offer_policy_authority.py` and
  `tests/integration/test_phase_03a1_agent_core.py` build a `PlanningBasis`
  by hand with verified facts in ledger order (and offers, approvals and
  constraints unsorted). They are not the canonical formula; this change
  does not touch them and did not investigate which inputs would expose the
  difference.
