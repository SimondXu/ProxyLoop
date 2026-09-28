"""The rep's backlog stays bounded when the agent speaks faster than the rep
(ADR-0021). On virtual time, a SimRep whose Ear and Mouth each take seconds
hears an agent turn every second through the kernel's ``SimRepChannel``; every
turn reaches the Ear within one rep round of its delivery, where a queue of
one round per turn would fall further behind with every turn."""

from __future__ import annotations

import asyncio
from pathlib import Path

from tests.concurrency.harness import VirtualTime
from tests.env.bus_sink import BusSink
from tests.support.sessions import fake, patient_task
from tests.support.web_demo import Reactive, rep_ear, rep_mouth

from proxyloop.env.counterparty.simrep import SimRep
from proxyloop.kernel.channels import SimRepChannel

EAR_S, MOUTH_S = 1.5, 1.0
ROUND_MS = round(1000 * (EAR_S + 2 * MOUTH_S))  # the longest here: two lines
IDENTIFY = "Hi, the account holder is Dana Reyes, last four 4821."
ASK = "Could you give me a lower monthly price?"
TURNS = 20


def test_t9_every_turn_reaches_the_ear_within_one_rep_round(tmp_path: Path) -> None:
    async def case() -> None:
        vt, sink = VirtualTime(), BusSink(tmp_path)
        world = sink.world.record
        ear = Reactive(fake("ear", True), rep_ear, vt, vt.sleep, EAR_S, world)
        mouth = Reactive(fake("mouth", True), rep_mouth, vt, vt.sleep, MOUTH_S, world)
        channel = SimRepChannel(SimRep(patient_task(), ear, mouth, sink.world))
        said: dict[str, int] = {}
        pending: list[asyncio.Future[None]] = []
        for text in [IDENTIFY] + [ASK] * (TURNS - 1):  # one turn a second
            heard = sink.heard(text)
            utt = str(heard.payload["utt_id"])
            said[utt] = vt.monotonic_ms()
            turn = channel.send(text, utt, heard.event_id, said[utt])
            pending.append(asyncio.ensure_future(turn))
            await vt.run_for(1000)
        await vt.run_for(120_000)
        assert all(p.done() for p in pending)
        calls = {e.event_id: e for e in sink.of("llm.call")}
        waits = {
            str(e.payload["utt_id"]): int(calls[e.cause_ids[1]].payload["t_start"])
            - said[str(e.payload["utt_id"])]
            for e in sink.of("rep.ear")
        }
        assert set(waits) == set(said)  # every turn was heard and labelled
        assert max(waits.values()) <= ROUND_MS, waits
        assert ear.calls < TURNS  # the queued turns shared Ear calls

    asyncio.run(case())
