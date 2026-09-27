"""The concurrency suite (ARCHITECTURE §11, S1-SYS-02): manual-clock cases on a
real kernel, asserting event-level outcomes. Guard decides every rule; the test
plays the partners, the UI and Slow's tool calls."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from tests.concurrency.harness import LONG, Sim, granted
from tests.support.sessions import fake_config, patient_task

from proxyloop.contract.events import ApprovalPost, Event
from proxyloop.contract.state import CaseStatus
from proxyloop.evidence.check import check_path
from proxyloop.guard.authorize import Denial, accept_offer, decide
from proxyloop.guard.readback import readback_text
from proxyloop.kernel.speaker import speech_s


def arun(case: Coroutine[Any, Any, None]) -> None:
    asyncio.run(asyncio.wait_for(case, timeout=30))


class Valve:
    """A gate on a Fast lane's calls: open unless the test closes it."""

    def __init__(self) -> None:
        self.open = asyncio.Event()
        self.open.set()

    async def __call__(self) -> None:
        await self.open.wait()


def _status(sim: Sim) -> CaseStatus:
    return sim.bb.public.status


def _cites(e: Event, other: Event) -> bool:
    return other.event_id in e.cause_ids


def test_a_granted_accept_is_released_heard_and_committed(tmp_path: Path) -> None:
    async def case() -> None:
        sim = Sim(tmp_path)
        await sim.start()
        await granted(sim)
        assert sim.accept().startswith("accept_offer: accept line queued")
        assert _status(sim) is CaseStatus.COMMIT_AUTHORIZED
        await sim.vt.run_for(15_000)
        (line,) = sim.of("speak.verbatim", kind="accept")
        (released,) = sim.of("speak.released", cap_id=line.payload["cap_id"])
        (heard,) = [e for e in sim.of("utt.delivered") if _cites(e, released)]
        assert heard.payload["interrupted"] is False
        (moved,) = sim.of("status.changed", status="COMMITTED")
        assert _cites(moved, heard) and _status(sim) is CaseStatus.COMMITTED
        await sim.stop()
        report = check_path(sim.k.path, "offline")
        assert report.ok, report.failures

    arun(case())


def test_1_a_stop_while_an_accept_is_queued_revokes_it_under_the_fence(
    tmp_path: Path,
) -> None:
    async def case() -> None:
        fast_user = Valve()
        sim = Sim(tmp_path, {"fast_cp": [LONG]}, gates={"fast_user": fast_user})
        await sim.start()
        await granted(sim)
        sim.rep_says("Anything else?")
        await sim.vt.run_for(500)  # FastC holds the floor for ten seconds
        assert sim.accept().startswith("accept_offer: accept line queued")
        fast_user.open.clear()  # FastU has not answered the stop yet
        sim.user_says("Stop, do not accept anything.")
        await sim.vt.run_for(15_000)
        (fence,) = sim.of("authority.fence", op="raised")
        (revoked,) = sim.of("speak.revoked")
        assert revoked.payload["reason"] == "fence" and revoked.seq > fence.seq
        (line,) = sim.of("speak.verbatim", kind="accept")
        assert revoked.payload["cap_id"] == line.payload["cap_id"]
        assert not sim.of("speak.released", cap_id=line.payload["cap_id"])
        heard = [
            e for e in sim.of("utt.delivered") if "accept" in str(e.payload["utt_id"])
        ]
        assert heard == []  # no delivered accept
        (replan,) = sim.of("status.changed", status="NEEDS_REPLAN")
        assert _cites(replan, revoked)  # accept_revoked: only a real revoke
        fast_user.open.set()  # FastU answers; Slow sees it; the fence clears
        await sim.vt.run_for(1_000)
        (cleared,) = sim.of("authority.fence", op="cleared")
        assert sim.bb.fences == () and cleared.payload["fence_id"] == "fence-1"
        assert _status(sim) is CaseStatus.IN_CALL  # replanned after Slow's step
        await sim.stop()

    arun(case())


