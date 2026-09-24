.DEFAULT_GOAL := help

.PHONY: help preflight preflight-fast check-layout validate format format-check lint typecheck \
	unit-test test contracts contracts-check simulator benchmark benchmark-check \
	negotiation-check fast-slow-split-report fast-slow-split-check \
	data-pilot data-pilot-check harness harness-check baselines baselines-check \
	baselines-historical-check errata errata-check hosted-rerun-source-check \
	hosted-rerun-check hosted-rescore hosted-rescore-check \
	validity-smoke-check phase03b-readiness-check phase03b-experiment-check \
	phase03c-errata phase03c-smoke-check phase03c-invariants phase03c-invariants-check \
	phase03c-cloud-bundle phase03c-cloud-bundle-check phase03c-training-data phase03c-training-check phase03c-rescore-check \
	phase03c-mlx-adapter phase03c-local-parity phase03c-local-parity-check local-fast-gateway \
	lock-check postgres-check phase04d-check phase04d-profile-check phase05a-check phase06b1-check web-check \
	runtime-server portfolio-demo portfolio-demo-stop portfolio-demo-reset \
	portfolio-demo-channel portfolio-demo-recovery dev

PYTHON_RUN := uv run --project runtime --all-packages
# Runtime pytest JUnit report; `make preflight` pins its gated-skip count.
GATED_SKIPS_REPORT := .gate/runtime-junit.xml
ML_PYTHON_RUN := uv run --project ml
PYTHON_PATHS := runtime/packages/contracts/src runtime/packages/contracts/tests \
	runtime/packages/agent_core/src \
	runtime/packages/case_runtime/src \
	runtime/packages/connectors/src \
	runtime/packages/local_fast/src \
	runtime/packages/openai_adapter/src \
	runtime/packages/telecom_domain/src runtime/packages/provider_simulator/src \
	runtime/packages/provider_simulator/tests \
	runtime/packages/telecom_domain/tests \
	runtime/services/api/src \
	runtime/services/workflow_worker/src \
	tests/contract tests/integration scripts/generate_contracts.py \
	scripts/run_phase_01b_benchmark.py scripts/run_phase_03a1_harness.py \
	scripts/run_negotiation_ceiling.py scripts/run_fast_slow_split_report.py \
	scripts/run_phase_04d_control_plane_profile.py \
	scripts/run_phase_07a_portfolio_demo.py \
	scripts/validate_layout.py scripts/check_gated_skips.py
ML_PYTHON_PATHS := ml/data_pipeline/src ml/evaluation/src ml/tests \
	scripts/run_phase_02_data_pilot.py scripts/run_phase_03a1_baselines.py \
	scripts/run_phase_03a1_evaluation_erratum.py \
	scripts/run_phase_03a1_evaluation_erratum_models.py \
	scripts/run_phase_03a1_hosted_rerun.py \
	scripts/run_phase_03a1_hosted_rescore.py \
	scripts/run_phase_03a1_validity_smoke.py \
	scripts/prepare_phase03b_readiness.py \
	scripts/prepare_phase03b_experiment.py scripts/run_phase03b_smoke.py \
	scripts/prepare_phase03c_errata.py scripts/run_phase03c_smoke.py \
	scripts/run_phase03c_scenario_invariants.py scripts/build_phase03c_prompt_set.py \
	scripts/run_phase03c_teacher_pilot.py scripts/run_phase03c_teacher_generation.py \
	scripts/build_phase03c_cloud_bundle.py ml/training/phase03c_cloud \
	scripts/prepare_phase03c_training_data.py scripts/run_phase03c_training.py \
	scripts/run_phase03c_dev_eval.py scripts/rescore_phase03c_heldout.py \
	scripts/convert_phase03c_adapter_mlx.py scripts/run_local_fast_gateway.py \
	scripts/run_phase03c_local_parity.py
# Cloud bundle inputs: the accepted teacher JSONL and an optional local Qwen3-8B tokenizer snapshot for token stats.
PHASE03C_ACCEPTED ?= data/experiments/phase-03c/teacher-full-v6/claude-sonnet-5-accepted.jsonl
PHASE03C_TOKENIZER_PATH ?=
# PR-9b local Fast backend (manual lane, one model run at a time): the cached base snapshot and the
# git-ignored PEFT adapter; nothing is downloaded (HF_HUB_OFFLINE=1).
QWEN3_8B_MLX_PATH ?= $(HOME)/.cache/huggingface/hub/models--Qwen--Qwen3-8B-MLX-bf16/snapshots/6766fd4b8101fa4201cc55c5a2e464f3d301f792
PHASE03C_PEFT_ADAPTER ?= data/experiments/phase-03c/training/cloud-run-01/train/adapter
BACKEND ?= distilled

