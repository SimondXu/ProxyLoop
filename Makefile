.DEFAULT_GOAL := help

.PHONY: help preflight check-layout validate lint test contracts dev

help:
	@printf '%s\n' 'Targets: preflight, check-layout, validate, lint, test, contracts, dev'

preflight: check-layout lint
	python3 -m compileall -q scripts
	docker compose config --quiet

check-layout:
	python3 scripts/validate_layout.py

validate: check-layout

lint:
	git diff --check
	git diff --cached --check

test: check-layout

contracts:
	@printf '%s\n' 'Contract generation starts with the prepared Phase 00B Pydantic models.'

dev:
	@printf '%s\n' 'Phase 0 has no running product service. See README.md and docs/planning/initial-project-plan.md.'
