"""A SimRep turn for a heard block reaches the kernel as the same turns heard
one at a time would (S1-SYS-63, ADR-0021): one ``chan.strike`` per strike,
each citing its own decision's event (its voiced line's ``rep.mouth``, or its
``rep.policy`` when its line was voiced once for a run of equal intents); a
transfer after a strike closes the call (``chan.closed``), it is no hang-up;
a strike-out hangs up. The fold's ``cp.strikes`` (Slow's STATUS line) and obs
``identity.strikes`` equal the one-turn-at-a-time run. A turn of one decision
cites exactly what it did before: its first line's cause. Rep-chat sessions:
a scripted person speaks for the agent, the world's SimRep answers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from tests.kernel.test_session import SCRIPTS as SESSION
from tests.support import sessions
from tests.support.manual_clock import ScaledClock

from proxyloop.contract.events import Event, check_causes
from proxyloop.contract.llm import (
    LLMCallRecord,
    LLMClient,
    LLMRole,
    ModelRef,
    TextRequest,
    ToolRequest,
    ToolResponse,
)
from proxyloop.core.fold import fold
from proxyloop.env.tasks.schema import Task
from proxyloop.kernel.channels import Channel, Incoming
from proxyloop.kernel.session import run_session
from proxyloop.llm.http import RecordSink
from proxyloop.obs.detectors import DETECTORS, Inputs

Line = tuple[str, dict[str, Any]]  # what the agent says, and the Ear's act for it
LINE = "Northwind Mobile, may I have the account holder name?"
HOLD: Line = ("One moment please.", {"act": "hold_request"})
REFUSE: Line = ("I'd rather not say.", {"act": "refuse_fact"})
FACTS = [
    {"key": "account.holder_name", "value": "Dana Reyes"},
    {"key": "account.last4", "value": "4821"},
]
ID: Line = ("Dana Reyes, last four 4821.", {"act": "provide_fact", "facts": FACTS})
SUPERVISOR: Line = ("Can I talk to a supervisor?", {"act": "ask_supervisor"})


class Batch(Channel):
    """A person speaking for the agent: on each rep line heard, the next
    group of lines, all at once (a group of several: the rep hears them while
    its turn on the first is in flight)."""

    def __init__(self, groups: list[list[str]]) -> None:
        super().__init__()
        self.groups = groups

    async def send(self, text: str | None, utt_id: str, cause: str, t_ms: int) -> None:
        if text and self.groups:
            for line in self.groups.pop(0):
                self.incoming.put_nowait(Incoming(((line, None),)))


class Listening:
    """An Ear that yields to the loop before it answers, as a real call does:
    the lines said meanwhile are heard while the rep's turn is in flight."""

    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner

    @property
    def ref(self) -> ModelRef:
        return self._inner.ref

    def stream_text(self, request: TextRequest) -> AsyncIterator[str | LLMCallRecord]:
        return self._inner.stream_text(request)

    async def chat_tools(self, request: ToolRequest) -> ToolResponse:
        for _ in range(3):
            await asyncio.sleep(0)
        return await self._inner.chat_tools(request)


def _call(
    tmp_path: Path, lines: Sequence[Line], block: bool
) -> tuple[str, tuple[Event, ...]]:
    texts = [text for text, _ in lines]
    ear = [sessions.ear("other")]  # the kernel's disclosure line opens the call
    ear += [sessions.ears(act) for _, act in lines]
    person = Batch([texts] if block else [[t] for t in texts])
    clock = ScaledClock(100)
    scripted = sessions.clients({"ear": ear, "mouth": [LINE]}, clock, (), {})

    def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
        client = scripted(role, ref, sink)
        return Listening(client) if role == "ear" else client

    session = run_session(
        sessions.fake_config(),
        sessions.patient_task(),
        {"cp": "sim", "cp_agent": person},
        runs_dir=tmp_path,
        clock=clock,
        sleep=clock.sleep,
        clients=make,
    )
    result = asyncio.run(asyncio.wait_for(session, timeout=30))
    return result.reason, sessions.only_bundle(tmp_path).events


def _identity(events: tuple[Event, ...]) -> dict[str, Any]:
    value = DETECTORS["identity.strikes"](Inputs(events, None, lambda _: None))
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _outcome(reason: str, events: tuple[Event, ...]) -> dict[str, object]:
    of, identity = [e.type for e in events], _identity(events)
    return {
        "reason": reason,
        "chan.strike": of.count("chan.strike"),
        "fold cp.strikes": fold(events).channels["cp"].strikes,  # Slow's STATUS
        "obs identity strikes": len(identity["strikes"]),
        "obs h5_pass": identity["h5_pass"],
        "chan.closed": of.count("chan.closed"),
    }