help:
	@printf '%s\n' 'Targets: preflight, preflight-fast, validate, format, format-check, lint, typecheck, test, postgres-check, phase04d-check, phase04d-profile-check, phase05a-check, phase06b1-check, web-check, contracts, contracts-check, simulator, benchmark, benchmark-check, negotiation-check, fast-slow-split-report, fast-slow-split-check, data-pilot, data-pilot-check, harness, harness-check, baselines, baselines-check, baselines-historical-check, errata, errata-check, hosted-rerun-source-check, hosted-rerun-check, hosted-rescore, hosted-rescore-check, validity-smoke-check, phase03b-readiness-check, phase03b-experiment-check, phase03c-smoke-check, phase03c-invariants, phase03c-invariants-check, phase03c-prompt-set-check, phase03c-teacher-pilot-check, phase03c-teacher-generation-check, phase03c-cloud-bundle, phase03c-cloud-bundle-check, phase03c-training-data, phase03c-training-check, phase03c-mlx-adapter, phase03c-local-parity, phase03c-local-parity-check, local-fast-gateway, check-layout, lock-check, runtime-server, portfolio-demo, portfolio-demo-stop, portfolio-demo-reset, portfolio-demo-channel, portfolio-demo-recovery, dev'

preflight: validate lock-check
	python3 -m compileall -q scripts
	docker compose config --quiet
	python3 scripts/check_gated_skips.py $(GATED_SKIPS_REPORT)

preflight-fast: check-layout
	python3 -m compileall -q scripts
	git diff --check
	git diff --cached --check

check-layout:
	python3 scripts/validate_layout.py

validate: format-check lint typecheck test check-layout web-check

web-check:
	pnpm --filter @proxyloop/web lint
	pnpm --filter @proxyloop/web typecheck
	pnpm --filter @proxyloop/web test
	pnpm --filter @proxyloop/web build

format:
	$(PYTHON_RUN) ruff format --config runtime/pyproject.toml $(PYTHON_PATHS)
	$(ML_PYTHON_RUN) ruff format --config ml/pyproject.toml $(ML_PYTHON_PATHS)

format-check:
	$(PYTHON_RUN) ruff format --check --config runtime/pyproject.toml $(PYTHON_PATHS)
	$(ML_PYTHON_RUN) ruff format --check --config ml/pyproject.toml $(ML_PYTHON_PATHS)

lint:
	$(PYTHON_RUN) ruff check --config runtime/pyproject.toml $(PYTHON_PATHS)
	$(ML_PYTHON_RUN) ruff check --config ml/pyproject.toml $(ML_PYTHON_PATHS)
	git diff --check
	git diff --cached --check

typecheck:
	$(PYTHON_RUN) mypy --config-file runtime/pyproject.toml \
		runtime/packages/contracts/src runtime/packages/agent_core/src \
		runtime/packages/case_runtime/src \
		runtime/packages/connectors/src \
		runtime/packages/local_fast/src \
		runtime/packages/openai_adapter/src \
		runtime/packages/telecom_domain/src \
		runtime/services/api/src \
		runtime/services/workflow_worker/src \
		runtime/packages/provider_simulator/src scripts/generate_contracts.py \
		scripts/run_phase_01b_benchmark.py scripts/run_phase_03a1_harness.py \
		scripts/run_negotiation_ceiling.py scripts/run_fast_slow_split_report.py \
		scripts/run_phase_04d_control_plane_profile.py \
		scripts/run_phase_07a_portfolio_demo.py scripts/validate_layout.py \
		scripts/check_gated_skips.py
	$(ML_PYTHON_RUN) mypy --config-file ml/pyproject.toml \
		ml/data_pipeline/src ml/evaluation/src scripts/run_phase_02_data_pilot.py \
		scripts/run_phase_03a1_baselines.py \
		scripts/run_phase_03a1_evaluation_erratum.py \
		scripts/run_phase_03a1_evaluation_erratum_models.py \
		scripts/run_phase_03a1_hosted_rerun.py \
		scripts/run_phase_03a1_hosted_rescore.py \
		scripts/run_phase_03a1_validity_smoke.py \
		scripts/prepare_phase03b_readiness.py \
		scripts/prepare_phase03b_experiment.py scripts/run_phase03b_smoke.py \
		scripts/prepare_phase03c_errata.py scripts/run_phase03c_smoke.py \
		scripts/run_phase03c_scenario_invariants.py scripts/build_phase03c_prompt_set.py \
		scripts/run_phase03c_teacher_pilot.py scripts/run_phase03c_teacher_generation.py \
		scripts/build_phase03c_cloud_bundle.py \
		scripts/prepare_phase03c_training_data.py scripts/run_phase03c_training.py \
		scripts/run_phase03c_dev_eval.py scripts/rescore_phase03c_heldout.py \
		scripts/convert_phase03c_adapter_mlx.py scripts/run_local_fast_gateway.py \
		scripts/run_phase03c_local_parity.py

