from __future__ import annotations

import json
from pathlib import Path

from scripts.run_negotiation_ceiling import (
    REPORT_PATH,
    build_ceiling_report,
    check_report,
    write_report,
)


def test_committed_ceiling_report_is_current_and_passes() -> None:
    assert check_report(REPORT_PATH) == ()
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert report["gate_passed"] is True
    assert report["scenario_count"] == 22
    assert report["leakage_violation_count"] == 0


def test_check_fails_on_a_tampered_report(tmp_path: Path) -> None:
    path = tmp_path / "ceiling.json"
    write_report(path)
    assert check_report(path) == ()
    report = json.loads(path.read_text(encoding="utf-8"))
    report["metrics"]["false_completion_count"] = 1
    path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    assert check_report(path) == ("ceiling_report_drift",)


def test_report_is_deterministic() -> None:
    assert build_ceiling_report() == build_ceiling_report()
