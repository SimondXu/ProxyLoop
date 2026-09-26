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
  --middleware serving.attest.AttestMiddleware
  --lora-modules Qwen3.5-9B-zero=/adapters/zero-<rung> Qwen3.5-9B-live=/adapters/live-<rung>`.
  Two deliberate equivalences to the §13 text: the API key comes from `VLLM_API_KEY` in the container
  environment (the Modal secret `proxyloop-vllm`), never from argv, so it cannot leak through the process list
  or `/pl/attest`; and the model argument is the local HF snapshot at the pinned revision, loaded with
  `HF_HUB_OFFLINE=1`, so the files hashed are the files loaded.
- **Two LoRA slots** from the chosen rung (`PL_LORA_RUNG`): `Qwen3.5-9B-zero` (`lora_B = 0`) and
  `Qwen3.5-9B-live` (`lora_B != 0`, same targets). Liveness in the served process (`serving/liveness.py`, also
  used by pull-through) requires zero: max |Δ prompt_logprob| ≤ 1e-4 and live: mean |Δ| > 1e-3 nats against base
  on the 5 fixed pairs, and every response must echo the requested model.
- **Measure-only variant:** `prefix-align` (`--enable-prefix-caching --mamba-cache-mode align`) deploys as a
  separate Modal app (`proxyloop-vllm-prefix-align`) and is never the pinned configuration.
- **Attestation:** at container start, before vLLM starts, sha256 of every `*.safetensors` shard, the tokenizer
  files (`tokenizer.json`, `tokenizer_config.json`, `vocab.json`, `merges.txt`, `chat_template.jinja`) and every
  file in each LoRA slot. Shard and tokenizer digests are cached on the HF volume per (real path, size,
  mtime_ns); adapter digests are never cached; `digest_source` records "cached" or "fresh" per file. The
  document (`pl.attest/1`, plus a `runtime` block: vLLM version, GPU name, argv, variant, rung, container start
  time) is served at `GET /pl/attest` by a pure ASGI middleware inside the vLLM API server process: it answers
  that path only (bearer-authenticated) and hands every other scope to vLLM untouched. No index file and no
  greedy-output hashes. The `session.started.attest` field shape is S0-CON-01's to freeze.
- **LoRA ladder** (`scripts/mod/lora_ladder.py`, its own Modal app, one offline vLLM engine with the served
  engine arguments): PEFT adapters built on a meta-device model into the adapters volume. Per rung R
  (`all` = attention + GDN + MLP, `attn-mlp`): `zero-R` (`lora_B = 0`) and `live-R` (`lora_B != 0`); plus one
  probe per §13 target that is non-zero on that target only. The `in_proj_z` probe also carries `in_proj_qkv`
  with `lora_B = 0` (`lora_A` initialised as usual): vLLM 0.29.0 packs both into `in_proj_qkvz` (4 output
  slices, 2 members) and its `expand_packed_lora` cannot place `in_proj_z` when `in_proj_qkv` is missing (see
  History). The zero-B leader adds nothing to the output, so the probe still measures `in_proj_z` alone, over
  the same packed path the `all` rungs load (`serving/config.py` `PACKS_NEEDING_LEADER`). A target counts as
  **applied** only when its probe loads and moves the mean |Δ prompt_logprob| above 1e-3 nats. A rung is OK
  when `zero-R` loads and equals base within 1e-4, `live-R` moves the mean above 1e-3, all of R's targets are
  applied, and the run completed. Each finished record is printed as one JSON line as it completes. Any engine
  exception stops the run (a worker-side LoRA failure kills the V1 engine): the result keeps the finished
  records with `aborted_at` and the error, its summary fails every rung and lists the missing adapters, and
  `serve-lora-ladder` writes it to `data/vllm-lora-ladder.aborted.json`, never to `data/vllm-lora-ladder.json`
  (it deletes a stale copy of that one file), so the `serve-up` order guard stays closed, then exits non-zero. The Modal function saves the result on the `proxyloop-adapters` volume
  (`results/lora-ladder-<UTC time>.json`, named in `volume_copy`) before returning it. Rule:
  serve `all` if `rung_ok:all`, else `attn-mlp` if `rung_ok:attn-mlp`, else escalate to rung 3 (merged BF16 as a
  separate process). The probe fails unless the ladder JSON says `rung_ok:<served rung>`.
  **Rung chosen:** <!-- root-run: fill from docs/decisions/data/vllm-lora-ladder.json (summary) -->
- **Modal shape:** one container (`max_containers=1`, 64 concurrent inputs), idle scale-down after 5 min,
  1 h function timeout. The container exits as soon as vLLM exits or anything before it fails, so a dead server
  does not hold the GPU until the start-up timeout. `serve-up` stops the app when the deploy or the health wait
  (900 s) fails; `serve-probe` also stops it from a shell trap (EXIT, HUP, INT, TERM).
- **Probe checks** (`scripts/mod/probe.py`; exit non-zero if any fails, the JSON is written either way): `/tokenize`
  = HF ids on the 5 prompts (every rendered prompt must end with the ids of `<think>\n\n</think>\n\n`); zero and
  live liveness; no failed request in any block, warm-ups included (an HTTP error, a stream error, a missing
  finish, or an echoed model different from the requested one all count); every request in every block has a
  TTFS; keyless `GET /v1/models` and keyless `GET /pl/attest` both return 401; the served rung is OK in the
  ladder JSON. TTFS: the first `[.!?]` followed by whitespace, or a final `[.!?]` once the stream has finished.
  Each latency request has its own prompt index, so only the shared prefix is cacheable.

## Evidence
**Run order:** `serve-lora-ladder` → `serve-probe` → `serve-attest-local` → `serve-probe SERVE_VARIANT=prefix-align`
(`serve-up` refuses to deploy until `data/vllm-lora-ladder.json` exists).

No number below is typed by hand; each is copied from the committed raw JSON (derived rows from the probe's
`derived` block) after the root's run. All `make` targets are `make -f mk/mod.mk <target>`.

| Measurement | Value | Raw artefact | Command |
|---|---|---|---|
| Ladder: applied targets, rung verdicts | <!-- root-run --> | `data/vllm-lora-ladder.json` | `serve-lora-ladder` |
| vLLM version, GPU name, `/v1/models` | <!-- root-run --> | `data/vllm-probe.json` | `serve-probe` |
| Cold start: from `modal deploy` returning to `/health` 200 (includes the first model download and hashing when the volume is cold) | <!-- root-run --> | `data/vllm-coldstart.json` | `serve-probe` (via `serve-up`) |
| TTFT p50/p95, concurrency 1 and 4 (~1.5k-token prompt, 20 requests, from the Mac) | <!-- root-run --> | `data/vllm-probe.json` | `serve-probe` |
| TTFS p50/p95, concurrency 1 and 4 | <!-- root-run --> | `data/vllm-probe.json` | `serve-probe` |
| `/tokenize` ids = HF ids, 5 prompts | <!-- root-run --> | `data/vllm-probe.json` | `serve-probe` |
| Zero-LoRA liveness: max \|Δ prompt_logprob\| (≤ 1e-4) | <!-- root-run --> | `data/vllm-probe.json` | `serve-probe` |
| Live-LoRA liveness: mean \|Δ prompt_logprob\| (> 1e-3) | <!-- root-run --> | `data/vllm-probe.json` | `serve-probe` |
| Keyless `/v1/models` and `/pl/attest` → 401 | <!-- root-run --> | `data/vllm-probe.json` | `serve-probe` |
| LoRA overhead: TTFT/TTFS p50, zero-LoRA minus base (`derived.lora_overhead`) | <!-- root-run --> | `data/vllm-probe.json` | `serve-probe` |
| `/pl/attest` = local recomputation, 2 shards | <!-- root-run --> | `data/vllm-attest-local.json` | `serve-attest-local` |
| Prefix caching (align) minus pinned, TTFT/TTFS p50, measure-only (`derived.minus_baseline`) | <!-- root-run --> | `data/vllm-probe-prefix-align.json` | `serve-probe SERVE_VARIANT=prefix-align` |

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
  - The attest cache trusts (path, size, mtime_ns) for shards and tokenizer files; a volume edit that preserves
    all three would not be re-hashed. Adapter files are always hashed fresh.
  - On vLLM 0.29.0 any served adapter that contains `in_proj_z` must also contain `in_proj_qkv`, or loading it
    kills the serving engine (`expand_packed_lora`, History). S0-MOD-02 trains the `all` rung, which has both,
    so it is unaffected; a future adapter over a subset of the GDN targets must keep the pair.
  - The Modal endpoint is public at the HTTP layer: `/health`, `/version` and `/tokenize` answer without the key
    (vLLM guards only `/v1/...`), and anyone can wake a GPU container with a request. Modal's
    `requires_proxy_auth` would close that; it is deferred (it changes every client, including the probe).

## History
- **2026-09-26, ladder run 1 failed** (root-run, 1 × H100, vLLM 0.29.0). The engine died at adapter 10 of 16,
  `probe-linear_attn.in_proj_z` (then non-zero on `in_proj_z` only): `ValueError: Cannot determine how to split
  lora_b with 4096 rows into 4 slices with output sizes [2048, 2048, 4096, 4096] starting from index 4.`
  (`vllm/lora/layers/column_parallel_linear.py` `expand_packed_lora`: the missing `in_proj_qkv` member took all
  4 slices), surfacing as `EngineDeadError`. The script then only returned at the end, so the 9 finished records
  were lost. Fixes: the `in_proj_z` probe carries a zero-B `in_proj_qkv`, and the ladder streams, stops and
  saves as described under Decision.
