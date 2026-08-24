.DEFAULT_GOAL := help

.PHONY: help preflight check-layout validate format format-check lint typecheck \
	unit-test test contracts contracts-check simulator benchmark benchmark-check \
	data-pilot data-pilot-check harness harness-check baselines baselines-check \
	lock-check dev

PYTHON_RUN := uv run --project runtime --all-packages
ML_PYTHON_RUN := uv run --project ml
PYTHON_PATHS := runtime/packages/contracts/src runtime/packages/contracts/tests \
	runtime/packages/agent_core/src \
	runtime/packages/telecom_domain/src runtime/packages/provider_simulator/src \
	runtime/packages/provider_simulator/tests \
	tests/contract tests/integration scripts/generate_contracts.py \
	scripts/run_phase_01b_benchmark.py scripts/run_phase_03a1_harness.py \
	scripts/validate_layout.py
ML_PYTHON_PATHS := ml/data_pipeline/src ml/evaluation/src ml/tests \
	scripts/run_phase_02_data_pilot.py scripts/run_phase_03a1_baselines.py

help:
	@printf '%s\n' 'Targets: preflight, validate, format, format-check, lint, typecheck, test, contracts, contracts-check, simulator, benchmark, benchmark-check, data-pilot, data-pilot-check, harness, harness-check, baselines, baselines-check, check-layout, lock-check, dev'

preflight: validate lock-check
	python3 -m compileall -q scripts
	docker compose config --quiet

check-layout:
	python3 scripts/validate_layout.py

validate: format-check lint typecheck test check-layout

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
		runtime/packages/telecom_domain/src \
		runtime/packages/provider_simulator/src scripts/generate_contracts.py \
		scripts/run_phase_01b_benchmark.py scripts/run_phase_03a1_harness.py \
		scripts/validate_layout.py
	$(ML_PYTHON_RUN) mypy --config-file ml/pyproject.toml \
		ml/data_pipeline/src ml/evaluation/src scripts/run_phase_02_data_pilot.py \
		scripts/run_phase_03a1_baselines.py

unit-test:
	$(PYTHON_RUN) pytest -c runtime/pyproject.toml -q \
		runtime/packages/contracts/tests runtime/packages/provider_simulator/tests \
		tests/contract tests/integration
	$(ML_PYTHON_RUN) pytest -c ml/pyproject.toml ml/tests -q

test: unit-test contracts-check benchmark-check data-pilot-check harness-check baselines-check

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

lock-check:
	uv lock --project runtime --check
	uv lock --project ml --check
	pnpm install --lockfile-only --frozen-lockfile --ignore-scripts --offline

dev:
	@printf '%s\n' 'Phase 0 has no running product service. See README.md and docs/planning/initial-project-plan.md.'
