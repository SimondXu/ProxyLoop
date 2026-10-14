"""S1-SYS-126: a guidance trigger whose GUIDE a reply already voiced is moot.
Slow's GUIDE queues a ``guidance`` trigger; a rep line queues ``rep_spoke``,
which is served first (URGENT) and voices the GUIDE. The guidance trigger
must not run afterwards: its view still renders the GUIDE as new guidance, so
FastC asked again for a read-back after COMMITTED (fc41ec 252.7 s, aebf80
234.7 s; 27 of 256 guidance requests in runs/b3-41313c3)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from tests.concurrency.harness import Sim
from tests.concurrency.test_cases import Valve, arun

DISCOUNT = {"tool": "guide_fast", "move": "ask_discount"}


def test_a_guidance_trigger_voiced_by_a_reply_is_dropped(tmp_path: Path) -> None:
    async def case() -> None:
        fast_cp = Valve()
        sim = Sim(tmp_path, gates={"fast_cp": fast_cp})
        await sim.start()
        fast_cp.open.clear()  # FastC busy: what follows queues behind it
        sim.rep_says("Let me look at your account.")
        await sim.vt.run_for(100)
        assert "guide" in sim.act(DISCOUNT)[-1]
        sim.rep_says("Is there anything else I can help with?")
        await sim.vt.run_for(100)
        fast_cp.open.set()
        await sim.vt.run_for(30_000)
        (msg,) = sim.of("s2f.msg", type="GUIDE")
        (voiced,) = sim.of("s2f.voiced", msg_id=msg.payload["msg_id"])
        (turn,) = sim.of("fast.turn", gen_id=voiced.payload["gen_id"])
        (asked,) = sim.of("fast.request", gen_id=voiced.payload["gen_id"])
        assert asked.payload["trigger"] == "rep_spoke"
        assert not [
            e for e in sim.of("fast.request", trigger="guidance") if e.seq > turn.seq
        ]
        assert sim.k.counts["guidance_moot"] == 1
        await sim.stop()

    arun(case())


def test_a_guide_voiced_by_a_reply_never_said_keeps_its_trigger(
    tmp_path: Path,
) -> None:
    """The reply that voiced the GUIDE is overtaken by a rep line
    (``fast.cancelled{partner}``) and its re-run says nothing (R3a re-triggers
    no carried GUIDE): the rep never heard it, so the guidance trigger runs."""

    async def case() -> None:
        tickets, moved = [-1], asyncio.Event()  # -1: open

        async def held() -> None:  # each FastC call takes one ticket
            while tickets[0] == 0:
                moved.clear()
                await moved.wait()
            if tickets[0] > 0:
                tickets[0] -= 1

        def let(n: int) -> None:
            tickets[0] = n
            moved.set()

        until = {"fast_cp": ("Anything else?", "")}  # FastC silent once it hears it
        sim = Sim(tmp_path, gates={"fast_cp": held}, until=until)
        await sim.start()
        let(0)
        sim.act(DISCOUNT)  # its guidance turn is held in flight
        await sim.vt.run_for(100)
        sim.act(DISCOUNT)  # a newer GUIDE: a guidance trigger queued
        sim.rep_says("One moment.")  # a rep_spoke trigger queued, served first
        await sim.vt.run_for(100)
        let(1)  # the first turn is said; the reply (it voices the GUIDE) is held
        await sim.vt.run_for(5_000)
        sim.rep_says("Anything else?")
        await sim.vt.run_for(100)
        let(-1)
        await sim.vt.run_for(30_000)
        (msg,) = [e for e in sim.of("s2f.msg", type="GUIDE")][-1:]
        (voiced,) = sim.of("s2f.voiced", msg_id=msg.payload["msg_id"])
        (asked,) = sim.of("fast.request", gen_id=voiced.payload["gen_id"])
        assert asked.payload["trigger"] == "rep_spoke"
        (cancel,) = sim.of("fast.cancelled", reason="partner")
        assert cancel.payload["gen_id"] == voiced.payload["gen_id"]
        assert [
            e for e in sim.of("fast.request", trigger="guidance") if e.seq > cancel.seq
        ]
        assert sim.k.counts["guidance_moot"] == 0
        await sim.stop()

    arun(case())
