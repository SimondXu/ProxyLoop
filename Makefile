# Root-owned. Lane targets go in mk/sys.mk and mk/mod.mk (AGENTS.md, PLAN.md §0.2).
.DEFAULT_GOAL := check
.PHONY: check lint typecheck test imports docs-check format

check: lint typecheck test imports docs-check

lint:
	uv run ruff check src tests scripts serving
	uv run ruff format --check src tests scripts serving

typecheck:
	uv run pyright

test:
	uv run pytest -q

imports:
	uv run lint-imports

docs-check:
	uv run python scripts/check_legacy_links.py docs/v0-retrospective.md
	uv run python scripts/lint_readme.py

format:
	uv run ruff check --fix src tests scripts serving
	uv run ruff format src tests scripts serving

-include mk/*.mk
