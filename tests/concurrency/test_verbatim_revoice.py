"""S1-SYS-59: a re-run re-voices the GUIDE its cancelled turn voiced. A FastC
turn cancelled ``{verbatim}`` had already voiced its GUIDEs (``s2f.voiced``,
before speaking), so the fold dropped them from ``s2f_pending``; the re-run's
view still shows the newest GUIDE and FastC says it again. The re-run voices
it again (citing its own ``fast.turn``), so ``SlowTools._heard`` anchors the
ask at the re-run's delivery: only while it is still the lane's newest GUIDE,
and only if the re-run acts (R3a). The epoch path is unchanged."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from tests.concurrency.harness import Sim, slots, terms
from tests.concurrency.test_cases import Valve, arun

from proxyloop.contract.events import Event

DECLINED = "we will not take that offer"  # in FastC's prompt once it is heard
FINAL = {"tool": "guide_fast", "move": "ask_final_offer"}


def _caused(sim: Sim, type_: str, cause: str, **match: object) -> list[Event]:
    return [e for e in sim.of(type_, **match) if e.cause_ids[-1] == cause]


def _after(sim: Sim, type_: str, seq: int) -> list[Event]:  # cp's, past seq
    return [e for e in sim.of(type_, lane="cp") if e.seq > seq]


def _guide_ids(sim: Sim) -> list[str]:
    return [str(e.payload["msg_id"]) for e in sim.of("s2f.msg", type="GUIDE")]


def _once_per_turn(sim: Sim) -> None:
    """N4: no turn voices one message twice."""
    pairs = Counter((e.cause_ids[0], e.payload["msg_id"]) for e in sim.of("s2f.voiced"))
    assert all(n == 1 for n in pairs.values()), pairs


async def _guided_while_declining(
    sim: Sim, *calls: Mapping[str, object], second: bool = False
) -> Event:
    """The decline of o1 has the floor (released, not yet heard) when Slow
    sends ``calls``: FastC's request is made between the release and the
    delivery, so its turn (which voices the GUIDE) is cancelled ``{verbatim}``.
    ``second``: Slow sends the same calls again before the cancellation."""
    assert "queued" in sim.act({"tool": "decline_offer", "offer_ref": "o1"})[0]
    await sim.vt.run_for(500)
    (said,) = sim.of("speak.verbatim", kind="decline")
    (released,) = _caused(sim, "speak.released", said.event_id)
    assert "guide" in sim.act(*calls)[-1]
    await sim.vt.run_for(100)
    (asked,) = _after(sim, "fast.request", released.seq)
    if second:
        assert "guide" in sim.act(*calls)[-1]
    assert not _caused(sim, "utt.delivered", released.event_id)
    await sim.vt.run_for(20_000)
    return asked


async def _declining(sim: Sim) -> None:
    await sim.start()
    await sim.offer("o1", 68)
    await sim.vt.run_for(10_000)
    assert not sim.k.speakers["cp"].speaking


def _rerun(sim: Sim, asked: Event) -> tuple[Event, Event]:
    """The cancelled turn of ``asked`` and its re-run's turn."""
    gen = asked.payload["gen_id"]
    (turn,) = sim.of("fast.turn", gen_id=gen)
    (cancelled,) = sim.of("fast.cancelled", gen_id=gen)
    assert cancelled.payload["reason"] == "verbatim"
    rerun = _after(sim, "fast.turn", cancelled.seq)[0]
    return turn, rerun


def _heard_at(sim: Sim, rerun: Event) -> int:
    """The first cp line after the re-run's last delivered line."""
    gen = rerun.payload["gen_id"]
    utts = [str(e.payload["utt_id"]) for e in sim.of("fast.sentence", gen_id=gen)]
    assert utts
    for u in utts:  # delivered whole
        (d,) = sim.of("utt.delivered", utt_id=u)
        assert d.payload["interrupted"] is False
    ids = [x.utt_id for x in sim.bb.channels["cp"].lines]
    return ids.index(utts[-1]) + 1


def _revoiced(sim: Sim, msg: str, turn: Event, rerun: Event) -> None:
    """``msg`` voiced once by the cancelled turn and once by its re-run."""
    voiced = sim.of("s2f.voiced", msg_id=msg)
    assert [e.cause_ids for e in voiced] == [(turn.event_id,), (rerun.event_id,)]
    assert voiced[1].payload["gen_id"] == rerun.payload["gen_id"]


