# Phase 03C Stage 2 Preflight — training package (cloud) and local pipeline smoke

Date: 2026-09-22

## Activation evidence

- Stage 1c merged as PR #41 (`36a7916`): 7,196 accepted rows over all ten
  train families, `training_ready = true`, prompt v6.
- The user chose (2026-09-22) to run the real training on a rented CUDA box
  with free credits, which is the contract's own Stage 2 path; ProxyLoop
  supplies a self-contained package and the user executes it. No cloud
  credential is held by the repository or the orchestrator.
- Branch `feat/phase-03c-stage2-training-package`; `harness/status.toml`
  `blocked` while the cloud run is in the user's hands.

## Observed state

- Rendered rows with the Qwen3-8B tokenizer: 7,596 (train + valid), min
  1,850, p95 2,123, max 2,228 tokens; 2,279 rows (30%) exceed the
  contract's 2,048.
- Qwen3's chat template exposes no `{% generation %}` span, so TRL's
  `assistant_only_loss` is unavailable; prompt/completion masking with the
  template pre-rendered under `enable_thinking=False` is the equivalent.
- No torch / trl / vllm locally; `mlx-lm 0.31.3` is installed. The cloud
  package's TRL/vLLM API assumptions are untested until the user runs it.

## Frozen decisions

1. **Cloud package** `ml/training/phase03c_cloud/` (train.py, eval_heldout.py,
   scoring.py, run.sh, configs/lora-8b.json, requirements.txt, README) is
   the Stage 2 + Stage 3 execution path. It imports nothing from ProxyLoop;
   the bundle `data/experiments/phase-03c/cloud-bundle/` carries train /
   valid / dev-eval / held-out JSONL (git-ignored), `schema.json`, and
   `bundle-manifest.json` (committed, `make phase03c-cloud-bundle-check`).
2. Recipe = contract Stage 2 with two documented adjustments:
   `max_length` **2,304** (covers the 2,228 max; dropping or truncating 30%
   of rows would bias against the longer, fully-argued answers) and
   prompt/completion masking instead of `assistant_only_loss`. Everything
   else as contracted: LoRA r 32 / α 64 / dropout 0.05 / all linear, 3
   epochs, 4 × 4, LR 1.5e-4 cosine, warmup 3%, bf16, gradient
   checkpointing, seed 0, eval + save every 100 steps; checkpoint selected
   by dev `oracle_act_agreement` with `policy_violation == 0` (ties: lower
   unsupported, earlier step), never by loss; ≤ 4-run search budget.
3. Stage 3 arms A1/A2/A3/A4 run on the same box (`eval_heldout.py`, vLLM
   guided JSON from `schema.json`), greedy, 512 tokens,
   `enable_thinking=False`, held-out = 3 development + 3 test families × 2
   configurations × seeds 950..959 × 2 positions = 240 rows; pre-registered
   rules GO_DISTILLED / GO_PROMPT_ONLY / NO_GO exactly as the contract,
   safety regression checked first. A0 is computed offline; A5/A6 hosted
   arms are out of scope for this change.
4. The cloud scorer reproduces the Stage 0 evaluator's row metrics (parity
   test over 184 comparisons) except `stale_pin_violation` (always false on
   the adapter path) and the verifier replay; every raw output is returned
   so the root re-scores locally with the real evaluator before any
   decision is recorded.
5. **Local MLX pipeline** (`phase03c_training/`, `run_phase03c_training.py`,
   `run_phase03c_dev_eval.py`) stays as a pipeline smoke and fallback only;
   the 4B smoke run manifest is committed. The real 8B run is not executed
   locally.
6. What comes back from the box: `run-manifest.json`, `dev-evals.jsonl`,
   `heldout-report.json`, the selected adapter directory, logs — no merged
   weights in Git. The root orchestrator records the Stage 3 decision only
   after local re-scoring.

## Operator steps (user)

1. Rent a CUDA box with ≥ 40 GB VRAM (A100 40/80 GB, H100, L40S).
2. Copy `ml/training/phase03c_cloud/` and `data/experiments/phase-03c/cloud-bundle/` (≈ 96 MB) to the box.
3. `bash run.sh ../cloud-bundle ../out` (≈ 3.5–4 h on an A100-80GB; add
   `PHASE03C_TRAIN_FLAGS="--smoke"` first for a 10-minute pipeline check;
   on 40 GB use `--per-device-train-batch-size 2 --gradient-accumulation-steps 8`).
4. Upload `phase03c-upload.tar.gz` back into
   `data/experiments/phase-03c/training/cloud-run-01/`.
