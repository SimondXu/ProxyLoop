# SYS lane make targets (PLAN.md §0.2). Included by the root Makefile.

# llm-smoke (S0-SYS-04). Root-run only, flags L+G: it calls the live vLLM app and the relay.
# Before: `make serve-up`; after: `make serve-down`. The root exports, in the shell only
# (never a file in the repo), the server roots without /v1 and the keys:
#   PL_VLLM_BASE_URL PL_VLLM_API_KEY PL_RELAY_BASE_URL PL_RELAY_API_KEY
# Writes docs/decisions/data/llm-smoke.json: 20 vLLM streams (request ids, TTFT), 3 Sonnet
# forced tool calls, the P3 result and the /pl/attest document. No recipe uses $(MAKE), so
# `make -n` only prints.
.PHONY: llm-smoke
llm-smoke:
	uv run python -m scripts.sys.llm_smoke --out docs/decisions/data/llm-smoke.json