def test_r1_a_readback_ask_is_revoiced_and_anchors_after_the_rerun(
    tmp_path: Path,
) -> None:
    """R1: the ask_readback of o2 is voiced by a turn cancelled ``{verbatim}``;
    its re-run voices it again, and the read-back window of o2 opens at the
    first cp line after the re-run's delivery: the rep's earlier statement of
    o2's terms does not read it back, a later one does."""

    async def case() -> None:
        sim = Sim(tmp_path)
        await _declining(sim)
        sim.rep_says(terms(60))  # o2, stated before the ask
        await sim.vt.run_for(10_000)
        stated = [x for x in sim.bb.channels["cp"].lines if x.speaker == "partner"]
        record: dict[str, object] = {"tool": "record_offer", "offer_ref": "o2"}
        record["offer_slots"] = slots(60, stated[-1].utt_id)
        ask = {"tool": "guide_fast", "move": "ask_readback", "slots": ["offer:o2"]}
        asked = await _guided_while_declining(sim, record, ask)
        msg = _guide_ids(sim)[-1]
        turn, rerun = _rerun(sim, asked)
        _revoiced(sim, msg, turn, rerun)
        at = _heard_at(sim, rerun)
        tools = sim.tools
        assert tools._heard()[msg] == at  # pyright: ignore[reportPrivateUsage]
        windows = tools._windows(tools._heard())  # pyright: ignore[reportPrivateUsage]
        assert [w.at for w in windows["o2"]] == [at]
        tools.readback()  # the statement before the re-run's delivery: no read-back
        assert "confirmed" not in {s.status for s in sim.bb.public.offers["o2"].slots}
        sim.rep_says(terms(60))
        await sim.vt.run_for(3_000)
        tools.readback()
        assert {s.status for s in sim.bb.public.offers["o2"].slots} == {"confirmed"}
        _once_per_turn(sim)
        await sim.stop()

    arun(case())


def test_r2_a_final_offer_ask_is_revoiced_and_heard_after_the_rerun(
    tmp_path: Path,
) -> None:
    """R2: the ask_final_offer voiced by a cancelled turn is voiced again by
    its re-run; ``_heard`` (which S1-SYS-57's ``asked_final`` reads) maps it
    to the first cp line after the re-run's delivery."""

    async def case() -> None:
        sim = Sim(tmp_path)
        await _declining(sim)
        asked = await _guided_while_declining(sim, FINAL)
        (msg,) = _guide_ids(sim)[-1:]
        turn, rerun = _rerun(sim, asked)
        _revoiced(sim, msg, turn, rerun)
        at = _heard_at(sim, rerun)
        (decline,) = sim.of("speak.verbatim", kind="decline")
        ids = [x.utt_id for x in sim.bb.channels["cp"].lines]
        assert at > ids.index(f"decline-{decline.seq}") + 1  # after the decline
        assert sim.tools._heard()[msg] == at  # pyright: ignore[reportPrivateUsage]
        _once_per_turn(sim)
        await sim.stop()

    arun(case())


def test_n1_a_superseded_guide_is_not_revoiced(tmp_path: Path) -> None:
    """N1: Slow sends an equal GUIDE (a new message) before the cancellation:
    the re-run voices the newer one from ``s2f_pending``, never the older."""

    async def case() -> None:
        sim = Sim(tmp_path)
        await _declining(sim)
        asked = await _guided_while_declining(sim, FINAL, second=True)
        old, new = _guide_ids(sim)[-2:]
        turn, rerun = _rerun(sim, asked)
        (voiced,) = sim.of("s2f.voiced", msg_id=old)
        assert voiced.cause_ids == (turn.event_id,)
        (voiced,) = sim.of("s2f.voiced", msg_id=new)
        assert voiced.cause_ids == (rerun.event_id,)
        _once_per_turn(sim)
        await sim.stop()

    arun(case())


def test_n2_the_epoch_path_voices_the_pending_guide_once(tmp_path: Path) -> None:
    """N2: a generation cancelled ``{epoch}`` voiced nothing; its re-run voices
    the pending GUIDE once, as before."""

    async def case() -> None:
        fast_cp = Valve()
        sim = Sim(tmp_path, gates={"fast_cp": fast_cp})
        await sim.start()
        fast_cp.open.clear()
        sim.act({"tool": "guide_fast", "move": "ask_discount"})
        await sim.vt.run_for(100)
        (asked,) = sim.of("fast.request", lane="cp", trigger="guidance")
        sim.revoke()
        fast_cp.open.set()
        await sim.vt.run_for(10_000)
        gen = asked.payload["gen_id"]
        (cancelled,) = sim.of("fast.cancelled", gen_id=gen)
        assert cancelled.payload["reason"] == "epoch"
        assert not sim.of("fast.turn", gen_id=gen)
        rerun = _after(sim, "fast.turn", cancelled.seq)[0]
        (msg,) = _guide_ids(sim)
        (voiced,) = sim.of("s2f.voiced", msg_id=msg)
        assert voiced.cause_ids == (rerun.event_id,)
        _once_per_turn(sim)
        await sim.stop()

    arun(case())


def test_n3_an_empty_rerun_voices_no_carried_guide(tmp_path: Path) -> None:
    """N3: the re-run (its view holds the decline line) says nothing: it
    voices no GUIDE, and R3a counts no re-trigger for the carried one."""

    async def case() -> None:
        sim = Sim(tmp_path, until={"fast_cp": (DECLINED, "")})
        await _declining(sim)
        asked = await _guided_while_declining(sim, FINAL)
        (msg,) = _guide_ids(sim)[-1:]
        turn, rerun = _rerun(sim, asked)
        items = cast(list[dict[str, object]], rerun.payload["items"])
        assert all(i["kind"] == "issue" for i in items)
        (voiced,) = sim.of("s2f.voiced", msg_id=msg)
        assert voiced.cause_ids == (turn.event_id,)
        assert msg not in sim.tools._heard()  # pyright: ignore[reportPrivateUsage]
        assert sim.k.counts["guide_retrigger"] == 0
        _once_per_turn(sim)
        await sim.stop()

    arun(case())
