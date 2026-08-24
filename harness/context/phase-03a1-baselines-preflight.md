# Phase 03A1 Baselines Preflight

Date: 2026-08-23

## Starting Point

- `main` and `origin/main`: `e08c9b6faa8a235eb30f9621ff999996de8cfe84`;
- Harness PR #8: squash merged; final CI, GitGuardian, independent Terra review,
  and post-merge `make preflight` passed;
- active branch: `experiment/phase-03a1-baselines`;
- starting worktree: clean;
- Phase 02 remains `pending_human`, `training_ready=false`.

## Observed Local Runtime

- Apple M4 Pro with 48 GB unified memory and approximately 467 GiB free disk;
- no Qwen checkpoint is cached locally;
- project ML environment has no MLX, Transformers, OpenAI, or Hugging Face SDK;
- the user-level Python environment has OpenAI, Transformers, and Hugging Face
  packages but no MLX; the repository will not rely on that unpinned environment;
- no supported frontier API credential is present in the process environment;
- hardware serial number and UUID are deliberately excluded from all evidence.

## Source and License Evidence

- official Qwen model card: `Qwen/Qwen3-4B-Instruct-2507`, 4.0B parameters,
  non-thinking instruct mode, 262,144 native context, Apache-2.0;
- practical Apple-Silicon candidate:
  `mlx-community/Qwen3-4B-Instruct-2507-4bit`, approximately 2.28 GB, derived
  from the official Qwen checkpoint and labeled 4-bit MLX;
- the original official `gpt-5.6-sol` candidate was superseded by the user's
  explicit 2026-08-24 decision to use `gpt-5.6-terra` through the 29qg
  OpenAI-compatible Chat Completions endpoint;
- all drift-prone revisions and runtime versions must be captured again by the
  actual runner.

## Root-Frozen Decisions

- use the 4-bit MLX derivative for the bounded local baseline and label every
  result `quantized_untuned`;
- retain exact source and derivative lineage; do not claim parity with native
  BF16 weights;
- use no episode-specific held-out reference strategy and no gold/evaluator
  field in prompts;
- preserve the two distinct Slow-off interpretations defined by the Harness;
- keep actual model execution manual and networked, while CI runs only the
  deterministic offline artifact validator;
- reject the hosted result if the proxy remaps `gpt-5.6-terra` to another model
  family; record an exact returned snapshot suffix when present;
- missing frontier credentials are an honest execution blocker, not a model
  result.

## Risks for Independent Review

- quantized results may be mislabeled as source-checkpoint quality;
- prompt or reference-strategy construction may consume held-out labels;
- structured-output parsing may repair invalid generations and inflate quality;
- a model adapter may bypass current-pin or `action_intent=null` validation;
- the baseline runner may reuse Harness internals in a way that forks authority;
- committed results may omit failed calls, retries, token use, or cost;
- the offline gate may validate shape without binding exact manifests, prompts,
  models, and outputs;
- model-visible logs may leak evaluator-only Family, Entity, Provider, safety, or
  oracle metadata.
