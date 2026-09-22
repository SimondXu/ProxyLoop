# Fix log: one offer-policy authority, one material-terms hash, one change list (G2a / P0-7)

Spec: `harness/context/fix-one-offer-policy-authority-preflight.md`.
Design: `harness/context/group2-evaluator-proposal.md` §G2a. Programme:
`harness/context/audit-remediation-decisions.md` (decision 3). Branch
`fix/one-offer-policy-authority` from `main` @ `5eef7c0`. Resolves audit
B1-5/D1-2, B1-4, D1-7.

## What changed

- New pure modules in `proxyloop_contracts`: `offer_policy.py`
  (`OfferComplianceContext`, `OfferComplianceTerms`,
  `offer_compliance_violations` moved verbatim — reason codes and order
  unchanged — plus `SUPPORTED_APPLIED_CHANGES`, `REMOVE_ADD_ON_PREFIX`,
  `is_supported_applied_change`, `unsupported_applied_changes`) and
  `material_terms.py` (`offer_material_terms`, `material_terms_hash`).
  `contracts` still depends only on pydantic; the generated `contracts/`
  schema is unchanged (`make contracts-check`).
- `proxyloop_telecom_domain` re-exports them (public interface unchanged).
- `agent_core/observation.py`: `ScriptedOracleConsumer` defaults to the
  shared policy; the frozen Phase 01B legacy predicate, the private change
  list and the two private transport dataclasses are deleted; the
  `offer_policy=` keyword stays as an injection seam.
- `agent_core/capabilities.py`: executor hash → `material_terms_hash`.
- `openai_adapter/outputs.py`: the compiled Slow intent derives the
  domain's 6 material terms and the shared hash instead of an unsorted
  3-term `canonical_fingerprint` (B1-4: it now matches the runtime
  executor's `terms_derivation=offer_material_terms`).
- `provider_simulator/environment.py`: the verifier rejects any applied
  change outside the shared supported list with `unsupported_action`
  (previously only `account_cancellation`).

## Red → green

| Test | Pre-fix | Post-fix |
|---|---|---|
| oracle declines an offer whose 12-month total omits fees (legacy bounds satisfied) | `ACCEPT_OFFER ('valid_offer',)` | `DECLINE ('no_valid_offer',)` |
| `_legacy_offer_is_valid` absent | present | absent |
| compiled Slow accept executes through `CapabilityExecutor(adapter, terms_derivation=offer_material_terms)` | `REJECTED ('action_material_terms_hash_mismatch', 'current_offer_terms_mismatch')`; terms `monthly_price` ≠ `monthly_price_minor` | `EXECUTED` |
| accept of an offer applying `contract_term_extension` (not forbidden, not supported) | `valid_outcome=True, completed=True` | rejected with `unsupported_action` |
| hash vectors (3-term `6d25bd2d…`, 6-term `b303382d…`, captured on `main`) | — | equal; order-insensitive |

## Historical copies (recorded, not authorities)

Byte-equal copies of the 3-term derivation and the sorted hash remain in
`ml/evaluation/src/proxyloop_evaluation/slow_output.py` (frozen by the r4
execution contract), `ml/evaluation/src/proxyloop_evaluation/legacy_slow_output.py`
and `scripts/run_phase_03a1_harness.py` (both reproduce historical
artifacts and build `CapabilityExecutor` without `terms_derivation`, so
they cannot mismatch the executor). `tests/integration/test_offer_policy_authority.py`
pins this allowlist and fails on any other definition, including renamed
private copies. Converging the harness script onto the shared derivation
would change committed harness artifact bytes and is a separate change.

## Checks

- Passed: focused suite 106; `test_offer_policy_authority.py` 5;
  `make lint`, `make typecheck`, `make format-check`,
  `scripts/validate_layout.py`, `make contracts-check`.
- Passed (`PYTHONPATH=.`): `benchmark-check`, `data-pilot-check`,
  `harness-check`, `baselines-check`, `errata-check`, `hosted-rerun-check`,
  `validity-smoke-check`, `phase03b-readiness-check`,
  `phase03b-experiment-check`, `phase03c-invariants-check`,
  `phase03c-prompt-set-check` — `git status --porcelain data contracts`
  empty afterwards (zero artifact bytes changed; the architect's
  measurement of 0/32 label/offer-id/reason-code differences holds).
- Passed: `ml/tests/test_fresh_phase03a1_fixtures.py` unmodified, r2 bundle
  fingerprint `729e4e43…` unchanged.
- Passed: `make preflight` — runtime 324 / 42 gated skips, ML 318 / 1
  skipped, web 51, all gates valid.
- Independent review (`reviewer`, Opus): **Approve**. Verified: dependency
  direction and no import cycle; moved policy diffs clean against `main`;
  hash equality across five vectors × three implementations, and the
  empty-tuple hash equals the old `canonical_fingerprint(())` so no-offer
  approvals keep their stored hash; no consumer depends on term names
  (Web validates only a non-empty hash); 11 artifact checks green; mypy
  green over the frozen `phase03b_experiment.py` injection. Important:
  two further byte-equal historical copies the proposal had not listed —
  recorded above; the definition-count test was tightened to catch
  renamed copies with an explicit allowlist. Minors: docstring wording
  (applied); the verifier now appends `unsupported_action` after
  `forbidden_term_present` for a change that is both forbidden and
  unsupported (no committed artifact takes that path).
