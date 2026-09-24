# Local opt-in Fast serving (PR-9b)

The Phase 03C distilled adapter served locally as an opt-in Fast backend,
labelled **local opt-in candidate** (the untuned base is the **untuned local
baseline**). Never "promoted" or "production". The frozen design is
`harness/context/pr9-local-distilled-fast-design.md`; decision 18 in
`harness/context/audit-remediation-decisions.md` lists the caveats (the four
Phase 03C caveats and E1–E5) that travel with every number.

This directory holds committed hashes only. The code lives in
`ml/evaluation/src/proxyloop_evaluation/local_fast/` because
`ml/pyproject.toml` is frozen by the r4 execution contract and its wheel
package list cannot grow.

| File | What it is |
|---|---|
| `phase-03c-cloud-run-01-mlx-attestation.json` | The PEFT → MLX conversion of the Phase 03C cloud-run-01 adapter: source weights and config sha256 (equal to the run manifest), converter version, output content fingerprint (sorted key, dtype, shape, sha256 of each tensor), the MLX config sha256, 36 layers × 7 modules = 252 LoRA layers, rank 32, alpha 64, scale 2.0. |

## What is never committed

The PEFT adapter, the converted MLX adapter, the base weights, and the
resumable per-row run files are git-ignored (`.gitignore`). Publishing the
adapter or converted weights would be a release and is excluded. Nothing here
downloads: every target that loads a model runs with `HF_HUB_OFFLINE=1`, and
the base snapshot `Qwen/Qwen3-8B-MLX-bf16@6766fd4b` must already be in the
local Hugging Face cache.

## Steps (manual lane, Apple silicon, one model run at a time)

1. `make phase03c-mlx-adapter`: converts the PEFT adapter into the ignored
   `data/experiments/phase-03c/training/cloud-run-01/train/mlx/adapters/` and
   fails unless the result equals the committed attestation. The converter is
   standard-library only (safetensors read, transpose, write), so CI tests it
   on synthetic files without MLX.
2. `make phase03c-local-parity BACKEND=distilled`, then `BACKEND=untuned`:
   the M1 stack-parity run over the 240 held-out rows (resumable), then
   `python -m scripts.run_phase03c_local_parity --write` for
   `data/experiments/phase-03c/local-parity/parity-report.json`.
   `make phase03c-local-parity-check` (in `make test`) replays the committed
   raw outputs through the repository evaluator without a model.
3. `make local-fast-gateway BACKEND=distilled|untuned` serves
   `local-fast-wire-v1` on `127.0.0.1:8765`.

## Fail-closed start

The gateway refuses to start when the base snapshot fails
`attest_qwen_spec(..., QWEN3_8B_BF16_SPEC)`, when the MLX adapter differs from
the committed attestation, or when the LoRA self-check fails. The self-check
exists because `mlx_lm` loads adapter weights with `strict=False` and
initialises `lora_b` to zero: an adapter whose tensor names miss the model
loads nothing and the "distilled" backend is silently the untuned model. The
check requires exactly the 252 attested LoRA modules, each with a non-zero
`lora_b` (the untuned backend requires none). A real load of a renamed copy
returned without error, created 252 LoRA modules with 0 non-zero `lora_b`,
and the check refused it (`harness/log/feat-pr9b-local-fast-gateway.md`).

## Endpoints (`local-fast-wire-v1`)

- `GET /v1/identity`: backend, label, base model and revision, adapter
  fingerprint (distilled only), prompt v6, compiler, observation renderer,
  trained-view version, decoding fingerprint (greedy, seed 0,
  `max_tokens` 512, thinking off), MLX versions, and `identity_fingerprint`.
- `POST /v1/fast/decide` with `{wire_version, view, observation}` (at most
  256 KiB): `200` with `status` `succeeded` (the six Fast output fields),
  `invalid_output` or `unrenderable` plus an allow-listed `detail_code`, and
  token usage; `400 request_invalid`, `413`, `503 busy` (single flight, no
  queue), `500 gateway_error`. Error bodies carry a code only; logs carry no
  prompt, observation, or model text.

The gateway side of the wire lives in `local_fast/wire.py` until PR-9a lands
`agent_core/local_fast_wire.py`; the gateway then switches to that module so
the wire has one owner.

## Local limits

Loopback only, no authentication: any local process can call it. MLX cannot
cancel a running generation. No p95, capacity, concurrency, OOM, or
production latency is measured or claimed.
