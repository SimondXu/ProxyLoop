"""S1-SYS-128 (ADR-0034): a standing cp hold ends when its answer arrives,
without a FastC turn. ``cp_hold`` changed only through FastC's ``chan.hold``,
so FastC's prompt kept HOLD STATUS ``offer`` after the rep had heard the
decline (9a7dd3 turn 394, 6ebdc0 turn 428), and ``fact_request`` after the
user's facts were recorded (527345 turn 178). The kernel ends it with
``chan.hold{reason: null, ended}`` (actor ``kernel``), caused by the answer."""

from __future__ import annotations

from pathlib import Path

from tests.concurrency.harness import Sim
from tests.concurrency.test_cases import arun

from proxyloop.contract.events import Event

ASKED = "Shall I put that through for you?"
HOLD_OFFER = "One moment, let me check with my customer.\n@hold offer"
HOLD_FACT = "I am getting that from my customer, please hold.\n@hold fact_request"
KEYS = ["tenure_years", "competitor.name"]


def _caused(sim: Sim, type_: str, cause: Event) -> list[Event]:
    return [e for e in sim.of(type_) if e.cause_ids == (cause.event_id,)]


def _cleared(sim: Sim) -> list[Event]:
    return [e for e in sim.of("chan.hold", reason=None) if e.actor == "kernel"]


async def _held(sim: Sim, reason: str) -> None:
    await sim.start()
    await sim.offer("o1", 68)
    sim.rep_says(ASKED)  # FastC holds from this line on (``until``)
    await sim.vt.run_for(10_000)
    hold = sim.bb.public.cp_hold
    assert hold is not None and hold.reason == reason, hold


def test_a_heard_decline_ends_an_offer_hold(tmp_path: Path) -> None:
    async def case() -> None:
        sim = Sim(tmp_path, until={"fast_cp": (ASKED, HOLD_OFFER)})
        await _held(sim, "offer")
        assert "queued" in sim.act({"tool": "decline_offer", "offer_ref": "o1"})[0]
        await sim.vt.run_for(20_000)
        (said,) = sim.of("speak.verbatim", kind="decline")
        (released,) = _caused(sim, "speak.released", said)
        (heard,) = _caused(sim, "utt.delivered", released)
        (cleared,) = _cleared(sim)
        assert cleared.cause_ids == (heard.event_id,)
        assert cleared.payload == {"lane": "cp", "reason": None, "ended": "decided"}
        assert cleared.seq == heard.seq + 1  # before any FastC turn can render
        assert sim.bb.public.cp_hold is None
        await sim.stop()

    arun(case())


def test_the_users_facts_end_a_fact_hold_once_no_asked_key_waits(
    tmp_path: Path,
) -> None:
    """Slow asked for two keys; the user answered both. A private fact (a
    competitor never goes public, ADR-0033) ends nothing, nor does a heard
    decline; the user's public fact, with no asked key left waiting, does."""

    async def case() -> None:
        sim = Sim(tmp_path, until={"fast_cp": (ASKED, HOLD_FACT)})
        await _held(sim, "fact_request")
        ask = {"tool": "ask_user", "text": "How long, and who?", "keys": KEYS}
        assert "sent" in sim.act(ask)[0]
        await sim.vt.run_for(5_000)
        sim.user_says("Eight years, and Lumen offered me less.")
        await sim.vt.run_for(5_000)
        (msg,) = sim.of("user.msg")
        cite = {"tool": "record_fact", "utt_ref": msg.event_id}
        assert "private" in sim.act(cite | {"key": KEYS[1], "value": "Lumen"})[0]
        assert not _cleared(sim) and sim.bb.public.cp_hold is not None
        assert "queued" in sim.act({"tool": "decline_offer", "offer_ref": "o1"})[0]
        await sim.vt.run_for(20_000)
        assert not _cleared(sim) and sim.bb.public.cp_hold is not None
        assert "public" in sim.act(cite | {"key": KEYS[0], "value": "8"})[0]
        (cleared,) = _cleared(sim)
        (answer,) = sim.of("fact.recorded", key=KEYS[0])
        assert cleared.cause_ids == (answer.event_id,)
        assert cleared.payload["ended"] == "answered"
        assert sim.bb.public.cp_hold is None
        await sim.stop()

    arun(case())