def test_2_a_correction_during_acceptance_makes_the_card_stale(
    tmp_path: Path,
) -> None:  # the endpoint's pre-check is this decide: a Denial is its 409
    async def case() -> None:
        revoke = "Understood.\n@slow: revoke the user changed the limit"
        sim = Sim(tmp_path, {"fast_user": ["Okay.", revoke]})
        await sim.start()
        await sim.offer()
        card = sim.card()
        await sim.vt.run_for(100)  # FastU voices the card (its first answer)
        sim.user_says("Actually my limit is $60, not $70.")
        await sim.vt.run_for(100)
        (bump,) = sim.of("authority.epoch", reason="f2s_revoke")
        (relay,) = sim.of("f2s.msg", type="REVOKE")
        assert _cites(bump, relay) and sim.bb.epoch == card.authority_epoch + 1
        post = ApprovalPost(
            subject="approval",
            subject_id=card.approval_id,
            decision="granted",
            subject_hash=card.terms_hash,
            authority_epoch=card.authority_epoch,
        )
        assert decide(sim.k.bb, post, "ui") == Denial("stale_epoch")  # 409 stale
        sim.post(card)  # posted anyway: the kernel's own decide refuses it
        await sim.vt.run_for(100)
        assert not sim.of("approval.decided") and not sim.of("approval.post")
        (denied,) = sim.of("action.denied", intent="approval.post")
        assert denied.payload["reason"] == "stale_epoch"
        await sim.stop()

    arun(case())


