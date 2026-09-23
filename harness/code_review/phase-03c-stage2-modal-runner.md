# Phase 03C Stage 2 Modal runner — independent review

Reviewer: project `reviewer` agent (Opus, high effort), read-only, not the
session that wrote the diff. Recorded by the root orchestrator.
Diff reviewed: `feat/phase-03c-stage2-cloud-run` vs `main` at `fa479f2`,
four files under `ml/training/phase03c_cloud/`.

**Verdict: Request Changes.** All findings addressed; see disposition below.

## Confirmed sound (recorded so it is not re-litigated)

- **warmup semantics.** The reviewer unpacked the `transformers==5.17.0` and
  `trl==0.29.1` sdists rather than reasoning from memory.
  `training_args.py:2122` computes
  `int(warmup_steps) if warmup_steps >= 1 else ceil(num_training_steps * warmup_steps)`;
  the 4.x path computes `ceil(num_training_steps * warmup_ratio)`. For 0.03
  these are the same expression — 41 steps at 1,349. `warmup_ratio` has zero
  references left in the 5.17.0 tree, so the feature-detect always selects
  `warmup_steps`, matching `warmup_arg` in the manifest. The contracted
  "warmup 3%" is preserved.
- **All four arms decode greedily.** `eval_heldout.py:151` is the only
  `SamplingParams` construction site (`temperature=0.0, seed=0`) and A1-A4
  share `run_arm`, so `VLLM_USE_FLASHINFER_SAMPLER=0` cannot change a scored
  output.
- **`torch==2.13.0` alongside `vllm==0.30.0` is not a conflict.** vllm
  0.30.0's own `requires_dist` pins `torch==2.13.0` and
  `flashinfer-python==0.6.18.post1` exactly. The previous comment warning
  against pinning torch is obsolete.
- **`run_logged` does not swallow failures.** `bash -o pipefail` + `tee`
  propagates the inner exit code (tested).
- **Scope compliant.** No frozen module and no `configs/lora-8b.json` change.

## Findings and disposition

| # | Severity | Finding | Disposition |
|---|---|---|---|
| B1 | Blocking | `eval/heldout-report.json` was only mirrored after the dev round, so a dev-round OOM would destroy Stage 3's contracted artifact with no resume path (merged weights live on the container's disk) | Fixed: mirror `eval/` + log + commit immediately after the held-out round |
| B2 | Blocking | The pinned `requirements.txt` was written *after* the smoke, so no image had ever been built from it; `xgrammar` (the A2/A4 guided-JSON backend), `tokenizers` and `numpy` were still unpinned | Fixed: those three pinned explicitly; two further smoke runs executed on the final file |
| I1 | Important | Missing tarball members were silently filtered, and `--download-only` never prints the member list | Fixed: missing member raises `SystemExit` |
| I2 | Important | A training failure at hour 4 lost the adapter, `dev-evals.jsonl` and checkpoints with no mirror | Fixed: `try/finally` mirrors whatever training produced |
| m1 | Minor | `--download-only --skip-download` printed a success-shaped message having done nothing | Fixed: refused |
| m2 | Minor | `ensure_cuda_home()` docstring read as load-bearing though nothing compiles any more | Fixed: relabelled diagnostic |
| m3 | Minor | No guard on `warmup_ratio >= 1`, where the two paths mean silently different things | Fixed: range check in `train.py` |
| m4 | Minor | `--smoke --run cloud-run-01` would overwrite the real run's outputs | Fixed: smoke run names must start with `smoke` |
| m8 | Minor | A comment stated the wrong reason for setting `XDG_CACHE_HOME` at runtime | Fixed: pip's own cache is the actual reason |
| m5–m7 | Minor | No download checksum; `copytree(dirs_exist_ok=True)` can leave stale files under a reused run name; `ml/training/phase03c_cloud` is outside the mypy target list | Accepted, not fixed. The first two are visible failures, not silent ones; the third is pre-existing repository state and out of this change's scope |

## Regression introduced while fixing, and caught

The I1 fix filtered smoke members by `"dev" not in name`, which also
matched `train/dev-evals.jsonl` — the per-step record holding the untuned
step-0 baseline, i.e. the Stage 2 before/after evidence. Detected by
comparing `tarball_members` against the previous run's, fixed with an
explicit `DEV_ROUND_MEMBERS` list, and verified by asserting both branches
locally and by a further smoke run that shows the file restored.

## Escalation accepted by the root orchestrator

`harness/status.toml` described the Stage 2 execution path as a rented CUDA
box. Updated to name Modal. The phase stays `blocked`: the runner being
ready is not the run having happened.
