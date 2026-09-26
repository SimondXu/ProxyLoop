# ADR-0003: Pinned BF16 LoRA training configuration and the SFT smoke

- **Status:** proposed. The module dump (`train-modules`, CPU, no weights) was run while writing this ADR and is
  committed. `train-smoke` (G) and adapter liveness in the S0-MOD-01 server are root runs and still pending: every
  value they produce is named below by its key, never typed here (AGENTS rule 13).
- **Date:** 2026-09-26
- **Task:** S0-MOD-02

## Context
TRAINING §8 fixes a BF16 LoRA recipe on `Qwen/Qwen3.5-9B` whose targets are "restricted to what vLLM serves".
ADR-0002 chose the served ladder rung `all` (attention + GDN + MLP, `docs/decisions/data/vllm-lora-ladder.json`
`summary["applied_targets"]`) and found that vLLM 0.29.0 needs `linear_attn.in_proj_qkv` in every adapter that
has `linear_attn.in_proj_z`. Three things had to be settled before any paid training: that PEFT can target the
Gated DeltaNet (GDN) projections under the served module names, that the vision tower stays out, and that
training never silently runs the GDN and causal-conv paths on their PyTorch reference implementations.

Facts checked in the pinned sources (not measurements):
- transformers 5.17.0 `models/qwen3_5/modeling_qwen3_5.py` wraps `causal_conv1d_fn`, `causal_conv1d_update`,
  `torch_chunk_gated_delta_rule` and `torch_recurrent_gated_delta_rule` with
  `integrations/hub_kernels.py` `use_kernel_func_from_hub_with_fallback`. At import, each wrapper imports its
  package (`causal_conv1d`; `fla`, i.e. flash-linear-attention) and keeps the resolved function in a closure
  variable `implementation`; on any import failure it keeps the torch function and only logs a warning once.
- The same file's `Qwen3_5GatedDeltaNet.forward` calls these module-level names; the `kernels` hub package, which
  could re-wrap them, is not installed in the training image.
- `Trainer._save_checkpoint` writes `trainer_state.json` after the model, optimizer, scheduler and RNG files, so a
  checkpoint directory without it is incomplete.
- transformers 5.17.0 ships `train_sampling_strategy="batch_rebalance"` (`trainer_pt_utils.BatchRebalanceSampler`):
  per optimizer step it sorts the step's rows by length and splits them into `gradient_accumulation_steps`
  micro-batches of balanced padded cost, so long rows land in smaller micro-batches.
- causal-conv1d 1.7.0 publishes a prebuilt `cu12torch2.10cxx11abiTRUE-cp312` wheel; torch 2.10.0 on PyPI is a
  CUDA 12.8 build. No newer torch has a prebuilt causal-conv1d 1.7.0 CUDA 12 wheel.

## Decision
- **Image** (`training_jobs/sft.py` `PINS`, built by `training_jobs/modal_train.py`): Modal `debian_slim`
  Python 3.12 with exactly `torch==2.10.0`, `transformers==5.17.0`, `peft==0.21.0` and `accelerate==1.15.0` (the
  S0-MOD-01 pins, imported from `serving/config.py`), `trl==1.14.0`, `datasets==5.0.1`, `huggingface_hub==1.33.0`,
  `flash-linear-attention==0.5.2`, `fla-core==0.5.2`, `pydantic==2.13.5`, and causal-conv1d 1.7.0 from its
  prebuilt wheel URL (no nvcc build). None of these enter `pyproject.toml` or `uv.lock`. One H100
  (`serving.config.GPU`); model and tokenizer from the pinned revision on the shared HF volume.
- **Model and targets:** `AutoModelForImageTextToText` in BF16, so module names are exactly the ones vLLM loads
  (`base_model.model.model.language_model.layers.N.<parent>.<proj>`, ADR-0002 Migration). PEFT `target_modules`
  is `serving.config.target_regex(RUNGS["all"])`, anchored to `model.language_model.layers.<N>.`: rank and
  alpha are `serving.config.LORA_RANK` / `LORA_ALPHA`, dropout 0.05. Train targets = served targets by
  construction; a test compares them with the ladder's `applied_targets` and checks the packing leader rule.
- **Vision tower frozen and untargeted:** PEFT freezes every base parameter, and the job aborts unless every
  trainable parameter is a `lora_A`/`lora_B` weight of a served target on a language-model layer and every target
  is present (`sft.target_report`). The HF model has no `mtp.*` modules.
- **Fused GDN kernel check** (`sft.fused_kernels`, before the model is loaded): read the `implementation` closure
  variable of the four wrappers above; each must come from `causal_conv1d.*` or `fla.*`. A torch reference
  implementation raises and aborts the run: there is no fallback path.
- **Rows** (`proxyloop.training.dataset`): the prompt is `contract.protocol.render_prompt` only; the completion is
  `format_turn(parse_turn(raw, lane)) + "<|im_end|>"`, and a turn with any parse issue is rejected. Prompt and
  completion are tokenised separately (what vLLM sees); prompt labels are `-100`. No truncation: `max_length=None`
  in TRL, and a row over 4,096 tokens raises.
- **P5** (`proxyloop.training.masking.verify_trained_span` / `verify_batch`): on every row of the first batch from
  the trainer's own dataloader and collator, the trained span must be one contiguous run, equal the input ids,
  decode to exactly the target completion (ending in `<|im_end|>`), and the masked prefix must end with
  `<think>\n\n</think>\n\n`. Any failure aborts before step 1.
- **Micro-batching:** `batch_rebalance` with an effective 64 rows per step (8 × 8; smoke 4 × 2). Before step 1
  the job plans every micro-batch of the run and aborts if one pads to more than 16,384 tokens
  (`dataset.TOKEN_BUDGET`).
