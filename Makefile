.DEFAULT_GOAL := help

.PHONY: help check-layout validate lint test contracts dev

help:
	@printf '%s\n' 'Targets: check-layout, validate, lint, test, contracts, dev'

check-layout:
	python3 scripts/validate_layout.py

validate: check-layout

lint:
	git diff --check

test: check-layout

contracts:
	@printf '%s\n' 'Contract generation starts with Phase 1 Pydantic models.'

dev:
	@printf '%s\n' 'Phase 0 has no running product service. See README.md and docs/planning/initial-project-plan.md.'
