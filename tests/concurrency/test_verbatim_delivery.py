"""S1-SYS-59 follow-up. A verbatim line enters the transcript at its
``utt.delivered``, not at its ``speak.released``: a FastC turn requested
while the line is being said has a board without it, so it is stale too
(review D3). A cancelled turn leaves no hold the rep never heard (D2), and a
``fresh`` check that raises gives the floor back."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import pytest
from tests.concurrency.harness import Sim
from tests.concurrency.test_cases import arun

from proxyloop.contract.events import Event

MARK = "best and final offer"  # in FastC's prompt once Slow guides it
HELD = "One moment, let me check.\n@hold decision"


def _caused(sim: Sim, type_: str, cause: str, **match: object) -> list[Event]:
    return [e for e in sim.of(type_, **match) if e.cause_ids[-1] == cause]


def _after(sim: Sim, type_: str, seq: int) -> list[Event]:  # cp's, past seq
    return [e for e in sim.of(type_, lane="cp") if e.seq > seq]


def _released(sim: Sim) -> Event:
    (said,) = sim.of("speak.verbatim", kind="decline")
    (released,) = _caused(sim, "speak.released", said.event_id)
    return released


async def _guided_while_the_decline_is_said(sim: Sim) -> Event:
    """The decline has the floor (released, not yet heard) when Slow guides
    FastC: FastC's request is made between the release and the delivery."""
    await sim.start()
    await sim.offer("o1", 68)
    await sim.vt.run_for(10_000)
    assert not sim.k.speakers["cp"].speaking
    assert "queued" in sim.act({"tool": "decline_offer", "offer_ref": "o1"})[0]
    await sim.vt.run_for(500)
    released = _released(sim)
    guide = {"tool": "guide_fast", "move": "ask_final_offer"}
    assert "guide" in sim.act(guide)[0]
    await sim.vt.run_for(100)
    (asked,) = _after(sim, "fast.request", released.seq)
    assert not _caused(sim, "utt.delivered", released.event_id)
    return asked


def test_a_turn_requested_while_the_verbatim_is_said_is_cancelled(
    tmp_path: Path,
) -> None:
    """Its basis is past the release but before the delivery: the board it saw
    has the offer declined and no decline line. It is cancelled
    (``fast.cancelled{verbatim}`` citing its turn and the delivery), never
    said, and its trigger runs again on a board with the line."""

    async def case() -> None:
        sim = Sim(tmp_path)
        asked = await _guided_while_the_decline_is_said(sim)
        await sim.vt.run_for(20_000)
        released = _released(sim)
        (delivered,) = _caused(sim, "utt.delivered", released.event_id)
        assert released.seq < int(str(asked.payload["basis_seq"])) < delivered.seq
        gen = asked.payload["gen_id"]
        (turn,) = sim.of("fast.turn", gen_id=gen)
        (cancelled,) = sim.of("fast.cancelled", gen_id=gen)
        assert cancelled.payload["reason"] == "verbatim"
        assert cancelled.cause_ids == (turn.event_id, delivered.event_id)
        heard = [str(e.payload["utt_id"]) for e in sim.of("utt.delivered")]
        assert not [u for u in heard if u.startswith(f"{gen}-")]
        again = _after(sim, "fast.request", cancelled.seq)
        assert again and again[0].payload["trigger"] == asked.payload["trigger"]
        assert int(str(again[0].payload["basis_seq"])) >= delivered.seq
        await sim.stop()

    arun(case())


def test_a_cancelled_turn_leaves_no_hold(tmp_path: Path) -> None:
    """The cancelled turn held (``@hold decision``): the rep never heard it, so
    no ``chan.hold`` of it is set; the re-run voices its own hold (relayed,
    not deduped as a repeat) as its speech takes the floor."""

    async def case() -> None:
        sim = Sim(tmp_path, until={"fast_cp": (MARK, HELD)})
        asked = await _guided_while_the_decline_is_said(sim)
        await sim.vt.run_for(20_000)
        gen = asked.payload["gen_id"]
        (turn,) = sim.of("fast.turn", gen_id=gen)
        items = cast(list[dict[str, object]], turn.payload["items"])
        assert [i["kind"] for i in items] == ["speech", "hold"]
        (cancelled,) = sim.of("fast.cancelled", gen_id=gen)
        assert not _caused(sim, "chan.hold", turn.event_id)
        rerun = _after(sim, "fast.turn", cancelled.seq)[0]
        (hold,) = _caused(sim, "chan.hold", rerun.event_id, reason="decision")
        utt_id = f"{rerun.payload['gen_id']}-u0"
        (heard,) = sim.of("utt.delivered", utt_id=utt_id)
        (said,) = sim.of("fast.sentence", utt_id=utt_id)
        assert said.seq < hold.seq < heard.seq  # set as its speech takes the floor
        assert _caused(sim, "f2s.msg", rerun.event_id, type="HOLD")
        assert sim.k.bb.public.cp_hold is not None
        await sim.stop()

    arun(case())


def test_a_raising_fresh_check_gives_the_floor_back(tmp_path: Path) -> None:
    async def case() -> None:
        sim = Sim(tmp_path)
        await sim.start()
        speaker = sim.k.speakers["cp"]

        def fresh() -> bool:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            await speaker.speak([("x-u0", "Hello.", "cause")], fresh=fresh)
        async with asyncio.timeout(1):  # the floor is free again
            assert await speaker.speak([], fresh=lambda: False) is False
        await sim.stop()

    arun(case())