@pytest.mark.parametrize(
    ("lines", "want"),
    [
        pytest.param(
            [HOLD, REFUSE, SUPERVISOR],
            {"reason": "stopped", "chan.strike": 1, "chan.closed": 1},
            id="a strike, then a transfer",
        ),
        pytest.param(
            [HOLD, REFUSE, REFUSE, ID, SUPERVISOR],
            {"reason": "stopped", "chan.strike": 2, "chan.closed": 1},
            id="two strikes in one block",
        ),
        pytest.param(
            [HOLD, REFUSE, REFUSE, REFUSE],
            {"reason": "abandoned", "chan.strike": 3, "chan.closed": 0},
            id="three strikes: a hang-up",
        ),
    ],
)
def test_a_heard_block_ends_and_strikes_as_its_turns_one_at_a_time(
    tmp_path: Path,
    lines: list[Line],
    want: dict[str, object],
) -> None:
    (tmp_path / "seq").mkdir()
    (tmp_path / "block").mkdir()
    seq = _outcome(*_call(tmp_path / "seq", lines, block=False))
    reason, events = _call(tmp_path / "block", lines, block=True)
    *_, last = [e for e in events if e.type == "rep.ear"]
    heard = cast(list[str], last.payload["heard_utt_ids"])
    assert len(heard) == len(lines) - 1  # not vacuous: one block after the hold
    block = _outcome(reason, events)
    assert block == seq
    assert {k: block[k] for k in want} == want
    assert block["fold cp.strikes"] == block["chan.strike"]


def test_obs_counts_a_strike_out_block_as_its_turns_one_at_a_time(
    tmp_path: Path,
) -> None:
    lines = [HOLD, REFUSE, REFUSE, REFUSE]
    (tmp_path / "seq").mkdir()
    (tmp_path / "block").mkdir()
    _, seq = _call(tmp_path / "seq", lines, block=False)
    _, block = _call(tmp_path / "block", lines, block=True)
    assert _identity(block)["count"] == _identity(seq)["count"] == 3


def _first_line_cause(events: tuple[Event, ...], strike: Event) -> tuple[str, ...]:
    """What a ``chan.strike`` cited before S1-SYS-63 (a): its turn's first
    line's cause (the kernel emits a turn's strikes, then its lines)."""
    line = next(
        e
        for e in events
        if e.seq > strike.seq
        and e.type == "utt.final"
        and e.payload["speaker"] == "partner"
    )
    return line.cause_ids


def _one_decision_strikes_cite_their_first_line(events: tuple[Event, ...]) -> None:
    by_id = {e.event_id: e for e in events}
    strikes = [e for e in events if e.type == "chan.strike"]
    assert strikes  # not vacuous
    for strike in strikes:
        assert strike.cause_ids == _first_line_cause(events, strike)
        (cause,) = strike.cause_ids
        assert by_id[cause].type == "rep.mouth"
    check_causes(events)


@pytest.mark.parametrize(
    "lines",
    [[HOLD, REFUSE, SUPERVISOR], [HOLD, REFUSE, REFUSE, REFUSE]],
    ids=["a strike, then a transfer", "a strike-out"],
)
def test_a_turn_of_one_identity_strike_cites_its_first_line_as_before(
    tmp_path: Path, lines: list[Line]
) -> None:
    _, events = _call(tmp_path, lines, block=False)
    _one_decision_strikes_cite_their_first_line(events)


def test_a_timer_strike_cites_its_first_line_as_before(tmp_path: Path) -> None:
    """The world's own SimRep over a silent agent: its silence strikes."""
    data = sessions.patient_task().model_dump(mode="json")
    data["counterparty"]["patience"]["silence_s"] = 10
    scripts = SESSION | {"fast_cp": ["@wait"], "fast_user": ["Okay."]}
    sessions.run(tmp_path, scripts, task=Task.model_validate(data))
    events = sessions.only_bundle(tmp_path).events
    assert {e.payload["kind"] for e in events if e.type == "chan.strike"} == {"timer"}
    _one_decision_strikes_cite_their_first_line(events)


@pytest.mark.parametrize(
    ("lines", "voiced"),
    [
        pytest.param(
            [HOLD, REFUSE, REFUSE, ID, SUPERVISOR],
            ["rep.policy", "rep.mouth"],
            id="two strikes, the first voiced with the second",
        ),
        pytest.param(
            [HOLD, REFUSE, REFUSE, REFUSE],
            ["rep.policy", "rep.mouth", "rep.mouth"],
            id="a strike-out",
        ),
    ],
)
def test_each_strike_of_a_block_cites_its_own_decision(
    tmp_path: Path, lines: list[Line], voiced: list[str]
) -> None:
    """The i-th ``chan.strike`` cites the i-th struck decision: its voiced
    line's ``rep.mouth``, or its ``rep.policy`` when its line was voiced once
    for it and the next equal intent (ADR-0021 D4)."""
    _, events = _call(tmp_path, lines, block=True)
    by_id = {e.event_id: e for e in events}
    refused = {
        e.event_id
        for e in events
        if e.type == "rep.ear" and e.payload["act"] == "refuse_fact"
    }
    struck = [
        e for e in events if e.type == "rep.policy" and set(e.cause_ids) & refused
    ]
    mouths = {e.cause_ids[0]: e for e in events if e.type == "rep.mouth"}
    want = [
        mouths[p.event_id].event_id if p.event_id in mouths else p.event_id
        for p in struck
    ]
    strikes = [e for e in events if e.type == "chan.strike"]
    assert [s.cause_ids for s in strikes] == [(w,) for w in want]
    assert [by_id[w].type for w in want] == voiced  # not vacuous: both kinds
    check_causes(events)
