"""The partner-turn fence (S1-SYS-23, option C): a rep line that lands while an
accept is in flight raises a fence; the accept waits (never revoked ``fence``
for it) until a Slow step that saw the rep's turn completes, then Guard
revalidates. A user fence still revokes it; its expiry fails closed; and an
accept still waiting when the session ends gets no terminal event (N3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.concurrency.harness import Sim, granted, slots, terms
from tests.concurrency.test_cases import FIX, Valve, arun
from tests.support.sessions import act

from proxyloop.contract.events import Event
from proxyloop.contract.llm import LLMUnavailable
from proxyloop.kernel.channels import Incoming
from proxyloop.kernel.speaker import speech_s

GONE = "One moment.\n@slow: the rep says that offer is gone"  # FastC's relay
DECLINE = act("gone", {"tool": "decline_offer", "offer_ref": "o1"})
ELSE = "Anything else?"


def _one(sim: Sim, type_: str, **match: object) -> Event:
    (e,) = sim.of(type_, **match)
    return e


def _ends(sim: Sim, cap: str = "cap-1") -> list[Event]:
    return sim.of("speak.released", cap_id=cap) + sim.of("speak.revoked", cap_id=cap)


async def _queued_then_rep(sim: Sim, text: str) -> Event:
    """A granted accept queued while the rep composes (option A holds it),
    then the rep's line lands: the partner fence it raises."""
    await sim.start()
    await granted(sim)
    sim.rep_composes()
    assert sim.accept().startswith("accept_offer: accept line queued")
    await sim.vt.run_for(1_000)
    assert _ends(sim) == []
    sim.rep_done(text)
    await sim.vt.run_for(50)
    said = _one(sim, "utt.final", text=text)
    fence = _one(sim, "authority.fence", op="raised")
    assert fence.cause_ids == (said.event_id,) and fence.seq == said.seq + 1
    assert fence.payload["utt_id"] == said.payload["utt_id"]
    return fence


@pytest.mark.parametrize("change", ["decline", "revise"])
def test_a_a_correction_during_a_queued_accept_revokes_it(
    tmp_path: Path, change: str
) -> None:
    """decline: FastC relays the correction and the Slow step that saw it
    declines the offer; revise: Slow re-records it while FastC is still out."""

    async def case() -> None:
        fast_cp = Valve()
        mark = {"fast_cp": ("that offer is gone", GONE)}
        mark |= {"slow": ("that offer is gone", DECLINE)}
        until = mark if change == "decline" else None
        sim = Sim(tmp_path, gates={"fast_cp": fast_cp}, until=until)
        if change == "revise":
            fast_cp.open.clear()
        fix = FIX if change == "decline" else terms(75)  # the new terms, whole
        fence = await _queued_then_rep(sim, fix)
        if change == "revise":
            said = _one(sim, "utt.final", text=fix).payload["utt_id"]
            record = {"tool": "record_offer", "offer_ref": "o1"}
            out = sim.act(record | {"offer_slots": slots(75, str(said))})
            assert out[0].startswith("record_offer: recorded"), out
            await sim.vt.run_for(1_000)
            assert _ends(sim) == []  # still waiting: FastC has not answered
            fast_cp.open.set()
        await sim.vt.run_for(15_000)
        cleared = _one(sim, "authority.fence", op="cleared")
        assert cleared.payload["fence_id"] == fence.payload["fence_id"]
        step = sim.events[_seq(sim, cleared.cause_ids[0])]
        assert step.type == "slow.step.completed"
        (revoked,) = _ends(sim)
        why = "offer_closed" if change == "decline" else "terms_changed"
        assert revoked.type == "speak.revoked" and revoked.payload["reason"] == why
        assert revoked.seq > cleared.seq
        if change == "decline":  # the step that cleared the fence declined
            (declined,) = sim.of("speak.verbatim", kind="decline")
            assert fence.seq < declined.seq < cleared.seq
        assert not sim.of("status.changed", status="COMMITTED")
        await sim.stop()

    arun(case())


def test_b_a_harmless_rep_turn_delays_the_accept_until_the_fence_clears(
    tmp_path: Path,
) -> None:
    async def case() -> None:
        sim = Sim(tmp_path)
        fence = await _queued_then_rep(sim, ELSE)
        await sim.vt.run_for(15_000)
        cleared = _one(sim, "authority.fence", op="cleared")
        assert cleared.payload["fence_id"] == fence.payload["fence_id"]
        (released,) = _ends(sim)
        assert released.type == "speak.released" and released.seq > cleared.seq
        _one(sim, "status.changed", status="COMMITTED")
        await sim.stop()

    arun(case())


def test_c_a_user_fence_during_the_wait_still_revokes_the_accept(
    tmp_path: Path,
) -> None:
    async def case() -> None:
        fast_cp, fast_user = Valve(), Valve()
        gates = {"fast_cp": fast_cp, "fast_user": fast_user}
        sim = Sim(tmp_path, gates=gates)
        fast_cp.open.clear()  # the partner fence stays up
        await _queued_then_rep(sim, ELSE)
        await sim.vt.run_for(2_000)
        assert _ends(sim) == []  # waiting, not revoked for the partner fence
        fast_user.open.clear()
        sim.user_says("Stop, do not accept anything.")
        await sim.vt.run_for(100)
        (user_fence,) = [
            f
            for f in sim.of("authority.fence", op="raised")
            if sim.events[_seq(sim, f.cause_ids[0])].type == "user.msg"
        ]
        (revoked,) = _ends(sim)
        assert revoked.type == "speak.revoked" and revoked.payload["reason"] == "fence"
        assert revoked.seq > user_fence.seq
        fast_cp.open.set()
        fast_user.open.set()
        await sim.vt.run_for(15_000)
        assert len(_ends(sim)) == 1 and sim.bb.fences == ()
        await sim.stop()

    arun(case())


