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
3. `make phase03c-product-parity BACKEND=distilled`, then `BACKEND=untuned`:
   the M2 run of the same 240 rows through the product rendering path
   (resumable), then `python -m scripts.run_phase03c_product_parity --write`
   for `data/experiments/phase-03c/local-parity/product-path-report.json`.
   `make phase03c-product-parity-check` (in `make test`) replays it without a
   model. After a change to the gate, validation, compile or observation,
   `python -m scripts.run_phase03c_product_parity --rebuild-from-report`
   re-derives every delivery stage, gate code and aggregate from the
   committed per-row raw outputs. It needs no model and no git-ignored run
   files. It refuses if a generated row's product prompt changed; then the
   model must run again.
4. `make local-fast-gateway BACKEND=distilled|untuned` serves
   `local-fast-wire-v1` on `127.0.0.1:$(LOCAL_FAST_PORT)`, default
   `LOCAL_FAST_PORT=8765`. If that port is taken, pass another, for example
   `LOCAL_FAST_PORT=8775`. The split report's `FAST_GATEWAY_URL` follows it;
   start the Runtime with `PROXYLOOP_FAST_GATEWAY_URL` on the same port. With
   the gateway running,
   `make fast-slow-split-report FAST_BACKEND=distilled|untuned` writes
   `data/evaluation/fast-slow-split-<backend>.json`.

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
A second check then fingerprints every loaded `lora_a` and `lora_b` with the
attestation formula and requires the committed `content_fingerprint`. It
refuses a partial load (one `lora_a` left at its random init while every
`lora_b` loaded, which the layer check passes) and a file changed between
the file check and the model load, because it binds the weights in memory,
not the file. The attested `config_sha256` is recomputable in CI from the
committed PEFT `adapter_config.json`.

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

The wire has one owner, `proxyloop_agent_core.local_fast_wire` (PR-9a); the
gateway imports it and has no copy.

## M1 result

Stack parity held (pre-registered bar ≥ 0.95 on both): on the 240 held-out
trained-format prompts the local distilled arm reaches act agreement
236/240 = 0.983 (cloud A3: 236/240) and per-row act concordance with cloud
A3 of 240/240; the untuned arm 133/240 (cloud A1: 130/240). Details, per-row
raw outputs and the claim boundary: the parity report and
`harness/log/feat-pr9b-local-fast-gateway.md`. M1 measures the trained
prompt format only; the product path is M2 below.

