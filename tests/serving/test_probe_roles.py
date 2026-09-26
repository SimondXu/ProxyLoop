"""S0-ROOT-12 probe: selection, validity, metrics and abort on fake data only.

The probe runs through the real ``make_client`` adapters; the network is an
``httpx.MockTransport`` (``tests/support/mod_probe.py``).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from tests.support.mod_probe import (
    HEARD,
    KEY,
    FakeTeamRouter,
    set_env,
    write_probe_bundle,
)

from proxyloop.contract.bundle import read_bundle
from proxyloop.contract.llm import Usage
from proxyloop.slow import prompt as slow_prompt
from scripts.mod import probe_roles as pr

Json = dict[str, Any]
ACT_OK = json.dumps(
    {"private_summary": "ok", "calls": [{"tool": "wait", "seconds": 5}]}
)


def run_part(
    tmp_path: Path, part: str, fake: FakeTeamRouter, n: int = 4
) -> tuple[int, Json]:
    bundle = read_bundle(write_probe_bundle(tmp_path / "run"))
    out = tmp_path / f"{part}.json"
    code = asyncio.run(
        pr.run(bundle, part, pr.select(bundle, part, n), out, fake.transport())
    )
    return code, json.loads(out.read_text("utf-8"))


def test_violations_cover_the_act_schema():
    schema = slow_prompt.ACT.parameters
    assert pr.violations(json.loads(ACT_OK), schema) == []
    bad = {
        "private_summary": "x" * 10_000,
        "calls": [
            {"tool": "dance"},
            {"tool": "wait", "seconds": 99},
            {"tool": "wait", "seconds": True},
        ],
    }
    got = pr.violations(bad, schema)
    assert any("private_summary: longer" in v for v in got)
    assert "$.calls[0].tool: not in enum" in got
    assert "$.calls[1].seconds: out of range" in got
    assert "$.calls[2].seconds: not integer" in got
    assert pr.violations({"calls": []}, schema) == ["$.private_summary: missing"]
    with pytest.raises(ValueError, match="unsupported"):
        pr.violations("x", {"type": "string", "pattern": "a"})


def test_judge_slow_counts_zero_and_foreign_calls_invalid():
    from proxyloop.contract.llm import ToolCall

    assert pr.judge_slow(())["valid"] is False
    wrong = (ToolCall(call_id="a", name="other", arguments="{}"),)
    assert pr.judge_slow(wrong)["n_valid_calls"] == 0
    two = tuple(
        ToolCall(call_id=str(i), name="act", arguments=ACT_OK) for i in range(2)
    )
    assert pr.judge_slow(two) | {"invalid": []} == {
        "n_calls": 2,
        "n_valid_calls": 2,
        "valid": True,
        "invalid": [],
    }


def test_spread_is_deterministic_and_spans_the_session():
    picks = pr.spread(list(range(58)), 24)
    assert picks == pr.spread(list(range(58)), 24)
    assert len(set(picks)) == 24 and picks == sorted(picks)
    assert picks[0] < 58 // 6 and picks[-1] > 58 * 5 // 6
    assert pr.spread([1, 2], 5) == [1, 2]


def test_plan_makes_no_call_and_projects_recorded_tokens(
    tmp_path: Path, capsys: Any, monkeypatch: Any
):
    monkeypatch.delenv("PL_TEAMROUTER_API_KEY", raising=False)  # no client may be built
    run = write_probe_bundle(tmp_path / "run")
    assert pr.main(["--run", str(run), "--part", "ear", "--plan"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["calls"] == 4 * 4
    assert plan["projected_tokens_per_arm"]["prompt"] == 4 * 1000
    assert plan["projected_tokens_total"]["completion"] == 4 * 4 * 50
    assert plan["completion_bound_total"] == 16 * 512


def test_slow_part_measures_validity_per_arm(tmp_path: Path, monkeypatch: Any):
    set_env(monkeypatch)
    fake = FakeTeamRouter(
        tools=lambda b: [("act", ACT_OK)] if b.get("reasoning_effort") else []
    )
    code, out = run_part(tmp_path, "slow", fake)
    assert code == 0 and out["complete"] is True and out["aborted"] is None
    low, default = out["arms"]["low"], out["arms"]["default"]
    assert (low["valid_rate"], low["calls_per_response"]) == (1.0, {"1": 4})
    assert (default["valid_rate"], default["calls_per_response"]) == (0.0, {"0": 4})
    assert low["tokens"] == {
        "prompt": 400,
        "completion": 80,
        "reasoning": 28,
        "reasoning_unknown": 0,
        "records_without_usage": 0,
        "records": 4,
    }
    assert low["finish_reasons"] == {"tool_calls": 4}
    assert low["served_model_echo"] == ["gemini-3.8-flash"]
    assert low["reasoning_tokens_p50"] == 7 and default["reasoning_effort"] is None
    body = fake.requests[0]
    assert body["tool_choice"] == {"type": "function", "function": {"name": "act"}}
    assert body["max_tokens"] == slow_prompt.MAX_TOKENS and "temperature" not in body
    assert (
        body["reasoning_effort"] == "low" and "reasoning_effort" not in fake.requests[1]
    )
    assert {c["request_id"] for c in out["calls"]} == {f"req-{i}" for i in range(1, 9)}
    assert {c["served_model_echo"] for c in out["calls"]} == {"gemini-3.8-flash"}
    assert KEY not in json.dumps(out)


def test_ear_part_uses_check_act_and_agreement_with_default(
    tmp_path: Path, monkeypatch: Any
):
    set_env(monkeypatch)

    def answer(body: Json) -> list[tuple[str, str]]:
        effort = body.get("reasoning_effort")
        if effort == "none":  # a number the caller never said: check_act rejects it
            return [("classify", json.dumps({"act": "ask_discount", "price_usd": 9.0}))]
        act = "other" if effort == "minimal" else "ask_discount"
        return [("classify", json.dumps({"act": act}))]

    code, out = run_part(tmp_path, "ear", FakeTeamRouter(tools=answer))
    arms = out["arms"]
    assert code == 0 and "9" not in HEARD
    assert arms["none"]["valid_rate"] == 0.0 and arms["none"]["agreement_n"] == 0
    assert arms["minimal"]["agreement_with_default"] == 0.0
    assert (
        arms["low"]["agreement_with_default"] == 1.0 and arms["low"]["agreement_n"] == 4
    )
    assert out["calls"][0]["invalid"].startswith("price_usd")


def test_fast_part_streams_parses_and_records_rejections(
    tmp_path: Path, monkeypatch: Any
):
    set_env(monkeypatch)
    fake = FakeTeamRouter(text="Sure, one moment.\n@bogus")
    fake.status = lambda b: 400 if len(fake.requests) == 2 else 200  # continues
    code, out = run_part(tmp_path, "fast", fake)
    arm = out["arms"]["default"]
    assert code == 0 and out["complete"] is True
    assert (arm["n"], arm["n_ok"], arm["n_rejected"]) == (4, 3, 1)
    assert arm["rejections"] == ["EndpointError: HTTP 400: unsupported parameter 2"]
    assert arm["parse_issue_rate"] == 1.0
    assert arm["issues_by_reason"] == {"unknown_directive": 3}
    assert (
        arm["latency"]["relay_measured"] is True
        and arm["latency"]["ttft_ms_p50"] is not None
    )
    assert all(c["relay_measured"] for c in out["calls"] if not c["error"])
    body = fake.requests[0]
    assert (body["temperature"], body["top_p"], body["max_tokens"]) == (0.3, 0.9, 160)
    assert body["stream"] is True and body["model"] == "gpt-6-luna"
    assert "reasoning_effort" not in body and isinstance(body["seed"], int)
    lanes = [c["source"].split(":")[0] for c in out["calls"]]
    assert lanes == ["fast_user", "fast_user", "fast_cp", "fast_cp"]


def test_a_dead_endpoint_aborts_after_saving_finished_calls(
    tmp_path: Path, monkeypatch: Any
):
    set_env(monkeypatch)
    fake = FakeTeamRouter(tools=lambda b: [("act", ACT_OK)])
    fake.status = lambda b: 503 if len(fake.requests) == 3 else 200
    code, out = run_part(tmp_path, "slow", fake)
    assert code == 1 and out["complete"] is False and "HTTP 503" in out["aborted"]
    assert len(out["calls"]) == 3 and out["calls"][-1]["fatal"] is True
    assert len(fake.requests) == 3  # nothing after the failure, no retry


def test_unknown_usage_is_never_counted_as_zero(tmp_path: Path, monkeypatch: Any):
    """M1: a response without usage, or without reasoning tokens, is not a 0."""
    set_env(monkeypatch)
    fake = FakeTeamRouter(tools=lambda b: [("act", ACT_OK)])
    fake.usage_mode = lambda b: "none" if b.get("reasoning_effort") else "no_reasoning"
    _, out = run_part(tmp_path, "slow", fake)
    low, default = out["arms"]["low"]["tokens"], out["arms"]["default"]["tokens"]
    assert low["records_without_usage"] == 4
    assert low["prompt"] is None and low["reasoning"] is None
    assert (default["reasoning"], default["reasoning_unknown"]) == (None, 4)
    assert default["prompt"] == 400 and out["arms"]["default"]["reasoning_n"] == 0


def test_plan_keeps_unknown_recorded_reasoning_unknown(tmp_path: Path, capsys: Any):
    """M1 in --plan: vLLM-recorded Fast usage has no reasoning tokens."""
    usage = Usage(prompt_tokens=1000, completion_tokens=50)
    run = write_probe_bundle(tmp_path / "run", usage=usage)
    assert pr.main(["--run", str(run), "--part", "fast", "--plan"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["projected_tokens_per_arm"]["reasoning"] is None
    assert plan["projected_tokens_total"]["reasoning"] is None
    assert plan["projected_tokens_per_arm"]["reasoning_unknown"] == 8
    run = write_probe_bundle(tmp_path / "bare", usage=None)
    assert pr.main(["--run", str(run), "--part", "fast", "--plan"]) == 0
    per_arm = json.loads(capsys.readouterr().out)["projected_tokens_per_arm"]
    assert per_arm["records_without_usage"] == 8 and per_arm["prompt"] is None


def test_rejected_calls_stay_in_the_denominators(tmp_path: Path, monkeypatch: Any):
    """M2 (I10): 3 of 4 calls rejected; rates are over n, answered-only is named."""
    set_env(monkeypatch)
    fake = FakeTeamRouter(text="Sure, one moment.")
    fake.status = lambda b: 400 if len(fake.requests) <= 3 else 200
    _, out = run_part(tmp_path, "fast", fake)
    arm = out["arms"]["default"]
    assert (arm["n"], arm["n_ok"], arm["n_rejected"]) == (4, 1, 3)
    assert arm["parse_issue_rate"] == 0.75 and arm["parse_issue_rate_answered"] == 0.0
    assert arm["finish_reasons"] == {"None": 3, "stop": 1}

    fake = FakeTeamRouter(tools=lambda b: [("act", ACT_OK)])
    fake.status = lambda b: 400 if len(fake.requests) <= 6 else 200
    _, out = run_part(tmp_path, "slow", fake)
    low = out["arms"]["low"]  # items 0-2 rejected on both arms, item 3 answered
    assert (low["n"], low["valid_rate"], low["valid_rate_answered"]) == (4, 0.25, 1.0)
    assert low["tool_call_valid_rate_answered"] == 1.0


def test_arm_order_alternates_across_items(tmp_path: Path, monkeypatch: Any):
    """M3: no arm always runs second (implicit prefix caching)."""
    set_env(monkeypatch)
    fake = FakeTeamRouter(tools=lambda b: [("act", ACT_OK)])
    _, out = run_part(tmp_path, "slow", fake)
    efforts = [b.get("reasoning_effort", "default") for b in fake.requests]
    assert efforts == ["low", "default", "default", "low"] * 2
    assert "reversed on odd" in out["selection_rule"]


def test_an_unexpected_exception_is_recorded_saved_and_raised(
    tmp_path: Path, monkeypatch: Any
):
    """N2: a crash that is not LLMUnavailable still leaves the finished calls."""
    set_env(monkeypatch)

    def boom(body: Json) -> list[tuple[str, str]]:
        if len(fake.requests) == 2:
            raise RuntimeError("boom")
        return [("act", ACT_OK)]

    fake = FakeTeamRouter(tools=boom)
    with pytest.raises(RuntimeError, match="boom"):
        run_part(tmp_path, "slow", fake)
    out = json.loads((tmp_path / "slow.json").read_text("utf-8"))
    assert out["complete"] is False and "boom" in out["aborted"]
    assert len(out["calls"]) == 1
