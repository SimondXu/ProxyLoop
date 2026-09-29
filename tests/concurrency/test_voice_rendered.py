"""S1-SYS-67: a turn voices only the GUIDE its view rendered. ``view_cp`` renders
only the lane's newest GUIDE (``guidance_cp``), so when Slow sends GUIDE A and
then GUIDE B before FastC's next turn, that turn voices B alone: A gets no
``s2f.voiced``, so it anchors no read-back window (#219), no ``asked_final``
(#227) and no heard lever. ``slow.heard.fates`` calls A dead (superseded) once
no generation whose view rendered it is still open, so ``final_pending`` is
False and Slow may ask again. #230's re-voicing is in test_verbatim_revoice."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from tests.concurrency.harness import Sim, slots, terms
from tests.concurrency.test_cases import Valve, arun

from proxyloop.contract.events import Event
from proxyloop.slow import heard

FINAL = {"tool": "guide_fast", "move": "ask_final_offer"}
DISCOUNT = {"tool": "guide_fast", "move": "ask_discount"}


def _guides(sim: Sim) -> list[str]:
    return [str(e.payload["msg_id"]) for e in sim.of("s2f.msg", type="GUIDE")]


def _fates(sim: Sim) -> dict[str, heard.Fate]:
    return heard.fates(sim.events, sim.bb.channels["cp"].lines)


def _guide_turns(sim: Sim) -> list[Event]:
    """cp turns of generations requested on the ``guidance`` trigger."""
    gens = {e.payload["gen_id"] for e in sim.of("fast.request", trigger="guidance")}
    return [e for e in sim.of("fast.turn", lane="cp") if e.payload["gen_id"] in gens]


async def _two_guides(sim: Sim, *calls: Mapping[str, object]) -> tuple[str, str]:
    """Slow sends ``calls`` in one step (the last two are GUIDEs A and B, both
    pending when FastC's next generation starts); FastC's turn plays out."""
    out = sim.act(*calls)
    assert all("sent" in line for line in out[-2:]), out
    await sim.vt.run_for(20_000)
    a, b = _guides(sim)[-2:]
    return a, b


def _voices_only(sim: Sim, a: str, b: str) -> None:
    (turn,) = _guide_turns(sim)
    assert not sim.of("s2f.voiced", msg_id=a)
    (voiced,) = sim.of("s2f.voiced", msg_id=b)
    assert voiced.cause_ids == (turn.event_id,)
    fates = _fates(sim)
    assert fates[a] == heard.Fate("dead", None, superseded=True)  # never heard
    assert fates[b].state == "heard"
    assert a not in sim.tools._heard()  # pyright: ignore[reportPrivateUsage]


def test_s1_a_superseded_readback_ask_opens_no_window(tmp_path: Path) -> None:
    """S1: ask_readback of o1 (A), then ask_final_offer (B): the turn voices B
    only, no read-back window opens at A, and the rep's restatement after the
    turn confirms no slot of o1."""

    async def case() -> None:
        sim = Sim(tmp_path)
        await sim.start()
        sim.rep_says(terms(60))
        await sim.vt.run_for(10_000)
        stated = [x for x in sim.bb.channels["cp"].lines if x.speaker == "partner"]
        record: dict[str, object] = {"tool": "record_offer", "offer_ref": "o1"}
        record["offer_slots"] = slots(60, stated[-1].utt_id)
        ask = {"tool": "guide_fast", "move": "ask_readback", "slots": ["offer:o1"]}
        a, b = await _two_guides(sim, record, ask, FINAL)
        _voices_only(sim, a, b)
        tools = sim.tools
        windows = tools._windows(tools._heard())  # pyright: ignore[reportPrivateUsage]
        assert windows["o1"] == []
        sim.rep_says(terms(60))
        await sim.vt.run_for(3_000)
        tools.readback()
        assert "confirmed" not in {s.status for s in sim.bb.public.offers["o1"].slots}
        await sim.stop()

    arun(case())


def test_s2_a_superseded_final_ask_is_not_asked_and_not_pending(
    tmp_path: Path,
) -> None:
    """S2: ask_final_offer (A), then ask_discount (B): A is never voiced, so
    ``asked_final`` stays None, and ``final_pending`` is False (A is dead)."""

    async def case() -> None:
        sim = Sim(tmp_path)
        await sim.start()
        a, b = await _two_guides(sim, FINAL, DISCOUNT)
        _voices_only(sim, a, b)
        assert sim.tools.final_asks == [a]
        assert sim.tools.asked_final is None
        assert sim.tools.final_pending is False
        await sim.stop()

    arun(case())


def test_s3_a_superseded_discount_ask_is_never_voiced(tmp_path: Path) -> None:
    """S3: ask_discount (A), then ask_final_offer (B): the ask is never voiced
    and its fate is dead (available again), never heard."""

    async def case() -> None:
        sim = Sim(tmp_path)
        await sim.start()
        a, b = await _two_guides(sim, DISCOUNT, FINAL)
        _voices_only(sim, a, b)
        await sim.stop()

    arun(case())


def test_s5_a_single_pending_guide_is_voiced_by_its_turn(tmp_path: Path) -> None:
    """S5: the common case is unchanged: one pending GUIDE, voiced once by the
    turn whose view rendered it, and heard."""

    async def case() -> None:
        sim = Sim(tmp_path)
        await sim.start()
        assert "sent" in sim.act(FINAL)[-1]
        await sim.vt.run_for(20_000)
        (msg,) = _guides(sim)
        (turn,) = _guide_turns(sim)
        (voiced,) = sim.of("s2f.voiced", msg_id=msg)
        assert voiced.cause_ids == (turn.event_id,)
        assert voiced.payload == {"msg_id": msg, "gen_id": turn.payload["gen_id"]}
        assert _fates(sim)[msg].state == "heard"
        assert sim.tools.asked_final is not None
        await sim.stop()

    arun(case())


def test_s6_a_guide_in_flight_is_not_dead_before_its_turn(tmp_path: Path) -> None:
    """S6: A's generation is streaming (its view rendered A) when Slow sends
    B: A is not called dead while that generation is open (it is still
    pending), and its turn voices A; the next turn voices B."""

    async def case() -> None:
        fast_cp = Valve()
        sim = Sim(tmp_path, gates={"fast_cp": fast_cp})
        await sim.start()
        fast_cp.open.clear()
        assert "sent" in sim.act(FINAL)[-1]
        await sim.vt.run_for(100)
        (asked,) = sim.of("fast.request", lane="cp", trigger="guidance")
        assert "sent" in sim.act(DISCOUNT)[-1]
        await sim.vt.run_for(100)
        a, b = _guides(sim)
        assert a not in _fates(sim)  # neither voiced nor dead: still pending
        assert sim.tools.final_pending is True
        fast_cp.open.set()
        await sim.vt.run_for(20_000)
        first, second = _guide_turns(sim)
        assert first.payload["gen_id"] == asked.payload["gen_id"]
        (voiced,) = sim.of("s2f.voiced", msg_id=a)
        assert voiced.cause_ids == (first.event_id,)
        (voiced,) = sim.of("s2f.voiced", msg_id=b)
        assert voiced.cause_ids == (second.event_id,)
        assert _fates(sim)[a].state == "heard"
        await sim.stop()

    arun(case())