What the committed report can and cannot prove: `--check` verifies that
every derived field, the exact row set and order (the cloud arm's prompt ids)
and each arm's identity follow from the recorded fields. It cannot verify
that the raw outputs came from the model: that needs the git-ignored adapter
and a rerun. `report_fingerprint` is computed by the script over the
document; it is a consistency check, not a signature. Each arm records the
code state it ran from (`code_state`); for this run it was reconstructed after
the fact, with a byte-identical regeneration of sampled rows from the
committed code as evidence (see the log).

## M2 result: a negative product result

The frozen spec's root answer Q1 records this as the headline product number
and does not hide it. The run covered the same 240 held-out rows, rendered through the product
path (a plain Provider message plus `fast_public_observation`,
`fast-observation-v1`). They were generated locally and replayed through the
runtime delivery rules (compile, `validate_fast_result`, `fast-gate-v1`).
Report: `data/experiments/phase-03c/local-parity/product-path-report.json`.

- **Delivered distilled lines: 0/240.** 40 rows (all of the refusal-transfer
  family) are refused before the model: the family has no offer, so
  `fast_public_observation` refuses (`fast_observation_offer_missing`). The
  runtime delivers the fallback line for them. All 200 outputs that reach the
  gate are withheld by `fast-gate-v1`: 200/200 carry a dialogue act the gate
  does not allow (`fast_gate_dialogue_act`) and 200/200 a number the strategy
  does not allow (`fast_gate_number_not_allowed`). Also flagged:
  `fast_gate_completion` 181, `fast_gate_non_ascii_text` 72,
  `fast_gate_text_too_long` 47. No output failed compilation,
  `validate_fast_result`, or the no-fact-updates rule. The model was trained on
  minor-unit arithmetic and confirm/counter acts, which the gate withholds by
  design.
- **Untuned baseline: 8/240 delivered** (192 gate-rejected, on the act and
  number rules; the same 40 refused before the model).
- **Act agreement with the true oracle: distilled 157/240 = 0.654**
  (0.983 on the trained path, M1); untuned 97/240 (133/240 on M1).
- **Where the drop from 236 to 157 comes from** (distilled, agreement with
  the true oracle per family, M1 → M2). The net drop is 79: 80 rows lost,
  one gained.
  - refusal-transfer 40 → 0 (−40). The family has no offer, so
    `fast_public_observation` refuses and the model is never called. This is
    not D4.
  - unsupported-action 40 → 0 (−40), from D4. The product observation carries
    no `applied_changes`; without the applied change its oracle act is
    confirm instead of the true counter. The model answers confirm on all 40
    rows, following its input (40/40 against the product-observation oracle).
  - required-feature-loss 36 → 37 (+1).
  - promotion-credit stays 40/40 against the true oracle. D4 changes its
    product-observation act from confirm to counter, but the model keeps
    confirm (0/40 against the product oracle). The input changed; the act did
    not.

  So D4 accounts for 40 of the 80 lost rows, about half; the refusal family
  accounts for the other 40. All 200 generated rows lose `applied_changes`,
  and no product prompt equals its trained prompt. D3 (the declared
  Provider-state defaults) changed no held-out row.
- On the trained path (the M1 outputs), the gate would also pass 0/240
  distilled and 44/240 untuned lines. The gate, not only the renderer, blocks
  the distilled output.
- Latency (descriptive, one M4 Pro, sequential, measured while other work ran
  on the machine): distilled product-path generation p50 23.9 s, max 32.5 s;
  untuned p50 10.4 s, max 12.9 s. 64 of the 200 distilled generations ran
  longer than 25 s by `generation_ms` (65 by `wall_ms`), roughly a third.
  Under the 25 s default timeout the runtime would end each of those calls as
  `fast_adapter_timeout`. The trained-path rate (M1, 15/240) is context only;
  the load on the machine was not controlled in either run. The split runs
  below saw 0 of 16 calls over 25 s.

What M2 does not measure: the strategy text is the training fixture's, not the
product Slow's (D6). The product prompt never contains the consumer's words
(D5).

## Local Fast/Slow split reports

`data/evaluation/fast-slow-split-distilled.json` and `-untuned.json` run
PR-8's two scenarios through the real runtime path against the real gateway.
The runtime was in-process, with the in-memory repository and the stepping
clock. Calls were sequential, with the default 25 s timeout. On both backends
the turn structure equals the scripted replay:

- demo path: 1 slow-only and 1 fast-only turn;
- dialogue path: 1 slow-only, 5 fast-only and 2 slow-then-fast turns.

Every one of the 8 Fast calls per backend returned `succeeded` and was
withheld by the gate. So `fast_model_line_rate` is 0.0, every Fast turn
delivered the fallback, and `fallback_cause` is `gate` 8, `failure` 0. The
gate codes: distilled, act, number and completion on every call; untuned, act
and number. No call timed out or got `busy`. Distilled Fast calls took
21.0–24.1 s (p50 22.1 s on the dialogue path), untuned 10.4–12.1 s. Every call had the
same token counts (1869 in; 184 out distilled, 78 out untuned). That fits D5:
the product prompt does not carry the consumer's words, so these scenarios
give the model the same input on every turn. `make fast-slow-split-check`
verifies integrity and structural invariance only. It cannot replay the model.

Both reports predate the Stage 2 Judge (PR-14). They stay at
`fast-slow-split-local-v1` with no Judge calls and are not rewritten; a run
now writes `fast-slow-split-local-v2`, which also counts the scripted Judge's
calls apart from the Fast/Slow counts (`docs/architecture.md`).

## Local limits

- Loopback only, no authentication: any local process can call it. The
  gateway listens on IPv4 `127.0.0.1` only. Requests must carry
  `Host: 127.0.0.1:<port>` or `Host: localhost:<port>` (DNS rebinding); every
  other name is refused, and `[::1]` cannot reach the socket. Decide calls
  `Content-Type: application/json` (no browser simple POST); socket reads time
  out after 10 s.
- All model work runs on one thread (MLX streams are thread-local) and
  `decide` is single flight with no queue.
- MLX cannot cancel a running generation. With PR-9a's default Fast timeout of
  25 s (the cap, root decision), a call the client abandons still occupies the
  gateway until its generation ends, so the next Fast call in that window gets
  `503 busy` and the runtime delivers the fallback line.
- Observed on one M4 Pro, sequentially, while other work ran on the same
  machine during the distilled arm: distilled generation p50 21.3 s, max
  26.9 s (134 of 240 above 20 s, 15 above 25 s); untuned p50 9.9 s. These are
  descriptive single-machine numbers under uncontrolled load. No p95,
  capacity, concurrency, OOM, or production latency is measured or claimed.
