# Phase 03C Fast Model Re-baseline and Verifier-Filtered Distillation

## Authorization

**Status: prepared, not activated.** This contract exists so the user can
gate it; `harness/status.toml` remains `idle` and nothing below is
authorized until the user activates the phase. Stage 0 needs no external
spend. Stage 1 requires a separate hosted-spend gate and Stage 2 a separate
cloud-GPU gate; each is its own user decision.

Historical Phase 03A1 r2–r5 and Phase 03B artifacts stay byte-identical.
Every Phase 03C artifact is a new versioned file. The recorded
`NO_GO_STOP_PHASE03B` decision is not rewritten; Phase 03C records what that
decision does and does not support.

## Baseline and problem

`docs/research/2026-09-21-phase-03b-post-training-review.md` found that the
Phase 03B result is inconclusive for three reasons that compound: the 03B
prompt dropped the JSON schema and broke the untuned baseline (its six
"invalid" outputs are valid JSON with an over-long `reason_code`); the
evaluator's bare `json.loads` refused the tuned arm's six markdown-fenced
outputs; and 20 examples with 6 distinct lookup targets and 10 optimizer
updates at LR 1e-5 do not constitute a training run. The MLX/Mac run was a
symptom, not the cause.

The Fast checkpoint frozen in
`docs/decisions/2026-08-22-implementation-defaults.md` was
`Qwen/Qwen3-4B-Instruct-2507` on "one 24GB CUDA GPU, 4-bit QLoRA". Phase 03B
ran a community 4-bit MLX base instead, so nothing transfers to the planned
vLLM path. On 2026-09-21 the user redirected the Fast checkpoint to
**`Qwen/Qwen3-8B`** (amendment recorded in the ADR). Checked on Hugging Face
the same day: no `Qwen3-8B-Instruct-2507` exists; `Qwen/Qwen3-8B` is the
hybrid thinking/non-thinking instruct model, so every prompt render, training
row, and inference call must pass `enable_thinking=False` and the evaluator
must reject any `<think>` content in the output.

## Objective

Re-establish an honest untuned baseline, then decide with pre-registered
rules whether verifier-filtered teacher distillation improves the Fast model
over prompt-plus-constrained-decoding. "Prompt and constrained decoding are
enough" is a first-class outcome, not a failure.

## Stage 0 — Fix the evaluator and re-baseline (USD 0, local, no training)

Code changes are additive; Phase 03B evaluator bytes do not change
(`phase03b_experiment.py` and `scripts/run_phase03b_smoke.py` are bound by the
03B pipeline fingerprint; `qwen_mlx.py` is not).

