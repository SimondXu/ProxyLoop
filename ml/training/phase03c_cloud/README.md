# Phase 03C cloud package: Stage 2 LoRA SFT + Stage 3 held-out arms

Self-contained directory for one rented CUDA box. It imports nothing from the
ProxyLoop repository; everything it needs is in the bundle rendered locally by
`scripts/build_phase03c_cloud_bundle.py`.

```
phase03c_cloud/
  README.md            this file
  requirements.txt     torch/vllm/trl/peft/... (see pin notes inside)
  configs/lora-8b.json the Stage 2 recipe (r 32 / alpha 64 / dropout 0.05, LR 1.5e-4 cosine, 3 epochs, ...)
  scoring.py           pure-Python copy of the Phase 03C row evaluator (parity-tested in the repo)
  train.py             TRL SFTTrainer + PEFT LoRA on Qwen/Qwen3-8B, dev-eval callback, checkpoint selection
  eval_heldout.py      vLLM arms A1-A4 over heldout.jsonl (and dev-eval.jsonl with --dev)
  run.sh               install -> train -> eval -> tar the upload set
```

## 1. Build the bundle locally (repo, CPU)

```bash
make phase03c-cloud-bundle PHASE03C_ACCEPTED=data/experiments/phase-03c/teacher-full-v6/claude-sonnet-5-accepted.jsonl
# optional token stats: add PHASE03C_TOKENIZER_PATH=<local Qwen3-8B tokenizer snapshot>
make phase03c-cloud-bundle-check
```

Output `data/experiments/phase-03c/cloud-bundle/`:

| file | rows | content |
|---|---|---|
| `train.jsonl` | accepted rows | `{"messages":[system,user,assistant]}`; system/user byte-equal to `prompt_builder("v6")` |
| `valid.jsonl` | 400 | development rows with the canonical oracle target as assistant (eval loss only) |
| `dev-eval.jsonl` | 400 | `prompt_id, family_id, split, messages[system,user], oracle_target, public_observation, view, ...` |
| `heldout.jsonl` | 240 | 3 development + 3 test families x 2 configs x seeds 950-959 x 2 positions, same fields |
| `schema.json` | - | `FastModelOutput.model_json_schema()` for guided JSON |
| `bundle-manifest.json` | - | counts, SHA-256 per file, prompt/compiler version, base model + revision, git commit |

Only the manifest and `schema.json` are committed; the JSONL files carry
teacher text and are git-ignored. `oracle_target`, `public_observation`, and
`view` are evaluator inputs; the model only ever sees `messages`.

## 2. On the GPU box

```bash
# copy the two directories
scp -r ml/training/phase03c_cloud data/experiments/phase-03c/cloud-bundle box:~/phase03c/
ssh box
cd ~/phase03c/phase03c_cloud
export HF_HOME=/workspace/hf            # optional: put the 16 GB base download on the big disk
bash run.sh ../cloud-bundle ../out       # install + train + eval + tar
```

`run.sh` runs, in order:

1. `pip install -r requirements.txt` (skip with `PHASE03C_SKIP_INSTALL=1`). No
   HF token is needed: `Qwen/Qwen3-8B` is public and pinned to revision
   `b968826d9c46dd6066d109eabc6255188de91218` by the bundle manifest.
2. `python train.py --bundle-dir ../cloud-bundle --out-dir ../out/train --merge`
3. `python eval_heldout.py --bundle-dir ../cloud-bundle --run-dir ../out/train --out-dir ../out/eval`
   and the same with `--dev` (A1-A4 over the 400 dev rows, to compare with the training-loop numbers).
4. `tar` of the upload set -> `../out/phase03c-upload.tar.gz`.

Pipeline smoke before spending hours (about 10 minutes after the download):

```bash
PHASE03C_TRAIN_FLAGS="--smoke" bash run.sh ../cloud-bundle ../out-smoke
```

40 GB card: `PHASE03C_TRAIN_FLAGS="--per-device-train-batch-size 2 --gradient-accumulation-steps 8"`
(same effective batch 16; recorded in `run-manifest.json`).