unit-test:
	$(PYTHON_RUN) pytest -c runtime/pyproject.toml -q \
		runtime/packages/contracts/tests runtime/packages/provider_simulator/tests \
		runtime/packages/telecom_domain/tests \
		tests/contract tests/integration \
		-o junit_family=xunit1 --junitxml=$(GATED_SKIPS_REPORT)
	$(ML_PYTHON_RUN) pytest -c ml/pyproject.toml ml/tests -q

test: unit-test contracts-check benchmark-check data-pilot-check harness-check baselines-historical-check errata-check hosted-rerun-check validity-smoke-check phase03b-readiness-check phase03b-experiment-check phase03c-smoke-check phase03c-invariants-check phase03c-prompt-set-check phase03c-teacher-pilot-check phase03c-teacher-generation-check phase03c-cloud-bundle-check phase03c-training-check phase03c-rescore-check phase03c-local-parity-check negotiation-check fast-slow-split-check

contracts:
	$(PYTHON_RUN) python scripts/generate_contracts.py

contracts-check:
	$(PYTHON_RUN) python scripts/generate_contracts.py --check
	pnpm exec tsc --noEmit -p contracts/typescript/tsconfig.json

simulator:
	$(PYTHON_RUN) python -m proxyloop_provider_simulator

benchmark:
	$(PYTHON_RUN) python scripts/run_phase_01b_benchmark.py

benchmark-check:
	$(PYTHON_RUN) python scripts/run_phase_01b_benchmark.py --check

negotiation-check:
	$(PYTHON_RUN) python scripts/run_negotiation_ceiling.py --check

fast-slow-split-report:
	$(PYTHON_RUN) python scripts/run_fast_slow_split_report.py --write

fast-slow-split-check:
	$(PYTHON_RUN) python scripts/run_fast_slow_split_report.py --check

data-pilot:
	$(ML_PYTHON_RUN) python scripts/run_phase_02_data_pilot.py

data-pilot-check:
	$(ML_PYTHON_RUN) python scripts/run_phase_02_data_pilot.py --check

harness:
	$(PYTHON_RUN) python scripts/run_phase_03a1_harness.py --write

harness-check:
	$(PYTHON_RUN) python scripts/run_phase_03a1_harness.py --check

baselines: baselines-check

# r1 replay through the current evaluator; historical, not part of `make test`.
# This legacy replay fails on the current tree by design: it binds r1 to the
# Harness episodes of its time, which were regenerated with opaque public ids.
# `baselines-historical-check` reports that drift as a state instead.
baselines-check:
	$(ML_PYTHON_RUN) python -m scripts.run_phase_03a1_baselines --check

# r1 integrity only (fingerprints, provenance, truthfulness); no replay.
baselines-historical-check:
	$(ML_PYTHON_RUN) python -m scripts.run_phase_03a1_baselines --check-historical

errata:
	$(ML_PYTHON_RUN) python -m scripts.run_phase_03a1_evaluation_erratum --write-fixtures

errata-check:
	$(ML_PYTHON_RUN) python -m scripts.run_phase_03a1_evaluation_erratum --check

hosted-rerun-source-check:
	$(ML_PYTHON_RUN) python -m scripts.run_phase_03a1_hosted_rerun --check-sources

# r4 gate: integrity + execution-contract state + rescored artifact.  The r4-era
# gate `python -m scripts.run_phase_03a1_hosted_rerun --check` (frozen bytes,
# fresh-fixture replay) stays runnable but is no longer part of `make test`.
hosted-rerun-check: hosted-rescore-check

