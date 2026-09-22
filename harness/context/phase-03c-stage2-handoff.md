# Phase 03C Stage 2/3 handoff (written 2026-09-22)

Purpose: let a fresh session run the real training on Modal and close
Phase 03C without re-deriving the state. Read this, then
`harness/status.toml`, `harness/context/phase-03c-stage2-preflight.md`
(frozen decisions + operator steps), and
`harness/build/phase-03c-fast-model-distillation.md` Stage 2/3 sections.
Do not start from `PLANS.md` prose or from the 144 KB `harness/build-log.md`.

First sentence for the new session: **"读 `harness/context/phase-03c-stage2-handoff.md`，
然后按第 3 节在 Modal 上跑 Stage 2。"**

## 1. Where things are (all merged to `main`)

| PR | change | key evidence |
|---|---|---|
| #33 | Stage 0 evaluator fix + untuned Qwen3-8B re-baseline | strict JSON 6/6, act 0/6 with prompt v3 |
| #34 | Stage 1a scenario parameterisation | 32,000 instances, 0 quarantined |
| #35 | Stage 1b teacher pipeline + pilot | prompt v4; Sonnet Go, Gemini unusable (fenced output) |
| #41 | Stage 1c prompt v5/v6 + full generation | **7,196 accepted rows, all 10 train families, `training_ready = true`** |
| #42 | Stage 2 cloud package + local MLX smoke | code only; **no 8B training has run** |

`harness/status.toml` is `blocked` on `03C-stage2` (external execution).
Every gate so far: independent `reviewer` agent → log under `harness/log/`
→ review artifact under `harness/code_review/` → PR → CI → squash merge.
The user authorized the whole flow autonomously ("不用咨询我 全自动完成所有任务")
including merges; only real spend and credentials are user actions.

## 2. What exists locally (git-ignored, do not regenerate unless missing)

- Training data: `data/experiments/phase-03c/teacher-full-v6/claude-sonnet-5-accepted.jsonl`
  (7,196 rows, teacher = claude-sonnet-5 via the 29qg relay, prompt v6).
- Cloud bundle: `data/experiments/phase-03c/cloud-bundle/` ≈ 96 MB —
  `train.jsonl` 7,196 / `valid.jsonl` 400 / `dev-eval.jsonl` 400 /
  `heldout.jsonl` 240, plus committed `schema.json` and `bundle-manifest.json`
  (`make phase03c-cloud-bundle-check` must stay green; rebuild only with
  `make phase03c-cloud-bundle PHASE03C_TOKENIZER_PATH=<8B snapshot>`).
- Base models in `~/.cache/huggingface/hub/`: `Qwen/Qwen3-8B-MLX-bf16`
  (rev `6766fd4b…`, for local MLX) and the 4B 4-bit base. The cloud run
  downloads `Qwen/Qwen3-8B` (rev `b968826d…`) itself.
- Cloud package: `ml/training/phase03c_cloud/` — `train.py`
  (TRL/PEFT LoRA r32/α64, 3 epochs, 4×4, LR 1.5e-4 cosine, `max_length`
  **2304**, prompt/completion masking, dev-eval callback every 100 steps,
  selects the checkpoint by dev `oracle_act_agreement` with zero policy
  violations), `eval_heldout.py` (vLLM arms A1/A2/A3/A4, guided JSON from
  `schema.json`, Wilson CIs, pre-registered GO_DISTILLED / GO_PROMPT_ONLY /
  NO_GO), `scoring.py` (repo-free scorer, parity-tested), `run.sh`,
  `configs/lora-8b.json`, `requirements.txt`, `README.md`. **Never executed
  on a GPU** — expect TRL/vLLM API drift on first run; README says which
  pins to relax first.

## 3. What to do next: run Stage 2 on Modal

The user has a Modal account (free USD 30/month, no card). Nothing in the
repo talks to Modal yet.