### What train.py does

- Loads `Qwen/Qwen3-8B` bf16 at the bundle's revision, LoRA on all linear
  projections, `SFTConfig(max_length=2304, 3 epochs, 4 x 4, LR 1.5e-4 cosine,
  warmup 3 %, bf16, gradient checkpointing, seed 0, eval + save every 100 steps)`.
- Loss masking: the Qwen3 chat template has no `{% generation %}` markers, so
  `assistant_only_loss=True` is impossible; `train.py` detects that and falls
  back to TRL prompt/completion masking with the prompt pre-rendered through
  the chat template with `enable_thinking=False`. Which mode ran is logged and
  written to `run-manifest.json` (`loss_masking`). Before training it decodes
  the labels the collator actually emits for the first row and refuses to
  train unless they equal the assistant JSON + `<|im_end|>` and the masked
  prefix ends with the empty `<think>\n\n</think>\n\n` block.
- **Token overflow.** Prompts are ~1,790-1,915 tokens and teacher answers up
  to ~260, so ~8% of rows exceed 2,048 tokens (max ≈ 2,155); `configs/lora-8b.json` therefore sets `max_length: 2304` (root decision, Stage 2 preflight) so nothing is dropped at the contract's effective batch. It also sets
  `overflow_policy: "drop"`: rows longer than `max_length` are dropped and
  counted in `run-manifest.json` (`token_stats.train.over_max_length`,
  first 20 prompt ids). Right-truncation would cut the JSON target, so it is
  never the default; raise `max_length` (e.g. 2304) in the config if the
  dropped share matters (memory is not the constraint on 80 GB).
