"""S1-SYS-103 (ADR-0028): the sim approver's decision reaches the SimUser's
chat before its next reply is requested, on a real kernel and virtual time.

Live run 20261012T043721Z-99c310: the approver granted a $69 card (within the
hidden limit) while the chat voice, which knew only the stated budget, said "I
don't approve the $69 offer" and Slow revoked. Now the card's answer is a
``Card:`` line in the user's chat from the moment it is decided.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.concurrency.harness import Sim
from tests.concurrency.test_cases import arun
from tests.concurrency.test_user_fence_grant import (
    ANSWER,
    CHAT,
    NOTICE,
    SILENT,
    Latency,
)
from tests.support.sessions import reply

from proxyloop.contract.bundle import PROMPTS
from proxyloop.contract.events import Event
from proxyloop.env.tasks.loader import load_task
from proxyloop.env.tasks.schema import Task


def _family(name: str, reply_s: float, approver_s: float) -> Task:
    data = load_task(name).model_dump(mode="json")
    data["user"]["reply_delay_s"]["range"] = [reply_s, reply_s]
    data["principal"]["approver_delay_s"]["range"] = [approver_s, approver_s]
    return Task.model_validate(data)


def _simuser_prompts(sim: Sim) -> list[tuple[int, str]]:
    """Each SimUser request (its ``llm.call`` seq, its messages), in order;
    read once the session has stopped and its prompts are written."""
    content = {}
    for raw in (sim.k.path / PROMPTS).read_text().splitlines():
        line = json.loads(raw)
        content[line["sha"]] = str(line["content"])
    calls = sim.of("llm.call", role="simuser")
    return [(e.seq, content[str(e.payload["prompt_sha"])]) for e in calls]


def test_a_sim_decided_card_is_in_the_users_chat_before_their_next_reply(
    tmp_path: Path,
) -> None:
    async def case() -> None:
        scripts = {
            "simuser": [
                reply("Please lower my phone bill."),
                SILENT,  # to "Okay."
                reply(CHAT),  # to the notice
                SILENT,
            ],
            "fast_user": ["Okay.", NOTICE, ANSWER],
        }
        task = _family("x-out-of-envelope-approval", 0.5, 3.0)
        fastu = Latency()
        sim = Sim(tmp_path, scripts, task, "sim", gates={"fast_user": fastu})
        fastu.sim = sim
        await sim.start()
        await sim.offer(dollars=70)  # above the stated 65, within the card limit
        fastu.on = True
        card = sim.card()
        await sim.vt.run_for(10_000)
        await sim.stop()
        (asked,) = sim.of("approval.requested")
        assert sim.of("approval.decided", decision="granted")  # the card held
        (sim_reply,) = sim.of("user.sim", text=CHAT)
        line = f"Card: you approved these terms: {card.readback_text}"
        prompts = _simuser_prompts(sim)
        assert not any(line in c for seq, c in prompts if seq < asked.seq)
        after = [c for seq, c in prompts if seq > asked.seq]
        assert after and all(line in c for c in after)
        # the reply to the notice was asked with the card's answer before it
        (asked_reply,) = [c for seq, c in prompts if seq in _seqs(sim, sim_reply)]
        assert asked_reply.index(line) < asked_reply.index(f"Assistant: {NOTICE}")

    arun(case())


def _seqs(sim: Sim, ev: Event) -> set[int]:
    """The seqs of the ``llm.call`` events ``ev`` cites."""
    cited = set(ev.cause_ids)
    return {e.seq for e in sim.events if e.event_id in cited}
