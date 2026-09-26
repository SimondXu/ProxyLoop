"""``pl.report/1`` (DOCS §4): generated from bundles only, errors in every
denominator, not-computable metrics named, latency labelled by endpoint."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.contract.samples import SONNET
from tests.eval.streams import Stream, fact, speech

from proxyloop.contract import CONTRACT_VERSION
from proxyloop.eval.report import build_report, evidence_sha


def _ok(run_dir: Path, recalled: bool, reason: str = "info_only") -> Path:
    s = Stream()
    msg = s.user_says("I am Dana.", name="Dana")
    s.fast("user", msg, [speech("Hi."), fact(("n", "Dana" if recalled else "Eve"))])
    s.charge("slow", "tokens", 1_000_000, "relay")
    return s.write(run_dir, reason)


def _report(tmp_path: Path) -> dict[str, Any]:
    c2 = [_ok(tmp_path / f"c2-{i}", recalled=i < 3) for i in range(4)]
    c4 = [_ok(tmp_path / "c4-0", True), _ok(tmp_path / "c4-1", True, "llm_unavailable")]
    (tmp_path / "c4-2").mkdir()  # a crashed run left no readable bundle
    bundles = {"C2": c2, "C4": [*c4, tmp_path / "c4-2"]}
    return build_report("r1", "spec", bundles, git_sha="abc", seed=1, resamples=200)


def test_the_report_has_the_pl_report_1_shape(tmp_path: Path) -> None:
    report = _report(tmp_path)
    assert set(report) == {  # exactly DOCS §4.1; the name pl.report/1 is the shape
        "report_id",
        "git_sha",
        "contract_version",
        "spec_hash",
        "bundles",
        "tables",
        "generated_at",
    }
    assert report["contract_version"] == CONTRACT_VERSION
    for table in report["tables"].values():
        assert set(table) == {"columns", "rows", "n", "ci"}
    json.dumps(report)  # serialisable as is
    assert len(report["bundles"]) == 7
    assert report["bundles"][0] == {
        "run_id": "run-s",
        "evidence_sha": evidence_sha(tmp_path / "c2-0"),
    }


def test_prereg_hash_is_present_only_when_given(tmp_path: Path) -> None:
    run = _ok(tmp_path / "a", True)
    report = build_report("r", "s", {"C2": [run]}, git_sha="g", prereg_hash="p")
    assert report["prereg_hash"] == "p"


def test_errors_stay_in_every_denominator(tmp_path: Path) -> None:
    outcome = _report(tmp_path)["tables"]["outcome"]
    c4 = outcome["rows"]["C4"]
    assert outcome["n"]["C4"] == 3 and c4["errors"] == 2
    assert c4["error_rate"] == pytest.approx(2 / 3)
    assert (
        outcome["ci"]["C4"]["error_rate"][0]
        < 2 / 3
        < outcome["ci"]["C4"]["error_rate"][1]
    )
    # success is unknown on the clean episode, so the rate is not computable
    assert c4["success"] is None and outcome["rows"]["C2"]["success"] is None


def test_pooled_rates_carry_cluster_bootstrap_intervals(tmp_path: Path) -> None:
    outcome = _report(tmp_path)["tables"]["outcome"]
    c2 = outcome["rows"]["C2"]
    assert c2["relay_recall"] == pytest.approx(3 / 4)
    lo, hi = outcome["ci"]["C2"]["relay_recall"]
    assert 0 <= lo <= 3 / 4 <= hi <= 1


def test_not_computable_metrics_are_listed_with_reasons(tmp_path: Path) -> None:
    table = _report(tmp_path)["tables"]["not_computable"]
    assert "acceptable_outcomes" in table["rows"]["success"]["reason"]
    assert "S2" in table["rows"]["harm_realised"]["reason"]
    assert "speech clock" in table["rows"]["latency.cp.time_to_heard"]["reason"]


def test_latency_rows_name_their_endpoint(tmp_path: Path) -> None:
    latency = _report(tmp_path)["tables"]["latency"]
    assert set(latency["rows"]) == {
        "C2|user|self-hosted (vllm)",
        "C4|user|self-hosted (vllm)",
    }
    row = latency["rows"]["C2|user|self-hosted (vllm)"]
    assert row["ttft_p50"] == 60 and latency["n"]["C2|user|self-hosted (vllm)"] == 4


def test_hosted_latency_is_labelled_relay_measured(tmp_path: Path) -> None:
    s = Stream()
    s.fast("user", s.user_says("Hi."), [speech("Hello.")], ref=SONNET)
    report = build_report("r", "s", {"C4": [s.write(tmp_path / "x")]}, git_sha="g")
    assert list(report["tables"]["latency"]["rows"]) == [
        "C4|user|relay-measured (relay)"
    ]


def test_cost_is_per_episode_by_role(tmp_path: Path) -> None:
    cost = _report(tmp_path)["tables"]["cost"]
    assert cost["rows"]["C2|slow"]["usd_per_episode"] == pytest.approx(1.0)
    assert cost["rows"]["C2|slow"]["unpriced_calls"] == 0
