"""The local Fast/Slow split reports (PR-9b, P2) against 9a's fake gateway.

The real reports need the MLX gateway and run by hand; CI checks their
integrity (``--check``) and, here, that the local mode keeps the scripted turn
structure, carries no text, and that the integrity check catches edits.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.run_fast_slow_split_report import (
    TURN_STRUCTURE_KEYS,
    _canonical_json,
    _fingerprint,
    build_local_report,
    build_report,
    check_local_report,
)
from tests.integration.local_fast_fake_gateway import FakeGateway


def _local(backend: str, behaviour: str = "success") -> dict[str, Any]:
    with FakeGateway(backend=backend) as gateway:
        gateway.behaviour = behaviour
        report = build_local_report(backend, gateway.url, 5.0)
    return json.loads(_canonical_json(report))


def _structure(report: dict[str, Any], scenario: str) -> list[list[Any]]:
    return [
        [turn[key] for key in TURN_STRUCTURE_KEYS]
        for turn in report["scenarios"][scenario]["turns"]
    ]


@pytest.mark.parametrize("backend", ["distilled", "untuned"])
def test_a_local_report_keeps_the_scripted_structure_and_passes_its_check(
    backend: str, tmp_path: Path
) -> None:
    report = _local(backend)
    scripted = build_report()
    for scenario in ("demo_path", "dialogue_path"):
        assert _structure(report, scenario) == _structure(
            json.loads(_canonical_json(scripted)), scenario
        )
    assert report["gateway_identity"]["backend"] == backend
    assert report["adapter_mode"] == f"local_{backend}_" + (
        "candidate" if backend == "distilled" else "baseline"
    )
    dialogue = report["scenarios"]["dialogue_path"]["turns"]
    fast_turns = [turn for turn in dialogue if turn["fast_calls"]]
    calls = report["measured"]["dialogue_path"]["fast_calls"]
    assert len(calls) == len(fast_turns) == 7
    path = tmp_path / f"fast-slow-split-{backend}.json"
    path.write_text(_canonical_json(report), encoding="utf-8")
    assert check_local_report(backend, scripted, path) == ()


def test_a_failing_backend_changes_the_outcome_not_the_structure() -> None:
    report = _local("distilled", behaviour="invalid_output")
    turns = report["scenarios"]["dialogue_path"]["turns"]
    fast_turns = [turn for turn in turns if turn["fast_calls"]]
    assert {turn["fallback_cause"] for turn in fast_turns} == {"failure"}
    assert {turn["delivered"] for turn in fast_turns} == {"fallback"}
    scripted = json.loads(_canonical_json(build_report()))
    assert _structure(report, "dialogue_path") == _structure(scripted, "dialogue_path")


def _rewrite(report: dict[str, Any], path: Path) -> None:
    body = {key: value for key, value in report.items() if key != "report_fingerprint"}
    path.write_text(
        _canonical_json({**body, "report_fingerprint": _fingerprint(body)}),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("edit", "failure"),
    [
        (
            lambda r: r["measured"]["demo_path"]["fast_calls"][0].update(
                response_text="hello"
            ),
            "text_keys_present",
        ),
        (
            lambda r: r["scenarios"]["dialogue_path"]["turns"][2].update(
                {"class": "slow_then_fast", "slow_calls": 1}
            ),
            "dialogue_path_structure_differs_from_scripted",
        ),
        (
            lambda r: r["scenarios"]["dialogue_path"]["aggregates"].update(
                fast_model_line_rate=1.0, gate_fallback_rate=0.0
            ),
            "dialogue_path_aggregates",
        ),
        (
            lambda r: r["gateway_identity"].update(prompt_version="v5"),
            "gateway_identity",
        ),
        (lambda r: r.update(label="production"), "schema_or_labels"),
    ],
)
def test_the_local_check_catches_a_rewritten_report(
    tmp_path: Path, edit: Any, failure: str
) -> None:
    report = _local("distilled", behaviour="invalid_output")
    edit(report)
    path = tmp_path / "fast-slow-split-distilled.json"
    _rewrite(report, path)
    assert failure in check_local_report("distilled", build_report(), path)


def test_the_local_check_catches_a_stale_fingerprint(tmp_path: Path) -> None:
    report = _local("untuned")
    report["fast_timeout_s"] = 20.0
    path = tmp_path / "fast-slow-split-untuned.json"
    path.write_text(_canonical_json(report), encoding="utf-8")
    assert "fingerprint_or_encoding" in check_local_report(
        "untuned", build_report(), path
    )
