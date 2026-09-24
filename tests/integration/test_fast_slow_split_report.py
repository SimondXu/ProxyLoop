"""The per-turn Fast/Slow split (S1-S3) and its committed scripted report."""

from __future__ import annotations

import inspect
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from proxyloop_agent_core import BOUNDED_FAST_STATUS_TEXT, SCRIPTED_DIALOGUE_LINES
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseRuntimeState,
    ThinAgentRuntime,
)
from proxyloop_case_runtime import runtime as runtime_module
from proxyloop_case_runtime.turn_split import (
    NON_TURN_EVENT_TYPES,
    TURN_TRIGGER_EVENT_TYPES,
    fast_slow_split,
)
from proxyloop_contracts import ModelResult, ModelTrace

from scripts.run_fast_slow_split_report import (
    REPORT_PATH,
    build_report,
    check_report,
    run_demo_path,
    run_dialogue_path,
    write_report,
)

T0 = datetime(2035, 1, 1, tzinfo=UTC)


def _run(runtime: ThinAgentRuntime) -> tuple[tuple[ModelTrace, ...], CaseRuntimeState]:
    state = runtime.repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    return runtime.repository.list_model_traces(SCRIPTED_CASE_ID), state


def _as(trace: ModelTrace, result: ModelResult, *codes: str) -> ModelTrace:
    return trace.model_copy(update={"result": result, "reason_codes": codes})


def _at(trace: ModelTrace, cursor: int) -> ModelTrace:
    assert trace.input_pins is not None
    pins = trace.input_pins.model_copy(update={"event_cursor": cursor})
    return trace.model_copy(update={"input_pins": pins})


def _turn(split: dict[str, Any], cursor: int) -> dict[str, Any]:
    return next(turn for turn in split["turns"] if turn["turn"] == cursor)


def _roles(traces: tuple[ModelTrace, ...]) -> list[str | None]:
    return [trace.role for trace in traces]


# S1 The pure split.
def test_s1_classes_on_the_scripted_dialogue_path() -> None:
    traces, state = _run(run_dialogue_path())
    split = fast_slow_split(traces, state)
    assert [turn["class"] for turn in split["turns"]] == [
        "slow_only",
        "slow_then_fast",
        "fast_only",
        "fast_only",
        "fast_only",
        "fast_only",
        "slow_then_fast",
        "fast_only",
    ]
    aggregates = split["aggregates"]
    assert aggregates["unapplied_model_calls"] == 0
    assert aggregates["dialogue_turns"] == 7
    assert aggregates["slow_involved_turn_share"] == 0.375


def test_s1_a_repeated_create_case_is_an_unapplied_attempt() -> None:
    # M7: the repeated create traces a succeeded Slow call (and its Judge
    # call) at cursor 1, then conflicts. It is not a second Slow call of the
    # creation turn.
    traces, state = _run(run_demo_path())
    assert _roles(traces) == ["slow", "judge", "slow", "judge", "fast"]
    assert [trace.result for trace in traces[:4]] == [ModelResult.SUCCEEDED] * 4
    split = fast_slow_split(traces, state)
    assert _turn(split, 1) == {
        "turn": 1,
        "trigger_event_type": "provider_offer",
        "class": "slow_only",
        "slow_calls": 1,
        "fast_calls": 0,
        "fast_result": None,
        "fallback_cause": None,
        "delivered": "none",
        "fast_reject_codes": [],
        "judge_calls": 1,
        "slow_retry": None,
    }
    aggregates = split["aggregates"]
    assert aggregates["unapplied_model_calls"] == 1
    assert aggregates["unapplied_judge_calls_by_result"]["succeeded"] == 1
    assert aggregates["calls_by_role_and_result"]["slow"]["succeeded"] == 1
    assert aggregates["unapplied_calls_by_role_and_result"]["slow"]["succeeded"] == 1


