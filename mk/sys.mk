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
# WORLD_EFFORT: provisional: ADR-0005; S1 probe decides. EAR_/MOUTH_/SIMUSER_EFFORT
# override it per world role (unset: WORLD_EFFORT).
# FAST/FAST_ENDPOINT and SLOW/SLOW_ENDPOINT pick the Fast and Slow ModelRefs (unset: the
# CLI defaults, Qwen3.5-9B@vllm and claude-sonnet-5@relay); FAST_EFFORT (hosted Fast only)
# and SLOW_EFFORT pin reasoning_effort (unset: the CLI's provisional values for a hosted
# Fast and a TeamRouter Slow; a vLLM Fast and a relay Slow keep the provider's default).
# FAST_CP_BASE_URL: the dead-endpoint smoke only, a dead server root for fast_cp.
# CLAIM=0 checks the bundle offline instead of --claim (a hosted Fast); removed by S1-SYS-14.
WORLD_EFFORT ?= low
CLAIM ?= 1
.PHONY: smoke-live replay-cli
smoke-live:
	uv run python -m proxyloop.cli session --family $(FAMILY) --user sim --rep sim \
		--world-effort $(WORLD_EFFORT) \
		$(if $(EAR_EFFORT),--ear-effort $(EAR_EFFORT),) \
		$(if $(MOUTH_EFFORT),--mouth-effort $(MOUTH_EFFORT),) \
		$(if $(SIMUSER_EFFORT),--simuser-effort $(SIMUSER_EFFORT),) \
		$(if $(FAST),--fast-model $(FAST),) $(if $(FAST_ENDPOINT),--fast-endpoint $(FAST_ENDPOINT),) \
		$(if $(FAST_EFFORT),--fast-effort $(FAST_EFFORT),) \
		$(if $(SLOW),--slow-model $(SLOW),) $(if $(SLOW_ENDPOINT),--slow-endpoint $(SLOW_ENDPOINT),) \
		$(if $(SLOW_EFFORT),--slow-effort $(SLOW_EFFORT),) \
		$(if $(FAST_CP_BASE_URL),--fast-cp-base-url $(FAST_CP_BASE_URL),) \
		$(if $(filter 0,$(CLAIM)),,--claim)

# replay-cli: the terminal replay of a bundle (no keys, no GPU). RUN=runs/<run_id>
replay-cli:
	uv run python -m proxyloop.cli replay $(RUN)
