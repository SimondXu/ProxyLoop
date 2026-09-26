# MOD lane targets (S0-MOD-01, ADR-0002). Root-run only: they need Modal auth, the Modal secret
# `proxyloop-vllm` (VLLM_API_KEY) and PROXYLOOP_VLLM_API_KEY in the shell. Both
# `make -f mk/mod.mk <target>` and `include mk/*.mk` from the root Makefile work.
#   SERVE_VARIANT=pinned|prefix-align   (prefix-align is measure-only)
#   PL_ZERO_LORA=zero-all|zero-attn-mlp (the ladder rung served as the zero-LoRA slot)

SERVE_VARIANT ?= pinned
MOD_SUFFIX := $(if $(filter pinned,$(SERVE_VARIANT)),,-$(SERVE_VARIANT))
MOD_DATA := docs/decisions/data
MOD_MODAL := uv run --no-project --with modal==1.5.5 modal
MOD_PY := uv run --no-project --with modal==1.5.5 --with httpx==0.28.1 \
	--with transformers==5.17.0 --with jinja2==3.1.6 python
# No recipe uses $(MAKE), so `make -n` only prints and never reaches Modal.
MOD_SERVE_UP := PL_SERVE_VARIANT=$(SERVE_VARIANT) $(MOD_MODAL) deploy -m serving.modal_vllm && \
	$(MOD_PY) -m serving.probe --wait-healthy --variant $(SERVE_VARIANT) \
	--out $(MOD_DATA)/vllm-coldstart$(MOD_SUFFIX).json
MOD_SERVE_DOWN := $(MOD_MODAL) app stop --yes proxyloop-vllm$(MOD_SUFFIX)

.PHONY: serve-lora-ladder serve-up serve-down serve-probe serve-attest-local

serve-lora-ladder:
	$(MOD_MODAL) run -m serving.modal_vllm --out $(MOD_DATA)/vllm-lora-ladder.json

serve-up:
	$(MOD_SERVE_UP)

serve-down:
	$(MOD_SERVE_DOWN)

# serve-down runs from a trap, so an interrupted or failed probe never leaves a GPU running.
serve-probe:
	trap '$(MOD_SERVE_DOWN)' EXIT INT TERM; $(MOD_SERVE_UP) && \
	$(MOD_PY) -m serving.probe --variant $(SERVE_VARIANT) --out $(MOD_DATA)/vllm-probe$(MOD_SUFFIX).json

# Downloads 2 shards (~8.6 GB) at the pinned revision and compares them with /pl/attest.
serve-attest-local:
	uv run --no-project --with huggingface_hub==2.0.0 python -m serving.attest --shards 1,4 \
		--against $(MOD_DATA)/vllm-probe.json --out $(MOD_DATA)/vllm-attest-local.json
