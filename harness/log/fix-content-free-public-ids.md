# Fix log: content-free public ids and value-level leakage scan (G2d / P0-5)

Spec: `harness/context/fix-content-free-public-ids-preflight.md`. Design:
`harness/context/group2-evaluator-proposal.md` §G2d (F3/F9/F10/F11).
Programme: `harness/context/audit-remediation-decisions.md`. Branch
`fix/content-free-public-ids` from `main` @ `d4335f3`. Resolves audit
D1-1, D3-1, D3-2 and D3-4.

## What changed

- `provider_simulator/scenarios.py`: `_episode_ref(scenario_id) =
  "ep-" + sha256(scenario_id)[:16]`; `offer_id`, `turn_id`,
  `evidence_ref` and the `expected_*` pins are
  `ep-<hash>::offer|turn-1|confirmation`. `scenario_id` stays
  content-bearing as the evaluation join key (it never reaches a public
  view). The ids are **content-free, not unlinkable**: an unsalted
  truncated digest is reversible by a dictionary over the catalogue —
  stated in the docstring and `docs/ml-evidence.md`.
- New `provider_simulator/leakage.py`: `private_tokens(scenarios)` returns
  two tiers — family/configuration/scenario **identifiers** matched as
  casefolded substrings (including JSON encoded inside a string) and
  hazard / outcome / reason-code **labels** matched as whole values,
  excluding `SUPPORTED_APPLIED_CHANGES` and the action vocabulary. A
  literal substring scan of the label tier would flag legitimate public
  content (`plan_change`, `accept_offer`, "clarification"), so the spec's
  single-tier wording could not be satisfied by any honest payload; root
  accepted the two-tier reading.
- Scan call sites: `run_phase_01b_benchmark.py` (per-row
  `leaked_public_values`, folded into the gate),
  `run_phase_03a1_harness.py` (same, over the exported public episode, and
  the capability `idempotency_key` now derives from the episode ref
  instead of the scenario id — reviewer I-1), `data_pipeline/pipeline.py`
  (`_forbidden_values`, quarantine reason `private_value_leak`), new
  `ml/evaluation/.../prompt_guard.py` used by
  `phase03c_prompt_set.render_prompt_view` (view) and
  `phase03c_experiment.Phase03CQwenAdapter.build_prompt` (rendered
  sections). The frozen `openai_frontier` / `qwen_mlx` key-name guards are
  wrapped, never edited.
- D3-4: `phase03b_readiness.source_manifest_fingerprint()` reads the
  committed Phase 02 manifest instead of a hard-coded literal.
- Historical-artifact checks (root decision, same rule as G2b): the 03B
  experiment manifest's three Phase 02 provenance fields, r1's binding to
  the harness episodes, and the 03C cloud bundle's binding to the prompt
  set now report `drifted_since_03b` / `drifted_since_r1` /
  `drifted_since_bundle` as labelled states instead of failing, and the
  historical artifacts are not rewritten. Tampering still fails: the 03B
  manifest is bound by the `manifest_fingerprint` every `results/arm-*.json`
  recorded (zero new literals), the bundle by its committed
  `dataset_fingerprint`, r1 by its own fingerprints.
- Regenerated (deterministic, no spend): `phase-01b-ceiling-report.json`,
  `phase-02-pilot-manifest.json`, `phase-02-review-sample.json`,
  `phase-03a1-episodes.json`, `phase-03a1-ceiling-report.json`,
  `phase-03b-train-dev-review-packet.json`, `phase-03c-prompt-set.json`.
  Unchanged: `phase-01b-split.json`, `phase-03a1-manifest.json`, the Phase
  02 quality/quarantine reports, r1–r5, the rescored r4, the 03B
  experiment artifacts, the 03C teacher and cloud artifacts.

## Field-level diffs of the regenerated artifacts

