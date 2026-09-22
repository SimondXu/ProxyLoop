# Fix: content-free public ids and value-level leakage scan (G2d / P0-5)

Bounded change under `harness/context/audit-remediation-decisions.md`.
Design: `harness/context/group2-evaluator-proposal.md` §G2d and evidence
F3/F9/F10/F11. Branch `fix/content-free-public-ids` from `main` after G2a,
G2b, G2c merge. Resolves audit D1-1, D3-1, D3-2 (+ D3-4 in passing).

## Root decisions on the proposal's open questions

6. `provider_config_ref = f"{configuration_id}@2.0"` in the frozen r2 views
   and the 03C pins is a known residual, recorded in the log and
   `docs/ml-evidence.md`; it is handled with the next catalogue version.
9. Lineage/evaluation-side ids (`trajectory_id`, `derivation_parent_id`,
   `ProviderTurn.scenario_id`, episode ids) are not rewritten — they never
   reach a model.

## Frozen design

1. **Opaque ids at the source**, `provider_simulator/scenarios.py`
   `_build_scenario`: `episode_ref = f"ep-{sha256(scenario_id)[:16]}"`,
   `offer_id = f"{episode_ref}::offer"`, `turn_id = f"{episode_ref}::turn-1"`
   (the `::turn-<n>` structure `multi_turn.py` derives later turns from is
   kept), `evidence_ref = f"{episode_ref}::confirmation"`; `expected_offer_id`
   / `expected_evidence_ref` follow. `scenario_id` itself stays content-bearing
   (evaluation join key; never in `SafeObservation`).
2. **Value-level scan**, new `provider_simulator/leakage.py`:
   `private_tokens(scenarios) -> frozenset[str]` (every `family_id`,
   `configuration_id`, `scenario_id`, hazard token, `expected_action` /
   `expected_outcome` value, `private_reason_codes`) and
   `leaked_private_values(payload, tokens) -> tuple[str, ...]` walking every
   `str` including JSON-in-string, casefolded substring match. Applied in:
   `scripts/run_phase_01b_benchmark.py` (per-row `leaked_public_values`, gate
   requires 0), `ml/data_pipeline/.../pipeline.py` (`_forbidden_values` next
   to `_forbidden_keys`, quarantine reason `private_value_leak`),
   `ml/evaluation/.../phase03c_prompt_set.render_prompt_view` (assert on the
   `FastModelView` JSON minus `pins.provider_config_ref` and on the rendered
   `system`/`user` sections), and a new
   `ml/evaluation/src/proxyloop_evaluation/prompt_guard.py` wrapper for the
   03C/relay path. Frozen `openai_frontier._assert_prompt_allowlist` and
   `qwen_mlx._assert_safe_keys` stay untouched (documented as key-name-only,
   historical).
3. **Regeneration (deterministic, no spend)**: `make benchmark`
   (`phase-01b-ceiling-report.json`; `phase-01b-split.json` must not change),
   `make data-pilot` (`phase-02-pilot-manifest.json`,
   `phase-02-review-sample.json`; verify `quality-report`/`quarantine`),
   `make harness` (`phase-03a1-episodes.json`, `phase-03a1-ceiling-report.json`;
   `phase-03a1-manifest.json` must not change),
   `python scripts/prepare_phase03b_readiness.py --write` (packet embeds Phase
   02 offer ids; also D3-4: derive `source_manifest_fingerprint` from the
   committed `phase-02-pilot-manifest.json` instead of the literal in
   `phase03b_readiness.py`), `make phase03c-prompt-set` (`oracle_offer_id`,
   `input_fingerprint`, `content_fingerprint` change; `prompt_fingerprint`
   must not). Not touched: r2 artifacts, r2–r5 reports, the rescored r4, 03B
   experiment artifacts, 03C teacher/cloud bundles.
4. `docs/ml-evidence.md:~20`: remove the D1-1 note once true; add the
   `provider_config_ref` residual.

## Regression tests (write first)

- For the 32 benchmark scenarios, `SafeObservation.to_json()` built the
  benchmark way contains none of `private_tokens(BENCHMARK_SCENARIOS)`;
  `ProviderTurn.to_dict()` minus `scenario_id` likewise (fails on main:
  `direct-success@1.0::…` in `offer_id`/`turn_id`).
- `leaked_private_values({"x": json.dumps({"offer_id": "direct-success@1.0::x"})}, tokens)` is non-empty (JSON-in-string).
- Every Phase 02 `learning_content` row has no private value.
- 03C `render_prompt_view`: view JSON (minus `pins.provider_config_ref`) and
  rendered sections carry no private value.
- `multi_turn` later-turn ids keep the `::turn-<n>` structure.
- `build_fresh_phase03a1_bundle().metadata.bundle_fingerprint ==
  "729e4e43849cf094c25ee0532157658d7867bb9749c7f5c0e48c979f77183a8d"`
  (pins r2–r5 safety explicitly).

## Acceptance

`SafeObservation.to_json()` and a 03C example-view prompt contain no
family/config/scenario id; `benchmark-check`, `data-pilot-check`,
`harness-check`, `phase03b-readiness-check`, `phase03c-prompt-set-check` pass
on the regenerated artifacts; `hosted-rerun-check`, `hosted-rescore-check`,
`errata-check`, `validity-smoke-check`, `phase03b-experiment-check`,
`phase03c-teacher-pilot-check`, `phase03c-teacher-generation-check`,
`phase03c-cloud-bundle-check` (if present), `phase03c-smoke-check` pass
**without** regeneration — any drift there is a STOP; every regenerated
JSON's diff is limited to id/fingerprint fields (the reviewer diffs by
field, not by byte).

## Verification

`uv run --project runtime --all-packages pytest -c runtime/pyproject.toml -q tests/integration -k "01b or 03a1_agent_core" runtime/packages/provider_simulator/tests`;
`uv run --project ml pytest -q ml/tests`; regeneration commands above; the
full `PYTHONPATH=. make test`; `make lint typecheck format-check`; root runs
`make preflight` once.

## Escalate instead of deciding

Drift in any hosted/teacher check; a `prompt_fingerprint` change in the 03C
prompt set; a `phase-01b-split.json` or `phase-03a1-manifest.json` change; any
frozen-file change.