def test_s1_the_last_fast_trace_at_a_cursor_is_the_delivered_attempt() -> None:
    traces, state = _run(run_dialogue_path())
    # A fast_only turn: a failed attempt there has no Slow call either.
    fast = next(
        trace
        for trace in traces
        if trace.role == "fast"
        and trace.input_pins is not None
        and trace.input_pins.event_cursor == 4
    )
    failed_attempt = _as(fast, ModelResult.REJECTED, "stale_fast_result")
    index = traces.index(fast)
    replayed = (*traces[:index], failed_attempt, *traces[index:])
    split = fast_slow_split(replayed, state)
    assert fast.input_pins is not None
    turn = _turn(split, fast.input_pins.event_cursor)
    assert (turn["fast_calls"], turn["fast_result"], turn["delivered"]) == (
        1,
        "succeeded",
        "model",
    )
    aggregates = split["aggregates"]
    assert aggregates["unapplied_model_calls"] == 1
    # The failed attempt is reported apart from the applied calls.
    assert aggregates["fast_reject_reason_histogram"] == {}
    assert aggregates["unapplied_fast_reject_reason_histogram"] == {
        "stale_fast_result": 1
    }
    assert aggregates["unapplied_calls_by_role_and_result"]["fast"]["rejected"] == 1
    # A validation reject is not a fallback.
    assert aggregates["gate_fallback_rate"] == 0.0


def test_s1_a_retried_refresh_keeps_only_the_delivered_slow_call() -> None:
    traces, state = _run(run_dialogue_path())
    slow_index = next(
        index
        for index, trace in enumerate(traces)
        if trace.role == "slow"
        and trace.input_pins
        and trace.input_pins.event_cursor > 1
    )
    slow, judge, fast = traces[slow_index : slow_index + 3]
    assert (judge.role, fast.role) == ("judge", "fast")
    retried = (
        *traces[:slow_index],
        slow,
        judge,
        _as(fast, ModelResult.REJECTED, "stale_fast_result"),
        *traces[slow_index:],
    )
    split = fast_slow_split(retried, state)
    assert fast.input_pins is not None
    turn = _turn(split, fast.input_pins.event_cursor)
    assert (turn["class"], turn["slow_calls"], turn["fast_calls"]) == (
        "slow_then_fast",
        1,
        1,
    )
    assert turn["judge_calls"] == 1
    assert split["aggregates"]["unapplied_model_calls"] == 2
    assert split["aggregates"]["unapplied_judge_calls_by_result"]["succeeded"] == 1


@pytest.mark.parametrize(
    ("result", "codes", "cause"),
    [
        (
            ModelResult.REJECTED,
            ("fast_gate_commitment", "fast_gate_number_not_allowed"),
            "gate",
        ),
        (ModelResult.FAILED, (), "failure"),
    ],
)
def test_s1_a_fallback_turn_records_its_cause_and_no_text(
    result: ModelResult, codes: tuple[str, ...], cause: str
) -> None:
    traces, state = _run(run_demo_path())
    delivered = _as(traces[-1], result, *codes)
    split = fast_slow_split((*traces[:-1], delivered), state)
    turn = _turn(split, 2)
    assert turn["fast_result"] == result.value
    assert turn["fallback_cause"] == cause
    assert turn["delivered"] == "fallback"
    assert turn["fast_reject_codes"] == list(codes)
    aggregates = split["aggregates"]
    assert aggregates["fallback_cause_counts"] == {
        "gate": int(cause == "gate"),
        "failure": int(cause == "failure"),
    }
    assert aggregates["gate_fallback_rate"] == (1.0 if cause == "gate" else 0.0)
    assert aggregates["fast_reject_reason_histogram"] == dict.fromkeys(codes, 1)
    assert aggregates["fast_model_line_rate"] == 0.0


def test_s1_a_trace_at_a_non_trigger_cursor_is_unapplied() -> None:
    traces, state = _run(run_demo_path())
    # Cursor 3 is the assistant line of turn 2, never a trigger.
    split = fast_slow_split((*traces, _at(traces[-1], 3)), state)
    assert split["aggregates"]["unapplied_model_calls"] == 2
    assert _turn(split, 2)["fast_calls"] == 1


def test_s1_a_trigger_without_traces_is_no_model() -> None:
    _, state = _run(run_demo_path())
    split = fast_slow_split((), state)
    assert split["aggregates"]["turns_by_class"]["no_model"] == 2


def test_s1_an_unclassified_event_type_is_refused() -> None:
    _, state = _run(run_demo_path())
    event = state.snapshot.visible_events[-1].model_copy(
        update={"event_type": "surprise_event"}
    )
    snapshot = state.snapshot.model_copy(
        update={"visible_events": (*state.snapshot.visible_events[:-1], event)}
    )
    state = CaseRuntimeState(
        snapshot=snapshot,
        events=state.events,
        provider=state.provider,
        execution_count=state.execution_count,
        execution_source_pins=state.execution_source_pins,
        execution_intent=state.execution_intent,
        execution_approval=state.execution_approval,
        execution_proposal=state.execution_proposal,
        transitions=state.transitions,
        execution_claim=state.execution_claim,
    )
    with pytest.raises(ValueError, match="unclassified event type"):
        fast_slow_split((), state)