Only id/fingerprint-derived fields moved; every count, outcome, reason
code, split and review state is unchanged. 03C prompt set:
`prompt_fingerprint` identical for **4400/4400** rows; only
`input_fingerprint` (3520), `oracle_offer_id` (880) and the header
`content_fingerprint` changed. `phase-01b`: `oracle_offer_id` 10,
`evidence_ref` 10, `observation_fingerprint` 26, plus the new
`leaked_public_values: []` on 32/32 rows. `phase-03a1-episodes`: turn/offer
ids, evidence refs, observation/episode/pins fingerprints, adapter trace
ids. Phase 02: `content_hash` 104, `evidence_ref` 5, manifest/sample
fingerprints. 03B packet: `content_hash` 12, `offer_id` 12,
`oracle_offer_id` 5, `source_manifest_fingerprint`, `packet_fingerprint`.

## Known residuals (recorded, not fixed here)

- `pins.provider_config_ref` still carries `<configuration_id>@2.0` in the
  frozen r2 views and the 03C pins (spec decision 6; changing it would move
  the pinned 03C prompt fingerprints and the hosted teacher artifacts).
- The frozen `artifacts_v2.py` r2 public episodes keep
  `r2-oracle:<scenario_id>` as the capability idempotency key.
- The label tier cannot apply to a rendered prompt section (one prose
  string); rendered prompts are checked for the identifier tier.
- The cloud bundle's `dev-eval.jsonl` / `heldout.jsonl` are git-ignored and
  absent here, so held-out prompt identity is argued from the mechanism
  (rendered prompts contain no ids; 4400/4400 fingerprints unchanged) and
  from `valid.jsonl`'s byte-equal hash, not proven locally.

## Checks

- Passed: runtime `tests/integration tests/contract runtime/packages` 686 /
  42 gated skips; `ml/tests` 363 / 1 skipped; full `PYTHONPATH=. make test`
  (exit 0) printing `harness episodes: drifted_since_r1`, `phase02 source:
  drifted_since_03b (3 fields)`, `prompt set content: drifted_since_bundle
  (3 items)`, and `execution contract: unchanged`; `make lint typecheck
  format-check`.
- Passed **without regeneration**: `hosted-rerun-check`/`hosted-rescore-check`,
  `errata-check`, `validity-smoke-check`, `phase03c-smoke-check`,
  `phase03c-teacher-pilot-check`, `phase03c-teacher-generation-check`,
  `phase03c-training-check`, `phase03c-invariants-check`,
  `phase03c-cloud-bundle-check`, `phase03b-experiment-check`,
  `hosted-rerun-source-check`.
- `git status --porcelain data/` = exactly the 7 regenerated artifacts; the
  12 frozen `_R4_EXECUTION_PATHS` files unchanged; r2 bundle fingerprint
  `729e4e43…` pinned by a test and unchanged.
- Passed: `make preflight` — runtime 686 / 42 gated skips, ML 363 / 1
  skipped, web 51, all gates valid.
- Independent review (`reviewer`, Opus): **Request Changes** → all
  addressed. I-1 the harness `idempotency_key` leaked the scenario id into
  32/32 public episodes (fixed; harness rows now carry a value scan and the
  episodes regenerated; the docs claim is now true). I-2 the relaxed bundle
  check let a tampered-and-resigned manifest pass (fixed by pinning the
  committed `dataset_fingerprint` in the check and the test). I-3 the 03B
  provenance fields had no binding (fixed with the arm-results fingerprint
  binding). Minors applied: drift-state tests assert membership plus pinned
  fingerprints so a legitimate rebuild does not turn them red (M-1); the
  smoke scripts record the committed manifest's fingerprint (M-3);
  unlinkability, label-tier and legacy-`baselines-check` limits documented
  (M-4/M-5/M-6); the replay test renamed (M-2). The reviewer verified the
  field-level diffs, 224 scenarios' `SafeObservation`/`ProviderTurn` and
  03C views/prompts with zero identifier hits, and that the quarantine
  count stays 8.