1. `ml/evaluation/src/proxyloop_evaluation/fast_output.py`: add
   `extract_fast_json(raw) -> (text, mode)` with modes `strict`, `fenced`,
   `prefixed_fenced` (strip one ```` ```json ````/```` ``` ```` fence, or a
   leading `json`/`Json` word plus fence; never edit content), and
   `parse_fast_json(text)` that rejects duplicate keys via
   `object_pairs_hook` (`DuplicateJSONKeyError`; move
   `_reject_duplicate_json_object` here, leaving 03B's copy in place).
2. `qwen_mlx.py::QwenMLXAdapter.generate`: replace bare `json.loads(raw)` with
   the two helpers; add `json_parse_mode` and `json_valid_strict` to
   `QwenMLXMetadata`; new error codes `duplicate_json_key`,
   `invalid_json_after_fence_strip`. Strict validity is still reported;
   tolerant parsing only changes what is scored downstream.
3. New `phase03c_experiment.py`:
   - `Phase03CQwenAdapter(Phase03BQwenAdapter).build_prompt` keeps the compact
     view (token fit) but re-embeds `FastModelOutput.model_json_schema()`
     exactly as `QwenMLXAdapter.build_prompt` does, plus one literal line:
     `reason_code: short snake_case code, max 256 chars. Examples:
     offer_candidate_requires_slow_review, provider_state_requires_replan,
     none.` Version `phase-03c-fast-compiler-v3`.
   - `evaluate_fast_result_v3`: rename `_policy_violation` to
     `oracle_act_mismatch` (task metric); redefine `policy_violation` as
     `disclosure_violation or authority_violation or false_completion or
     stale_pin_violation` (safety composite). Import the 03B detectors.
   - Row metrics gain `json_parse_mode`, `json_valid_strict`,
     `json_valid_tolerant`, `duplicate_key`.
4. New `scripts/run_phase03c_smoke.py` (copy of the 03B runner pointed at v3;
   results under `data/experiments/phase-03c/results/`).
5. Offline erratum, following the r2→r3 pattern
   (`replay_v2.derive_r3_report_from_r2`):
   `derive_parser_erratum(source_path)` re-scores the stored `raw_output` of
   `data/experiments/phase-03b-qlora-smoke/results/arm-a-untuned.json` and
   `arm-b-qlora.json` into
   `data/experiments/phase-03c/errata/phase-03b-arm-{a,b}-parser-erratum.json`
   (`schema_version="phase-03c-parser-erratum-v1"`, `source_sha256`,
   `new_external_dispatch_count=0`, per-episode parse mode / duplicate key /
   schema validity / failing field / `oracle_act_mismatch`). Expected, and
   asserted by test: Arm A strict-parse 6/6, schema 1/6, 5× `reason_code`
   > 256; Arm B strict-parse 0/6, tolerant-parse 6/6, duplicate `action_intent`
   2/6, all six `dialogue_act=counter`.
6. Local untuned smoke: `run_phase03c_smoke.py --arm a` on the 6 dev
   scenarios, v3 prompt, greedy, 512 tokens, MLX →
   `results/arm-a-untuned-v3.json`; `--verify-token-fit` over all 26 rows
   ≤ 2048 tokens.

Tests: change
`test_qwen_mlx_adapter.py::test_invalid_json_or_schema_is_a_failure_without_repair`
(fenced input now parses with `json_parse_mode="fenced"`,
`json_valid_strict=False`); add `test_phase03c_experiment.py` covering the
four parse variants, duplicate key inside a fence, v3 prompt contains
`maxLength` 256 and the example codes and no oracle fields, `policy_violation`
false when only `oracle_act_mismatch` is true, and erratum numbers reproduced
from the committed 03B files. All 03B tests stay untouched and green.

**Checkpoint (decided 2026-09-21): `Qwen/Qwen3-8B`, non-thinking mode.**
Stage 0 therefore re-baselines 8B, not 4B. Requirements that follow from the
hybrid-thinking model: (a) `Phase03CQwenAdapter.build_prompt` and the local
MLX/HF adapters apply the chat template with `enable_thinking=False` and the
evaluator records `thinking_leak=True` (a failure) if `<think>` appears in the
output; (b) the local smoke uses `Qwen/Qwen3-8B-MLX-bf16` (official MLX
export) rather than a community quantised base, so the base matches the bf16
weights later served by vLLM; (c) Stage 0 also records the untuned **4B**
numbers on the same 6 scenarios as a one-time reference row, because the
32/32 03A1 evidence is for 4B and the reviewer needs to see whether the 8B
port changes format validity. Model license (Apache-2.0 per the card) and
revision hash are pinned in the Stage 0 manifest.

Acceptance: two erratum JSONs with matching `source_sha256` and the counts
above; `arm-a-untuned-v3.json` with strict JSON ≥ 5/6 and schema-valid ≥ 5/6
(03A1 r2 reached 32/32 with the schema prompt, so < 5/6 means the prompt port
is wrong); new tests green; `make preflight`, `git diff --check`, and
`make phase03b-experiment-check` pass; SHA-256 of every 03A1/03B artifact
unchanged and listed in the log.
Non-goals: training, data expansion, hosted calls, changing 03B decision
text, semantic output repair.
Stop: after the smoke result is committed and reviewed. Estimated 1–2 days.

## Stage 1 — Parameterised scenarios and verifier-filtered teacher data (hosted-spend gate)

**Parameterisation** (`runtime/packages/provider_simulator`). Today every
scenario shares `CASE_CURRENT_MONTHLY_TOTAL_MINOR = 9_200` /
`CASE_TARGET_MONTHLY_TOTAL_MINOR = 7_500` (`scenarios.py:154`), fixed base
price, fee, and promo deltas, and `episode.py` hard-codes the same numbers.
Add `ScenarioParameters(seed, current_monthly_minor, target_monthly_minor,
base_price_minor, trap_fee_minor, promo_credit_minor, required_features,
forbidden_changes, expires_in_minutes, message_variant)`;
`_build_scenario(family, configuration, params=DEFAULT_PARAMS)`; `scenario_id`
gains `::p<seed>` and `DEFAULT_PARAMS` must reproduce today's 32 ids
byte-for-byte so Phase 01B/02/03A1 artifact checks stay green. Per-instance
invariants, quarantined on failure: twelve-month total arithmetic; hazard
truth per family (fee-trap ⇒ monthly ≤ target and total > 12 × target;
required-feature-loss ⇒ exactly one required feature missing; forbidden-term
⇒ forbidden change present; success families ⇒ all `offer_policy.py` checks
pass); and oracle/verifier agreement
(`ScriptedOracleConsumer.decide(obs).action == family.expected_action`,
`MultiTurnProviderEnvironment` outcome == `family.expected_outcome`).
Multi-turn positions: start the environment, submit the oracle's first
message, and harvest 2–3 Fast decision positions per episode.

**Teacher adapters** (`ml/evaluation`). Keep `OpenAIFrontierAdapter` for
`gpt-5.6-terra`. Add `claude_teacher.py::ClaudeTeacherAdapter` on the same
`decide(view) -> FastAdapterResult` seam, reusing `FrontierCallRecord`,
`FrontierCostEstimate`, and `usd_ceiling`; Anthropic SDK structured output
(`client.messages.parse(..., output_format=FastStructuredOutput)` or
`output_config={"format": {"type": "json_schema", ...}}`), the Batches API for
bulk sampling, lazy `import anthropic`, credential only from
`PROXYLOOP_CLAUDE_API_KEY`, `max_retries=0`, sanitized errors. Model id
`claude-sonnet-5` (from the `claude-api` skill table; re-check at execution).
Prices are never hard-coded: the ledger multiplies returned `usage` by a
user-maintained `ml/configs/teacher-rates.json` and is labelled an accounted
estimate. A second family (Gemini) plugs in only as `AgreementFilter` on the
same seam, producing one boolean `second_family_act_agrees`; no version or
price is asserted, and the field is `null` if no adapter is written.

**Rejection-sampling pipeline**
(`ml/data_pipeline/.../teacher_pipeline.py`, reusing `NormalizedTrajectory`
and `GeneratorSnapshot.role`):

1. `build_prompt_set` → `data/manifests/phase-03c-prompt-set.json` with
   family, entity cluster, configuration, seed, split (from
   `phase-01b-split.json`), prompt fingerprint, evaluator-only oracle action.
2. `sample_teacher` (k = 3, temperature 0.7, batches) → raw JSONL under
   `data/experiments/phase-03c/teacher/` plus `phase-03c-cost-ledger.json`.
3. F1 strict JSON + `FastModelOutput` schema (no tolerant parsing for
   training data).
4. F2 `dialogue_act` and `reasoner_request.needed` equal the oracle-derived
   target; `action_intent is None`; `completion_claim.status == "not_done"`.
5. F3 verifier replay through the `runner_v2` coordinator path.
6. F4 detectors: PII, disclosure, false completion, numeric grounding,
   `fact_updates` provenance ids exist in the view.
7. F5 optional second-family agreement.
8. Dedup by lexical fingerprint and exact hash; ≤ 2 kept samples per prompt.
9. `curate_candidates` → `phase-03c-teacher-manifest.json` (accepted, content
   hashes), `-quarantine.json` (reason counts per filter),
   `-quality-report.json` with `training_ready` computed, never hand-set.
   Accepted JSONL is git-ignored.

Splits: train = 10 train families × 2 configs × 100 seeds × ~2 positions
≈ 4,000 prompts → target ≥ 2,500 accepted rows; dev = same families, disjoint
seeds 900–949 (~400 prompts, labelled within-family); the 3 dev families and
3 test families are never sampled and are used only in Stage 3. A test asserts
the accepted manifest's family set ⊆ train families.

Pilot before full spend: 200 prompts (20 per train family), k = 3 →
`phase-03c-teacher-pilot-report.json`. Go if F1 ≥ 95%, F1∧F2 ≥ 60%, F1–F4
≥ 40%; if F2 < 40%, stop — the teacher disagrees with the oracle too often and
the view/prompt must be fixed first (the r4 3/32 lesson).

Acceptance: parameterisation keeps 01B/02/03A1 checks green under
`DEFAULT_PARAMS`; invariant suite over ≥ 1,000 seeds with zero
oracle/verifier disagreement; pilot report and ledger committed; full
manifest ≥ 2,500 rows, zero forbidden model-input keys, zero cross-split
family/entity, ledger ≤ cap.
Non-goals: training, Slow-model data, RL/DPO, real providers, a full Gemini
pipeline, human-review claims.
Spend cap (estimate): pilot ≤ USD 15; full run ≤ USD 150, enforced by
`usd_ceiling`. Stop after the quality report is reviewed. Estimated 3–5 days.

## Stage 2 — Cloud training (GPU gate)

Recipe (`ml/training/phase03c/`, TRL + PEFT pinned in an optional
`training` dependency group):

- Base: `Qwen/Qwen3-8B` official bf16 weights at the revision pinned in the
  Stage 0 manifest; not a quantised base. Chat template rendered with
  `enable_thinking=False` for every training row.
- Data: accepted rows rendered as `messages` with the v3 prompt; one test
  compares a rendered row byte-for-byte with `Phase03CQwenAdapter.build_prompt`.
- `SFTConfig`: `max_length=2048`, assistant-only loss (verify the Qwen3 chat
  template exposes the assistant span; otherwise use prompt/completion
  masking), 3 epochs, per-device batch 4 × grad-accum 4, LR 1.5e-4, cosine,
  warmup 3%, bf16, gradient checkpointing, seed 0, eval and save every 100
  steps.
- `LoraConfig`: r 32, alpha 64, dropout 0.05, all linear projections. Full
  fine-tuning is one optional ablation only if LoRA dev act agreement is
  < untuned + 5 points. Search budget ≤ 4 runs over LR ∈ {1e-4, 2e-4},
  r ∈ {32, 64}.
- Checkpoint selection: a `TrainerCallback` that at every eval step generates
  greedily over the ~400-row dev set and calls `evaluate_fast_result_v3`;
  select by dev `oracle_act_agreement` with `policy_violation == 0`, ties by
  lower `unsupported_response_violation`. Never select by loss.
- Export adapter and merged bf16 weights to the cloud bucket; commit only
  `data/experiments/phase-03c/training/run-<id>-manifest.json` (dataset
  fingerprint, base revision, config hash, package versions, GPU, wall time,
  per-eval metric table, selected step, SHA-256 of adapter and merged
  weights, MLflow run id).

Cloud target: one A100-80GB or H100-80GB (8B bf16 weights ≈ 16 GB; LoRA with
gradient checkpointing at 2k sequence fits comfortably). ≈ 9M training
tokens, LoRA on 8B ≈ 1–2 h plus dev evals ≈ 2–3 h total, USD 10–30
(estimate). A 24 GB card would force 4-bit QLoRA on 8B, which reintroduces
the quantised-base mismatch with bf16 vLLM serving; use it only for the local
pipeline smoke, never for the selected checkpoint.

Acceptance: run manifest committed; dev `schema_valid` ≥ 98%; dev
`oracle_act_agreement` ≥ untuned-v3 measured in the same loop, otherwise the
run is recorded as No-Go for this data; no weights in Git.
Non-goals: RL/DPO, serving, wider hyper-parameter search. Stop after the
selected checkpoint's manifest is reviewed. Estimated 1–2 days.

## Stage 3 — Held-out evaluation and pre-registered decision

Arms on one frozen held-out manifest, v3 prompt, greedy, 512 tokens,
`enable_thinking=False`: A0 oracle ceiling; A1 untuned Qwen3-8B bf16 via
vLLM; A2 A1 + vLLM guided JSON
(`guided_json=FastModelOutput.model_json_schema()` through the existing Phase
04B typed adapter); A3 distilled plain; A4 distilled + guided JSON; A5 hosted
teacher as Fast (budget-capped); A6 `gpt-5.6-terra` as Fast. A1 and A2 may run
right after Stage 0, before any training.

Held-out set: 3 dev families + 3 test families × 2 configs × 10 seeds × ~2
positions ≈ 240 episodes plus the unchanged 03A1 safety suite; n ≥ 200 per
arm; Wilson 95% CIs; family breakdown. Metrics: strict and tolerant JSON
validity, schema, canonical, `oracle_act_agreement`, `needed_agreement`,
verifier E2E, false completion, authority, PII/disclosure, unsupported facts,
p50/p95 latency, tokens.

Decision rules, frozen before Stage 2 starts:

- **GO_DISTILLED**: A3 or A4 act agreement − A1 ≥ 10 points with CI excluding
  0; `false_completion` and `policy_violation` = 0; unsupported-fact rate not
  worse than A1 by > 2 points.
- **GO_PROMPT_ONLY**: A2 − A1 ≥ 0 and A3/A4 − A2 < 5 points → schema prompt
  plus constrained decoding is sufficient; distillation is not promoted and
  the evidence is recorded as a valid result.
- **NO_GO**: neither rule fires, or any safety regression in A3/A4 vs A1.

Artifact: `data/evaluation/phase-03c-heldout-report.json`
(`schema_version="phase-03c-heldout-v1"`, decision field naming the rule that
fired) and this contract's closeout. Hosted arms capped at ≈ USD 20
(estimate). Estimated 1 day.

## Order, dependencies, and parallelism

1. Stage 0 (no gate). 2. Stage 1 parameterisation is USD 0 and may run in
parallel with Stage 0. 3. Stage 1 pilot needs Stage 0's v3 prompt, the
parameterisation, and the hosted gate. 4. Full generation needs the pilot Go.
5. Stage 2 needs full generation and the GPU gate. 6. Stage 3 A1/A2 can run
after Stage 0; A3/A4 after Stage 2. Total ≈ 1.5–2.5 weeks part-time
(estimate).

## Risks and built-in mitigations

1. Parser fix incomplete — dual strict/tolerant reporting, erratum test pinned
   to 03B raw outputs, guided-JSON arms isolate format from decision.
2. Teacher disagrees with the oracle — 200-prompt pilot with an F2 floor
   before spend; oracle is the label authority, teacher supplies text.
3. Parameterisation breaks hazard truth — per-instance oracle/verifier
   assertion, twelve-month arithmetic invariant, `DEFAULT_PARAMS` byte-for-byte
   reproduction of existing artifacts.
4. Train/eval prompt drift (the 03A1-V lesson) — one prompt builder for
   dataset rendering, dev loop, and Stage 3, with a byte-equality test.
5. Underpowered conclusion — n ≥ 200 per arm, CIs required, rules frozen
   before training, and "prompt-only is enough" as a first-class outcome.

## Explicitly out of scope

Real providers or channels, Slow-model training, RL/DPO, model promotion or
serving changes, production claims, and any change to Phase 03A1/03B
artifacts or decisions.
