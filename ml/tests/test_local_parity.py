"""M1 parity statistics and the committed report's replay (P1); no model."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from proxyloop_evaluation.local_fast.parity import (
    PARITY_HELD,
    PARITY_NOT_ESTABLISHED,
    nearest_rank,
    parsed_act,
    verdict,
)

from scripts.run_phase03c_local_parity import (
    OBSERVED_ROW_KEYS,
    REPORT,
    _observed_from_report,
    build_report,
)

ROOT = Path(__file__).resolve().parents[2]


def test_parsed_act_is_tolerant_and_never_repairs() -> None:
    assert parsed_act('{"dialogue_act":"confirm"}') == "confirm"
    assert parsed_act('```json\n{"dialogue_act":"counter"}\n```') == "counter"
    assert parsed_act('{"dialogue_act":"confirm","dialogue_act":"counter"}') is None
    assert parsed_act('{"dialogue_act": 3}') is None
    assert parsed_act("not json") is None
    assert parsed_act("[]") is None
    assert parsed_act(None) is None


@pytest.mark.parametrize(
    ("agreement", "concordance", "expected"),
    [
        (0.95, 0.95, PARITY_HELD),
        (0.983, 1.0, PARITY_HELD),
        (0.9499, 1.0, PARITY_NOT_ESTABLISHED),
        (1.0, 0.9499, PARITY_NOT_ESTABLISHED),
        (0.542, 0.5, PARITY_NOT_ESTABLISHED),
    ],
)
def test_pre_registered_bar(
    agreement: float, concordance: float, expected: str
) -> None:
    assert verdict(agreement, concordance) == expected


def test_nearest_rank() -> None:
    assert nearest_rank([], 50) is None
    assert nearest_rank([5, 1, 3], 50) == 3
    assert nearest_rank(list(range(1, 101)), 95) == 95


def _committed() -> dict[str, Any]:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def _subset(report: dict[str, Any], rows: int) -> dict[str, dict[str, Any]]:
    observed = _observed_from_report(report)
    for arm in observed.values():
        arm["rows"] = arm["rows"][:rows]
    return observed


def test_committed_report_has_both_arms_and_raw_outputs() -> None:
    report = _committed()
    assert set(report["arms"]) == {"distilled", "untuned"}
    for arm in report["arms"].values():
        assert arm["summary"]["rows"] == len(arm["rows"]) == 240
        assert all(set(OBSERVED_ROW_KEYS) <= set(row) for row in arm["rows"])
    assert report["verdict"]["result"] in (PARITY_HELD, PARITY_NOT_ESTABLISHED)
    assert "/Users/" not in REPORT.read_text(encoding="utf-8")


def test_derived_fields_replay_from_the_raw_outputs() -> None:
    report = _committed()
    rebuilt = build_report(_subset(report, 3))
    for backend in ("distilled", "untuned"):
        for replayed, committed in zip(
            rebuilt["arms"][backend]["rows"],  # type: ignore[index]
            report["arms"][backend]["rows"][:3],
            strict=True,
        ):
            assert replayed == committed


def test_a_tampered_raw_output_changes_the_derived_fields() -> None:
    report = _committed()
    observed = _subset(report, 1)
    first = next(
        row
        for row in report["arms"]["distilled"]["rows"]
        if row["status"] == "succeeded"
    )
    observed["distilled"]["rows"] = [{key: first[key] for key in OBSERVED_ROW_KEYS}]
    row = observed["distilled"]["rows"][0]
    other = "close" if parsed_act(row["raw_output"]) != "close" else "clarify"
    tampered = copy.deepcopy(observed)
    tampered["distilled"]["rows"][0]["raw_output"] = json.dumps(
        {**json.loads(row["raw_output"]), "dialogue_act": other}
    )
    original = build_report(observed)["arms"]["distilled"]["rows"][0]  # type: ignore[index]
    changed = build_report(tampered)["arms"]["distilled"]["rows"][0]  # type: ignore[index]
    assert changed["local_act"] == other != original["local_act"]
    assert changed["metrics"] != original["metrics"]
