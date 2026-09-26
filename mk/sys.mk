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

# smoke-live (S0-SYS-06). Root-run only, flags L+G: one real session of FAMILY (sim user,
# sim rep) through run_session, then evidence-check --claim on its bundle (non-zero exit on
# failure). Before: `make serve-up`. The root exports in the shell only (never a repo file)
# the server roots without /v1 and the keys:
#   PL_VLLM_BASE_URL PL_VLLM_API_KEY PL_RELAY_BASE_URL PL_RELAY_API_KEY
#   PL_TEAMROUTER_BASE_URL PL_TEAMROUTER_API_KEY
# WORLD_EFFORT: provisional: ADR-0005; S1 probe decides.
WORLD_EFFORT ?= low
.PHONY: smoke-live replay-cli
smoke-live:
	uv run python -m proxyloop.cli session --family $(FAMILY) --user sim --rep sim \
		--world-effort $(WORLD_EFFORT) $(if $(FAST),--fast-model $(FAST),) --claim

# replay-cli: the terminal replay of a bundle (no keys, no GPU). RUN=runs/<run_id>
replay-cli:
	uv run python -m proxyloop.cli replay $(RUN)
