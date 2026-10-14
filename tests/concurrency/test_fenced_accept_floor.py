"""An accept fenced by the rep's reply while FastC's turn waits (S1-SYS-101;
runs 4b9901, afa368: 7 accepts queued after a grant, 0 heard). The rep's reply
raised a partner fence at once; the accept took the floor, found the fence and
gave the floor back, and FastC's turn held behind it took the floor for ten
seconds; the fence cleared while FastC spoke, its line drew the rep's next
reply and a new fence, until the capability expired. Now, while every raised
cp fence is bound (a Slow step alone clears it: always so under
``transcript``), the waiting accept keeps FastC off the floor too. A user
fence or an epoch bump still revokes it; ``relay_only`` (an unbound fence
needs a FastC turn) keeps S1-SYS-23's behaviour: ``test_partner_fence``."""

from __future__ import annotations

from collections.abc import AsyncIterator, Coroutine
from pathlib import Path
from typing import Any

import pytest
from tests.concurrency.harness import A5, LONG, Sim, SlowGate
from tests.concurrency.test_cases import Valve, arun
from tests.concurrency.test_verbatim_floor import (
    FAST_MS,
    REPLY,
    HearingRep,
    delivery,
    fastc_holds_the_floor,
    line_ends,
    unheard,
    verbatim_of,
)

from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.events import Event
from proxyloop.contract.llm import LLMCallRecord, TextRequest, ToolRequest, ToolResponse
from proxyloop.evidence.check import check_path

STEP_MS = 3_000  # a live Slow step took 2 to 6 s


class ChattyRep(HearingRep):
    """Once ``chatty``, answers every agent line it hears with REPLY."""

    def __init__(self) -> None:
        super().__init__()
        self.chatty = False

    def send(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, text: str | None, utt_id: str, cause: str, t_ms: int
    ) -> Coroutine[Any, Any, None]:
        if self.chatty:
            self.answer = REPLY
        return super().send(text, utt_id, cause, t_ms)


class SlowSteps:
    """Each Slow step call takes ``ms`` of virtual time, then answers."""

    def __init__(self, sim: Sim, ms: int) -> None:
        loud = sim.k.clients["slow"]
        self.inner, self.ref = loud.inner, loud.inner.ref
        loud.inner = self
        self._sleep, self._ms = sim.vt.sleep, ms

    def stream_text(self, request: TextRequest) -> AsyncIterator[str | LLMCallRecord]:
        return self.inner.stream_text(request)

    async def chat_tools(self, request: ToolRequest) -> ToolResponse:
        await self._sleep(self._ms / 1000)
        return await self.inner.chat_tools(request)


async def _fenced_while_fastc_waits(sim: Sim, rep: HearingRep) -> tuple[Event, Event]:
    """An accept queued while FastC holds the floor, Slow held: the rep's
    reply to FastC's line lands and fences it, and FastC's answer to that
    reply waits. (the reply, FastC's held line)"""
    fast = await fastc_holds_the_floor(sim)
    gate = SlowGate(sim)
    gate.let(0)
    rep.answer = REPLY
    assert sim.accept().startswith("accept_offer: accept line queued")
    await sim.vt.run_for(12_000)
    heard = delivery(sim, fast)
    (said,) = sim.of("utt.final", text=REPLY)
    assert said.seq > heard.seq and sim.bb.fences
    assert sim.k.authority.partner_only()
    await sim.vt.run_for(3_000)
    held = [e for e in unheard(sim) if e.seq > said.seq]
    assert held, "FastC generated no answer to the reply"
    assert not sim.k.speakers["cp"].speaking, "FastC took the floor"
    assert not [e for e in sim.of("utt.delivered", lane="cp") if e.seq > said.seq]
    assert line_ends(sim) == []
    return said, held[0]


