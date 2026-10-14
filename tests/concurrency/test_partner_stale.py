"""A FastC turn generated before the rep's newest line is not said (S1-SYS-123,
live runs v2-2862d54: 56% of rep lines waited > 1 s, p50 8.5 s, while FastC
first said a reply composed before the rep spoke). On the floor such a turn is
``fast.cancelled{partner}``: its relays stay, its speech is never heard, and
its trigger runs again on the new basis, which also answers the newest line.
A re-run is never dropped this way again, so a talking rep cannot starve FastC."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from itertools import pairwise
from pathlib import Path

from tests.concurrency.harness import Sim
from tests.concurrency.test_cases import arun


def gated() -> tuple[asyncio.Event, dict[str, Callable[[], Awaitable[None]]]]:
    """An open gate on FastC's calls; clear it to hang the next one in flight."""
    go = asyncio.Event()
    go.set()

    async def wait() -> None:
        await go.wait()

    return go, {"fast_cp": wait}


def test_a_turn_older_than_the_reps_newest_line_is_not_said(tmp_path: Path) -> None:
    async def case() -> None:
        go, gates = gated()
        sim = Sim(tmp_path, gates=gates)
        await sim.start()
        go.clear()  # FastC's next generation hangs in flight
        sim.rep_says("Let me look at your account.")
        await sim.vt.run_for(500)
        (first,) = [e for e in sim.of("fast.request", lane="cp") if e.seq > 0][-1:]
        sim.rep_says("I can offer you a lower price.")  # lands while it streams
        await sim.vt.run_for(500)
        go.set()
        await sim.vt.run_for(10_000)
        newest = sim.of("utt.final", text="I can offer you a lower price.")[0]
        (cancel,) = sim.of("fast.cancelled", reason="partner")
        assert cancel.payload["gen_id"] == first.payload["gen_id"]
        assert newest.event_id in cancel.cause_ids
        stale = {
            e.payload["utt_id"]
            for e in sim.of("fast.sentence", gen_id=first.payload["gen_id"])
        }
        heard = sim.of("utt.delivered", lane="cp")
        assert not [e for e in heard if e.payload["utt_id"] in stale]
        assert [e for e in heard if e.seq > cancel.seq]  # the re-run answers
        await sim.stop()

    arun(case())


def test_a_rerun_is_said_even_if_the_rep_spoke_again(tmp_path: Path) -> None:
    """Every FastC call is held until the test lets it go, and the rep speaks
    during every generation: drops and said turns alternate, never two drops
    in a row, so FastC is heard while the rep keeps talking."""

    async def case() -> None:
        tickets, moved = [-1], asyncio.Event()  # -1: open (the opening turns)

        async def held() -> None:  # each FastC call takes one ticket
            while tickets[0] == 0:
                moved.clear()
                await moved.wait()
            if tickets[0] > 0:
                tickets[0] -= 1

        def let(n: int) -> None:
            tickets[0] = n
            moved.set()

        sim = Sim(tmp_path, gates={"fast_cp": held})
        await sim.start()
        await sim.vt.run_for(5_000)
        let(0)
        sim.rep_says("Zero.")
        await sim.vt.run_for(500)  # its generation is held in flight
        zero = sim.of("utt.final", text="Zero.")[0]
        for line in ("One.", "Two.", "Three.", "Four.", "Five."):
            sim.rep_says(line)  # lands while the held generation is in flight
            await sim.vt.run_for(500)
            let(1)
            await sim.vt.run_for(500)
        let(-1)
        await sim.vt.run_for(20_000)
        cancels = {
            str(e.payload["gen_id"]) for e in sim.of("fast.cancelled", reason="partner")
        }
        assert cancels, "no turn was overtaken: the test is vacuous"
        chain = [t for t in sim.of("fast.turn", lane="cp") if t.seq > zero.seq]
        dropped = [str(t.payload["gen_id"]) in cancels for t in chain]
        assert not any(a and b for a, b in pairwise(dropped)), dropped
        heard = [e for e in sim.of("utt.delivered", lane="cp") if e.seq > zero.seq]
        assert len(heard) >= 2, "FastC was starved while the rep kept talking"
        await sim.stop()

    arun(case())
