# Fix: one offer-policy authority, one material-terms hash, one change list (G2a / P0-7)

Bounded change under `harness/context/audit-remediation-decisions.md`
(decision 3). Design: `harness/context/group2-evaluator-proposal.md` §G2a
(architect proposal, root-adopted with the open-question answers below).
Branch `fix/one-offer-policy-authority` from `main` @ `5eef7c0`. Resolves
audit B1-5/D1-2, B1-4, D1-7.

## Root decisions on the proposal's open questions

1. `runtime/packages/contracts` is in scope as the home of the pure policy;
   `make contracts-check` must stay green (generated `contracts/` unchanged).
8. `ScriptedOracleConsumer(*, offer_policy=None)` keeps the keyword as a
   test seam; the default is the shared policy; the legacy predicate is
   deleted.

## Frozen design

New pure modules in `runtime/packages/contracts/src/proxyloop_contracts/`:

- `offer_policy.py`: `OfferComplianceContext`, `OfferComplianceTerms`,
  `offer_compliance_violations` moved verbatim from
  `telecom_domain/offer_policy.py` (same reason codes, same order); plus
  `SUPPORTED_APPLIED_CHANGES: frozenset[str] = {"plan_change",
  "revised_plan_change", "predefined_promotion_credit"}`,
  `REMOVE_ADD_ON_PREFIX = "remove_add_on:"`,
  `is_supported_applied_change(change) -> bool`,
  `unsupported_applied_changes(changes) -> tuple[str, ...]` (order-preserving,
  deduplicated).
- `material_terms.py`: `offer_material_terms(offer) -> tuple[MaterialTerm, ...]`
  (6 terms, moved from `telecom_domain/domain.py`) and
  `material_terms_hash(terms) -> str` (sorted by `(name, value)`, canonical
  JSON, sha256 — byte-identical to today's `telecom_domain.material_terms_hash`,
  `agent_core.capabilities._material_terms_hash`, and the frozen
  `ml/.../slow_output._material_terms_hash`).

`proxyloop_telecom_domain` re-exports all of the above from
`offer_policy.py`, `domain.py`, `__init__.py` (public interface unchanged).

Call-site changes:

- `agent_core/observation.py`: default `offer_policy` →
  `offer_compliance_violations`; delete `_legacy_offer_is_valid` and the
  module-level `_SUPPORTED_APPLIED_CHANGES`; the `_OfferCompliancePolicy`
  Protocol uses the contracts types; `_supported_applied_changes` →
  `not unsupported_applied_changes(...)`.
- `agent_core/capabilities.py` `_material_terms_hash` →
  `material_terms_hash(intent.material_terms)`.
- `openai_adapter/outputs.py` (`_material_terms`, the hash at ~:239, the
  3-term derivation at ~:290-295) → `offer_material_terms` +
  `material_terms_hash` so a compiled intent matches the executor's
  `terms_derivation=offer_material_terms` and hash (B1-4).
- `provider_simulator/environment.py` `_offer_constraint_violations`: replace
  the `"account_cancellation" in offer.applied_changes` check with
  `if unsupported_applied_changes(offer.applied_changes): reasons.append("unsupported_action")`
  (reason string unchanged).
- Frozen `ml/evaluation/.../slow_output.py` untouched; its private hash is
  recorded in the log as a byte-equal historical copy.

## Regression tests (write first; fail on pre-fix code)

- `tests/integration/test_phase_01b_observation.py`: an offer with
  `total_cost_12_months_minor != monthly*12 + fees − known credit` that
  passes the legacy bounds (e.g. monthly 7000, fees 500, total 84000, current
  8000, target 7500) → `ScriptedOracleConsumer().decide(...)` returns
  `decline` with `("no_valid_offer",)` (legacy returned `accept_offer`);
  `assert not hasattr(ScriptedOracleConsumer, "_legacy_offer_is_valid")`.
- New `tests/integration/test_offer_policy_authority.py`: (a)
  `compile`d Slow output → intent `material_terms == offer_material_terms(offer)`
  and `material_terms_hash == material_terms_hash(intent.material_terms)`;
  executing it through `CapabilityExecutor(adapter, terms_derivation=offer_material_terms)`
  yields no `current_offer_terms_mismatch` / `action_material_terms_hash_mismatch`
  (fails on main because `outputs.py` hashes an unsorted 3-term list); (b)
  hash vectors: fixed 3-term and 6-term inputs equal literal digests captured
  from today's `telecom_domain.material_terms_hash` (write the literals into
  the test from a run on `main` first); (c) exactly one definition each of
  `offer_compliance_violations`, `material_terms_hash`, `offer_material_terms`,
  `SUPPORTED_APPLIED_CHANGES` outside the frozen `slow_output.py`
  (grep-based).
- `tests/integration/test_phase_01b_environment.py`: an accept of an offer
  whose `applied_changes` contains a change that is neither forbidden by the
  Case nor in `SUPPORTED_APPLIED_CHANGES` (e.g. `contract_term_extension`)
  is rejected with `unsupported_action` (today only `account_cancellation`
  is).
- `ml/tests/test_fresh_phase03a1_fixtures.py` stays green and unmodified
  (r2 bundle fingerprint `729e4e43849cf094c25ee0532157658d7867bb9749c7f5c0e48c979f77183a8d` unchanged).

## Acceptance

1. `grep -rn "_legacy_offer_is_valid\|_SUPPORTED_APPLIED_CHANGES" runtime ml scripts` → 0 hits.
2. After running every check below, `git status --porcelain data/ contracts/` is empty (zero artifact change — the architect measured 0/32 label, offer-id and reason-code differences).
3. `make contracts-check` passes with the generated schema unchanged.

## Verification

Focused: `uv run --project runtime --all-packages pytest -c runtime/pyproject.toml -q tests/integration/test_phase_01b_observation.py tests/integration/test_phase_01b_environment.py tests/integration/test_phase_03a1_agent_core.py tests/integration/test_offer_policy_authority.py runtime/packages/telecom_domain/tests runtime/packages/provider_simulator/tests`.
Static: `make lint`, `make typecheck`, `make format-check`, `python3 scripts/validate_layout.py`.
Artifacts: `make contracts-check benchmark-check data-pilot-check harness-check baselines-check errata-check hosted-rerun-check validity-smoke-check phase03b-readiness-check phase03b-experiment-check phase03c-invariants-check phase03c-prompt-set-check` (`PYTHONPATH=.` where a script imports `scripts.*`).
Root runs `make preflight` once.

## Escalate instead of deciding

Any artifact byte change; any need to touch a file in
`hosted_rerun._R4_EXECUTION_PATHS`; any change to a reason code or its
order; `scripts/validate_layout.py` rejecting the new modules; any test that
must flip semantics other than the ones listed.
