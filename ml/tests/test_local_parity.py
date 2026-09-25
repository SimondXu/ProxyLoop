"""M1 parity statistics and the committed report's replay (P1); no model."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
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

from scripts import run_phase03c_local_parity as parity_script
from scripts.run_phase03c_local_parity import (
    OBSERVED_ROW_KEYS,
    REPORT,
    _observed_from_report,
    build_report,
    validate_observed,
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


# --- I1: the row set, order and identity cannot be rewritten consistently -----


def test_the_committed_report_validates() -> None:
    validate_observed(_observed_from_report(_committed()))


def _without_wrong_rows(observed: dict[str, dict[str, Any]]) -> None:
    wrong = {
        row["prompt_id"]
        for row in _committed()["arms"]["distilled"]["rows"]
        if row["local_act"] != row["oracle_act"]
    }
    assert len(wrong) == 4
    observed["distilled"]["rows"] = [
        row for row in observed["distilled"]["rows"] if row["prompt_id"] not in wrong
    ]


def _duplicate_rows(observed: dict[str, dict[str, Any]]) -> None:
    rows = observed["distilled"]["rows"]
    observed["distilled"]["rows"] = rows[:-10] + rows[:10]


def _reorder_rows(observed: dict[str, dict[str, Any]]) -> None:
    rows = observed["untuned"]["rows"]
    rows[0], rows[1] = rows[1], rows[0]


def _zero_decoding_fingerprint(observed: dict[str, dict[str, Any]]) -> None:
    observed["distilled"]["identity"]["decoding_fingerprint"] = "0" * 64


def _swap_backend_label(observed: dict[str, dict[str, Any]]) -> None:
    observed["untuned"]["identity"]["label"] = "local opt-in candidate"


def _refingerprint_after_edit(observed: dict[str, dict[str, Any]]) -> None:
    identity = observed["distilled"]["identity"]
    identity["prompt_version"] = "v5"
    identity["identity_fingerprint"] = "f" * 64


@pytest.mark.parametrize(
    "tamper",
    [
        _without_wrong_rows,
        _duplicate_rows,
        _reorder_rows,
        _zero_decoding_fingerprint,
        _swap_backend_label,
        _refingerprint_after_edit,
    ],
)
def test_validation_refuses_a_self_consistent_rewrite(
    tamper: Callable[[dict[str, dict[str, Any]]], None],
) -> None:
    observed = _observed_from_report(_committed())
    tamper(observed)
    with pytest.raises(SystemExit):
        validate_observed(observed)


def test_check_refuses_a_rewritten_report_that_rebuilds_consistently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reviewer's forgery: drop the four wrong distilled rows and rebuild
    every derived field; the report is self-consistent but must fail --check."""

    observed = _observed_from_report(_committed())
    _without_wrong_rows(observed)
    forged = tmp_path / "parity-report.json"
    forged.write_text(parity_script._render(build_report(observed)), "utf-8")
    assert json.loads(forged.read_text())["arms"]["distilled"]["summary"]["rows"] == 236
    monkeypatch.setattr(parity_script, "REPORT", forged)
    with pytest.raises(SystemExit, match="dropped, duplicated, or reordered"):
        parity_script.main(["--check"])