def test_a_fenced_accept_keeps_fastc_off_the_floor_and_is_released(
    tmp_path: Path,
) -> None:
    """The fence clears as Slow's step reads the reply: the accept takes the
    floor at once (FastC never spoke meanwhile), is heard and commits; FastC's
    held turn is then stale and cancelled (S1-SYS-59)."""

    async def case() -> None:
        rep = HearingRep()
        sim = Sim(tmp_path, {"fast_cp": [LONG]}, rep=rep)
        assert sim.k.cfg.slow_view is SlowViewMode.TRANSCRIPT
        said, held = await _fenced_while_fastc_waits(sim, rep)
        gate = sim.k.clients["slow"].inner
        assert isinstance(gate, SlowGate)
        gate.let(None)
        await sim.vt.run_for(2_000)
        (end,) = line_ends(sim)
        assert end.type == "speak.released", end.payload
        cleared = sim.of("authority.fence", op="cleared")
        assert cleared and end.seq > cleared[-1].seq > said.seq
        assert not [
            e for e in sim.of("utt.delivered", lane="cp") if said.seq < e.seq < end.seq
        ]
        await sim.vt.run_for(12_000)
        (line,) = sim.of(
            "utt.delivered", utt_id=f"accept-{verbatim_of(sim, 'accept').seq}"
        )
        assert line.payload["interrupted"] is False
        assert sim.of("status.changed", status="COMMITTED")
        (cancelled,) = sim.of("fast.cancelled", gen_id=held.payload["gen_id"])
        assert cancelled.payload["reason"] == "verbatim"
        assert not sim.of("utt.delivered", utt_id=held.payload["utt_id"])
        await sim.stop()
        assert check_path(sim.k.path, "offline").ok

    arun(case())


def test_an_accept_amid_a_chatty_rep_and_slow_steps_is_released(
    tmp_path: Path,
) -> None:
    """The live livelock: the rep answers every line FastC says, and each Slow
    step takes STEP_MS. The accept is released and heard, not revoked
    ``expired``."""

    async def case() -> None:
        rep = ChattyRep()
        sim = Sim(tmp_path, {"fast_cp": [LONG]}, rep=rep)
        await fastc_holds_the_floor(sim)
        SlowSteps(sim, STEP_MS)
        rep.chatty = True
        assert sim.accept().startswith("accept_offer: accept line queued")
        await sim.vt.run_for(70_000)  # past the capability's TTL
        (end,) = line_ends(sim)
        assert end.type == "speak.released", end.payload
        assert sim.of("status.changed", status="COMMITTED")
        await sim.stop()

    arun(case())


@pytest.mark.parametrize("why", ["fence", "epoch"])
def test_a_fenced_accept_holding_fastc_is_still_revoked(
    tmp_path: Path, why: str
) -> None:
    """A user's message (a user fence) or a revoke (an epoch bump) while the
    accept holds FastC off the floor revokes it at once; FastC's held turn is
    then said (only a heard line makes it stale)."""

    async def case() -> None:
        rep = HearingRep()
        sim = Sim(tmp_path, {"fast_cp": [LONG]}, rep=rep)
        _, held = await _fenced_while_fastc_waits(sim, rep)
        if why == "fence":
            sim.user_says("Stop, do not accept anything.")
        else:
            sim.revoke()
        await sim.vt.run_for(100)
        (end,) = line_ends(sim)
        assert end.type == "speak.revoked" and end.payload["reason"] == why
        assert not sim.of("status.changed", status="COMMITTED")
        await sim.vt.run_for(FAST_MS + 1_000)
        assert sim.of("utt.delivered", utt_id=held.payload["utt_id"])
        assert not sim.of("fast.cancelled", gen_id=held.payload["gen_id"])
        await sim.stop()

    arun(case())


