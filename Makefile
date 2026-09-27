# Root-owned. Lane targets go in mk/sys.mk and mk/mod.mk (AGENTS.md, PLAN.md §0.2).
.DEFAULT_GOAL := check
.PHONY: check lint typecheck test imports docs-check format

check: lint typecheck test imports docs-check

lint:
	uv run ruff check src tests scripts serving training_jobs
	uv run ruff format --check src tests scripts serving training_jobs

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
	uv run ruff check --fix src tests scripts serving training_jobs
	uv run ruff format src tests scripts serving training_jobs

# evidence-check (S0-ROOT-14): proxyloop.evidence.check.check_path on one bundle; no keys,
# no GPU. RUN=<bundle dir>; MODE=offline (default) or claim. Exits non-zero on any failure.
.PHONY: evidence-check
evidence-check: MODE ?= offline
evidence-check:
	$(if $(RUN),,$(error RUN=<bundle dir> is required))
	$(if $(filter-out offline claim,$(MODE)),$(error MODE must be offline or claim))
	uv run python -c 'import sys, pathlib; from proxyloop.evidence.check import check_path; \
	run, mode = sys.argv[1:]; r = check_path(pathlib.Path(run), mode); \
	print(f"evidence-check {mode} {run}:", "ok" if r.ok else "FAILED"); \
	print("".join(f"  - {f}\n" for f in r.failures), end=""); sys.exit(0 if r.ok else 1)' \
		"$(RUN)" "$(MODE)"

-include mk/*.mk