- Dev-eval callback at step 0 (untuned base, same loop) and at every eval step:
  greedy generation, `max_new_tokens` 512, `enable_thinking=False`, over a
  stratified 60-row subset of `dev-eval.jsonl` (6 per family, the same first-6
  rule as the repository's `subset60`; `--full-dev` for all 400). Scored with
  `scoring.py`, appended to `dev-evals.jsonl` with every raw output.
- Checkpoint selection (contract rule): max `oracle_act_agreement` with
  `policy_violation == 0`, ties by lower `unsupported_response_violation`,
  then the earlier step. Never by loss. Step 0 is recorded as
  `untuned_baseline` and excluded from selection;
  `selected_minus_untuned_act_agreement` is the Stage 2 acceptance number.
- Exports `adapter/` (`adapter_config.json`, `adapter_model.safetensors`) and,
  with `--merge`, `merged/` bf16 weights + tokenizer for vLLM.
- `run-manifest.json`: dataset fingerprint, base revision, config hash,
  package versions, GPU, wall time, per-eval table, selected step, SHA-256 of
  the adapter and merged files, loss masking mode and self-check.

### What eval_heldout.py does

Arms on the frozen `heldout.jsonl` (n = 240: 120 development-family rows,
120 test-family rows), greedy, 512 tokens, `enable_thinking=False`:

| arm | model | decoding |
|---|---|---|
| A1 | untuned Qwen3-8B bf16 | plain |
| A2 | untuned | vLLM structured outputs with `schema.json` |
| A3 | selected adapter merged | plain |
| A4 | merged | guided JSON |

Per arm: `scoring.py` metrics with Wilson 95 % CIs, family and split
breakdown, single-stream p50/p95 latency over the first `--latency-rows`
(24) prompts plus batched throughput, token counts, `finish_reason` counts,
and every raw output. `heldout-report.json` (`schema_version:
"phase-03c-heldout-v1"`, `result_role: "cloud_candidate"`) carries the
pre-registered decision exactly as the contract states (`GO_DISTILLED`,
`GO_PROMPT_ONLY`, `NO_GO`) with every check that fed it; the NO_GO clause
"any safety regression in A3/A4 vs A1" is applied literally and first.

A0 (oracle ceiling) is 100 % by construction and computed offline. A5/A6
(hosted teachers as Fast) are out of scope here. A1/A2 can run before
training (`--arms A1,A2`, no `--run-dir`) and be merged into the final report
with `--previous-report`.

### Fields the cloud scorer cannot reproduce

`scoring.py` reproduces every `Phase03CRowMetrics` field bit-for-bit
(parity test: `ml/tests/test_phase03c_cloud_scoring.py`) with these caveats:

- `stale_pin_violation` needs `ModelInputPins`; in the adapter path it is
  always `False` because the compiler binds the view's own pins, so it is
  reported `False`, not computed.
- Verifier end-to-end replay (`runner_v2`) is local only; `end_to_end_valid`
  is the row-level composite the repository evaluator also reports.
- The numeric-relation check (`unsupported_response_violation`) *is*
  reproduced from `public_observation` in the row.

Every raw output is in the reports, so the repository evaluator re-scores
them locally before any number is treated as canonical.

## 3. On Modal (`modal_run.py`)

`modal_run.py` runs the same three commands as `run.sh` inside one Modal
Function, so no box is rented or copied to by hand.

```bash
pip install modal && modal setup            # once: browser auth against your account
modal run ml/training/phase03c_cloud/modal_run.py --smoke        # ~30 min, pipeline check
modal run --detach ml/training/phase03c_cloud/modal_run.py       # the real run
modal run ml/training/phase03c_cloud/modal_run.py --download-only  # fetch after a --detach run
```

| piece | where |
|---|---|
| bundle | Volume `phase03c-bundle` at `/bundle`, uploaded by the local entrypoint |
| HF cache | Volume `phase03c-hf-cache` at `/hf`; the 16 GB base is downloaded once |
| training + merged weights | the container's own disk (`/scratch`), never a Volume |
| upload set | Volume `phase03c-out` at `/out/<run>/`, downloaded to `data/experiments/phase-03c/training/<run>/` |

- GPU is `["A100-80GB", "H100"]` (fallback order), `timeout` 12 h (billed per second used, not per timeout).
- `--smoke` passes `--smoke` to `train.py`, caps the arms at `--limit 8` and
  skips the dev-set arm pass; it uses run name `smoke-01` so it cannot
  overwrite the real run's outputs.
- The adapter, `run-manifest.json`, `dev-evals.jsonl` and `train.log` are
  mirrored to the out Volume *before* the vLLM arms start, so a Stage 3
  failure cannot destroy the Stage 2 evidence.
- Flags: `--run <name>`, `--train-flags "..."`, `--skip-upload` (bundle
  already on the Volume), `--skip-download`, `--bundle-dir`, `--download-dir`.
- Cost: check your own workspace rates with `modal billing rates`, and the
  spend so far with `modal billing summary`. Run the smoke first.

## 4. Expected wall time (A100-80GB, estimate)

| step | time |
|---|---|
| pip install + 16 GB base download | 10-20 min |
| train: 7,196 rows x 3 epochs / 16 = 1,349 optimizer steps at ~36k tokens/step | ~4-5 h |
| dev evals: 14 x 60 rows HF generate (+ eval loss on 400 rows) | ~30-50 min |
| merge + save bf16 | ~5 min |
| eval_heldout: 2 vLLM loads, 4 arms x 240 rows batched + 24-row latency samples | ~15-20 min |
| eval_heldout --dev: 4 arms x 400 rows | ~10 min |
| **total** | **~5.5-7 h** |

H100: roughly 35-45 % faster on the training step.

The step count is 1,349, not the ~710 an earlier draft of this table stated:
the bundle carries 7,196 train rows (`bundle-manifest.json`), none dropped at
`max_length` 2304. Budget the run against your provider's own rate.

## 5. What to upload back

`../out/phase03c-upload.tar.gz` (a few hundred MB, mostly the r-32 adapter):

- `train/run-manifest.json` -> committed as `data/experiments/phase-03c/training/run-<id>-manifest.json`
- `train/dev-evals.jsonl` (raw outputs for local re-scoring)
- `train/adapter/` (kept outside Git; `*.safetensors` is ignored)
- `eval/heldout-report.json`, `eval/dev-report.json`
- the three logs

Do **not** upload `merged/` (16 GB); the adapter + base revision reproduce it.
