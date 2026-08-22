#!/usr/bin/env python3
"""Validate the tracked Phase 0 repository layout without external dependencies."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PATHS = (
    "README.md",
    "docs/README.md",
    "docs/specs/2026-08-21-telecom-bill-optimization-agent.md",
    "docs/architecture.md",
    "docs/decisions/2026-08-21-monorepo.md",
    "docs/decisions/2026-08-22-implementation-defaults.md",
    "docs/planning/initial-project-plan.md",
    "docs/planning/progress.md",
    "docs/research/foundations.md",
    "apps/web",
    "runtime/packages/contracts/pyproject.toml",
    "runtime/services/api/pyproject.toml",
    "ml/data_pipeline",
    "voice/worker",
    "contracts/jsonschema",
    "data/manifests",
    "infra/compose",
    "tests/contract",
)


def main() -> int:
    missing = [path for path in REQUIRED_PATHS if not (ROOT / path).exists()]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    if missing:
        print("Missing required paths:", *missing, sep="\n- ")
        return 1
    if not readme.startswith("# ProxyLoop\n"):
        print("README.md must identify the project as ProxyLoop.")
        return 1

    print("Phase 0 layout is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
