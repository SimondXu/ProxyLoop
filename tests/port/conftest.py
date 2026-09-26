"""Port-fidelity tests: they read ``tests/fixtures/v0`` and never import v0."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

V0_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "v0"


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    body = json.loads((V0_FIXTURES / "terms_hash_v1.json").read_text("utf-8"))
    counts = ", ".join(
        f"{name}={count}" for name, count in sorted(body["scenario_counts"].items())
    )
    terminalreporter.write_line(
        f"terms_hash_v1 == v0 material_terms_hash fixture: v0 catalogue scenarios "
        f"{counts} (benchmark-v1 scenarios without an offer: "
        f"{body['benchmark_v1_scenarios_without_offer']}); {len(body['rows'])} rows"
    )
