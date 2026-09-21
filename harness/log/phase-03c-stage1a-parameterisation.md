# Phase 03C Stage 1a Scenario Parameterisation Execution Log

**Date**: 2026-09-21
**Baseline**: integrated `main` at `aaae134` (Phase 03C Stage 0)
**Branch**: `feat/phase-03c-stage1a-parameterisation`
**Contract**: `harness/build/phase-03c-fast-model-distillation.md`, Stage 1
"Parameterisation" paragraph (USD 0 part of Stage 1)
**Status**: complete locally, independently approved after one remediation
round; status returned to `idle` at this gate. Stage 1b (hosted spend) is
the next separate gate.

## Delivered

- `scenarios.py`: `ScenarioParameters` (validated arithmetic; rejects
  builder-token collisions and `current_monthly_minor <= 1000`),
  `DEFAULT_PARAMS`, `parameters_from_seed` (fixed PRNG draw sequence, seed 0
  = frozen default), `build_scenario`, `build_parameterised_scenarios`,
  `BenchmarkScenario.parameters`, three message variants per hazard rendered
  from `{feature}`/`{change}` templates (variant 0 renders the frozen text),
  `feature_phrase`/`change_phrase`; ids carry `::p<seed>` for seeded
  instances and `::p<seed>-<8hex>` for hand-built parameters.
- `environment.py`: compliance context from `scenario.parameters`.
- `episode.py`: `build_case(params)`; hard constraints derived from
  `forbidden_changes`; `_build_case()` unchanged in output.
- `ml/evaluation/.../phase03c_scenarios.py`: parameterised observation
  builder, per-instance invariants (`twelve_month_arithmetic`,
  `fee_trap_truth`, `required_feature_loss_truth`, `forbidden_term_truth`,
  `success_compliance`, `message_offer_consistency`, `oracle_agreement`,
  `verifier_agreement`), `harvest_positions` (2 positions; the 03A1
  environment is terminal after one input), invariant suite + manifest
  check; `scripts/run_phase03c_scenario_invariants.py`; Makefile targets
  `phase03c-invariants` / `phase03c-invariants-check` (in `make test`).
- `data/manifests/phase-03c-scenario-invariants.json`: seeds 1..1000 × 32 =
  32,000 instances, 32,000 accepted, 0 quarantined; content fingerprint
  `77d6df41…`, parameters fingerprint `41390f7c…`.
- Tests: 22 in `test_scenario_parameters.py` (frozen-catalogue sha
  `425c7afb…` and Case sha `37d8e149…` pinned; seeds 1/42/999 pinned as
  literals), 16 in `test_phase03c_scenarios.py`.
- `harness/context/phase-03c-stage1a-preflight.md` (incl. the Stage 1b
  teacher-path decision: relay seam, two teachers, select by F2).

## Checks

Passed (final tree): `make preflight` exit 0 — ruff/mypy both halves,
runtime 303 passed / 33 guarded skips, ML 236 passed, web 47, all artifact
checks (`benchmark`, `harness`, `phase03b-experiment`, `hosted-rerun`,
`validity-smoke`, `phase03c-smoke`, `phase03c-invariants`), layout, lock,
compose; `git diff --check` clean. Frozen catalogue and Case hashes verified
against `git archive main` by the reviewer.
Not run: `postgres-check`, `phase05a-check`, `phase06b1-check` (Compose
profiles; untouched paths). No model or network calls in this change.

## Independent review

`reviewer` (Opus, high, fresh context). First pass: Request Changes —
Important 1: variant texts hard-coded "mobile hotspot"/"device-financing"
and contradicted parameterised offers (222/600 forbidden-term instances in
seeds 1..300); Important 2: seeded parameter content had no pin. Both fixed
(templated messages + `message_offer_consistency` invariant, shown
non-vacuous by tampering; `parameters_fingerprint` + literal pins) together
with Minor 3–9 (tautological Case assertion → sha pin; tuple
materialisation; id-suffix collisions; parameter validation; quarantine-row
and variant tests; promo constant dedup). Re-review: **Approve**; residual
note that `message_offer_consistency` accepts any offer feature for success
families (generator only names `required_features[0]`).

Delegation: explorer evidence card, two parallel implementers (runtime /
ML lanes, non-overlapping files), one remediation implementer, one
reviewer; the root orchestrator froze the interface, decided the contract
deviations, and integrated.
