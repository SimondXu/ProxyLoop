# Phase 03C handoff (written 2026-09-21)

Purpose: let a fresh session pick up the Fast-model redo without re-deriving
the state. Read this, then `harness/build/phase-03c-fast-model-distillation.md`
(the contract) and `docs/research/2026-09-21-phase-03b-post-training-review.md`
(why 03B was inconclusive). Do not start from `PLANS.md` prose.

## 0. Where the repository is right now

- `main` = `763a1a9` (Phase 07A). Harness `idle`. Every roadmap phase through
  07A is merged; 06B2 and the rest of 07 are unauthorized.
- Branch `chore/docs-progress-sync` (local, unpushed, **uncommitted**) holds
  two kinds of changes in one working tree:
  1. Documentation sync done on 2026-09-21: rewritten `README.md`,
     `docs/planning/progress.md`, `docs/README.md`; new `docs/development.md`,
     `docs/ml-evidence.md`, `docs/research/2026-09-21-phase-03b-post-training-review.md`,
     `harness/build/phase-03c-fast-model-distillation.md` (prepared, not
     activated); ADR amendment in `docs/decisions/2026-08-22-implementation-defaults.md`;
     small fixes in `GOALS.md`, `apps/README.md`, `infra/README.md`,
     `harness/context/README.md`, `docs/architecture.md`, `docs/portfolio-demo.md`,
     `docs/research/foundations.md`, `docs/specs/...`, `docs/decisions/2026-08-21-monorepo.md`;
     deleted `docs/planning/phase-03b-qwen-qlora-experiment.md` (superseded).
  2. Changes **not** made by the docs session (appeared 12:46–12:53 the same
     day, presumably another session adding Claude Code support):
     `AGENTS.md` (tool-agnostic wording), `CONTRIBUTING.md`, `PROMPTS.md`,
     `harness/README.md`, `.github/pull_request_template.md`, new `CLAUDE.md`
     and `.claude/agents/*.md`, `.claude/settings.json`.
  `make preflight-fast` passes with everything in place. Decide whether to
  ship as one PR or split; then commit and open the PR before any code work.
- Git leftovers: `git worktree prune` (dead `/private/tmp/proxyloop-ui-worktree`);
  local+remote `feat/phase-00b-contracts` is merged and can be deleted;
  keep branch `feat/pine-inspired-ui-prototype` (referenced by `docs/ui/research.md`).

## 1. Decisions already taken by the user

- Fast checkpoint is **`Qwen/Qwen3-8B`**, not the 4B ADR default. Verified on
  Hugging Face 2026-09-21: no `Qwen3-8B-Instruct-2507` exists; `Qwen/Qwen3-8B`
  is the hybrid thinking model → force `enable_thinking=False` everywhere and
  treat `<think>` in output as a failure. Recorded in the ADR amendment.
- Redo method: verifier-filtered teacher distillation (teacher candidates:
  Claude Sonnet, Gemini Flash), cloud GPU for the real training run, local
  Mac only for evaluator fixes and pipeline smokes.
- 03B's `NO_GO_STOP_PHASE03B` is not rewritten; 03A1/03B artifacts stay
  byte-identical.

## 2. What to do first: Stage 0 (USD 0, local)

Activation (user has to say "go"; then):
1. `git checkout main && git pull`, branch `feat/phase-03c-stage0-rebaseline`.
2. `harness/status.toml`: `product_phase_state = "in_progress"`,
   `active_product_phase = "03C-stage0"`,
   `active_contract = "harness/build/phase-03c-fast-model-distillation.md"`,
   `updated_at`. `make check-layout` validates the shape.
3. Add `harness/context/phase-03c-preflight.md` (baseline sha, observed
   cache state below, frozen decisions) — the repo convention.

Work items (all in the contract, Stage 0 section; summary):
- `ml/evaluation/src/proxyloop_evaluation/fast_output.py`: `extract_fast_json`
  (strict / fenced / prefixed_fenced) + `parse_fast_json` with duplicate-key
  rejection.
- `qwen_mlx.py::QwenMLXAdapter.generate` (~line 346–392): use them; add
  `json_parse_mode`, `json_valid_strict`, `thinking_leak` to metadata; new
  error codes. `QWEN_MLX_MODEL` (line 25) becomes configurable so 8B and the
  4B reference can both run; apply chat template with `enable_thinking=False`.
- New `phase03c_experiment.py` (v3 prompt = compact view + embedded
  `FastModelOutput.model_json_schema()` + `reason_code ≤ 256` line;
  `oracle_act_mismatch` / real `policy_violation`; `derive_parser_erratum`).
- New `scripts/run_phase03c_smoke.py`; Makefile target `phase03c-smoke-check`
  following the `phase03b-experiment-check` pattern.
