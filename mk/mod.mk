# MOD lane targets (S0-MOD-01, ADR-0002). Root-run only: they need Modal auth, the Modal secret
# `proxyloop-vllm` (VLLM_API_KEY) and PROXYLOOP_VLLM_API_KEY in the shell. Both
# `make -f mk/mod.mk <target>` and `include mk/*.mk` from the root Makefile work.
#   SERVE_VARIANT=pinned|prefix-align  (prefix-align is measure-only)
#   PL_LORA_RUNG=all|attn-mlp          (the ladder rung whose zero/live adapters are served)
#   SERVE_MODEL=9b|4b                  (serve-up/serve-down only; 4b: C3's base Qwen3.5-4B)
# No recipe uses $(MAKE), so `make -n` only prints and never reaches Modal.

SERVE_VARIANT ?= pinned
MOD_SUFFIX := $(if $(filter pinned,$(SERVE_VARIANT)),,-$(SERVE_VARIANT))
MOD_DATA := docs/decisions/data
MOD_MODAL := uv run --no-project --with modal==1.5.5 modal
MOD_PY := uv run --no-project --with modal==1.5.5 --with httpx==0.28.1 \
	--with transformers==5.17.0 --with jinja2==3.1.6 python
MOD_BASELINE := $(if $(MOD_SUFFIX),--baseline $(MOD_DATA)/vllm-probe.json,)
SERVE_MODEL ?= 9b
MOD_MODEL := 9b
serve-up serve-down: MOD_MODEL := $(SERVE_MODEL)
# Every other recipe (serve-probe, pull-through, liveness) serves the 9B, whatever the shell has.
export PL_SERVE_MODEL = $(MOD_MODEL)
MOD_APP_SUFFIX = $(if $(filter 9b,$(MOD_MODEL)),,-$(MOD_MODEL))$(MOD_SUFFIX)
MOD_SERVE_DOWN = $(MOD_MODAL) app stop --yes proxyloop-vllm$(MOD_APP_SUFFIX)
# Run order (ADR-0002): serve-lora-ladder -> serve-probe -> serve-attest-local -> prefix-align probe.
MOD_LADDER_GUARD := test -f $(MOD_DATA)/vllm-lora-ladder.json || \
	{ echo "missing $(MOD_DATA)/vllm-lora-ladder.json: run serve-lora-ladder first" >&2; exit 1; }
# serve-up refuses to deploy without the ladder, and stops the app itself when the deploy or the
# health wait fails.
MOD_SERVE_UP = $(MOD_LADDER_GUARD); { PL_SERVE_VARIANT=$(SERVE_VARIANT) $(MOD_MODAL) deploy -m serving.modal_vllm && \
	$(MOD_PY) -m scripts.mod.probe --wait-healthy --variant $(SERVE_VARIANT) --model $(MOD_MODEL) \
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
# Fast turns of one label source from PT_EVIDENCE (P5 on every row), train the pull-through
# recipe on Modal, serve the adapter in the trained LoRA slot (PL_TRAINED_ADAPTER), then liveness, one
# product-path session with both lanes on it (evidence-check --claim), and
# docs/results/pull-through.json (written only when every check passes; each run's raw
# JSON stays in PT_DIR). MODE=verify: the serving steps again, with that file's adapter.
# PT_DIR=<an earlier run's dir> with a train.json skips select and training (no paid
# retrain after a transient serving or session failure).
# S1-MOD-07: MODE=full needs PT_SOURCE=base_9b|hosted. base_9b: base-9B turns, and no
# PT_LABEL_MODEL; hosted: one hosted model's turns, PT_LABEL_MODEL=<endpoint>:<model_id>
# (e.g. openrouter:openai/gpt-6-luna). A missing or unknown value stops make as it expands
# the recipe, before any spend and under `make -n` too. MODE=verify takes neither.
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
PT_SOURCE ?=
PT_LABEL_MODEL ?=
PT_SOURCE_base_9b = --source base_9b$(if $(PT_LABEL_MODEL),$(error PT_SOURCE=base_9b takes no PT_LABEL_MODEL))
PT_SOURCE_hosted = --source hosted --label-model $(or $(PT_LABEL_MODEL),$(error PT_SOURCE=hosted needs PT_LABEL_MODEL=<endpoint>:<model_id>))
PT_SOURCE_ARGS = $(or $(PT_SOURCE_$(PT_SOURCE)),$(error MODE=full needs PT_SOURCE=base_9b|hosted, got '$(PT_SOURCE)'))
PT_SERVE_DOWN := $(MOD_MODAL) app stop --yes proxyloop-vllm
PT_SERVE_UP := PL_SERVE_VARIANT=pinned PL_LORA_RUNG=all $(MOD_MODAL) deploy -m serving.modal_vllm && \
	$(MOD_PY) -m scripts.mod.probe --wait-healthy --variant pinned --out $(PT_DIR)/coldstart.json
PT_TRAIN := $(MOD_MODAL) run --detach -m training_jobs.modal_train::pull_through \
	--rows $(PT_DIR)/rows.json --out $(PT_DIR)/train.json

.PHONY: pull-through pull-through-liveness

pull-through:
	@case "$(MODE)" in full|verify) ;; *) echo "MODE=full|verify is required" >&2; exit 1;; esac
	$(MOD_LADDER_GUARD)
	$(if $(filter full,$(MODE)),test -f $(PT_DIR)/train.json || { $(PT_PY) select --dir $(PT_DIR) --evidence $(PT_EVIDENCE) $(PT_SOURCE_ARGS) && $(PT_TRAIN); })
	trap '$(PT_SERVE_DOWN)' EXIT HUP INT TERM; \
	PL_TRAINED_ADAPTER="$$($(PT_PY) slot --mode $(MODE) --dir $(PT_DIR))" && export PL_TRAINED_ADAPTER && \
	$(PT_SERVE_UP) && $(PT_PY) check --mode $(MODE) --dir $(PT_DIR) --family $(PT_FAMILY)

