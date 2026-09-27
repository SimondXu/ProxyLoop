"""A pending approval card that goes stale or expires (S1-SYS-38, §9.5, I6):
AWAITING_APPROVAL moves to NEEDS_REPLAN, caused by the ``authority.epoch``
that staled it, or at its ``expires_ms`` by the card itself. Restrict-only:
nothing is granted, no accept is minted, and every outcome legal from
NEEDS_REPLAN (then IN_CALL once Slow saw it) stays legal, so the case ends
without the session timeout."""

from __future__ import annotations

from pathlib import Path

from tests.concurrency.harness import Sim, SlowGate, granted
from tests.concurrency.test_cases import arun

from proxyloop.contract.events import Event
from proxyloop.contract.state import CaseStatus
from proxyloop.evidence.check import check_path

S = CaseStatus
STOP = "Understood.\n@slow: revoke the user said stop"


def _stale(sim: Sim) -> list[Event]:
    return sim.of("status.changed", previous="AWAITING_APPROVAL", status="NEEDS_REPLAN")


def _nothing_granted(sim: Sim) -> None:
    assert not sim.of("approval.decided") and not sim.of("action.authorized")
    assert not sim.of("speak.verbatim", kind="accept")
    assert not sim.of("status.changed", status="COMMIT_AUTHORIZED")


def test_a_stop_stales_the_pending_card_and_slow_can_close(tmp_path: Path) -> None:
    async def case() -> None:
        sim = Sim(tmp_path, {"fast_user": ["Okay.", STOP]})
        await sim.start()
        await sim.offer()
        card = sim.card()
        await sim.vt.run_for(100)  # FastU voices the card
        assert sim.bb.public.status is S.AWAITING_APPROVAL
        sim.user_says("Actually, stop.")
        await sim.vt.run_for(100)
        (msg,) = sim.of("user.msg")
        (fence,) = sim.of("authority.fence", op="raised")
        assert fence.cause_ids == (msg.event_id,)
        (relay,) = sim.of("f2s.msg", type="REVOKE")
        (bump,) = sim.of("authority.epoch", reason="f2s_revoke")
        assert bump.cause_ids == (relay.event_id,)
        (stale,) = _stale(sim)
        assert stale.cause_ids == (bump.event_id,) and stale.seq > bump.seq
        await sim.vt.run_for(2_000)  # Slow's step sees it: fence clears, replan
        assert sim.bb.fences == ()
        (back,) = sim.of("status.changed", previous="NEEDS_REPLAN", status="IN_CALL")
        assert back.seq > stale.seq and sim.bb.public.status is S.IN_CALL
        sim.post(card)  # a late click on the stale card grants nothing
        await sim.vt.run_for(100)
        (denied,) = sim.of("action.denied", intent="approval.post")
        assert denied.payload["reason"] == "stale_epoch"
        assert sim.accept().startswith("accept_offer: denied:")
        _nothing_granted(sim)
        (no_deal,) = sim.act({"tool": "finish", "outcome": "no_deal"})
        assert no_deal.startswith("finish: no deal not verified")  # not the status
        (closed,) = sim.act({"tool": "finish", "outcome": "info_only"})
        assert closed == "finish: case closed"
        await sim.vt.run_for(1_000)
        events = await sim.stop()
        assert events[-1].type == "session.ended"
        assert events[-1].payload["reason"] == "info_only"  # not timeout
        report = check_path(sim.k.path, "offline")
        assert report.ok, report.failures

    arun(case())


def test_an_expired_card_replans_at_its_expiry_and_slow_can_escalate(
    tmp_path: Path,
) -> None:
    async def case() -> None:
        sim = Sim(tmp_path)
        await sim.start()
        await sim.offer()
        card = sim.card()
        (asked,) = sim.of("approval.requested")
        gate = SlowGate(sim)
        gate.let(0)  # Slow's next step does not complete: the case stays replanning
        await sim.vt.run_for(card.expires_ms - sim.vt.monotonic_ms() - 1)
        assert sim.bb.public.status is S.AWAITING_APPROVAL and not _stale(sim)
        await sim.vt.run_for(1)
        (stale,) = _stale(sim)
        assert stale.cause_ids == (asked.event_id,)  # the card, at its expiry
        assert stale.t_ms == card.expires_ms
        assert sim.bb.public.status is S.NEEDS_REPLAN
        sim.post(card)
        await sim.vt.run_for(100)
        (denied,) = sim.of("action.denied", intent="approval.post")
        assert denied.payload["reason"] == "card_expired"
        _nothing_granted(sim)
        (out,) = sim.act({"tool": "finish", "outcome": "escalate"})
        assert out == "finish: case closed"
        await sim.vt.run_for(1_000)
        events = await sim.stop()
        assert sim.bb.public.status is S.ESCALATED
        assert events[-1].payload["reason"] == "escalate"
        report = check_path(sim.k.path, "offline")
        assert report.ok, report.failures

    arun(case())


def test_a_card_decided_before_the_bump_keeps_todays_path(tmp_path: Path) -> None:
    async def case() -> None:
        sim = Sim(tmp_path)
        await sim.start()
        card = await granted(sim)
        (decided,) = sim.of("approval.decided")
        (back,) = sim.of("status.changed", previous="AWAITING_APPROVAL")
        assert back.payload["status"] == "IN_CALL"
        assert back.cause_ids == (decided.event_id,)
        sim.revoke()
        await sim.vt.run_for(card.expires_ms - sim.vt.monotonic_ms() + 1_000)
        assert not _stale(sim) and not sim.of("status.changed", status="NEEDS_REPLAN")
        assert sim.bb.public.status is S.IN_CALL
        assert sim.accept() == "accept_offer: denied: approval_stale_epoch"
        await sim.stop()
        assert check_path(sim.k.path, "offline").ok

    arun(case())


def test_an_old_cards_expiry_never_moves_a_newer_card(tmp_path: Path) -> None:
    async def case() -> None:
        sim = Sim(tmp_path)
        await sim.start()
        await sim.offer()
        old = sim.card()
        await sim.vt.run_for(1_000)
        sim.revoke()  # Slow restricts: the card is stale
        (bump,) = sim.of("authority.epoch", reason="slow_revoke")
        (stale,) = _stale(sim)
        assert stale.cause_ids == (bump.event_id,)
        await sim.vt.run_for(2_000)  # Slow's step: back IN_CALL
        assert sim.bb.public.status is S.IN_CALL
        new = sim.card()  # a new request_approval at the new epoch
        assert sim.bb.public.status is S.AWAITING_APPROVAL
        assert old.expires_ms < new.expires_ms
        await sim.vt.run_for(old.expires_ms - sim.vt.monotonic_ms() + 1)
        assert sim.bb.public.status is S.AWAITING_APPROVAL and len(_stale(sim)) == 1
        sim.post(new)
        await sim.vt.run_for(100)
        assert sim.bb.private.approvals[new.approval_id].decision == "granted"
        assert sim.bb.public.status is S.IN_CALL
        await sim.vt.run_for(new.expires_ms - sim.vt.monotonic_ms() + 1)
        assert len(_stale(sim)) == 1  # a decided card never expires into a replan
        await sim.stop()
        assert check_path(sim.k.path, "offline").ok

    arun(case())
