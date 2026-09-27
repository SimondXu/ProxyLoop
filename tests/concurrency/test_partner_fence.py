"""The partner-turn fence (S1-SYS-23, option C) under ``slow_view=relay_only``
(ADR-0016 note: this mode keeps S1-SYS-23's rule; ``transcript`` mode is in
``test_partner_fence_transcript``): a rep line that lands while an accept is in
flight raises a fence; the accept waits (never revoked ``fence`` for it) until
a Slow step that saw FastC's turn on it completes, then Guard revalidates. A
user fence still revokes it; its expiry fails closed; and an accept still
waiting when the session ends gets no terminal event (N3)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from tests.concurrency.harness import A5, ACCEPT, Sim, SlowGate, granted, slots, terms
from tests.concurrency.test_cases import FIX, Valve, arun
from tests.support.sessions import act

from proxyloop.contract.events import Event
from proxyloop.contract.llm import LLMUnavailable
from proxyloop.evidence.check import check_path
from proxyloop.kernel.channels import Incoming
from proxyloop.kernel.speaker import speech_s

GONE = "One moment.\n@slow: the rep says that offer is gone"  # FastC's relay
DECLINE = act("gone", {"tool": "decline_offer", "offer_ref": "o1"})
ELSE = "Anything else?"


def _sim(tmp_path: Path, *args: Any, **kwargs: Any) -> Sim:
    return Sim(tmp_path, *args, cfg=A5, **kwargs)


def _one(sim: Sim, type_: str, **match: object) -> Event:
    (e,) = sim.of(type_, **match)
    return e


def _fence_of(sim: Sim, said: Event) -> Event:
    """The fence raised for the line ``said`` (its first cause)."""
    (fence,) = [
        f
        for f in sim.of("authority.fence", op="raised")
        if f.cause_ids[0] == said.event_id
    ]
    return fence


def _cleared(sim: Sim, fence: Event) -> Event:
    return _one(
        sim, "authority.fence", op="cleared", fence_id=fence.payload["fence_id"]
    )


def _ends(sim: Sim, cap: str = "cap-1") -> list[Event]:
    return sim.of("speak.released", cap_id=cap) + sim.of("speak.revoked", cap_id=cap)


async def _queued_then_rep(sim: Sim, text: str, hold: Valve | None = None) -> Event:
    """A granted accept queued while the rep composes (option A holds it),
    then the rep's line lands: the partner fence it raises. ``hold``: FastC
    is held from the accept on (it answered the offer's lines)."""
    await sim.start()
    await granted(sim)
    if hold is not None:
        hold.open.clear()
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
        sim = _sim(tmp_path, gates={"fast_cp": fast_cp}, until=until)
        fix = FIX if change == "decline" else terms(75)  # the new terms, whole
        hold = fast_cp if change == "revise" else None  # FastC is still out
        fence = await _queued_then_rep(sim, fix, hold)
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
        assert check_path(sim.k.path, "offline").ok

    arun(case())


def test_b_a_harmless_rep_turn_delays_the_accept_until_the_fence_clears(
    tmp_path: Path,
) -> None:
    async def case() -> None:
        sim = _sim(tmp_path)
        fence = await _queued_then_rep(sim, ELSE)
        await sim.vt.run_for(15_000)
        cleared = _one(sim, "authority.fence", op="cleared")
        assert cleared.payload["fence_id"] == fence.payload["fence_id"]
        (released,) = _ends(sim)
        assert released.type == "speak.released" and released.seq > cleared.seq
        _one(sim, "status.changed", status="COMMITTED")
        await sim.stop()
        assert check_path(sim.k.path, "offline").ok

    arun(case())


def test_c_a_user_fence_during_the_wait_still_revokes_the_accept(
    tmp_path: Path,
) -> None:
    async def case() -> None:
        fast_cp, fast_user = Valve(), Valve()
        gates = {"fast_cp": fast_cp, "fast_user": fast_user}
        sim = _sim(tmp_path, gates=gates)
        await _queued_then_rep(sim, ELSE, fast_cp)  # the partner fence stays up
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
        sim = _sim(tmp_path, gates={"fast_cp": fast_cp})
        await _queued_then_rep(
            sim, ELSE, fast_cp
        )  # FastC never answers: the fence never binds
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
        sim = _sim(tmp_path)
        await sim.start()
        await granted(sim)  # the offer and its read-back: no accept yet
        sim.rep_says(ELSE)
        await sim.vt.run_for(3_000)  # FastC answers it
        assert sim.of("authority.fence") == []  # no fence as it lands
        assert sim.k.slow is not None
        sim.k.slow.wake("fence")  # a step that sees FastC's turn: covered
        await sim.vt.run_for(1_000)
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
        sim = _sim(tmp_path, gates={"fast_cp": fast_cp})
        await _queued_then_rep(sim, ELSE, fast_cp)
        await sim.vt.run_for(1_000)
        sim.rep.incoming.put_nowait(Incoming((("Goodbye.", None),), end="closed"))
        await sim.vt.run_for(100)
        closed = _one(sim, "chan.closed")
        (revoked,) = _ends(sim)
        assert revoked.payload["reason"] == "call_closed" and revoked.seq > closed.seq
        assert len(sim.of("authority.fence", op="raised")) == 1
        cleared = _one(sim, "authority.fence", op="cleared")  # FastC never answers
        assert cleared.cause_ids == (closed.event_id,) and sim.bb.fences == ()
        await sim.stop()

    arun(case())


@pytest.mark.parametrize("end", ["hangup", "llm_unavailable"])
def test_f_an_accept_waiting_at_session_end_gets_no_terminal_event(
    tmp_path: Path, end: str
) -> None:  # N3 (main root decision): fail closed, pinned here, not changed
    async def case() -> None:
        fast_cp = Valve()
        sim = _sim(tmp_path, gates={"fast_cp": fast_cp})
        await _queued_then_rep(sim, ELSE, fast_cp)
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
        assert check_path(sim.k.path, "offline").ok  # a valid bundle all the same

    arun(case())


def _seq(sim: Sim, event_id: str) -> int:
    return next(e.seq for e in sim.events if e.event_id == event_id)


def _accept_seq(sim: Sim) -> int:
    return _one(sim, "speak.verbatim", kind="accept").seq


@pytest.mark.parametrize("change", ["none", "decline"])
def test_a_correction_before_the_authorising_step_mints_fences_the_accept(
    tmp_path: Path, change: str
) -> None:
    """Review M1: the rep's correction lands after the basis of the Slow step
    that then authorises the accept (no accept in flight yet, so no fence at
    the line). The mint raises the fence for it; the accept waits for a step
    that saw the line: released if it changed nothing, else revoked."""

    async def case() -> None:
        sim = _sim(tmp_path, {"slow": [ACCEPT]})
        await sim.start()
        gate = SlowGate(sim)
        await sim.offer()
        card = sim.card()
        gate.let(0)  # the step the grant wakes is in flight, held
        sim.post(card)
        await sim.vt.run_for(100)
        step = sim.of("slow.step.started")[-1]
        sim.rep_says(FIX)
        await sim.vt.run_for(3_000)  # FastC answers the line
        said = _one(sim, "utt.final", text=FIX)
        assert int(str(step.payload["basis_seq"])) < said.seq
        assert sim.of("authority.fence") == [] and sim.of("fast.turn", lane="cp")
        gate.let(1)  # that step authorises the accept; the next step is held
        await sim.vt.run_for(100)
        auth = _one(sim, "action.authorized")
        fence = _fence_of(sim, said)
        assert fence.cause_ids == (said.event_id, auth.event_id)
        assert fence.payload["utt_id"] == said.payload["utt_id"]
        for other in sim.of("authority.fence", op="raised"):  # all at the mint
            assert other.cause_ids[1:] == (auth.event_id,)
        await sim.vt.run_for(2_000)
        assert _ends(sim) == []  # waiting for a step that saw the correction
        if change == "decline":
            sim.act({"tool": "decline_offer", "offer_ref": "o1"})
        gate.let(None)
        await sim.vt.run_for(20_000)
        cleared = _cleared(sim, fence)
        saw = sim.events[_seq(sim, cleared.cause_ids[0])]
        assert int(str(saw.payload["basis_seq"])) >= said.seq
        (end,) = _ends(sim)
        assert end.seq > max(c.seq for c in sim.of("authority.fence", op="cleared"))
        if change == "none":
            assert end.type == "speak.released"
        else:
            assert end.type == "speak.revoked"
            assert end.payload["reason"] == "offer_closed"
        await sim.stop()
        assert check_path(sim.k.path, "offline").ok

    arun(case())


def test_an_epoch_bump_ends_a_waiting_accept_at_once(tmp_path: Path) -> None:
    """Review M2: a revoke during the partner-fence wait wakes the accept:
    ``speak.revoked{epoch}`` then, not at the capability's expiry."""

    async def case() -> None:
        fast_cp = Valve()
        sim = _sim(tmp_path, gates={"fast_cp": fast_cp})
        await _queued_then_rep(sim, ELSE, fast_cp)  # the partner fence stays up
        await sim.vt.run_for(500)
        sim.revoke()
        bump = sim.of("authority.epoch")[-1]
        await sim.vt.run_for(100)
        (revoked,) = _ends(sim)
        assert revoked.payload["reason"] == "epoch" and revoked.seq > bump.seq
        assert revoked.t_ms - bump.t_ms < 100
        _one(sim, "status.changed", status="NEEDS_REPLAN")
        await sim.stop()

    arun(case())


def _raised_by(sim: Sim, type_: str) -> Event:
    (fence,) = [
        f
        for f in sim.of("authority.fence", op="raised")
        if sim.events[_seq(sim, f.cause_ids[0])].type == type_
    ]
    return fence


def _up(sim: Sim, fence: Event) -> bool:
    return fence.payload["fence_id"] in {f.fence_id for f in sim.bb.fences}


def test_a_fastc_turn_never_binds_a_user_fence(tmp_path: Path) -> None:
    """Review M3: FastU has not answered the user; FastC answers the rep and
    Slow completes a step after that: the user fence stays up."""

    async def case() -> None:
        fast_user = Valve()
        sim = _sim(tmp_path, gates={"fast_user": fast_user})
        await sim.start()
        await granted(sim)
        fast_user.open.clear()
        sim.user_says("Hold on, stop.")
        await sim.vt.run_for(100)
        user = _raised_by(sim, "user.msg")
        sim.rep_says(ELSE)
        await sim.vt.run_for(3_000)
        turn = sim.of("fast.turn", lane="cp")[-1]
        assert turn.seq > user.seq
        assert sim.k.slow is not None
        sim.k.slow.wake("fence")
        await sim.vt.run_for(1_000)
        step = sim.of("slow.step.completed")[-1]
        assert int(str(step.payload["basis_seq"])) >= turn.seq
        assert _up(sim, user)
        assert sim.accept().startswith("accept_offer: denied: fence_raised")
        fast_user.open.set()
        await sim.stop()

    arun(case())


def test_a_fastu_turn_never_binds_a_partner_fence(tmp_path: Path) -> None:
    """Review M3, the reverse: FastC has not answered the rep; FastU answers
    the user and Slow completes a step after that: the partner fence stays up
    (the user fence clears, and still revoked the accept ``fence``)."""

    async def case() -> None:
        fast_cp = Valve()
        sim = _sim(tmp_path, gates={"fast_cp": fast_cp})
        partner = await _queued_then_rep(sim, ELSE, fast_cp)
        sim.user_says("Thanks, go ahead.")
        await sim.vt.run_for(1_000)
        user = _raised_by(sim, "user.msg")
        turn = sim.of("fast.turn", lane="user")[-1]
        assert turn.seq > user.seq > partner.seq
        assert sim.k.slow is not None
        sim.k.slow.wake("fence")
        await sim.vt.run_for(1_000)
        assert not _up(sim, user) and _up(sim, partner)
        (revoked,) = _ends(sim)
        assert revoked.payload["reason"] == "fence"
        fast_cp.open.set()
        await sim.vt.run_for(15_000)
        assert sim.bb.fences == ()
        await sim.stop()

    arun(case())


class Tickets:
    """A Fast lane's gate: ``let(n)`` lets ``n`` more generations through,
    ``let(None)`` opens it (review probe 10)."""

    def __init__(self) -> None:
        self._n: int | None = None
        self._moved = asyncio.Event()

    def let(self, n: int | None) -> None:
        self._n = n
        self._moved.set()

    async def __call__(self) -> None:
        while self._n == 0:
            self._moved.clear()
            await self._moved.wait()
        if self._n is not None:
            self._n -= 1


def test_a_rep_line_fastc_has_not_answered_fences_the_accept_at_the_mint(
    tmp_path: Path,
) -> None:
    """Review D1: the correction lands before the minting step's basis, but
    FastC has not answered it (nothing relayed to Slow): the mint fences it
    unbound; the accept waits for FastC's turn and a step that saw it."""

    async def case() -> None:
        fast_cp = Valve()
        sim = _sim(tmp_path, {"slow": [ACCEPT]}, gates={"fast_cp": fast_cp})
        await sim.start()
        gate = SlowGate(sim)
        await sim.offer()
        card = sim.card()
        gate.let(0)
        fast_cp.open.clear()
        sim.rep_says(FIX)
        await sim.vt.run_for(500)
        said = _one(sim, "utt.final", text=FIX)
        sim.post(card)
        await sim.vt.run_for(100)
        step = sim.of("slow.step.started")[-1]
        assert int(str(step.payload["basis_seq"])) > said.seq
        gate.let(1)  # that step mints the accept
        await sim.vt.run_for(100)
        auth = _one(sim, "action.authorized")
        fence = _fence_of(sim, said)
        assert fence.cause_ids == (said.event_id, auth.event_id)
        await sim.vt.run_for(5_000)
        assert _ends(sim) == []  # FastC has not answered the line
        fast_cp.open.set()
        gate.let(None)
        await sim.vt.run_for(20_000)
        cleared = _cleared(sim, fence)
        turn = next(t for t in sim.of("fast.turn", lane="cp") if t.seq > said.seq)
        saw = sim.events[_seq(sim, cleared.cause_ids[0])]
        assert int(str(saw.payload["basis_seq"])) >= turn.seq
        (released,) = _ends(sim)
        assert released.type == "speak.released" and released.seq > cleared.seq
        await sim.stop()
        assert check_path(sim.k.path, "offline").ok

    arun(case())


def test_a_fastc_turn_whose_request_missed_the_line_binds_nothing(
    tmp_path: Path,
) -> None:
    """Review D2: a FastC generation requested before the rep's line lands
    after it: its turn does not bind the line's fence, so the accept waits
    for the generation that saw the line."""

    async def case() -> None:
        fast_cp = Tickets()
        sim = _sim(tmp_path, gates={"fast_cp": fast_cp})
        await sim.start()
        await granted(sim)
        fast_cp.let(0)
        sim.rep_says("Let me see.")  # FastC's request for it is held
        await sim.vt.run_for(500)
        old = sim.of("fast.request", lane="cp")[-1]
        sim.rep_composes()
        assert sim.accept().startswith("accept_offer: accept line queued")
        await sim.vt.run_for(500)
        sim.rep_done(FIX)
        await sim.vt.run_for(200)
        said = _one(sim, "utt.final", text=FIX)
        fence = _fence_of(sim, said)
        assert int(str(old.payload["basis_seq"])) < said.seq
        fast_cp.let(1)  # only the old generation answers
        await sim.vt.run_for(500)
        assert sim.of("fast.turn", gen_id=old.payload["gen_id"])
        assert sim.k.slow is not None
        sim.k.slow.wake("fence")
        await sim.vt.run_for(5_000)
        assert _up(sim, fence) and _ends(sim) == []
        fast_cp.let(None)  # the generation that saw the line answers
        await sim.vt.run_for(20_000)
        (released,) = _ends(sim)
        cleared = _cleared(sim, fence)
        assert released.type == "speak.released" and released.seq > cleared.seq
        await sim.stop()

    arun(case())


def test_an_old_fastc_turn_never_covers_a_line_before_the_accept(
    tmp_path: Path,
) -> None:
    """Review round 4 (D-1, the mint-path twin of D2): the rep's line lands
    with no accept in flight; a FastC generation requested before it answers
    after it, and a Slow step completes past that turn. The line is still not
    covered, so the mint fences it and nothing is released until the
    generation that saw it answers and a step sees that."""

    async def case() -> None:
        fast_cp = Tickets()
        sim = _sim(tmp_path, gates={"fast_cp": fast_cp})
        await sim.start()
        await granted(sim)
        fast_cp.let(0)
        sim.rep_says("Let me see.")  # FastC's request for it is held
        await sim.vt.run_for(500)
        old = sim.of("fast.request", lane="cp")[-1]
        sim.rep_says(FIX)
        await sim.vt.run_for(500)
        said = _one(sim, "utt.final", text=FIX)
        assert int(str(old.payload["basis_seq"])) < said.seq
        assert sim.of("authority.fence") == []  # no accept in flight yet
        fast_cp.let(1)  # only the old generation answers
        await sim.vt.run_for(500)
        old_turn = _one(sim, "fast.turn", gen_id=old.payload["gen_id"])
        assert sim.k.slow is not None
        sim.k.slow.wake("fence")
        await sim.vt.run_for(3_000)
        step = sim.of("slow.step.completed")[-1]
        assert int(str(step.payload["basis_seq"])) >= old_turn.seq
        assert sim.accept().startswith("accept_offer: accept line queued")
        auth = _one(sim, "action.authorized")
        fence = _fence_of(sim, said)
        assert fence.cause_ids == (said.event_id, auth.event_id)
        await sim.vt.run_for(15_000)
        assert _up(sim, fence) and _ends(sim) == []  # no turn saw the line
        fast_cp.let(None)  # the generation that saw the line answers
        await sim.vt.run_for(20_000)
        (released,) = _ends(sim)
        assert released.type == "speak.released"
        assert released.seq > _cleared(sim, fence).seq
        await sim.stop()
        assert check_path(sim.k.path, "offline").ok

    arun(case())
