# serving/: the pinned vLLM configuration (ADR-0002)

One pinned configuration for Qwen3.5-9B on vLLM (`config.py`), served on Modal (`modal_vllm.py`), with
`GET /pl/attest` served from the vLLM process itself (`attest.py`, a pure ASGI `--middleware`) and adapter
liveness (`liveness.py`, reused by pull-through). One-off measurement code lives in `scripts/mod/`:
the LoRA ladder (`lora_ladder.py`), the endpoint probe (`probe.py`) and the local shard recomputation
(`attest_local.py`).

Everything that touches Modal or a GPU is **root-run**; the commands and their order are in ADR-0002
(`docs/decisions/0002-serving.md`), with the pins and the reasons for them.

## Mac-side dependencies

There is no root `pyproject.toml` yet, so the Mac-side modules run with `uv run --no-project --with …`.
At merge the root moves these into `[dependency-groups] mod`:

- `modal==1.5.5` (deploy, stop, endpoint lookup; imported by the ladder tests)
- `httpx==0.28.1` (probe)
- `transformers==5.17.0` and `jinja2==3.1.6` (HF chat-template ids; no torch needed)
- `huggingface_hub==2.0.0` (local shard recomputation)
- tests only: `pytest==9.1.1`, `starlette==1.7.0`

## Environment

- Modal secret `proxyloop-vllm` with `VLLM_API_KEY` (read by vLLM from its environment; never in argv).
- Mac: `PROXYLOOP_VLLM_API_KEY`, and optionally `PROXYLOOP_VLLM_BASE_URL` (otherwise the probe looks up
  the web URL of the Modal app). Neither is written into any output.
- `SERVE_VARIANT=pinned|prefix-align` (make) and `PL_LORA_RUNG=all|attn-mlp` (deploy time).
