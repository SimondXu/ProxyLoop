# MOD lane targets (S0-MOD-01, ADR-0002). Root-run only: they need Modal auth, the Modal secret
# `proxyloop-vllm` (VLLM_API_KEY) and PROXYLOOP_VLLM_API_KEY in the shell. Both
# `make -f mk/mod.mk <target>` and `include mk/*.mk` from the root Makefile work.
#   SERVE_VARIANT=pinned|prefix-align  (prefix-align is measure-only)
#   PL_LORA_RUNG=all|attn-mlp          (the ladder rung whose zero/live adapters are served)
#   MODEL=9b|4b                        (serve-up/serve-down only; 4b: C3's base Qwen3.5-4B)
# No recipe uses $(MAKE), so `make -n` only prints and never reaches Modal.

SERVE_VARIANT ?= pinned
MOD_SUFFIX := $(if $(filter pinned,$(SERVE_VARIANT)),,-$(SERVE_VARIANT))
MOD_DATA := docs/decisions/data
MOD_MODAL := uv run --no-project --with modal==1.5.5 modal
MOD_PY := uv run --no-project --with modal==1.5.5 --with httpx==0.28.1 \
	--with transformers==5.17.0 --with jinja2==3.1.6 python
MOD_BASELINE := $(if $(MOD_SUFFIX),--baseline $(MOD_DATA)/vllm-probe.json,)
MODEL ?= 9b
MOD_MODEL := 9b
serve-up serve-down: MOD_MODEL := $(MODEL)
MOD_APP_SUFFIX = $(if $(filter 9b,$(MOD_MODEL)),,-$(MOD_MODEL))$(MOD_SUFFIX)
MOD_SERVE_DOWN = $(MOD_MODAL) app stop --yes proxyloop-vllm$(MOD_APP_SUFFIX)
# Run order (ADR-0002): serve-lora-ladder -> serve-probe -> serve-attest-local -> prefix-align probe.
MOD_LADDER_GUARD := test -f $(MOD_DATA)/vllm-lora-ladder.json || \
	{ echo "missing $(MOD_DATA)/vllm-lora-ladder.json: run serve-lora-ladder first" >&2; exit 1; }
# serve-up refuses to deploy without the ladder, and stops the app itself when the deploy or the
# health wait fails.
MOD_ENV = PL_SERVE_MODEL=$(MOD_MODEL) PL_SERVE_VARIANT=$(SERVE_VARIANT)
MOD_SERVE_UP = $(MOD_LADDER_GUARD); { $(MOD_ENV) $(MOD_MODAL) deploy -m serving.modal_vllm && \
	$(MOD_ENV) $(MOD_PY) -m scripts.mod.probe --wait-healthy --variant $(SERVE_VARIANT) \
	--out $(MOD_DATA)/vllm-coldstart$(MOD_APP_SUFFIX).json; } || { $(MOD_SERVE_DOWN); exit 1; }

.PHONY: serve-lora-ladder serve-up serve-down serve-probe serve-attest-local

serve-lora-ladder:
	$(MOD_MODAL) run -m scripts.mod.lora_ladder --out $(MOD_DATA)/vllm-lora-ladder.json

serve-up:
	$(MOD_SERVE_UP)

serve-down:
	$(MOD_SERVE_DOWN)

# serve-down runs from a trap, so an interrupted or failed probe never leaves a GPU running.
serve-probe:
	$(MOD_LADDER_GUARD); trap '$(MOD_SERVE_DOWN)' EXIT HUP INT TERM; $(MOD_SERVE_UP) && \
	$(MOD_PY) -m scripts.mod.probe --variant $(SERVE_VARIANT) $(MOD_BASELINE) \
		--out $(MOD_DATA)/vllm-probe$(MOD_SUFFIX).json

# Downloads 2 shards (~8.6 GB) at the pinned revision and compares them with /pl/attest.
serve-attest-local:
	uv run --no-project --with huggingface_hub==2.0.0 python -m scripts.mod.attest_local --shards 1,4 \
		--against $(MOD_DATA)/vllm-probe.json --out $(MOD_DATA)/vllm-attest-local.json