# S4 The Judge (PR-14): its calls are counted apart and never in a share.
def _judge(
    slow: ModelTrace, *codes: str, result: ModelResult = ModelResult.SUCCEEDED
) -> ModelTrace:
    return slow.model_copy(
        update={
            "role": "judge",
            "result": result,
            "reason_codes": codes or ("judge_accept",),
            "output_ref": None,
            "output_schema_version": "judge-verdict-v1",
        }
    )


def _refresh_turn(
    build: Any,
) -> tuple[dict[str, Any], int]:
    """The dialogue path with its first refresh turn's calls rebuilt."""

    traces, state = _run(run_dialogue_path())
    plain = [trace for trace in traces if trace.role != "judge"]
    slow_index = next(
        index
        for index, trace in enumerate(plain)
        if trace.role == "slow"
        and trace.input_pins
        and trace.input_pins.event_cursor > 1
    )
    slow, fast = plain[slow_index], plain[slow_index + 1]
    assert fast.role == "fast" and fast.input_pins is not None
    rebuilt = (*plain[:slow_index], *build(slow, fast), *plain[slow_index + 2 :])
    return fast_slow_split(rebuilt, state), fast.input_pins.event_cursor


def test_s4_split_counts_judge_calls_apart() -> None:
    split, cursor = _refresh_turn(lambda slow, fast: (slow, _judge(slow), fast))
    turn = _turn(split, cursor)
    assert (turn["class"], turn["slow_calls"], turn["fast_calls"]) == (
        "slow_then_fast",
        1,
        1,
    )
    assert (turn["judge_calls"], turn["slow_retry"]) == (1, None)
    aggregates = split["aggregates"]
    assert set(aggregates["calls_by_role_and_result"]) == {"fast", "slow"}
    assert aggregates["judge_calls_by_result"] == {
        "failed": 0,
        "rejected": 0,
        "succeeded": 1,
    }
    assert aggregates["slow_retry_counts"] == {"admitted": 0, "rejected": 0}
    assert aggregates["unapplied_model_calls"] == 0
    assert aggregates["slow_involved_turn_share"] == 0.375


@pytest.mark.parametrize(
    ("retry_result", "outcome"),
    [(ModelResult.SUCCEEDED, "admitted"), (ModelResult.REJECTED, "rejected")],
)
def test_s4_a_slow_retry_after_a_revise_belongs_to_the_turn(
    retry_result: ModelResult, outcome: str
) -> None:
    def build(slow: ModelTrace, fast: ModelTrace) -> tuple[ModelTrace, ...]:
        revise = _judge(slow, "judge_revise", "judge_premature_give_up")
        return (slow, revise, _as(slow, retry_result, "slow_result_current"), fast)

    split, cursor = _refresh_turn(build)
    turn = _turn(split, cursor)
    assert (turn["slow_calls"], turn["judge_calls"], turn["slow_retry"]) == (
        2,
        1,
        outcome,
    )
    aggregates = split["aggregates"]
    assert aggregates["slow_retry_counts"] == {
        "admitted": int(outcome == "admitted"),
        "rejected": int(outcome == "rejected"),
    }
    assert aggregates["unapplied_model_calls"] == 0


def test_s4_a_slow_after_an_accept_starts_a_new_attempt() -> None:
    # Create, then a repeated create at the same cursor: two groups.
    traces, state = _run(run_demo_path())
    plain = [trace for trace in traces if trace.role != "judge"]
    first, again, fast = plain
    split = fast_slow_split((first, _judge(first), again, _judge(again), fast), state)
    turn = _turn(split, 1)
    assert (turn["slow_calls"], turn["judge_calls"], turn["slow_retry"]) == (
        1,
        1,
        None,
    )
    aggregates = split["aggregates"]
    assert aggregates["unapplied_model_calls"] == 1
    assert aggregates["unapplied_judge_calls_by_result"]["succeeded"] == 1
    assert aggregates["judge_calls_by_result"]["succeeded"] == 1


def test_s4_an_orphan_judge_trace_is_refused() -> None:
    with pytest.raises(ValueError, match="orphan judge trace"):
        _refresh_turn(lambda slow, fast: (_judge(slow), fast))


