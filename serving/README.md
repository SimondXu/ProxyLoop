# serving/: the pinned vLLM configuration (ADR-0002)

One pinned configuration for Qwen3.5-9B on vLLM (`config.py`), served on Modal (`modal_vllm.py`), with
`GET /pl/attest` served from the vLLM process itself (`attest.py`, loaded with `--middleware`).
`zero_lora.py` runs the LoRA ladder and `probe.py` measures the deployed endpoint from the Mac.

Everything here that touches Modal or a GPU is **root-run**.

Pins, flags and the reasons for them: `config.py` and ADR-0002 (`docs/decisions/0002-serving.md`).

## Mac-side dependencies

There is no root `pyproject.toml` yet, so the Mac-side modules run with `uv run --no-project --with …`.
At merge the root moves these into `[dependency-groups] mod`:

- `modal==1.5.5` (deploy, stop, endpoint discovery)
- `httpx==0.28.1` (probe)
- `transformers==5.17.0` and `jinja2==3.1.6` (HF chat-template ids for `/tokenize` parity and the probe prompts; no torch needed)
- `huggingface_hub==2.0.0` (local shard recomputation)
- tests only: `pytest==9.1.1`, `starlette==1.7.0`

## Environment

- Modal secret `proxyloop-vllm` with `VLLM_API_KEY` (read by vLLM from its environment; never in argv).
- Mac: `PROXYLOOP_VLLM_API_KEY`, and optionally `PROXYLOOP_VLLM_BASE_URL` (otherwise the probe looks up
  the web URL of the Modal app). Neither is written into any output.
- `SERVE_VARIANT=pinned|prefix-align` (make) and `PL_ZERO_LORA=zero-all|zero-attn-mlp` (deploy time).

## Root-run order

```sh
make -f mk/mod.mk serve-lora-ladder        # builds adapters on the volume -> vllm-lora-ladder.json
make -f mk/mod.mk serve-probe              # deploy, cold start, probe, then serve-down (trap)
make -f mk/mod.mk serve-attest-local       # 2 shards recomputed locally vs /pl/attest
make -f mk/mod.mk serve-probe SERVE_VARIANT=prefix-align   # measure-only prefix caching
```

The ladder must run before the first deploy: the served zero-LoRA slot is read from the adapters volume
and a missing slot fails the container start.