- **Packing: deferred.** GDN keeps a recurrent state and a causal-conv state across positions. Packed rows need
  both reset at every row boundary (`cu_seqlens` through the fla and causal-conv kernels, and position ids for the
  attention layers); a mistake leaks one sample into the next with no error. Before enabling it we would need a
  boundary test: for rows A and B packed as [A, B], the per-token logits and loss of B equal B run alone within
  BF16 tolerance, and B's loss gradient with respect to A's tokens is zero.
- **Resumable:** checkpoints every `save_steps` into `train/<run_id>/checkpoints` on the `proxyloop-adapters`
  volume, committed from the trainer's `on_save`. A restarted input resumes from the highest checkpoint that has
  `trainer_state.json` (`sft.latest_checkpoint`); a run whose `result.json` exists returns it. `train-smoke`
  runs detached; after a local disconnect, rerun with `--run-id <id>`.
- **Smoke** (`make -f mk/mod.mk train-smoke`): 64 rows from the 13 contract golden views paired with fixed
  synthetic turns (plumbing only: no claim), 50 steps. Per-step metrics stream as JSON lines and to
  `train/<run_id>/metrics.jsonl`. After training every `lora_B` must be non-zero; the adapter (with base model id
  and revision) is saved and hashed, then a merged BF16 copy is saved to `train/<run_id>/merged`. The result is
  written to the volume before it is returned, and locally to `docs/decisions/data/peft-train-smoke.json`.
- **Provenance:** the result carries a `runtime` block: provider, `gpu_name`, `driver_version`, `torch_cuda`,
  `modal_image_id`, the pinned image spec, and installed versions of every pinned distribution plus triton.

## Evidence
All `make` targets are `make -f mk/mod.mk <target>`.

| Measurement | Key (value lives in the JSON) | Raw artefact | Command |
|---|---|---|---|
| `named_modules()` of the pinned model (meta device) | `named_modules` | `data/peft-modules.json` | `train-modules` |
| LoRA module paths per target; trainable and total parameters | `per_target`, `lora_modules`, `trainable_params`, `all_params`, `target_regex` | `data/peft-modules.json` | `train-modules` |
| Same on the real model in the job | `lora.per_target`, `lora.lora_modules`, `lora.trainable_params` | `data/peft-train-smoke.json` | `train-smoke` (root, G) |
| Fused kernels active | `fused_kernels` (wrapper → implementation module) | `data/peft-train-smoke.json` | `train-smoke` |
| P5 on the real first batch | `p5.ok`, `p5.rows[*]` | `data/peft-train-smoke.json` | `train-smoke` |
| Throughput (non-pad tokens / train runtime) | `tokens_per_s`, `tokens`, `train.train_runtime` | `data/peft-train-smoke.json` | `train-smoke` |
| Peak GPU memory during training | `peak_mem_gib` | `data/peft-train-smoke.json` | `train-smoke` |
| Largest planned micro-batch | `max_microbatch_padded_tokens` | `data/peft-train-smoke.json` | `train-smoke` |
| Loss, per step and final | `train.train_loss`; per step `train/<run_id>/metrics.jsonl` on the volume | `data/peft-train-smoke.json` | `train-smoke` |
| Adapter files; resume | `adapter_sha256`, `resumed_from` | `data/peft-train-smoke.json` | `train-smoke` |
| Runtime provenance | `runtime.*` | `data/peft-train-smoke.json` | `train-smoke` |
| Adapter liveness in the served process (mean \|Δ prompt_logprob\| > 1e-3) | pending: needs a serving slot for a trained adapter (Risks) | – | root run |

The root compares `tokens_per_s` with TRAINING §8's 3–5k tok/s estimate.

**S0-MOD-02 acceptance** (PLAN.md):
- exact module paths and trainable parameters: **met by the CPU dump** (`data/peft-modules.json`); the job repeats
  them on the loaded model (`lora.*`) — pending `train-smoke`;
- tok/s, peak memory and the P5 result from the real run: **pending** `train-smoke`;
- the adapter loads in S0-MOD-01's server with liveness > 1e-3 nats: **pending**, blocked on a serving slot;
- train targets = serve-accepted targets: **met** (`tests/training/test_sft.py`, against
  `data/vllm-lora-ladder.json`).

## Consequences
- **Contract / fingerprint impact:** none. Rows go through `render_prompt`; `result.fingerprints` records the
  profile fingerprints the smoke trained under.
- **Data invalidated:** none.
- **Migration:** S0-MOD-03 (pull-through) reuses `proxyloop.training` and `training_jobs.sft` with teacher or
  base-9B rows instead of the synthetic smoke turns.
- **Risks and what would make us revisit this:**
  - The served slots (`serving.config.lora_slots`) are fixed to the ladder's `zero-<rung>` / `live-<rung>`
    adapters, so a trained adapter cannot be loaded without a `serving/` change (a trained-adapter slot, which
    TRAINING §9 step 4 needs anyway).
  - The kernel check reads a closure variable of transformers 5.17.0; a transformers bump must re-check it (the
    check fails loudly if the variable is missing).
  - The fused-kernel imports need a GPU and triton: on a CPU-only machine the check correctly reports the torch
    fallback, so only the root run can show them active.
  - `batch_rebalance` balances cost within a step but does not itself cap tokens; the pre-flight budget check does.
    If it trips on real data, raise `gradient_accumulation_steps` rather than the budget.
  - A run resumed after its last checkpoint reports throughput over the resumed segment only (`resumed_from`).