# S2 Every emitted event type is classified.
def _emitted_event_types() -> set[str]:
    runtime = ThinAgentRuntime(clock=lambda: T0 + timedelta(hours=2))
    runtime.create_case(occurred_at=T0)
    waiting = runtime.append_event(
        SCRIPTED_CASE_ID, content="Review.", occurred_at=T0 + timedelta(minutes=1)
    )
    assert waiting.approval is not None
    runtime.expire_approval(
        SCRIPTED_CASE_ID,
        waiting.approval.approval_id,
        expected_revision=waiting.snapshot.revision,
        expires_at=waiting.approval.expires_at,
        command_id=SCRIPTED_CASE_ID,
    )
    types: set[str] = set()
    for scenario in (run_demo_path(), run_dialogue_path(), runtime):
        _, state = _run(scenario)
        types.update(event.event_type for event in state.snapshot.visible_events)
    return types


def test_s2_every_emitted_event_type_is_classified() -> None:
    assert not TURN_TRIGGER_EVENT_TYPES & NON_TURN_EVENT_TYPES
    classified = TURN_TRIGGER_EVENT_TYPES | NON_TURN_EVENT_TYPES
    emitted = _emitted_event_types()
    assert emitted == {
        "provider_offer",
        "consumer_message",
        "assistant_message",
        "approval_decision",
        "approval_expired",
    }
    # Every literal event type in the Runtime source, including the channel
    # path's provider_message and provider_event.
    source = inspect.getsource(runtime_module)
    literals = set(re.findall(r'event_type="([a-z_]+)"', source))
    assert literals >= {"provider_message", "provider_event", "provider_offer"}
    assert emitted | literals <= classified


# S3 The committed report.
def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in _keys(child)}
    if isinstance(value, list):
        return {key for child in value for key in _keys(child)}
    return set()


def test_s3_the_committed_report_is_current_and_deterministic() -> None:
    assert check_report(REPORT_PATH) == ()
    assert build_report() == build_report()
    text = REPORT_PATH.read_text(encoding="utf-8")
    report = json.loads(text)
    assert not [key for key in _keys(report) if "latency" in key or key.endswith("_ms")]
    for line in (BOUNDED_FAST_STATUS_TEXT, *SCRIPTED_DIALOGUE_LINES):
        assert line not in text
    assert report["schema_version"] == "fast-slow-split-v2"
    assert report["fast_backend"] == "scripted_dialogue"
    assert report["judge_backend"] == "scripted_judge"
    # No verdict distribution is reported (decision 7).
    assert not [key for key in _keys(report) if "verdict" in key]
    assert report["fast_gate_version"] == "fast-gate-v1"
    assert report["unicode_data_version"] == "15.0.0"


def test_s3_the_report_meets_the_acceptance_values() -> None:
    # AC5
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    demo = report["scenarios"]["demo_path"]["aggregates"]
    dialogue = report["scenarios"]["dialogue_path"]["aggregates"]
    assert demo["turns_by_class"] == {
        "slow_only": 1,
        "fast_only": 1,
        "slow_then_fast": 0,
        "no_model": 0,
    }
    assert demo["unapplied_model_calls"] == 1
    assert dialogue["turns_by_class"]["slow_then_fast"] >= 1
    # PR-14: one Judge call per admitted Slow call, none of them a revise on
    # the default Slow, so no retry.
    assert demo["judge_calls_by_result"]["succeeded"] == 1
    assert demo["unapplied_judge_calls_by_result"]["succeeded"] == 1
    assert dialogue["judge_calls_by_result"]["succeeded"] == 3
    for aggregates in (demo, dialogue):
        assert aggregates["slow_retry_counts"] == {"admitted": 0, "rejected": 0}
        assert aggregates["gate_fallback_rate"] == 0.0
        assert aggregates["fallback_cause_counts"] == {"gate": 0, "failure": 0}
    for scenario in report["scenarios"].values():
        for turn in scenario["turns"]:
            assert turn["fallback_cause"] is None
            assert turn["fast_result"] in {"succeeded", None}


def test_s3_check_fails_on_a_tampered_report(tmp_path: Path) -> None:
    path = tmp_path / "split.json"
    write_report(path)
    assert check_report(path) == ()
    assert path.read_bytes() == REPORT_PATH.read_bytes()
    report = json.loads(path.read_text(encoding="utf-8"))
    report["scenarios"]["demo_path"]["aggregates"]["turns"] = 3
    path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    assert check_report(path) == ("fast_slow_split_report_drift",)
