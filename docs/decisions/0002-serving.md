# ADR-0002: Pinned CUDA serving configuration for Qwen3.5-9B

- **Status:** proposed (DRAFT: every measured value below is a `root-run` placeholder until the G run lands)
- **Date:** 2026-09-26
- **Task:** S0-MOD-01

## Context
ARCHITECTURE §13 needs one pinned serving configuration for the Fast model: the same weights on two lanes,
LoRA slots for the pull-through and later adapters, attestation of what is actually served, and a TTFS
that a real-time counterparty lane can live with. §12 P3 needs vLLM `/tokenize` to return the same ids as
the HF chat template with `enable_thinking=False`.

Facts checked while writing the configuration (sources, not measurements):
- `Qwen/Qwen3.5-9B` exists, is public and not gated (Apache-2.0). HF API `sha` on 2026-09-26:
  `c202236235762e1c871ad0ccb60c8ee5ba337b9a`. Architecture `Qwen3_5ForConditionalGeneration`; 4 safetensors
  shards; the text model has 24 GDN (`linear_attn`) and 8 full-attention (`self_attn`) layers, a vision tower
  (`model.visual.*`) and an MTP head (`mtp.*`).
- vLLM release notes: Qwen3.5 support and `--language-model-only` for hybrid models (v0.17.0, #34110, #34120);
  Mamba/hybrid prefix caching `--enable-prefix-caching --mamba-cache-mode align` (v0.15.0, #30877);
  `--lora-target-modules` and `language_model_only` respected by LoRA (v0.19.0, #34984, #37375);
  Qwen3.5 LoRA fixes (v0.19.0 #36976, v0.21.0 #37912, v0.29.0 #48850); Qwen3.5 text-only fixes (v0.27.0
  #50210, v0.28.0 #50734). Source: `https://api.github.com/repos/vllm-project/vllm/releases`.
- vLLM v0.29.0 source (tag archive):
  - `model_executor/models/qwen3_5.py` packs `in_proj_qkv`+`in_proj_z` into `in_proj_qkvz` and
    `in_proj_b`+`in_proj_a` into `in_proj_ba` for LoRA;
  - `lora/lora_model.py` raises on an adapter module outside the expected set, but a name check alone does
    not prove a module is applied;
  - `engine/arg_utils.py` turns prefix caching **on by default** for generative hybrid models, so the pinned
    configuration must pass `--no-enable-prefix-caching` explicitly;
  - `entrypoints/serve/middleware/register.py` loads `--middleware` import paths into the API server, and
    `authenticate.py` guards only `/v1`, `/v2`, `/inference` and `/cohere` (so `/health` and `/tokenize`
    are unauthenticated in this version).

## Decision
- **Pins** (`serving/config.py`): model `Qwen/Qwen3.5-9B@c202236235762e1c871ad0ccb60c8ee5ba337b9a`;
  vLLM `0.29.0` from `vllm/vllm-openai@sha256:082ca6f035279109041ffd3fe0695cb568b29bc580b35c4f297a66a08b216c1b`
  (Docker Hub tag `v0.29.0-x86_64`); Modal `H100`. v0.29.0 over v0.30.0 (released 2026-09-22) is a judgement:
  it contains every Qwen3.5 correctness and LoRA fix listed above and has had two more weeks of use; v0.30.0's
  Qwen3.5 items are start-up and kernel speed.
- **Flags:** ARCHITECTURE §13 exactly, with prefix caching explicitly off:
  `vllm serve <snapshot> --served-model-name Qwen3.5-9B --dtype bfloat16 --language-model-only --enable-lora
  --max-lora-rank 32 --max-loras 4 --max-model-len 16384 --port 8000 --no-enable-prefix-caching
  --middleware serving.attest.attest_middleware --lora-modules Qwen3.5-9B-zero=/adapters/<rung>`.
  Two deliberate equivalences to the §13 text: the API key comes from `VLLM_API_KEY` in the container
  environment (the Modal secret `proxyloop-vllm`), never from argv, so it cannot leak through the process list
  or `/pl/attest`; and the model argument is the local HF snapshot at the pinned revision, loaded with
  `HF_HUB_OFFLINE=1`, so the files hashed are the files loaded.
- **Measure-only variant:** `prefix-align` (`--enable-prefix-caching --mamba-cache-mode align`) deploys as a
  separate Modal app (`proxyloop-vllm-prefix-align`) and is never the pinned configuration.
- **Attestation:** at container start, before vLLM starts, sha256 of every `*.safetensors` shard, the tokenizer
  files (`tokenizer.json`, `tokenizer_config.json`, `vocab.json`, `merges.txt`, `chat_template.jinja`) and every
  file in each LoRA slot. Digests are cached on the HF volume per (real path, size, mtime_ns). The document
  (`pl.attest/1`, plus a `runtime` block: vLLM version, GPU name, argv, variant, rung, container start time) is
  served at `GET /pl/attest` by a bearer-authenticated middleware inside the vLLM API server process. No index
  file and no greedy-output hashes. The `session.started.attest` field shape is S0-CON-01's to freeze.
- **LoRA ladder** (`serving/zero_lora.py`, one offline vLLM engine with the served engine arguments): PEFT
  adapters built on a meta-device model: `zero-all` (rung 1 targets, `lora_B = 0`), `zero-attn-mlp` (rung 2),
  and one non-zero single-target probe per §13 target. A target counts as **applied** only when its probe loads
  and moves the mean |Δ prompt_logprob| above 1e-3 nats; a rung is OK when its zero adapter loads, equals base
  within 1e-4, and all its targets are applied. Rule: serve rung 1 if `rung_ok:zero-all`, else rung 2 if
  `rung_ok:zero-attn-mlp`, else escalate to rung 3 (merged BF16 as a separate process).
  **Rung chosen:** <!-- root-run: fill from docs/decisions/data/vllm-lora-ladder.json (summary) -->
- **Modal shape:** one container (`max_containers=1`, 64 concurrent inputs), idle scale-down after 5 min,
  1 h function timeout; `make -f mk/mod.mk serve-probe` stops the app from a shell trap.

## Evidence
No number below is typed by hand; each is filled from the committed raw JSON after the root's run.

| Measurement | Value | Raw artefact | Command |
|---|---|---|---|
| Ladder: applied targets, rung verdicts | <!-- root-run --> | `data/vllm-lora-ladder.json` | `make -f mk/mod.mk serve-lora-ladder` |
| vLLM version, GPU name, `/v1/models` | <!-- root-run --> | `data/vllm-probe.json` | `make -f mk/mod.mk serve-probe` |
| Cold start (deploy → `/health` 200) | <!-- root-run --> | `data/vllm-coldstart.json` | same |
| TTFT p50/p95, concurrency 1 and 4 (~1.5k-token prompt, 20 requests, from the Mac) | <!-- root-run --> | `data/vllm-probe.json` | same |
| TTFS p50/p95, concurrency 1 and 4 | <!-- root-run --> | `data/vllm-probe.json` | same |
| `/tokenize` ids = HF ids, 5 prompts | <!-- root-run --> | `data/vllm-probe.json` | same |
| Zero-LoRA liveness: max \|Δ prompt_logprob\| (≤ 1e-4) | <!-- root-run --> | `data/vllm-probe.json` | same |
| LoRA overhead: TTFT p50, zero-LoRA minus base | <!-- root-run --> | `data/vllm-probe.json` | same |
| `/pl/attest` = local recomputation, 2 shards | <!-- root-run --> | `data/vllm-attest-local.json` | `make -f mk/mod.mk serve-attest-local` |
| Prefix caching (align) TTFT vs pinned, measure-only | <!-- root-run --> | `data/vllm-probe-prefix-align.json` | `make -f mk/mod.mk serve-probe SERVE_VARIANT=prefix-align` |

## Consequences
- **Contract / fingerprint impact:** none. `/tokenize` parity here uses fixed probe prompts; P3 on the
  contract's golden prompts is S0-SYS-04's.
- **Data invalidated:** none.
- **Migration:** S0-MOD-02 trains on the targets the ladder reports as applied (train = serve). The adapter
  format the ladder builds (PEFT, `base_model.model.model.language_model.layers.N.<parent>.<proj>`) is what
  the served slots expect.
- **Risks and what would make us revisit this:**
  - TTFS p50 from the Mac above 1.5 s on H100, Qwen3.5-9B failing to load with `--language-model-only`, or
    neither LoRA rung working and merged serving failing: escalate (PLAN S0-MOD-01).
  - The Modal image build on the vLLM registry image (python symlink, cleared ENTRYPOINT) is unverified until
    the first deploy.
  - Mac-side latency includes the network path to Modal; latency claims need a co-located client (§13).
  - The attest cache trusts (path, size, mtime_ns); a volume edit that preserves all three would not be re-hashed.