def test_d_an_accept_outwaited_by_a_partner_fence_is_revoked_expired_once(
    tmp_path: Path,
) -> None:
    async def case() -> None:
        fast_cp = Valve()
        sim = Sim(tmp_path, gates={"fast_cp": fast_cp})
        fast_cp.open.clear()  # FastC never answers: the fence never binds
        await _queued_then_rep(sim, ELSE)
        (cap,) = sim.bb.capabilities.values()
        line = _one(sim, "speak.verbatim", kind="accept")
        speech = round(1000 * speech_s(str(line.payload["text"])))
        await sim.vt.run_for(cap.expires_ms - sim.vt.monotonic_ms() + 1_000)
        (revoked,) = _ends(sim)
        assert (
            revoked.type == "speak.revoked" and revoked.payload["reason"] == "expired"
        )
        assert revoked.t_ms < cap.expires_ms <= revoked.t_ms + speech
        assert sim.bb.fences != ()  # it expired under the fence
        fast_cp.open.set()  # the fence clears later: nothing more for the line
        await sim.vt.run_for(15_000)
        assert _ends(sim) == [revoked] and sim.bb.fences == ()
        assert sim.bb.capabilities == {}
        await sim.stop()

    arun(case())


def test_e_a_rep_turn_with_no_accept_in_flight_raises_no_fence(
    tmp_path: Path,
) -> None:
    async def case() -> None:
        sim = Sim(tmp_path)
        await sim.start()
        await granted(sim)  # the offer and its read-back: no accept yet
        sim.rep_says(ELSE)
        await sim.vt.run_for(3_000)
        assert sim.accept().startswith("accept_offer: accept line queued")
        await sim.vt.run_for(15_000)
        _one(sim, "speak.released", cap_id="cap-1")  # released and heard whole
        sim.rep_says("Great, that is done.")
        await sim.vt.run_for(3_000)
        assert sim.of("utt.final", text="Great, that is done.")
        assert sim.of("authority.fence") == []
        await sim.stop()

    arun(case())


def test_a_call_closed_during_the_wait_revokes_the_accept_at_once(
    tmp_path: Path,
) -> None:  # the closing line raises no fence; chan.closed wakes the wait
    async def case() -> None:
        fast_cp = Valve()
        sim = Sim(tmp_path, gates={"fast_cp": fast_cp})
        fast_cp.open.clear()
        await _queued_then_rep(sim, ELSE)
        await sim.vt.run_for(1_000)
        sim.rep.incoming.put_nowait(Incoming((("Goodbye.", None),), end="closed"))
        await sim.vt.run_for(100)
        closed = _one(sim, "chan.closed")
        (revoked,) = _ends(sim)
        assert revoked.payload["reason"] == "call_closed" and revoked.seq > closed.seq
        assert len(sim.of("authority.fence", op="raised")) == 1
        await sim.stop()

    arun(case())


@pytest.mark.parametrize("end", ["hangup", "llm_unavailable"])
def test_f_an_accept_waiting_at_session_end_gets_no_terminal_event(
    tmp_path: Path, end: str
) -> None:  # N3 (main root decision): fail closed, pinned here, not changed
    async def case() -> None:
        fast_cp = Valve()
        sim = Sim(tmp_path, gates={"fast_cp": fast_cp})
        fast_cp.open.clear()
        await _queued_then_rep(sim, ELSE)
        await sim.vt.run_for(1_000)
        assert _ends(sim) == []  # waiting on the partner fence
        if end == "hangup":
            sim.rep.incoming.put_nowait(Incoming((("Bye.", None),), end="hangup"))
        else:  # FastC's endpoint dies as it answers the rep's line
            sim.llms["fast_cp"]._dead = True  # pyright: ignore[reportPrivateUsage]
            fast_cp.open.set()
        await sim.vt.run_for(1_000)
        run = sim._run  # pyright: ignore[reportPrivateUsage]
        assert run is not None and run.done()
        died = run.exception()  # a hang-up ends it; a dead endpoint re-raises
        assert died is None if end == "hangup" else isinstance(died, LLMUnavailable)
        ended = sim.events[-1]
        assert ended.type == "session.ended"
        assert ended.payload["reason"] == ("abandoned" if end == "hangup" else end)
        assert _ends(sim) == []  # no speak.released or speak.revoked
        assert not sim.of("utt.delivered", utt_id=f"accept-{_accept_seq(sim)}")

    arun(case())


def _seq(sim: Sim, event_id: str) -> int:
    return next(e.seq for e in sim.events if e.event_id == event_id)


def _accept_seq(sim: Sim) -> int:
    return _one(sim, "speak.verbatim", kind="accept").seq