@pytest.mark.parametrize("why", ["fence", "epoch"])
def test_a_second_hold_then_a_revoke_leaves_fastc_free_to_speak(
    tmp_path: Path, why: str
) -> None:
    """Review of #308: the rep speaks again while the accept holds FastC off the
    floor, so the line takes the floor and holds a second time; a revoke then
    ends it. Every hold is given back: FastC speaks again (its held turn,
    older than the rep's line, is re-run on the new basis: S1-SYS-123), and
    nothing stays queued (a leaked count would silence FastC for the call)."""

    async def case() -> None:
        rep = HearingRep()
        sim = Sim(tmp_path, {"fast_cp": [LONG]}, rep=rep)
        _, held = await _fenced_while_fastc_waits(sim, rep)
        sim.rep_says("And one more thing about that offer.")
        await sim.vt.run_for(2_000)  # a second bound fence: the line holds again
        assert not sim.k.speakers["cp"].speaking and line_ends(sim) == []
        if why == "fence":
            sim.user_says("Stop, do not accept anything.")
        else:
            sim.revoke()
        await sim.vt.run_for(100)
        (end,) = line_ends(sim)
        assert end.type == "speak.revoked" and end.payload["reason"] == why
        speaker = sim.k.speakers["cp"]
        assert speaker._queued == 0  # pyright: ignore[reportPrivateUsage]
        await sim.vt.run_for(FAST_MS + 15_000)
        (cancel,) = sim.of("fast.cancelled", gen_id=held.payload["gen_id"])
        assert cancel.payload["reason"] == "partner"
        said = [e for e in sim.of("utt.delivered", lane="cp") if e.seq > end.seq]
        assert said, "FastC never spoke again"
        await sim.stop()

    arun(case())


def test_relay_only_an_unbound_fence_lets_fastc_s_held_turn_speak(
    tmp_path: Path,
) -> None:
    """Under ``relay_only`` a fence binds only through a FastC turn whose
    request saw the rep's line. FastC's turn requested before the reply is
    held behind the accept: were FastC kept off the floor, no later turn could
    bind the fence (the lane is sequential) and the accept would expire. It
    is not said (older than the rep's reply, S1-SYS-123): its re-run, which saw
    the reply, voices the guide again, binds the fence, and the accept is
    released."""

    async def case() -> None:
        rep, fast_cp = HearingRep(), Valve()
        scripts, gates = {"fast_cp": [LONG]}, {"fast_cp": fast_cp}
        sim = Sim(tmp_path, scripts, rep=rep, cfg=A5, gates=gates)
        await fastc_holds_the_floor(sim)
        rep.heard.clear()  # the rep hears FastC's line: the accept waits
        assert sim.accept().startswith("accept_offer: accept line queued")
        fast_cp.open.clear()
        assert "guide" in sim.act({"tool": "guide_fast", "move": "ask_final_offer"})[0]
        await sim.vt.run_for(12_000)  # FastC's line ends; the guide turn is asked
        (early,) = sim.of("fast.request", lane="cp")[-1:]
        sim.rep_says(REPLY)
        await sim.vt.run_for(100)
        (said,) = sim.of("utt.final", text=REPLY)
        assert int(str(early.payload["basis_seq"])) < said.seq
        rep.heard.set()
        await sim.vt.run_for(100)
        assert sim.bb.fences and not sim.k.authority.partner_bound()
        assert line_ends(sim) == []
        fast_cp.open.set()
        await sim.vt.run_for(40_000)
        (cancel,) = sim.of("fast.cancelled", gen_id=early.payload["gen_id"])
        assert cancel.payload["reason"] == "partner"
        rerun = [e for e in sim.of("fast.request", lane="cp") if e.seq > cancel.seq]
        assert rerun and int(str(rerun[0].payload["basis_seq"])) >= said.seq
        assert [e for e in sim.of("utt.delivered", lane="cp") if e.seq > said.seq]
        (end,) = line_ends(sim)
        assert end.type == "speak.released", end.payload
        bound = [t for t in sim.of("fast.turn", lane="cp") if t.seq > said.seq]
        assert len(bound) >= 2 and end.seq > bound[1].seq
        assert sim.of("status.changed", status="COMMITTED")
        await sim.stop()

    arun(case())
