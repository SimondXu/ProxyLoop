"""Per-turn Fast/Slow split of one Case, from its trace log and final state.

A **turn** is one applied command that appended a triggering visible event
(``TURN_TRIGGER_EVENT_TYPES``); the turn key is the trigger's event cursor.
Every other event type the Runtime emits is listed in ``NON_TURN_EVENT_TYPES``;
an event of any other type is refused, so a new type cannot fall through.

Traces join a turn by ``input_pins.event_cursor``: a Slow refresh, its Judge
call and Slow retry (PR-14), and the Fast call after them run on snapshots
with the trigger's cursor. The log has no command id, so attempts that share a
cursor are resolved by log order. Log order is call order within one process
(the Case lane and the API's direct lock serialize a Case's commands); across
processes it is not guaranteed, so a concurrent losing attempt at the same
cursor can be mistaken for the delivered one (spec risk R6; an exact join
needs a command id on the trace).

The traces at one cursor parse, in log order, into attempts. A Slow group is
``S [J [S']]``: a Judge trace follows the group's succeeded first Slow call
(anything else is an orphan and is refused), and a Slow call directly after a
Judge trace whose first code is ``judge_revise`` is that group's retry unless
a Judge trace follows it: a retry is never judged, so a judged Slow call there
is a new attempt (a Slow adapter without the feedback protocol is not retried,
and a repeated command then starts its own group). Any other Slow call starts
a new group. An attempt is a group, a group followed directly by its Fast
call, or a lone Fast call.

Known limit: a new attempt's Slow call that the coordinator rejects, logged
right after a ``revise`` that was not retried, is not judged either, so it is
indistinguishable from a rejected retry and is counted as one.

- a trace at a cursor that is no applied trigger is an unapplied attempt;
- the delivered attempt is the one holding the last Fast trace at the cursor;
- a turn with no Fast trace (Case creation) has the first attempt whose Slow
  call succeeded: a repeated ``create_case`` also traces a succeeded Slow
  call (and its Judge call) at that cursor before it conflicts;
- every other trace at an applied cursor is an unapplied attempt.

Aggregates count applied calls only; unapplied attempts are reported
separately (``unapplied_*``). Judge calls are counted apart and never enter a
Fast or Slow count or share (decision 7); a verdict is read only to recognise
a retry, and no verdict is reported. The split describes routing structure
only. A refresh turn runs Slow before Fast, sequentially; nothing here
measures latency or model quality, and no model text is read or emitted.
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
SLOW_RETRY_OUTCOMES: Final = ("admitted", "rejected")
_GATE_CODE_PREFIX = "fast_gate_"
_JUDGE_REVISE_CODE = "judge_revise"
_ROLES = frozenset({"fast", "slow", "judge"})

TurnClass = Literal["slow_only", "fast_only", "slow_then_fast", "no_model"]


def fast_slow_split(
    traces: tuple[ModelTrace, ...], state: CaseRuntimeState
) -> dict[str, object]:
    """The per-turn records and deterministic aggregates for one Case."""

    for trace in traces:
        if trace.role not in _ROLES or trace.input_pins is None:
            raise ValueError(
                "a turn split needs Runtime Fast/Slow/Judge traces with pins"
            )
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
        "aggregates": _aggregates(
            turns,
            [trace for index, trace in enumerate(traces) if index in applied],
            [trace for index, trace in enumerate(traces) if index not in applied],
        ),
    }


def _cursor(trace: ModelTrace) -> int:
    assert trace.input_pins is not None
    return trace.input_pins.event_cursor


def _turn_calls(traces: Sequence[ModelTrace], at_cursor: list[int]) -> list[int]:
    attempts = _attempts(traces, at_cursor)
    with_fast = [
        attempt
        for attempt in attempts
        if any(traces[index].role == "fast" for index in attempt)
    ]
    if with_fast:
        return with_fast[-1]
    created = next(
        (
            attempt
            for attempt in attempts
            if traces[attempt[0]].role == "slow"
            and traces[attempt[0]].result is ModelResult.SUCCEEDED
        ),
        None,
    )
    return [] if created is None else created


def _attempts(traces: Sequence[ModelTrace], at_cursor: list[int]) -> list[list[int]]:
    """The attempts at one cursor, in log order (see the module docstring)."""

    attempts: list[list[int]] = []
    current: list[int] | None = None  # the open attempt, until its Fast call
    for position, index in enumerate(at_cursor):
        trace = traces[index]
        if trace.role == "judge":
            if (
                current is None
                or len(current) != 1
                or traces[current[0]].role != "slow"
                or traces[current[0]].result is not ModelResult.SUCCEEDED
            ):
                raise ValueError("orphan judge trace")
            current.append(index)
        elif trace.role == "slow":
            judged = (
                position + 1 < len(at_cursor)
                and traces[at_cursor[position + 1]].role == "judge"
            )
            if (
                current is not None
                and len(current) == 2
                and _is_revise(traces[current[1]])
                and not judged
            ):
                current.append(index)
            else:
                current = [index]
                attempts.append(current)
        elif current is not None:
            current.append(index)
            current = None
        else:
            attempts.append([index])
    return attempts


def _is_revise(trace: ModelTrace) -> bool:
    codes = trace.reason_codes or ()
    return (
        trace.role == "judge"
        and trace.result is ModelResult.SUCCEEDED
        and bool(codes)
        and codes[0] == _JUDGE_REVISE_CODE
    )


def _turn_record(
    cursor: int, trigger_event_type: str, calls: list[ModelTrace]
) -> dict[str, object]:
    slow_calls = sum(trace.role == "slow" for trace in calls)
    judge_calls = sum(trace.role == "judge" for trace in calls)
    retry = next(
        (
            trace
            for position, trace in enumerate(calls)
            if trace.role == "slow" and position and calls[position - 1].role == "judge"
        ),
        None,
    )
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
        "judge_calls": judge_calls,
        "slow_retry": (
            None
            if retry is None
            else "admitted"
            if retry.result is ModelResult.SUCCEEDED
            else "rejected"
        ),
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
        trace.result is ModelResult.REJECTED
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
    applied: list[ModelTrace],
    unapplied: list[ModelTrace],
) -> dict[str, object]:
    """Turn aggregates count applied calls only; unapplied attempts are apart."""

    count = len(turns)
    by_class = {
        name: sum(turn["class"] == name for turn in turns) for name in TURN_CLASSES
    }
    dialogue = [turn for turn in turns if turn["fast_calls"]]
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
        # Applied Fast turns whose line was the fallback because of the gate.
        "gate_fallback_rate": _share(
            sum(turn["fallback_cause"] == "gate" for turn in dialogue), len(dialogue)
        ),
        "fallback_cause_counts": {
            cause: sum(turn["fallback_cause"] == cause for turn in turns)
            for cause in FALLBACK_CAUSES
        },
        "calls_by_role_and_result": _calls_by_role_and_result(applied),
        "fast_reject_reason_histogram": _fast_reject_histogram(applied),
        # Fast and Slow calls only; Judge calls are counted apart.
        "unapplied_model_calls": sum(trace.role != "judge" for trace in unapplied),
        "unapplied_calls_by_role_and_result": _calls_by_role_and_result(unapplied),
        "unapplied_fast_reject_reason_histogram": _fast_reject_histogram(unapplied),
        "judge_calls_by_result": _judge_calls_by_result(applied),
        "slow_retry_counts": {
            outcome: sum(turn["slow_retry"] == outcome for turn in turns)
            for outcome in SLOW_RETRY_OUTCOMES
        },
        "unapplied_judge_calls_by_result": _judge_calls_by_result(unapplied),
    }


def _judge_calls_by_result(traces: list[ModelTrace]) -> dict[str, int]:
    return {
        result.value: sum(
            trace.role == "judge" and trace.result is result for trace in traces
        )
        for result in ModelResult
    }


def _calls_by_role_and_result(
    traces: list[ModelTrace],
) -> dict[str, dict[str, int]]:
    return {
        role: {
            result.value: sum(
                trace.role == role and trace.result is result for trace in traces
            )
            for result in ModelResult
        }
        for role in ("fast", "slow")
    }


def _fast_reject_histogram(traces: list[ModelTrace]) -> dict[str, int]:
    histogram: dict[str, int] = {}
    for trace in traces:
        if trace.role == "fast" and trace.result is ModelResult.REJECTED:
            for code in trace.reason_codes or ():
                histogram[code] = histogram.get(code, 0) + 1
    return dict(sorted(histogram.items()))


def _share(part: int, whole: int) -> float:
    return round(part / whole, 6) if whole else 0.0


__all__ = [
    "FALLBACK_CAUSES",
    "NON_TURN_EVENT_TYPES",
    "SLOW_RETRY_OUTCOMES",
    "TURN_CLASSES",
    "TURN_TRIGGER_EVENT_TYPES",
    "fast_slow_split",
]