hosted-rescore:
	$(ML_PYTHON_RUN) python -m scripts.run_phase_03a1_hosted_rescore --write

hosted-rescore-check:
	$(ML_PYTHON_RUN) python -m scripts.run_phase_03a1_hosted_rescore --check

validity-smoke-check:
	$(ML_PYTHON_RUN) python -m scripts.run_phase_03a1_validity_smoke --check

phase03b-readiness-check:
	$(ML_PYTHON_RUN) python scripts/prepare_phase03b_readiness.py --check

phase03b-experiment-check:
	$(ML_PYTHON_RUN) python -m scripts.prepare_phase03b_experiment --check

phase03c-errata:
	$(ML_PYTHON_RUN) python -m scripts.prepare_phase03c_errata --write

phase03c-smoke-check:
	$(ML_PYTHON_RUN) python -m scripts.prepare_phase03c_errata --check

phase03c-invariants:
	$(ML_PYTHON_RUN) python -m scripts.run_phase03c_scenario_invariants --write

phase03c-invariants-check:
	$(ML_PYTHON_RUN) python -m scripts.run_phase03c_scenario_invariants --check

phase03c-prompt-set:
	$(ML_PYTHON_RUN) python -m scripts.build_phase03c_prompt_set --write

phase03c-prompt-set-check:
	$(ML_PYTHON_RUN) python -m scripts.build_phase03c_prompt_set --check

phase03c-teacher-pilot-check:
	$(ML_PYTHON_RUN) python -m scripts.run_phase03c_teacher_pilot --check

phase03c-teacher-generation-check:
	$(ML_PYTHON_RUN) python -m scripts.run_phase03c_teacher_generation --check

# Cloud bundle for ml/training/phase03c_cloud (JSONL git-ignored; manifest and schema committed).
phase03c-cloud-bundle:
	$(ML_PYTHON_RUN) python -m scripts.build_phase03c_cloud_bundle --accepted "$(PHASE03C_ACCEPTED)" \
		$(if $(PHASE03C_TOKENIZER_PATH),--tokenizer-path "$(PHASE03C_TOKENIZER_PATH)",)

# Locks the published Stage 3 numbers: replays every stored raw output through
# the repository evaluator and fails if the committed re-scored reports drift.
PHASE03C_RUN_EVAL ?= data/experiments/phase-03c/training/cloud-run-01/eval
phase03c-rescore-check:
	@test -f $(PHASE03C_RUN_EVAL)/heldout-report.json || \
		{ echo "no cloud run under $(PHASE03C_RUN_EVAL); nothing to check"; exit 0; }
	$(ML_PYTHON_RUN) python -m scripts.rescore_phase03c_heldout --check \
		--report $(PHASE03C_RUN_EVAL)/heldout-report.json \
		--out $(PHASE03C_RUN_EVAL)/heldout-rescored.json
	$(ML_PYTHON_RUN) python -m scripts.rescore_phase03c_heldout --check \
		--report $(PHASE03C_RUN_EVAL)/dev-report.json \
		--out $(PHASE03C_RUN_EVAL)/dev-rescored.json

# PEFT adapter -> git-ignored MLX adapter; must reproduce ml/serving/phase-03c-cloud-run-01-mlx-attestation.json.
phase03c-mlx-adapter:
	$(ML_PYTHON_RUN) python -m scripts.convert_phase03c_adapter_mlx --source "$(PHASE03C_PEFT_ADAPTER)"

# M1 stack parity, one arm per call (BACKEND=distilled|untuned; resumable); --write then combines both arms.
phase03c-local-parity:
	HF_HUB_OFFLINE=1 $(ML_PYTHON_RUN) python -m scripts.run_phase03c_local_parity --run \
		--backend $(BACKEND) --model-path "$(QWEN3_8B_MLX_PATH)"

# Replays the committed parity report's raw outputs through the repository evaluator; no model.
phase03c-local-parity-check:
	$(ML_PYTHON_RUN) python -m scripts.run_phase03c_local_parity --check

local-fast-gateway:
	HF_HUB_OFFLINE=1 $(ML_PYTHON_RUN) python -m scripts.run_local_fast_gateway \
		--backend $(BACKEND) --model-path "$(QWEN3_8B_MLX_PATH)"

phase03c-cloud-bundle-check:
	$(ML_PYTHON_RUN) python -m scripts.build_phase03c_cloud_bundle --check

