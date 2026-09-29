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
# and, for the world (its default) and for FAST_ENDPOINT/SLOW_ENDPOINT=openrouter,
# PL_OPENROUTER_BASE_URL (https://openrouter.ai/api) and PL_OPENROUTER_API_KEY.
# WORLD_EFFORT: provisional: ADR-0005; S1 probe decides. EAR_/MOUTH_/SIMUSER_EFFORT
# override it per world role (unset: WORLD_EFFORT).
# WORLD_MODEL=<endpoint>:<model>[@effort] picks every world role's model (unset: the
# CLI's openrouter:google/gemini-3.8-flash). Slow and the world on Gemini 3.8 Flash via
# OpenRouter (TeamRouter's Gemini hung, S1-SYS-96), the Fast unchanged:
#   make smoke-live FAMILY=<f> SLOW=google/gemini-3.8-flash SLOW_ENDPOINT=openrouter \
#     WORLD_MODEL=openrouter:google/gemini-3.8-flash
# FAST/FAST_ENDPOINT and SLOW/SLOW_ENDPOINT pick the Fast and Slow ModelRefs (unset: the
# CLI defaults, Qwen3.5-9B@vllm and claude-sonnet-5@relay); FAST_EFFORT (hosted Fast only)
# and SLOW_EFFORT pin reasoning_effort (unset: the CLI's provisional values for a hosted
# Fast and a Gemini Slow, TeamRouter or OpenRouter; a vLLM Fast and a relay Slow keep
# the provider's default).
# FAST_CP_BASE_URL: the dead-endpoint smoke only, a dead server root for fast_cp. The
# redirect is not recorded in the bundle, so it needs CLAIM=0: with the default CLAIM the
# CLI refuses it (a parser error, non-zero exit).
# MODE and INSTANCE pick the family mode and the seeded instance (unset: the family's default
# mode and instance 0, the file itself); the manifest's task_ref names both.
# CLAIM=0 checks the bundle offline instead of --claim (a hosted Fast); removed by S1-SYS-14.
WORLD_EFFORT ?= low
CLAIM ?= 1
.PHONY: smoke-live replay-cli
smoke-live:
	uv run python -m proxyloop.cli session --family $(FAMILY) --user sim --rep sim \
		$(if $(MODE),--mode $(MODE),) $(if $(INSTANCE),--instance $(INSTANCE),) \
		--world-effort $(WORLD_EFFORT) $(if $(WORLD_MODEL),--world-model $(WORLD_MODEL),) \
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

# web-test (S1-SYS-07). No flags: no keys, no GPU. The web suite in apps/web: lint,
# typecheck, vitest, build and the Playwright e2e (`npm run web-test`). `npm ci` runs only
# when node_modules/.package-lock.json (written by npm on install) is missing or not newer
# than package-lock.json.
# replay (S1-SYS-07, S1-SYS-30). No flags: no keys, no GPU. Builds the web, then serves it
# same-origin from the real API (`python -m proxyloop.serve.api --web-dir apps/web/dist`,
# http://127.0.0.1:8000) over its default roots: runs/ and each evidence/<stage>/. The API
# never serves a held-out bundle (evidence/s4/test, split test). It has no roots option, so
# there is no RUN=: pick a run under those roots in the page.
WEB_DEPS = cd apps/web && { [ node_modules/.package-lock.json -nt package-lock.json ] || npm ci; }
.PHONY: web-test replay
web-test:
	$(WEB_DEPS) && npm run web-test

replay:
	$(WEB_DEPS) && npm run build && cd $(CURDIR) && uv run python -m proxyloop.serve.api --web-dir apps/web/dist

# demo (S1-SYS-05). Root-run only, flag L; G only when a start picks the Qwen3.5-9B (vLLM)
# option (`make serve-up` first). Builds the web, then serves it same-origin with live starts
# (`python -m proxyloop.kernel.web --web-dir apps/web/dist`, http://127.0.0.1:8000): /start
# picks a training task, each lane's model (default: Luna on OpenRouter for both Fast lanes,
# gemini-3.8-flash on TeamRouter for Slow) and the rep (sim, or human at /rep/<case_id>).
# One case at a time; each run is written to runs/live/<run_id>/<run_id>. The root exports,
# in the shell only (never a repo file), the variables of the endpoints a start uses:
#   PL_OPENROUTER_BASE_URL PL_OPENROUTER_API_KEY PL_TEAMROUTER_BASE_URL PL_TEAMROUTER_API_KEY
# and, for the vLLM option, PL_VLLM_BASE_URL PL_VLLM_API_KEY. A start whose variables are
# missing is refused ("unavailable"); no value is printed. Afterwards:
# `make evidence-check RUN=runs/live/<run_id>/<run_id> MODE=claim`.
.PHONY: demo
demo:
	$(WEB_DEPS) && npm run build && cd $(CURDIR) && uv run python -m proxyloop.kernel.web --web-dir apps/web/dist
