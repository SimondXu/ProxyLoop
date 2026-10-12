"""S1-SYS-102: the sim rep hears each line of an agent turn as its own
utterance. In run 20261012T032545Z-6ebdc0 FastC said a lever and a read-back
ask in one turn; ``Speaker._send`` joined them into one utterance, the Ear
named one act for it (the ask), and the lever was lost. Now each line reaches
the world's SimRep as its own utterance, in delivery order, and the lines of
one turn form one heard block (ADR-0021: one Ear call, one act per utterance,
the policy steps them in order). Every other partner (the SimUser, a person)
still gets the turn as one message, its lines joined. A real ``Kernel`` on
virtual time; FastC, FastU, the Ear, the Mouth and the SimUser answer from
scripts (tests/support)."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from tests.concurrency.harness import Sim
from tests.concurrency.test_cases import arun
from tests.support.sessions import ear, reply

from proxyloop.contract.events import Event
from proxyloop.env.user.simuser import SimReply, SimUser
from proxyloop.kernel.channels import SimUserChannel

ME = "This is Dana Reyes, the account ending 4821."
DISCOUNT = "Can you lower the monthly price?"
TENURE = "Dana has been with Northwind Mobile for six years."
READBACK = "Could you please read back every term of that offer?"
IDENTIFIED = ear(
    "provide_fact",
    facts=[
        {"key": "account.holder_name", "value": "Dana Reyes"},
        {"key": "account.last4", "value": "4821"},
    ],
)
# one act per heard utterance; the disclosure's: other
LEVERS = [ear("ask_discount"), ear("tenure"), ear("ask_readback")]
EARS = [ear("other"), IDENTIFIED, *LEVERS]


def _turn(sim: Sim, first: str) -> list[Event]:
    """The cp ``utt.delivered`` of the FastC turn whose first line is ``first``."""
    (said,) = sim.of("fast.sentence", lane="cp", text=first)
    gen = said.payload["gen_id"]
    utts = {e.payload["utt_id"] for e in sim.of("fast.sentence", gen_id=gen)}
    return [
        e for e in sim.of("utt.delivered", lane="cp") if e.payload["utt_id"] in utts
    ]


def test_a_lever_and_an_ask_in_one_turn_are_one_block_of_two(tmp_path: Path) -> None:
    """The live run's shape: FastC's turn says the tenure lever, then the
    read-back ask. The rep hears both: two ``rep.ear`` (tenure, then
    ask_readback), each citing its own line's ``utt.delivered`` and naming the
    block; the policy steps the lever (the next rung: loyal-2, the final
    offer) and then the ask (that offer read back)."""

    async def case() -> None:
        pair = f"{TENURE}\n{READBACK}"
        scripts = {"fast_cp": [ME, DISCOUNT, pair, "@wait"], "ear": EARS}
        sim = Sim(tmp_path, scripts, rep="sim")
        await sim.start()
        for _ in range(60):
            await sim.vt.run_for(1_000)
            if len(sim.of("rep.ear")) >= 5:
                break
        lever, ask = _turn(sim, TENURE)
        assert [lever.payload["text_heard"], ask.payload["text_heard"]] == [
            TENURE,
            READBACK,
        ]
        ears = {e.cause_ids[0]: e for e in sim.of("rep.ear")}
        assert lever.event_id in ears and ask.event_id in ears  # each cites its own
        heard = [ears[lever.event_id], ears[ask.event_id]]
        assert [e.payload["act"] for e in heard] == ["tenure", "ask_readback"]
        block = [lever.payload["utt_id"], ask.payload["utt_id"]]
        assert [e.payload["heard_utt_ids"] for e in heard] == [block, block]
        (call,) = {e.cause_ids[1:] for e in heard}  # one Ear call for the block
        assert call
        ids = [h.event_id for h in heard]
        got: list[tuple[int, object, object]] = []
        for p in sim.of("rep.policy"):
            if not p.cause_ids or p.cause_ids[0] not in ids:
                continue
            intent = cast(dict[str, object], p.payload["intent"])
            got.append((ids.index(p.cause_ids[0]), intent["kind"], p.payload["rung"]))
        assert got == [(0, "final_offer", 1), (1, "readback", 1)]  # loyal-2
        assert sim.k.channels["cp"].incoming.empty()
        await sim.stop()

    arun(case())


def test_the_simuser_still_hears_a_turn_as_one_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FastU's turn of two lines reaches the SimUser as one message, its lines
    joined, as its last line's ``utt.delivered``: once per turn."""
    heard: list[tuple[str | None, str]] = []
    answer = SimUser.on_agent_message

    async def on_agent_message(
        self: SimUser, text: str | None, cause: str
    ) -> SimReply | None:
        heard.append((text, cause))
        return await answer(self, text, cause)

    monkeypatch.setattr(SimUser, "on_agent_message", on_agent_message)

    async def case() -> None:
        scripts = {
            "simuser": [reply("Please get me a lower price.")],
            "fast_user": ["I will call them now.\nI will tell you what they say."],
        }
        sim = Sim(tmp_path, scripts, user="sim")
        assert isinstance(sim.k.channels["user"], SimUserChannel)
        await sim.start()
        await sim.vt.run_for(30_000)
        turns: dict[str, list[Event]] = {}
        for e in sim.of("utt.delivered", lane="user"):
            turns.setdefault(str(e.payload["utt_id"]).rsplit("-u", 1)[0], []).append(e)
        assert turns and all(len(lines) == 2 for lines in turns.values())
        want = [
            (" ".join(str(e.payload["text_heard"]) for e in lines), lines[-1].event_id)
            for lines in turns.values()
        ]
        assert heard[0][0] is None  # the case opens
        assert heard[1:] == want
        await sim.stop()

    arun(case())