1. Write `ml/training/phase03c_cloud/modal_run.py` (owned by this change):
   a Modal app with an image built from `requirements.txt` (CUDA 12.x
   torch, transformers, trl, peft, accelerate, datasets, vllm, pydantic),
   a `Volume` holding the bundle and outputs, and one function on
   `gpu="A100-80GB"` (fallback `H100`) with `timeout` ≥ 6 h that runs
   `train.py --bundle-dir … --out-dir … --merge` then
   `eval_heldout.py … --dev`, exactly as `run.sh` does. A local entrypoint
   uploads `data/experiments/phase-03c/cloud-bundle/` to the Volume and
   downloads `phase03c-upload.tar.gz` (run-manifest, dev-evals.jsonl,
   heldout-report.json, dev report, adapter dir, logs; never merged
   weights) into `data/experiments/phase-03c/training/cloud-run-01/`.
   Secrets: none needed (public model, no relay calls).
2. The user must run `pip install modal && modal setup` once (browser
   auth) — that is the credential step; do not ask them for tokens.
3. Smoke first: `PHASE03C_TRAIN_FLAGS="--smoke"` (≈ 10 min, < USD 1), fix
   any dependency/API drift, then the full run (≈ 3.5–4 h, ≈ USD 10–15).
   Keep the run's Modal app name and call id in the log.
4. Back in the repo (branch `feat/phase-03c-stage2-cloud-run`): commit the
   returned reports and manifest (not adapters/weights; `.gitignore`
   already covers `**/adapters/`, `*.safetensors`), re-score every raw
   output locally with the real evaluator (`Phase03CQwenAdapter`
   generator injection + `run_phase03c_row`, or the dev-eval script's
   aggregation), and only then record the Stage 3 decision. Write
   `harness/log/phase-03c-stage2-stage3.md` and
   `harness/code_review/…` after an independent `reviewer` pass; return
   `status.toml` to `idle`; PR; merge. Stage 3's A0 (oracle ceiling) is
   computed offline from `heldout.jsonl`; A5/A6 hosted arms are out of
   scope (relay keys are empty anyway).

## 4. Decision rules to apply literally (contract Stage 3)

- GO_DISTILLED: A3 or A4 act agreement − A1 ≥ 10 points with CI excluding 0,
  `false_completion` and `policy_violation` = 0, unsupported-fact rate not
  worse than A1 by > 2 points.
- GO_PROMPT_ONLY: A2 − A1 ≥ 0 and A3/A4 − A2 < 5 points → prompt +
  constrained decoding is enough; distillation is not promoted and that is
  a valid result.
- NO_GO: neither, or any safety regression in A3/A4 vs A1 (checked first).
- Expect GO_PROMPT_ONLY to be a live outcome: untuned 8B with prompt v4
  already scored 6/6 end-to-end on the six dev scenarios
  (`data/experiments/phase-03c/results/arm-a-untuned-8b-v4.json`).

## 5. Facts that will save time

- All three relay keys in `.env` (`api`, `备用key1`, `备用key2`; `key:value`
  lines, never print them) are exhausted — no more teacher calls are
  possible or needed. Real relay usage over Stages 1b/1c ≈ USD 146.
- Prompt versions v3/v4/v5/v6 are additive constants in
  `ml/evaluation/src/proxyloop_evaluation/phase03c_experiment.py`; Stage 2/3
  use **v6**. v6's known weakness: disclosure-restriction position 2
  (`challenge` 6/30 in the re-pilot) — report that family separately.
- 30% of rendered rows exceed 2,048 tokens (max 2,228), hence
  `max_length` 2,304; Qwen3's template has no generation span, hence
  prompt/completion masking.
- `qwen_mlx.py`, `fast_output.py`, `fresh_fixtures.py`, `phase03b_experiment.py`,
  `hosted_rerun.py`, `openai_frontier.py` are frozen by the 03A1 r4 /
  03B fingerprints — add modules, never edit them.
- Local MLX LoRA pipeline (`scripts/run_phase03c_training.py`) is a smoke /
  fallback only (4B, 4 iters, 79 s); it is not the Stage 2 run.
- `.claude/worktrees/phase-03c-parallel` belongs to another session; never
  add it. PR #43 (`fix/web-failure-surfacing`) is also another session's.
- Subagent routing: `explorer` / `implementer` / `reviewer` / `fast-worker` /
  `architect` in `.claude/agents/`; keep the main session as orchestrator
  (the user asked for that explicitly). Reviewer findings so far have been
  substantive every time — do not skip the review pass.
- Run gates with `make preflight` (≈ 3 min; runtime 316 / ML 319 / web 47
  at last run). `make test` includes every phase-03c artifact check.
