"""The local Fast/Slow split reports (PR-9b, P2) against 9a's fake gateway.

The real reports need the MLX gateway and run by hand; CI checks their
integrity (``--check``) and, here, that the local mode keeps the scripted turn
structure, carries no text, and that the integrity check catches edits.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from proxyloop_agent_core import ModelIdentity, ScriptedJudgeAdapter
from proxyloop_case_runtime import ThinAgentRuntime

import scripts.run_fast_slow_split_report as split_report
from scripts.run_fast_slow_split_report import (
    TURN_STRUCTURE_KEYS,
    _canonical_json,
    _fingerprint,
    build_local_report,
    build_report,
    canonical_sha256,
    check_local_report,
    local_report_path,
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
    # PR-14: a local report written now carries the Judge's calls, apart.
    assert report["schema_version"] == "fast-slow-split-local-v2"
    demo = report["scenarios"]["demo_path"]
    assert demo["turns"][0]["judge_calls"] == 1
    assert demo["aggregates"]["judge_calls_by_result"]["succeeded"] == 1
    assert report["adapter_mode"] == f"local_{backend}_" + (
        "candidate" if backend == "distilled" else "baseline"
    )
    dialogue = report["scenarios"]["dialogue_path"]["turns"]
    fast_turns = [turn for turn in dialogue if turn["fast_calls"]]
    calls = report["measured"]["dialogue_path"]["fast_calls"]
    assert len(calls) == len(fast_turns) == 7
    path = tmp_path / f"fast-slow-split-{backend}.json"
    path.write_text(_canonical_json(report), encoding="utf-8")
    identity = report["gateway_identity"]
    assert check_local_report(backend, scripted, path, identity) == ()
    # A fake gateway's report is not the attested backend's.
    assert check_local_report(backend, scripted, path) == (
        "gateway_identity_not_attested",
    )


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
    identity = copy.deepcopy(report["gateway_identity"])
    edit(report)
    path = tmp_path / "fast-slow-split-distilled.json"
    _rewrite(report, path)
    assert failure in check_local_report("distilled", build_report(), path, identity)


def test_the_local_check_catches_a_stale_fingerprint(tmp_path: Path) -> None:
    report = _local("untuned")
    report["fast_timeout_s"] = 20.0
    path = tmp_path / "fast-slow-split-untuned.json"
    path.write_text(_canonical_json(report), encoding="utf-8")
    assert "fingerprint_or_encoding" in check_local_report(
        "untuned", build_report(), path, report["gateway_identity"]
    )


def _committed(backend: str) -> dict[str, Any]:
    report: dict[str, Any] = json.loads(
        local_report_path(backend).read_text(encoding="utf-8")
    )
    return report


@pytest.mark.parametrize("backend", ["distilled", "untuned"])
def test_the_committed_local_reports_carry_the_attested_identity(
    backend: str,
) -> None:
    assert check_local_report(backend, build_report()) == ()


@pytest.mark.parametrize("backend", ["distilled", "untuned"])
def test_the_committed_local_reports_predate_the_judge(backend: str) -> None:
    # PR-14 / review M6: observed before the Judge, kept at v1, never
    # rewritten; their Fast/Slow structure still equals the v2 scripted one.
    report = _committed(backend)
    assert report["schema_version"] == "fast-slow-split-local-v1"
    for scenario in report["scenarios"].values():
        assert all("judge_calls" not in turn for turn in scenario["turns"])
        assert "judge_calls_by_result" not in scenario["aggregates"]


class _OtherJudge(ScriptedJudgeAdapter):
    model_identity = ModelIdentity("scripted", "other_judge", "x", "x", "x")


class _OtherJudgeRuntime(ThinAgentRuntime):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, judge=_OtherJudge(), **kwargs)


def test_a_local_run_refuses_a_judge_that_is_not_the_scripted_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Review M6: the local mode checks the Judge traces' model too.
    monkeypatch.setattr(split_report, "ThinAgentRuntime", _OtherJudgeRuntime)
    with pytest.raises(RuntimeError, match="not from the scripted Judge"):
        _local("distilled")


def _reidentify(report: dict[str, Any]) -> None:
    """A self-consistent identity that is not the attested one."""

    identity = report["gateway_identity"]
    identity["adapter_fingerprint"] = "a" * 64
    body = {
        key: value for key, value in identity.items() if key != "identity_fingerprint"
    }
    identity["identity_fingerprint"] = canonical_sha256(body)


def _time_out_a_call(report: dict[str, Any]) -> None:
    report["measured"]["dialogue_path"]["fast_calls"][3]["outcome"] = (
        "fast_adapter_timeout"
    )


def _drop_a_call(report: dict[str, Any]) -> None:
    calls = report["measured"]["dialogue_path"]["fast_calls"]
    report["measured"]["dialogue_path"]["fast_calls"] = calls[:-1]


def _edit_the_max(report: dict[str, Any]) -> None:
    report["measured"]["demo_path"]["fast_call_ms"]["max"] = 1


def _move_a_call(report: dict[str, Any]) -> None:
    report["measured"]["dialogue_path"]["fast_calls"][0]["turn"] = 99


@pytest.mark.parametrize(
    ("tamper", "failure"),
    [
        (_reidentify, "gateway_identity_not_attested"),
        (_time_out_a_call, "dialogue_path_measured_inconsistent"),
        (_drop_a_call, "dialogue_path_measured_inconsistent"),
        (_edit_the_max, "demo_path_measured_inconsistent"),
        (_move_a_call, "dialogue_path_measured_inconsistent"),
    ],
)
def test_the_local_check_binds_identity_and_measured_calls(
    tmp_path: Path, tamper: Any, failure: str
) -> None:
    report = _committed("distilled")
    tamper(report)
    path = tmp_path / "fast-slow-split-distilled.json"
    _rewrite(report, path)
    failures = check_local_report("distilled", build_report(), path)
    assert failure in failures
    assert "fingerprint_or_encoding" not in failures
