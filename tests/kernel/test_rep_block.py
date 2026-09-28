"""A SimRep turn for a heard block reaches the kernel as the same turns heard
one at a time would (S1-SYS-63, ADR-0021): one ``chan.strike`` per strike; a
transfer after a strike closes the call (``chan.closed``), it is no hang-up;
a strike-out hangs up. The fold's ``cp.strikes`` (Slow's STATUS line) and obs
``identity.strikes`` equal the one-turn-at-a-time run. Rep-chat sessions: a
scripted person speaks for the agent, the world's SimRep answers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from tests.support import sessions
from tests.support.manual_clock import ScaledClock

from proxyloop.contract.events import Event
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


@pytest.mark.xfail(
    strict=True,
    reason="escalated (S1-SYS-63): obs identity.strikes `count` adds the "
    "abandonment unless some chan.strike's cause chain reaches the "
    "IDENTIFY->ENDED rep.policy; a block's strikes all cite its first line "
    "(kernel _turn), so a strike-out block whose first line is not the hang-up "
    "counts k + 1 (4 here, 3 one turn at a time); the strikes list is exact",
)
def test_obs_counts_a_strike_out_block_as_its_turns_one_at_a_time(
    tmp_path: Path,
) -> None:
    lines = [HOLD, REFUSE, REFUSE, REFUSE]
    (tmp_path / "seq").mkdir()
    (tmp_path / "block").mkdir()
    _, seq = _call(tmp_path / "seq", lines, block=False)
    _, block = _call(tmp_path / "block", lines, block=True)
    assert _identity(block)["count"] == _identity(seq)["count"] == 3