- Tests: update `ml/tests/test_qwen_mlx_adapter.py::test_invalid_json_or_schema_is_a_failure_without_repair`;
  add `ml/tests/test_phase03c_experiment.py` (parse variants, duplicate key,
  prompt contents, policy composite, erratum numbers).
- Artifacts: `data/experiments/phase-03c/errata/phase-03b-arm-{a,b}-parser-erratum.json`
  (offline, zero model calls; expected A strict 6/6 · schema 1/6; B strict 0/6 ·
  tolerant 6/6 · dup `action_intent` 2/6), then
  `data/experiments/phase-03c/results/arm-a-untuned-8b-v3.json` and
  `arm-a-untuned-4b-v3.json` (6 dev scenarios, greedy, 512 tokens,
  `--verify-token-fit`).
- Pass bar: 8B strict JSON ≥ 5/6, schema ≥ 5/6, `thinking_leak` 0/6;
  `make phase03b-experiment-check` still green; SHA-256 list of 03A1/03B
  artifacts unchanged in the log; `make preflight` green.
- Independent review (reviewer role) before merge; log in
  `harness/log/phase-03c-stage0-rebaseline.md`; status back to `idle`.

Do not in Stage 0: train anything, call a hosted model, touch 03B evaluator
bytes (`phase03b_experiment.py`, `scripts/run_phase03b_smoke.py` are bound by
the 03B fingerprint), or "repair" model output semantically.

## 3. Local model state (observed 2026-09-21)

- Present: `~/.cache/huggingface/hub/models--mlx-community--Qwen3-4B-Instruct-2507-4bit`
  (2.1 GB, snapshot `50d4277…`, the base used by 03A1/03B). Keep for the 4B
  reference row.
- Absent: official `Qwen/Qwen3-4B-Instruct-2507` bf16; any Qwen3-8B; the 03B
  LoRA adapter (never saved — Arm B cannot be re-scored with weights, only
  from stored `raw_output`).
- Stage 0 download: `Qwen/Qwen3-8B-MLX-bf16` (official MLX export, ≈16 GB).
  Pin the revision hash in the preflight. Machine: Apple M4 Pro 48 GB —
  enough for 8B bf16 inference and small LoRA smokes; expect ~2× the 4B
  latency.

## 4. After Stage 0 (each needs its own user gate)

- Stage 1a (USD 0): scenario parameterisation in
  `runtime/packages/provider_simulator/scenarios.py` (+ `episode.py`),
  `DEFAULT_PARAMS` must reproduce today's 32 scenario ids byte-for-byte.
- Stage 1b (hosted gate, ≤ USD 15): 200-prompt teacher pilot; stop if
  oracle-agreement (F2) < 40%.
- Stage 1c (≤ USD 150): full generation, ≥ 2,500 accepted rows.
- Stage 2 (GPU gate, ≈ USD 10–30): TRL/PEFT LoRA on 8B bf16, 80 GB-class GPU;
  checkpoint chosen by the real evaluator on dev.
- Stage 3: held-out arms incl. untuned + vLLM guided JSON; pre-registered
  `GO_DISTILLED` / `GO_PROMPT_ONLY` / `NO_GO`.
- Optional local pipeline smoke between 1a and 1b: MLX LoRA on 1–2k
  oracle-labelled parameterised rows — validates rendering/template/eval
  loop only, never a Go/No-Go.

## 5. Facts that will save time

- Test counts at last gate: runtime 303 collected (291 pass + 33 guarded
  infra skips), ML 177, web vitest 47. `make preflight` is the CI gate;
  `postgres-check`/`phase05a-check`/`phase06b1-check` need
  `PROXYLOOP_TEST_DATABASE_URL` and (last two) Temporal.
- `qwen_mlx.py` is *not* covered by the 03B pipeline fingerprint
  (`phase03b_experiment.py:78`, `run_phase03b_smoke.py:48`), so it can change.
- Arm A "invalid" = `reason_code` > 256 chars; Arm B "invalid" = markdown
  fence not stripped. Both verified from `results/*.json` raw outputs.
- Untuned 4B with the schema-embedding prompt scored 32/32 in 03A1 r2/r4
  (`data/evaluation/phase-03a1-r4-hosted-rerun-report.json`, condition
  `untuned_fast_reference_strategy_r2`); that prompt builder is
  `qwen_mlx.py::QwenMLXAdapter.build_prompt` (~line 271).
- Hosted Slow scored 3/32 E2E in r4 and 5/6 in r5 after input parity —
  teacher quality on this harness is unknown until the pilot measures it.
- Subagent routing in this repo: `.claude/agents/{explorer,implementer,
  reviewer,fast-worker,architect}.md`; global `test-log-analyzer` for noisy
  test runs; `claude-api` skill before quoting any Claude model id or price.
