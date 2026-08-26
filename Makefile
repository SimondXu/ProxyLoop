.DEFAULT_GOAL := help

.PHONY: help preflight preflight-fast check-layout validate format format-check lint typecheck \
	unit-test test contracts contracts-check simulator benchmark benchmark-check \
	data-pilot data-pilot-check harness harness-check baselines baselines-check \
	errata errata-check hosted-rerun-source-check hosted-rerun-check \
	validity-smoke-check phase03b-readiness-check phase03b-experiment-check \
	lock-check postgres-check phase04d-check phase04d-profile-check phase05a-check phase06b1-check web-check \
	runtime-server portfolio-demo portfolio-demo-stop portfolio-demo-reset \
	portfolio-demo-channel portfolio-demo-recovery dev

PYTHON_RUN := uv run --project runtime --all-packages
ML_PYTHON_RUN := uv run --project ml
PYTHON_PATHS := runtime/packages/contracts/src runtime/packages/contracts/tests \
	runtime/packages/agent_core/src \
	runtime/packages/case_runtime/src \
	runtime/packages/connectors/src \
	runtime/packages/openai_adapter/src \
	runtime/packages/telecom_domain/src runtime/packages/provider_simulator/src \
	runtime/packages/provider_simulator/tests \
	runtime/packages/telecom_domain/tests \
	runtime/services/api/src \
	runtime/services/workflow_worker/src \
	tests/contract tests/integration scripts/generate_contracts.py \
	scripts/run_phase_01b_benchmark.py scripts/run_phase_03a1_harness.py \
	scripts/run_phase_04d_control_plane_profile.py \
	scripts/run_phase_07a_portfolio_demo.py \
	scripts/validate_layout.py
ML_PYTHON_PATHS := ml/data_pipeline/src ml/evaluation/src ml/tests \
	scripts/run_phase_02_data_pilot.py scripts/run_phase_03a1_baselines.py \
	scripts/run_phase_03a1_evaluation_erratum.py \
	scripts/run_phase_03a1_evaluation_erratum_models.py \
	scripts/run_phase_03a1_hosted_rerun.py \
	scripts/run_phase_03a1_validity_smoke.py \
	scripts/prepare_phase03b_readiness.py \
	scripts/prepare_phase03b_experiment.py scripts/run_phase03b_smoke.py

help:
	@printf '%s\n' 'Targets: preflight, preflight-fast, validate, format, format-check, lint, typecheck, test, postgres-check, phase04d-check, phase04d-profile-check, phase05a-check, phase06b1-check, web-check, contracts, contracts-check, simulator, benchmark, benchmark-check, data-pilot, data-pilot-check, harness, harness-check, baselines, baselines-check, errata, errata-check, hosted-rerun-source-check, hosted-rerun-check, validity-smoke-check, phase03b-readiness-check, phase03b-experiment-check, check-layout, lock-check, runtime-server, portfolio-demo, portfolio-demo-stop, portfolio-demo-reset, portfolio-demo-channel, portfolio-demo-recovery, dev'

preflight: validate lock-check
	python3 -m compileall -q scripts
	docker compose config --quiet

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
		runtime/packages/openai_adapter/src \
		runtime/packages/telecom_domain/src \
		runtime/services/api/src \
		runtime/services/workflow_worker/src \
		runtime/packages/provider_simulator/src scripts/generate_contracts.py \
		scripts/run_phase_01b_benchmark.py scripts/run_phase_03a1_harness.py \
		scripts/run_phase_04d_control_plane_profile.py \
		scripts/run_phase_07a_portfolio_demo.py scripts/validate_layout.py
	$(ML_PYTHON_RUN) mypy --config-file ml/pyproject.toml \
		ml/data_pipeline/src ml/evaluation/src scripts/run_phase_02_data_pilot.py \
		scripts/run_phase_03a1_baselines.py \
		scripts/run_phase_03a1_evaluation_erratum.py \
		scripts/run_phase_03a1_evaluation_erratum_models.py \
		scripts/run_phase_03a1_hosted_rerun.py \
		scripts/run_phase_03a1_validity_smoke.py \
		scripts/prepare_phase03b_readiness.py \
		scripts/prepare_phase03b_experiment.py scripts/run_phase03b_smoke.py

unit-test:
	$(PYTHON_RUN) pytest -c runtime/pyproject.toml -q \
		runtime/packages/contracts/tests runtime/packages/provider_simulator/tests \
		runtime/packages/telecom_domain/tests \
		tests/contract tests/integration
	$(ML_PYTHON_RUN) pytest -c ml/pyproject.toml ml/tests -q

test: unit-test contracts-check benchmark-check data-pilot-check harness-check baselines-check errata-check hosted-rerun-check validity-smoke-check phase03b-readiness-check phase03b-experiment-check

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

data-pilot:
	$(ML_PYTHON_RUN) python scripts/run_phase_02_data_pilot.py

data-pilot-check:
	$(ML_PYTHON_RUN) python scripts/run_phase_02_data_pilot.py --check

harness:
	$(PYTHON_RUN) python scripts/run_phase_03a1_harness.py --write

harness-check:
	$(PYTHON_RUN) python scripts/run_phase_03a1_harness.py --check

baselines: baselines-check

baselines-check:
	$(ML_PYTHON_RUN) python -m scripts.run_phase_03a1_baselines --check

errata:
	$(ML_PYTHON_RUN) python -m scripts.run_phase_03a1_evaluation_erratum --write-fixtures

errata-check:
	$(ML_PYTHON_RUN) python -m scripts.run_phase_03a1_evaluation_erratum --check

hosted-rerun-source-check:
	$(ML_PYTHON_RUN) python -m scripts.run_phase_03a1_hosted_rerun --check-sources

hosted-rerun-check:
	$(ML_PYTHON_RUN) python -m scripts.run_phase_03a1_hosted_rerun --check

validity-smoke-check:
	$(ML_PYTHON_RUN) python -m scripts.run_phase_03a1_validity_smoke --check

phase03b-readiness-check:
	$(ML_PYTHON_RUN) python scripts/prepare_phase03b_readiness.py --check

phase03b-experiment-check:
	$(ML_PYTHON_RUN) python -m scripts.prepare_phase03b_experiment --check

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
