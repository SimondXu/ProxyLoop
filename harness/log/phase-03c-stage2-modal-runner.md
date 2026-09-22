# Phase 03C Stage 2 — Modal runner — execution log

Contract: `harness/build/phase-03c-fast-model-distillation.md` Stage 2/3.
Frozen decisions: `harness/context/phase-03c-stage2-preflight.md`.
Branch `feat/phase-03c-stage2-cloud-run`, base `main` at `fa479f2`.

Scope: make the existing cloud package runnable on Modal and make the stack
it runs on reproducible. No change to the contracted recipe, the evaluator,
the bundle, or any frozen module. The Stage 2 training run itself has NOT
been executed; this log covers the runner and its validation only.

## What changed

| File | Change |
|---|---|
| `ml/training/phase03c_cloud/modal_run.py` | new; one Modal Function running the same three commands as `run.sh` |
| `ml/training/phase03c_cloud/train.py` | 13 lines: `warmup_ratio` feature-detect + range guard, `warmup_arg` in the manifest |
| `ml/training/phase03c_cloud/requirements.txt` | lower bounds replaced with exact pins |
| `ml/training/phase03c_cloud/README.md` | Modal section; corrected wall-time table |

## Environment drift found by running it

`requirements.txt` carried lower bounds only and was written offline on
2026-09-22 without resolving against an index (its own comment said so).
pip resolved a stack the package predates:

| Package | Resolved |
|---|---|
| torch | 2.13.0+cu130 |
| transformers | 5.17.0 |
| trl | 0.29.1 |
| peft | 0.21.0 |
| vllm | 0.30.0 |
| flashinfer-python | 0.6.18.post1 |

Two incompatibilities, both fixed:

1. `transformers` 5 removed `SFTConfig.warmup_ratio`. `train.py` now
   feature-detects and passes `warmup_steps`, which in transformers >= 5 is
   a float whose value in [0, 1) is a ratio of total steps. **Verified
   equivalent at source level** by the independent reviewer against the
   5.17.0 and 4.x sdists: both paths evaluate `ceil(N * 0.03)` — 41 steps at
   the run's 1,349. Cross-checked against the smoke's `log_history`
   (step 1 LR 0.0, step 2 LR 1.5e-4, i.e. `ceil(4 * 0.03) = 1`). The
   contract's "warmup 3%" is unchanged. Which argument was used is recorded
   in `run-manifest.json` as `warmup_arg`.
2. vLLM's flashinfer sampler JIT-compiles kernels at first use and cannot:
   the CUDA wheels ship nvcc 13.4, torch is cu130, and flashinfer bundles
   its own cccl headers, which reject that combination
   ("CUDA compiler and CUDA toolkit headers are incompatible"). Disabled
   through `VLLM_USE_FLASHINFER_SAMPLER=0`. `eval_heldout.py:151` is the
   only `SamplingParams` construction site and sets `temperature=0.0,
   seed=0` for all four arms, so the PyTorch-native sampler cannot change a
   scored output.

## Verification

Six Modal smoke runs (`--smoke`: 32 train rows, 4 optimizer steps, 1 dev row
per family, `--limit 8` per arm). The first four failed and are the evidence
for the fixes above plus two defects in `modal_run.py` itself (a repo-root
lookup that is out of range on the container's `/root`, and an image-level
`XDG_CACHE_HOME` that populated the `/hf` mount point during the build so
the Volume could not mount).

Final two runs, on the pinned stack and the reviewed code, passed end to
end on A100-80GB: train → checkpoint selection (step 2, `policy_violation`
0) → merge → A1/A2/A3/A4 → decision → tarball → download. 601 s and 722 s
wall. The numbers those runs produce are meaningless (4 optimizer steps,
8 rows per arm); what they establish is that every stage executes and every
artifact is produced.

The loss-masking self-check passed on every run: 96 trained tokens equal to
the assistant JSON plus `<|im_end|>`, masked prefix ending in the empty
`<think>` block.

Repository gates: `make lint`, `make format-check`, `make preflight-fast`
passed. `make typecheck` does not cover `ml/training/phase03c_cloud` (the
mypy target list omits it; pre-existing, not introduced here).
`make test` and `make preflight` not rerun since the last green run on this
diff's predecessor; no repository artifact changed.

Cost: USD 4.16 metered, fully covered by the Modal free credit.

## Independent review

`harness/code_review/phase-03c-stage2-modal-runner.md`. Verdict Request
Changes: 2 blocking, 2 important, 8 minor. All addressed. Applying the
member-filter fix introduced a regression — `train/dev-evals.jsonl`, the
per-step before/after record, was silently dropped from the smoke tarball —
caught by comparing `tarball_members` against the previous run and fixed
with an explicit dev-round member list plus a local both-branch assertion.

## State at the gate

`harness/status.toml` stays `blocked` on `03C-stage2`: the runner is ready
and validated, the ~6-hour training run is a separate user decision. The
Stage 3 decision, the local re-scoring with the real evaluator, and the
return to `idle` all wait on that run's artifacts.