# Accepted teacher JSONL -> mlx_lm chat data (local pipeline smoke only); PHASE03C_ACCEPTED and PHASE03C_TOKENIZER_PATH select the source and tokenizer.
phase03c-training-data:
	$(ML_PYTHON_RUN) python scripts/prepare_phase03c_training_data.py \
		--accepted "$(PHASE03C_ACCEPTED)" --out-dir data/experiments/phase-03c/training/data \
		--prompt-version v6 --tokenizer-path "$(PHASE03C_TOKENIZER_PATH)"

phase03c-training-check:
	$(ML_PYTHON_RUN) python scripts/run_phase03c_training.py --check

# Accepted teacher JSONL -> mlx_lm chat data; PHASE03C_ACCEPTED and PHASE03C_TOKENIZER_PATH select the source and tokenizer.
lock-check:
	uv lock --project runtime --check
	uv lock --project ml --check
	pnpm install --lockfile-only --frozen-lockfile --ignore-scripts --offline

postgres-check:
	@test -n "$(PROXYLOOP_TEST_DATABASE_URL)" || (echo 'PROXYLOOP_TEST_DATABASE_URL is required' >&2; exit 1)
	PROXYLOOP_TEST_DATABASE_URL="$(PROXYLOOP_TEST_DATABASE_URL)" $(PYTHON_RUN) pytest -c runtime/pyproject.toml -q tests/integration/test_phase_04c_persistent_case_store.py

phase04d-check:
	$(PYTHON_RUN) pytest -c runtime/pyproject.toml -q tests/integration/test_phase_04d_control_plane_operations.py

phase04d-profile-check:
	$(PYTHON_RUN) python scripts/run_phase_04d_control_plane_profile.py --check

phase05a-check:
	@test -n "$(PROXYLOOP_TEST_DATABASE_URL)" || (echo 'PROXYLOOP_TEST_DATABASE_URL is required' >&2; exit 1)
	@test -n "$(PROXYLOOP_TEST_TEMPORAL_ADDRESS)" || (echo 'PROXYLOOP_TEST_TEMPORAL_ADDRESS is required' >&2; exit 1)
	PROXYLOOP_TEST_DATABASE_URL="$(PROXYLOOP_TEST_DATABASE_URL)" \
		PROXYLOOP_TEST_TEMPORAL_ADDRESS="$(PROXYLOOP_TEST_TEMPORAL_ADDRESS)" \
		$(PYTHON_RUN) pytest -c runtime/pyproject.toml -q \
		tests/integration/test_phase_05a_case_runtime.py \
		tests/integration/test_phase_05a_temporal_api.py \
		tests/integration/test_phase_05a_temporal_workflow.py

phase06b1-check:
	@test -n "$(PROXYLOOP_TEST_DATABASE_URL)" || (echo 'PROXYLOOP_TEST_DATABASE_URL is required' >&2; exit 1)
	@test -n "$(PROXYLOOP_TEST_TEMPORAL_ADDRESS)" || (echo 'PROXYLOOP_TEST_TEMPORAL_ADDRESS is required' >&2; exit 1)
	PROXYLOOP_TEST_DATABASE_URL="$(PROXYLOOP_TEST_DATABASE_URL)" \
		PROXYLOOP_TEST_TEMPORAL_ADDRESS="$(PROXYLOOP_TEST_TEMPORAL_ADDRESS)" \
		$(PYTHON_RUN) pytest -c runtime/pyproject.toml -q \
		tests/integration/test_phase_06b1_connectors.py \
		tests/integration/test_phase_06b1_channel_runtime.py \
		tests/integration/test_phase_06b1_workflow_worker.py \
		tests/integration/test_phase_06b1_temporal.py

runtime-server:
	$(PYTHON_RUN) python -m proxyloop_api.server --host 127.0.0.1 --port 8000

portfolio-demo:
	$(PYTHON_RUN) python scripts/run_phase_07a_portfolio_demo.py serve

portfolio-demo-stop:
	$(PYTHON_RUN) python scripts/run_phase_07a_portfolio_demo.py stop

portfolio-demo-reset:
	$(PYTHON_RUN) python scripts/run_phase_07a_portfolio_demo.py reset

portfolio-demo-channel:
	$(PYTHON_RUN) python scripts/run_phase_07a_portfolio_demo.py scene-channel

portfolio-demo-recovery:
	$(PYTHON_RUN) python scripts/run_phase_07a_portfolio_demo.py recovery

dev: runtime-server
