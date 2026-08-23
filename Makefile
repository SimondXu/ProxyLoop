.DEFAULT_GOAL := help

.PHONY: help preflight check-layout validate format format-check lint typecheck \
	unit-test test contracts contracts-check lock-check dev

PYTHON_RUN := uv run --project runtime --all-packages
PYTHON_PATHS := runtime/packages/contracts/src runtime/packages/contracts/tests \
	tests/contract scripts/generate_contracts.py scripts/validate_layout.py

help:
	@printf '%s\n' 'Targets: preflight, validate, format, format-check, lint, typecheck, test, contracts, contracts-check, check-layout, lock-check, dev'

preflight: validate lock-check
	python3 -m compileall -q scripts
	docker compose config --quiet

check-layout:
	python3 scripts/validate_layout.py

validate: format-check lint typecheck test check-layout

format:
	$(PYTHON_RUN) ruff format --config runtime/pyproject.toml $(PYTHON_PATHS)

format-check:
	$(PYTHON_RUN) ruff format --check --config runtime/pyproject.toml $(PYTHON_PATHS)

lint:
	$(PYTHON_RUN) ruff check --config runtime/pyproject.toml $(PYTHON_PATHS)
	git diff --check
	git diff --cached --check

typecheck:
	$(PYTHON_RUN) mypy --config-file runtime/pyproject.toml \
		runtime/packages/contracts/src scripts/generate_contracts.py \
		scripts/validate_layout.py

unit-test:
	$(PYTHON_RUN) pytest -q

test: unit-test contracts-check

contracts:
	$(PYTHON_RUN) python scripts/generate_contracts.py

contracts-check:
	$(PYTHON_RUN) python scripts/generate_contracts.py --check
	pnpm exec tsc --noEmit -p contracts/typescript/tsconfig.json

lock-check:
	uv lock --project runtime --check
	pnpm install --lockfile-only --frozen-lockfile --ignore-scripts --offline

dev:
	@printf '%s\n' 'Phase 0 has no running product service. See README.md and docs/planning/initial-project-plan.md.'
