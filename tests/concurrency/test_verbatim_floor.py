"""A verbatim line queued while FastC holds the floor (S1-SYS-56, run 45d7ed
seq 502): with the rep's channel idle it takes the floor as FastC's line ends,
before the rep, hearing that line, is busy again. The rep here hears as
``SimRepChannel`` does: busy from the send. Negatives: a rep turn begun, queued
or composed still goes first (S1-SYS-23), and the line is revalidated after it
takes the floor."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest
from tests.concurrency.harness import LONG, Sim, granted
from tests.concurrency.test_cases import arun

from proxyloop.contract.events import Event
from proxyloop.kernel.channels import Channel, Incoming

ELSE = "Anything else?"
REPLY = "Sorry, one more thing."


class HearingRep(Channel):
    """Busy from each send until ``heard`` is set (it is, unless the test
    clears it); ``answer`` is queued in the send, as the agent's line ends."""

    def __init__(self) -> None:
        super().__init__()
        self.heard = asyncio.Event()
        self.heard.set()
        self.answer: str | None = None

    def send(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, text: str | None, utt_id: str, cause: str, t_ms: int
    ) -> Coroutine[Any, Any, None]:
        self.composing(1)
        if text and self.answer is not None:
            self.incoming.put_nowait(Incoming(((self.answer, None),)))
            self.answer = None

        async def hear() -> None:
            try:
                await self.heard.wait()
            finally:
                self.composing(-1)

        return hear()


async def _fastc_holds_the_floor(sim: Sim, accept: bool = True) -> Event:
    """FastC answers the rep with ten seconds of speech; the rep is idle."""
    await sim.start()
    if accept:
        await granted(sim)
    else:
        await sim.offer()
    for _ in range(60):  # FastC has answered the offer's lines
        await sim.vt.run_for(1_000)
        if not sim.k.speakers["cp"].speaking:
            break
    sim.rep_says(ELSE)
    await sim.vt.run_for(500)
    assert sim.k.speakers["cp"].speaking and not sim.rep.busy
    (said,) = sim.of("utt.final", text=ELSE)
    fast = sim.of("fast.sentence", lane="cp")[-1]
    assert fast.seq > said.seq  # FastC's answer to it
    return fast


def _heard(sim: Sim, line: Event) -> Event:
    (e,) = sim.of("utt.delivered", utt_id=line.payload["utt_id"])
    return e


def _ends(sim: Sim) -> list[Event]:  # of the accept or decline line
    kinds = ("accept", "decline")
    lines = {e.event_id for k in kinds for e in sim.of("speak.verbatim", kind=k)}
    ends = sim.of("speak.released") + sim.of("speak.revoked")
    return [e for e in ends if e.cause_ids[0] in lines]


@pytest.mark.parametrize("kind", ["decline", "accept"])
def test_a_verbatim_queued_while_fastc_holds_the_floor_is_released(
    tmp_path: Path, kind: str
) -> None:
    async def case() -> None:
        rep = HearingRep()
        sim = Sim(tmp_path, {"fast_cp": [LONG]}, rep=rep)
        fast = await _fastc_holds_the_floor(sim, accept=kind == "accept")
        rep.heard.clear()  # from here the rep is still hearing FastC's line
        tool = "accept_offer" if kind == "accept" else "decline_offer"
        out = sim.act({"tool": tool, "offer_ref": "o1"})
        assert "queued" in out[0], out
        await sim.vt.run_for(100)
        assert _ends(sim) == []  # FastC holds the floor
        await sim.vt.run_for(15_000)
        heard = _heard(sim, fast)
        (released,) = _ends(sim)
        assert released.type == "speak.released" and released.seq > heard.seq
        assert released.t_ms == heard.t_ms  # the next floor
        await sim.vt.run_for(15_000)  # the line is said
        (line,) = sim.of("utt.delivered", utt_id=f"{kind}-{_said(sim, kind).seq}")
        assert line.payload["interrupted"] is False
        assert sim.rep.busy  # the rep hears FastC's line while the line is said
        if kind == "accept":
            assert sim.of("status.changed", status="COMMITTED")
        rep.heard.set()
        await sim.stop()

    arun(case())


def _said(sim: Sim, kind: str) -> Event:
    (e,) = sim.of("speak.verbatim", kind=kind)
    return e


@pytest.mark.parametrize("partner", ["begun", "queued", "composed"])
def test_an_accept_still_waits_for_a_pending_rep_turn(
    tmp_path: Path, partner: str
) -> None:
    """begun: the rep's line cuts FastC's; queued: it is queued as FastC's
    line ends; composed: the rep composes past it. No floor for the accept
    until the rep's turn has landed (or ended)."""

    async def case() -> None:
        rep = HearingRep()
        sim = Sim(tmp_path, {"fast_cp": [LONG]}, rep=rep)
        fast = await _fastc_holds_the_floor(sim)
        if partner == "composed":
            sim.rep_composes()
        elif partner == "queued":
            rep.answer = REPLY
        assert sim.accept().startswith("accept_offer: accept line queued")
        if partner == "begun":
            await sim.vt.run_for(1_000)
            sim.rep_says(REPLY)
        await sim.vt.run_for(12_000)
        assert sim.of("utt.delivered", utt_id=fast.payload["utt_id"])
        if partner == "composed":
            assert _ends(sim) == [] and sim.rep.busy
            sim.rep_done(REPLY)
            await sim.vt.run_for(100)
        (said,) = sim.of("utt.final", text=REPLY)
        assert all(e.seq > said.seq for e in _ends(sim)), _ends(sim)
        await sim.stop()

    arun(case())


def test_the_accept_is_revalidated_after_it_takes_the_floor(tmp_path: Path) -> None:
    """An epoch bump while FastC holds the floor: the accept, handed the next
    floor, is revalidated there and revoked ``epoch``, never released."""

    async def case() -> None:
        rep = HearingRep()
        sim = Sim(tmp_path, {"fast_cp": [LONG]}, rep=rep)
        fast = await _fastc_holds_the_floor(sim)
        rep.heard.clear()
        assert sim.accept().startswith("accept_offer: accept line queued")
        await sim.vt.run_for(1_000)
        sim.revoke()
        await sim.vt.run_for(100)
        assert _ends(sim) == []  # still waiting for the floor
        await sim.vt.run_for(12_000)
        (revoked,) = _ends(sim)
        assert revoked.type == "speak.revoked" and revoked.payload["reason"] == "epoch"
        heard = _heard(sim, fast)
        assert revoked.seq > heard.seq and revoked.t_ms == heard.t_ms
        rep.heard.set()
        await sim.stop()

    arun(case())