# S0-MOD-02 (ADR-0003). train-modules runs on this CPU with no weights and no keys: the
# meta-device named_modules() dump plus real PEFT over the train targets. train-smoke is
# root-run (G): the 50-step smoke on one H100; --detach keeps a paid run going if the
# local process disconnects (rerun with --run-id <id> to resume from its checkpoints).
MOD_TRAIN_CPU := uv run --no-project --with torch==2.13.0 --with transformers==5.17.0 \
	--with peft==0.21.0 --with accelerate==1.15.0 python

.PHONY: train-modules train-smoke

train-modules:
	$(MOD_TRAIN_CPU) -m training_jobs.sft $(MOD_DATA)/peft-modules.json

train-smoke:
	$(MOD_MODAL) run --detach -m training_jobs.modal_train::main --out $(MOD_DATA)/peft-train-smoke.json

# S0-MOD-03 (TRAINING §9). pull-through is root-run (L+G). MODE=full: select up to 60
# base-9B Fast turns from PT_EVIDENCE (P5 on every row), train the pull-through recipe on
# Modal, serve the adapter in the trained LoRA slot (PL_TRAINED_ADAPTER), then liveness, one
# product-path session with both lanes on it (evidence-check --claim), and
# docs/results/pull-through.json (written only when every check passes; each run's raw
# JSON stays in PT_DIR). MODE=verify: the serving steps again, with that file's adapter.
# PT_DIR=<an earlier run's dir> with a train.json skips select and training (no paid
# retrain after a transient serving or session failure).
# pull-through-liveness: the liveness step alone for ADAPTER, a path in the adapter volume
# (the S0-MOD-02 smoke adapter by default). The app stops from a trap. Export in the shell
# only, as for smoke-live: PL_VLLM_*, PL_RELAY_*, PL_TEAMROUTER_* (BASE_URL, API_KEY).
PT_STAMP := $(shell date -u +%Y%m%dT%H%M%SZ)
PT_DIR ?= runs/pull-through/$(PT_STAMP)
PT_EVIDENCE ?= evidence/s0
PT_FAMILY ?= cp-direct-discount
ADAPTER ?= train/20260926-smoke-3/adapter
ADAPTER_NAME ?= Qwen3.5-9B-pl-smoke
PT_PY := uv run python -m proxyloop.training.pull_through
PT_SERVE_DOWN := $(MOD_MODAL) app stop --yes proxyloop-vllm
PT_SERVE_UP := PL_SERVE_VARIANT=pinned PL_LORA_RUNG=all $(MOD_MODAL) deploy -m serving.modal_vllm && \
	$(MOD_PY) -m scripts.mod.probe --wait-healthy --variant pinned --out $(PT_DIR)/coldstart.json
PT_TRAIN := $(MOD_MODAL) run --detach -m training_jobs.modal_train::pull_through \
	--rows $(PT_DIR)/rows.json --out $(PT_DIR)/train.json

.PHONY: pull-through pull-through-liveness

pull-through:
	@case "$(MODE)" in full|verify) ;; *) echo "MODE=full|verify is required" >&2; exit 1;; esac
	$(MOD_LADDER_GUARD)
	$(if $(filter full,$(MODE)),test -f $(PT_DIR)/train.json || { $(PT_PY) select --dir $(PT_DIR) --evidence $(PT_EVIDENCE) && $(PT_TRAIN); })
	trap '$(PT_SERVE_DOWN)' EXIT HUP INT TERM; \
	PL_TRAINED_ADAPTER="$$($(PT_PY) slot --mode $(MODE) --dir $(PT_DIR))" && export PL_TRAINED_ADAPTER && \
	$(PT_SERVE_UP) && $(PT_PY) check --mode $(MODE) --dir $(PT_DIR) --family $(PT_FAMILY)

pull-through-liveness:
	$(MOD_LADDER_GUARD)
	trap '$(PT_SERVE_DOWN)' EXIT HUP INT TERM; \
	export PL_TRAINED_ADAPTER="$(ADAPTER_NAME)=$(ADAPTER)" && $(PT_SERVE_UP) && \
	$(PT_PY) liveness --name $(ADAPTER_NAME) --out $(PT_DIR)/liveness.json
