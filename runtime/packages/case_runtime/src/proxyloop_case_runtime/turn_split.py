"""Per-turn Fast/Slow split of one Case, from its trace log and final state.

A **turn** is one applied command that appended a triggering visible event
(``TURN_TRIGGER_EVENT_TYPES``); the turn key is the trigger's event cursor.
Every other event type the Runtime emits is listed in ``NON_TURN_EVENT_TYPES``;
an event of any other type is refused, so a new type cannot fall through.

Traces join a turn by ``input_pins.event_cursor``: a Slow refresh and the Fast
call after it run on snapshots with the trigger's cursor. The log has no
command id, so attempts that share a cursor are resolved by log order, which
is call order:

- a trace at a cursor that is no applied trigger is an unapplied attempt;
- the turn's Fast call is the last Fast trace at its cursor (the delivered
  attempt), with the Slow trace immediately before it at that cursor, if any;
- a turn with no Fast trace (Case creation) has the first succeeded Slow
  trace at its cursor: a repeated ``create_case`` also traces a succeeded Slow
  call at that cursor before it conflicts;
- every other trace at an applied cursor is an unapplied attempt.

The split describes routing structure only. A refresh turn runs Slow before
Fast, sequentially; nothing here measures latency or model quality, and no
model text is read or emitted.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Literal

from proxyloop_contracts import ModelResult, ModelTrace

from .repository import CaseRuntimeState

TURN_TRIGGER_EVENT_TYPES: Final = frozenset(
    {"provider_offer", "consumer_message", "provider_message"}
)
NON_TURN_EVENT_TYPES: Final = frozenset(
    {"assistant_message", "approval_decision", "approval_expired", "provider_event"}
)
TURN_CLASSES: Final = ("slow_only", "fast_only", "slow_then_fast", "no_model")
FALLBACK_CAUSES: Final = ("gate", "failure")
_GATE_CODE_PREFIX = "fast_gate_"

TurnClass = Literal["slow_only", "fast_only", "slow_then_fast", "no_model"]


def fast_slow_split(
    traces: tuple[ModelTrace, ...], state: CaseRuntimeState
) -> dict[str, object]:
    """The per-turn records and deterministic aggregates for one Case."""

    for trace in traces:
        if trace.role not in {"fast", "slow"} or trace.input_pins is None:
            raise ValueError("a turn split needs Runtime Fast/Slow traces with pins")
    triggers = []
    for event in state.snapshot.visible_events:
        if event.event_type in TURN_TRIGGER_EVENT_TYPES:
            triggers.append(event)
        elif event.event_type not in NON_TURN_EVENT_TYPES:
            raise ValueError(f"unclassified event type: {event.event_type}")

    applied: set[int] = set()
    turns: list[dict[str, object]] = []
    for trigger in triggers:
        at_cursor = [
            index
            for index, trace in enumerate(traces)
            if _cursor(trace) == trigger.event_cursor
        ]
        calls = _turn_calls(traces, at_cursor)
        applied.update(calls)
        turns.append(
            _turn_record(
                trigger.event_cursor,
                trigger.event_type,
                [traces[index] for index in calls],
            )
        )
    return {
        "turns": turns,
        "aggregates": _aggregates(turns, traces, len(traces) - len(applied)),
    }


def _cursor(trace: ModelTrace) -> int:
    assert trace.input_pins is not None
    return trace.input_pins.event_cursor


def _turn_calls(traces: Sequence[ModelTrace], at_cursor: list[int]) -> list[int]:
    fast = [index for index in at_cursor if traces[index].role == "fast"]
    if fast:
        delivered = fast[-1]
        position = at_cursor.index(delivered)
        before = at_cursor[position - 1] if position > 0 else None
        if before is not None and traces[before].role == "slow":
            return [before, delivered]
        return [delivered]
    created = next(
        (index for index in at_cursor if traces[index].result is ModelResult.SUCCEEDED),
        None,
    )
    return [] if created is None else [created]


def _turn_record(
    cursor: int, trigger_event_type: str, calls: list[ModelTrace]
) -> dict[str, object]:
    slow_calls = sum(trace.role == "slow" for trace in calls)
    fast = next((trace for trace in calls if trace.role == "fast"), None)
    fast_calls = int(fast is not None)
    fallback_cause = _fallback_cause(fast)
    delivered = "none"
    reject_codes: list[str] = []
    if fast is not None:
        if fast.result is ModelResult.SUCCEEDED:
            delivered = "model"
        elif fallback_cause is not None:
            delivered = "fallback"
        if fast.result is ModelResult.REJECTED:
            reject_codes = list(fast.reason_codes or ())
    return {
        "turn": cursor,
        "trigger_event_type": trigger_event_type,
        "class": _turn_class(slow_calls, fast_calls),
        "slow_calls": slow_calls,
        "fast_calls": fast_calls,
        "fast_result": fast.result.value if fast is not None else None,
        "fallback_cause": fallback_cause,
        "delivered": delivered,
        "fast_reject_codes": reject_codes,
    }


def _fallback_cause(fast: ModelTrace | None) -> str | None:
    if fast is None:
        return None
    if fast.result is ModelResult.FAILED:
        return "failure"
    if _is_gate_reject(fast):
        return "gate"
    return None


def _is_gate_reject(trace: ModelTrace) -> bool:
    codes = trace.reason_codes or ()
    return (
        trace.role == "fast"
        and trace.result is ModelResult.REJECTED
        and bool(codes)
        and all(code.startswith(_GATE_CODE_PREFIX) for code in codes)
    )


def _turn_class(slow_calls: int, fast_calls: int) -> TurnClass:
    if slow_calls and fast_calls:
        return "slow_then_fast"
    if fast_calls:
        return "fast_only"
    if slow_calls:
        return "slow_only"
    return "no_model"


def _aggregates(
    turns: list[dict[str, object]],
    traces: tuple[ModelTrace, ...],
    unapplied: int,
) -> dict[str, object]:
    count = len(turns)
    by_class = {
        name: sum(turn["class"] == name for turn in turns) for name in TURN_CLASSES
    }
    dialogue = [turn for turn in turns if turn["fast_calls"]]
    fast_traces = [trace for trace in traces if trace.role == "fast"]
    histogram: dict[str, int] = {}
    for trace in fast_traces:
        if trace.result is ModelResult.REJECTED:
            for code in trace.reason_codes or ():
                histogram[code] = histogram.get(code, 0) + 1
    return {
        "turns": count,
        "turns_by_class": by_class,
        "fast_only_turn_share": _share(by_class["fast_only"], count),
        "slow_involved_turn_share": _share(
            sum(bool(turn["slow_calls"]) for turn in turns), count
        ),
        "dialogue_turns": len(dialogue),
        "fast_model_line_rate": _share(
            sum(turn["delivered"] == "model" for turn in dialogue), len(dialogue)
        ),
        "fast_fallback_rate": _share(
            sum(_is_gate_reject(trace) for trace in fast_traces), len(fast_traces)
        ),
        "fallback_cause_counts": {
            cause: sum(turn["fallback_cause"] == cause for turn in turns)
            for cause in FALLBACK_CAUSES
        },
        "calls_by_role_and_result": {
            role: {
                result.value: sum(
                    trace.role == role and trace.result is result for trace in traces
                )
                for result in ModelResult
            }
            for role in ("fast", "slow")
        },
        "fast_reject_reason_histogram": dict(sorted(histogram.items())),
        "unapplied_model_calls": unapplied,
    }


def _share(part: int, whole: int) -> float:
    return round(part / whole, 6) if whole else 0.0


__all__ = [
    "FALLBACK_CAUSES",
    "NON_TURN_EVENT_TYPES",
    "TURN_CLASSES",
    "TURN_TRIGGER_EVENT_TYPES",
    "fast_slow_split",
]