pull-through-liveness:
	$(MOD_LADDER_GUARD)
	trap '$(PT_SERVE_DOWN)' EXIT HUP INT TERM; \
	export PL_TRAINED_ADAPTER="$(ADAPTER_NAME)=$(ADAPTER)" && $(PT_SERVE_UP) && \
	$(PT_PY) liveness --name $(ADAPTER_NAME) --out $(PT_DIR)/liveness.json

# S1-MOD-02: the EVAL §7 metrics of a bundle, or of a folder of bundles, as JSON. Offline:
# no keys, no GPU (`make metrics RUN=evidence/s0/<run_id>`).
.PHONY: metrics

metrics:
	uv run python -m proxyloop.eval.metrics $(RUN)

# S1-MOD-04: the Fast benchmark (src/proxyloop/eval/specs/fast_benchmark.yaml). benchmark-fast
# is root-run (L+G): C5 is hosted (OpenRouter), C2 and C1 need `make serve-up`; C1 fails loudly
# without PL_TRAINED_ADAPTER. BENCH_ARGS go to `proxyloop.cli session` (the Slow/world options).
# A runs dir holds one matrix: resume only with the identical BENCH_CONDITIONS. C1 runs later
# as its own matrix in a fresh dir (BENCH_CONDITIONS=C1 BENCH_RUNS=runs/fast-benchmark-c1
# BENCH_REPORT_RUNS="runs/fast-benchmark runs/fast-benchmark-c1"); comparisons across the
# two are marked "not interleaved". The report is gated (integrity, pairing, one shared
# config): refused, nothing written, unless `--descriptive` is passed by hand.
# benchmark-report is offline, no keys and no GPU (`make benchmark-report RUNS="<dir>..."`).
BENCH_RUNS ?= runs/fast-benchmark
BENCH_REPORT_RUNS ?= $(BENCH_RUNS)
BENCH_CONDITIONS ?= C5,C2
BENCH_OUT ?= docs/results/fast-benchmark.json
BENCH := uv run python -m proxyloop.eval.benchmark
BENCH_REPORT = $(BENCH) report --git-sha $$(git rev-parse HEAD) --out $(BENCH_OUT)

.PHONY: benchmark-fast benchmark-report

benchmark-fast:
	$(BENCH) run --runs $(BENCH_RUNS) --conditions $(BENCH_CONDITIONS) $(BENCH_ARGS)
	$(BENCH_REPORT) $(foreach r,$(BENCH_REPORT_RUNS),--runs $(r))

benchmark-report:
	$(BENCH_REPORT) $(foreach r,$(RUNS),--runs $(r))

# S1-MOD-08 same-state Fast probe: root-run (L+G) unless PSS_ARGS includes --plan.
.PHONY: probe-same-state
probe-same-state:
	uv run python -m scripts.mod.probe_same_state $(PSS_ARGS)

# S1-MOD-09 (PR1): freeze the world-model selection items from the train bundles under runs/.
# Offline: no keys, no model call; a sealed test path is refused. CONSTRUCTED (default: the
# committed constructed items) is copied in, kept apart and flagged; WORLD_SELECT_RUNS is the
# bundle dir (default runs). The blind Ear batches are
# exported by hand into an uncommitted dir:
#   uv run python -m scripts.mod.world_select export --items $(MOD_DATA)/world-select-items.json \
#       --out-dir runs/world-select-batches --key-out runs/world-select-key.json \
#       --batch 25 --seed <N>
CONSTRUCTED ?= $(MOD_DATA)/world-select-constructed.json
WORLD_SELECT_RUNS ?= runs
.PHONY: world-select-freeze

world-select-freeze:
	uv run python -m scripts.mod.world_select freeze --runs $(WORLD_SELECT_RUNS) \
		--out $(MOD_DATA)/world-select-items.json $(if $(CONSTRUCTED),--constructed $(CONSTRUCTED),)

# S1-MOD-09 (PR2a): replay the frozen items through the production world code, one JSONL per
# arm under WORLD_SELECT_OUT. Root-run (L) unless WSR_ARGS has --plan (no call, no key): run
# `make world-select-run WSR_ARGS=--plan` first. Keys only from the shell, by name:
# PL_TEAMROUTER_BASE_URL, PL_TEAMROUTER_API_KEY. The three arms (the incumbent first):
#   teamrouter:gemini-3.8-flash@low teamrouter:deepseek-flash@low teamrouter:glm-5.3-flash@low
# WSR_ARGS also takes --roles, --limit N (a smoke), --repeat-subset N --seed S, --concurrency K
# and --resume. WORLD_SELECT_RUNS (above) is read-only here.
WORLD_SELECT_ARMS ?= teamrouter:gemini-3.8-flash@low teamrouter:deepseek-flash@low \
	teamrouter:glm-5.3-flash@low
WORLD_SELECT_OUT ?= runs/world-select
WSR_ARGS ?=
.PHONY: world-select-run

world-select-run:
	uv run python -m scripts.mod.world_select run --items $(MOD_DATA)/world-select-items.json \
		--runs $(WORLD_SELECT_RUNS) --out-dir $(WORLD_SELECT_OUT) \
		$(foreach a,$(WORLD_SELECT_ARMS),--arm $(a)) $(WSR_ARGS)