def test_3_an_accept_that_would_end_past_its_expiry_is_revoked(
    tmp_path: Path,
) -> None:
    async def case() -> None:
        sim = Sim(tmp_path, {"fast_cp": [LONG]})
        await sim.start()
        await sim.offer()
        sim.rep_says("Anything else?")
        await sim.vt.run_for(500)  # FastC holds the floor for ten seconds
        long = sim.of("fast.sentence", lane="cp")[-1]
        text = (
            f"Yes, we accept these terms: {readback_text(sim.bb.public.offers['o1'])}."
        )
        free, speech = long.t_ms + 10_000, round(1000 * speech_s(text))
        sim.mandate(expires_ms=free + speech // 2)  # free in time, not for its end
        await sim.vt.run_for(100)
        assert sim.of("authority.epoch", reason="mandate_decided")
        assert sim.accept().startswith("accept_offer: accept line queued")
        (cap,) = sim.bb.capabilities.values()
        await sim.vt.run_for(12_000)
        (revoked,) = sim.of("speak.revoked")
        assert revoked.payload["reason"] == "expired"
        assert revoked.t_ms < cap.expires_ms < revoked.t_ms + speech  # t_release_end
        assert not sim.of("speak.released", cap_id=cap.cap_id)
        assert sim.bb.capabilities == {}  # nothing left in flight
        await sim.stop()
        assert check_path(sim.k.path, "offline").ok

    arun(case())


def test_4_a_barge_in_during_the_accept_leaves_it_unheard(tmp_path: Path) -> None:
    async def case() -> None:
        sim = Sim(tmp_path)
        await sim.start()
        await granted(sim)
        sim.accept()
        await sim.vt.run_for(1_000)  # a second into the accept line
        sim.rep_says("Sorry, what was that?")
        await sim.vt.run_for(100)
        (released,) = sim.of("speak.released", lane="cp", cap_id="cap-1")
        (cut,) = [e for e in sim.of("utt.delivered") if _cites(e, released)]
        heard, said = cut.payload["text_heard"], cut.payload["text_generated"]
        assert cut.payload["interrupted"] and heard != said
        assert str(said).startswith(str(heard))
        (replan,) = sim.of("status.changed", status="NEEDS_REPLAN")
        assert _cites(replan, cut) and not sim.of("status.changed", status="COMMITTED")
        await sim.stop()
        assert check_path(sim.k.path, "offline").ok

    arun(case())


def test_a_partner_turn_begun_before_a_queued_accept_lands_first(
    tmp_path: Path,
) -> None:  # the accept waits behind FastC's line; the rep barges in meanwhile
    async def case() -> None:
        sim = Sim(tmp_path, {"fast_cp": [LONG]})
        await sim.start()
        await granted(sim)
        sim.rep_says("Anything else?")
        await sim.vt.run_for(500)  # FastC holds the floor for ten seconds
        assert sim.accept().startswith("accept_offer: accept line queued")
        await sim.vt.run_for(2_000)
        sim.rep_says("Correction: that offer is gone, it is $75 now.")
        await sim.vt.run_for(15_000)
        (said,) = sim.of(
            "utt.final", text="Correction: that offer is gone, it is $75 now."
        )
        released = sim.of("speak.released", cap_id="cap-1")
        revoked = sim.of("speak.revoked", cap_id="cap-1")
        assert len(released) + len(revoked) == 1  # the line ends exactly once
        assert revoked or said.seq < released[0].seq  # heard, then revalidated
        for moved in sim.of("status.changed", status="COMMITTED"):
            assert said.seq < moved.seq
        await sim.stop()
        assert check_path(sim.k.path, "offline").ok

    arun(case())


def test_5_duplicate_approvals_decide_once(tmp_path: Path) -> None:
    async def case() -> None:
        sim = Sim(tmp_path)
        await sim.start()
        await sim.offer()
        card = sim.card()
        sim.post(card)  # a double click
        sim.post(card)
        await sim.vt.run_for(100)
        sim.post(card, by="sim_approver")  # a replayed POST, later
        await sim.vt.run_for(100)
        (decided,) = sim.of("approval.decided")
        (posted,) = sim.of("approval.post")
        assert _cites(decided, posted) and decided.payload["by"] == "ui"
        denied = sim.of("action.denied", intent="approval.post")
        assert [d.payload["reason"] for d in denied] == ["already_decided"] * 2
        asked = sim.of("approval.requested")[0]
        assert all(_cites(d, asked) for d in denied)  # restrict-only, cited (M1)
        (back,) = sim.of(
            "status.changed", status="IN_CALL", previous="AWAITING_APPROVAL"
        )
        assert _cites(back, decided)
        await sim.stop()

    arun(case())


def test_6_a_failing_observer_never_stops_the_session(tmp_path: Path) -> None:
    from tests.kernel.test_session import SCRIPTS, UNTIL
    from tests.support.manual_clock import ScaledClock
    from tests.support.sessions import clients

    from proxyloop.kernel.session import run_session

    seen: list[str] = []

    def exporter(e: Event) -> None:
        seen.append(e.type)
        if len(seen) % 5 == 0:
            raise RuntimeError("the exporter lost its collector")

    clock = ScaledClock(100)
    session = run_session(
        fake_config(),
        patient_task(),
        runs_dir=tmp_path,
        clock=clock,
        sleep=clock.sleep,
        clients=clients(SCRIPTS, clock, (), UNTIL),
        observers=[exporter],
    )
    result = asyncio.run(asyncio.wait_for(session, timeout=30))
    assert result.reason == "info_only" and len(seen) >= 10
    assert seen[-1] == "session.ended"
    assert check_path(result.path, "offline").ok


def test_7_a_generation_started_before_an_epoch_bump_is_cancelled(
    tmp_path: Path,
) -> None:
    async def case() -> None:
        fast_user = Valve()
        sim = Sim(tmp_path, gates={"fast_user": fast_user})
        await sim.start()
        fast_user.open.clear()
        sim.user_says("Can you also check my internet plan?")
        await sim.vt.run_for(100)
        (asked,) = sim.of("fast.request", lane="user")
        sim.revoke()  # Slow restricts while FastU is still generating
        fast_user.open.set()
        await sim.vt.run_for(1_000)
        gen = asked.payload["gen_id"]
        (cancelled,) = sim.of("fast.cancelled", gen_id=gen)
        assert cancelled.payload["reason"] == "epoch" and _cites(cancelled, asked)
        assert not sim.of("fast.turn", gen_id=gen)  # no turn, relay or speech
        again = sim.of("fast.request", lane="user")[1]  # its trigger, on the new basis
        assert again.payload["trigger"] == "user_msg" and again.epoch == 1
        assert sim.of("fast.turn", gen_id=again.payload["gen_id"])
        await sim.stop()
        assert check_path(sim.k.path, "offline").ok

    arun(case())


def test_8_an_epoch_bump_between_the_post_and_the_decide_grants_nothing(
    tmp_path: Path,
) -> None:
    async def case() -> None:
        sim = Sim(tmp_path)
        await sim.start()
        await sim.offer()
        card = sim.card()
        sim.post(card)  # queued, not yet decided
        sim.revoke()  # in between
        await sim.vt.run_for(100)
        assert not sim.of("approval.decided") and not sim.of("approval.post")
        (denied,) = sim.of("action.denied", intent="approval.post")
        assert denied.payload["reason"] == "stale_epoch"
        assert sim.bb.private.approvals == {}
        await sim.stop()

    arun(case())


def test_guard_runs_at_the_bus_clocks_now(tmp_path: Path) -> None:
    """A card and then a grant expire with no event since: Guard, reading
    ``bb.t_ms``, must see the clock's now, or it would decide on a stale board
    and the fold would then reject (raise on) what it emitted (N-c)."""

    async def case() -> None:
        sim = Sim(tmp_path)
        await sim.start()
        await sim.offer()
        card = sim.card()
        await sim.vt.run_for(card.expires_ms - sim.vt.monotonic_ms() + 1)
        assert sim.bb.t_ms < card.expires_ms  # no event since: the fold is stale
        sim.post(card)
        await sim.vt.run_for(100)
        (denied,) = sim.of("action.denied", intent="approval.post")
        assert denied.payload["reason"] == "card_expired"
        assert not sim.of("approval.post") and not sim.of("approval.decided")
        granted_card = await granted(sim, dollars=66)  # a new revision, granted
        await sim.vt.run_for(granted_card.expires_ms - sim.vt.monotonic_ms() + 1)
        case_ref = sim.tools._case  # pyright: ignore[reportPrivateUsage]
        assert sim.bb.t_ms < granted_card.expires_ms
        assert not isinstance(accept_offer(sim.bb, "o1", case_ref), Denial)  # stale
        assert isinstance(accept_offer(sim.k.bb, "o1", case_ref), Denial)  # now
        assert sim.accept() == "accept_offer: denied: approval_expired"
        assert not sim.of("action.authorized") and not sim.of(
            "speak.released", cap_id="cap-1"
        )
        await sim.stop()
        assert check_path(sim.k.path, "offline").ok

    arun(case())


def test_an_approval_notice_is_voiced_and_acknowledged(tmp_path: Path) -> None:
    async def case() -> None:
        sim = Sim(tmp_path)
        await sim.start()
        await sim.offer()
        sim.card()
        await sim.vt.run_for(100)
        (notice,) = sim.of("s2f.msg", type="APPROVAL_NOTICE")
        (asked,) = sim.of("fast.request", trigger="approval_card")
        assert _cites(asked, notice)
        (voiced,) = sim.of("s2f.voiced", msg_id=notice.payload["msg_id"])
        assert voiced.payload["gen_id"] == asked.payload["gen_id"]
        assert sim.bb.s2f_pending["user"] == ()
        await sim.stop()

    arun(case())


def test_a_tighten_bump_invalidates_the_mandate_until_regranted(
    tmp_path: Path,
) -> None:  # M7
    async def case() -> None:
        sim = Sim(tmp_path)
        await sim.start()
        await sim.offer()
        sim.mandate(expires_ms=sim.vt.monotonic_ms() + 600_000)
        await sim.vt.run_for(100)
        (text,) = sim.act(
            {"tool": "tighten_mandate", "changes": {"max_monthly_price_minor": 7000}}
        )
        assert "the user must re-grant it" in text
        assert sim.of("authority.epoch", reason="tighten_mandate")
        assert sim.accept().startswith("accept_offer: denied: not_authorized")
        m = sim.bb.private.mandate
        assert m is not None and m.status == "proposed"
        post = {"subject": "mandate", "subject_id": m.mandate_id, "decision": "granted"}
        post |= {"subject_hash": m.mandate_hash, "authority_epoch": m.epoch}
        sim.k.post_approval(ApprovalPost.model_validate(post))
        await sim.vt.run_for(100)
        (_, regranted) = sim.of("mandate.decided")
        assert regranted.payload["mandate_id"] == m.mandate_id
        assert sim.accept().startswith("accept_offer: accept line queued")
        await sim.vt.run_for(15_000)
        assert sim.of("speak.released", cap_id="cap-1")
        await sim.stop()

    arun(case())
