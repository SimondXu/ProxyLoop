"""S1-SYS-84: the sim grant and the card notice against the user's fence, on
virtual time.

R-h (F-h, x-user-mind-change). The sim approver decides a card at once and
posts its grant ``delay_s`` after the card, no earlier than the stop's
delivery (N6), and, since S1-SYS-84, no earlier than the stop's user fence
clearing (a Slow step saw FastU's turn on it), bounded by the card's expiry.
The stop becomes authority when FastU relays it (``@slow: revoke`` ->
``authority.epoch{f2s_revoke}``), one FastU turn after its ``user.msg``: so
the bump now stales the still-pending card (NEEDS_REPLAN) and the grant is
refused ``stale_epoch``. Before the fix the grant landed in that gap, in the
old epoch, and the bump staled nothing. A run with no stop keeps its timing.

R-l (F-l, x-out-of-envelope-approval; root ruling: option C, fail-closed
stays, #156 / ARCHITECTURE §9.4). The card is granted and Slow's accept waits
for the floor; the SimUser's plain chat reply to FastU's card notice raises a
user fence, and the Speaker revokes the accept ``fence`` -> NEEDS_REPLAN
(``floor``: the floor frees while the fence is up; ``partner``: the accept
waits on a partner fence when the user fence rises). Once the fence clears,
Slow's re-accept is released, heard and COMMITTED.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from tests.concurrency.harness import Sim, SlowGate
from tests.concurrency.test_cases import arun
from tests.concurrency.test_world import STOP
from tests.support.sessions import reply

from proxyloop.contract.events import Event
from proxyloop.contract.state import CaseStatus
from proxyloop.env.tasks.loader import load_task
from proxyloop.env.tasks.schema import Task
from proxyloop.evidence.check import check_path

FASTU_S = 2.0  # FastU's latency per turn from the card on (live: 1-2 s)
REVOKE = "Understood, I will not accept anything.\n@slow: revoke the user said stop"
NOTE = "Understood.\n@slow: the user said stop"  # a Fast failure: no revoke
NOTICE = "Please review the approval card in the app."
ANSWER = "Thanks, I will let you know how it goes."  # no relay
CHAT = "Okay, I will look at it now."  # the user's plain reply to the notice
_QUIET = {
    "call_id": "t",
    "name": "reply",
    "arguments": '{"silent": true, "revealed": {}}',
}
SILENT = json.dumps({"text": "", "tool_calls": [_QUIET]})  # the SimUser says nothing
WHEN = ["fastu_latency", "stop_behind_reply"]


class Latency:
    """A FastU gate: each streamed call takes ``FASTU_S`` once ``on``."""

    def __init__(self) -> None:
        self.on, self.sim = False, cast(Sim | None, None)

    async def __call__(self) -> None:
        if self.on and self.sim is not None:
            await self.sim.vt.sleep(FASTU_S)


def _family(name: str, reply_s: float, approver_s: float) -> Task:
    data = load_task(name).model_dump(mode="json")
    data["user"]["reply_delay_s"]["range"] = [reply_s, reply_s]
    data["principal"]["approver_delay_s"]["range"] = [approver_s, approver_s]
    return Task.model_validate(data)


def _sim(
    tmp_path: Path,
    task: Task,
    scripts: dict[str, list[str]],
    until: dict[str, tuple[str, str]] | None = None,
) -> tuple[Sim, Latency]:
    """The SimUser (with its approver) on ``task``; the rep a silent channel."""
    fastu = Latency()
    sim = Sim(tmp_path, scripts, task, "sim", gates={"fast_user": fastu}, until=until)
    fastu.sim = sim
    return sim, fastu


def _one(sim: Sim, type_: str, **match: object) -> Event:
    (e,) = sim.of(type_, **match)
    return e


def _fence_of_raised(sim: Sim, said: Event) -> Event:
    """The user fence ``said`` raised."""
    (up,) = [
        f
        for f in sim.of("authority.fence", op="raised")
        if f.cause_ids == (said.event_id,)
    ]
    return up


def _fence_of(sim: Sim, said: Event) -> tuple[Event, Event]:
    """The user fence ``said`` raised, and its clearing."""
    up = _fence_of_raised(sim, said)
    return up, _one(sim, "authority.fence", op="cleared", **_id(up))


def _id(fence: Event) -> dict[str, object]:
    return {"fence_id": fence.payload["fence_id"]}


def _offline_ok(sim: Sim) -> None:
    report = check_path(sim.k.path, "offline")
    assert report.ok, report.failures


# R-h
async def _mind_change(
    tmp_path: Path, when: str, relay: str, hold_slow: bool = False
) -> Sim:
    """``fastu_latency``: the stop lands 0.5-2.5 s after the card, the grant is
    due 3 s after it, FastU relays 2 s after its turn on the stop starts.
    ``stop_behind_reply``: the stop queues behind the user's reply due 20 s
    after "Okay." (the N6 case): the grant was due before the stop landed."""
    behind = when == "stop_behind_reply"  # the user answers "Okay." late
    scripts = {
        "simuser": [
            reply("Please get my cable bill down."),
            reply("Thanks.") if behind else SILENT,
            reply(STOP),  # after_card
            SILENT,
        ],
        "fast_user": ["Okay.", NOTICE],
    }
    until = {"fast_user": ("do not accept anything", relay)}
    task = _family("x-user-mind-change", 20.0, 3.0)
    sim, fastu = _sim(tmp_path, task, scripts, until=until)
    await sim.start()
    await sim.offer(dollars=76)  # above the stated 70, within the card limit
    fastu.on = True
    sim.card()
    if hold_slow:  # no Slow step completes from the card on
        SlowGate(sim).let(0)
    await sim.vt.run_for(130_000 if hold_slow else 30_000)
    asked = _one(sim, "approval.requested")
    stop = _one(sim, "user.msg", text=STOP)
    # the scenario: the approver's 3 s fall between the stop and FastU's relay
    relayed = [e for e in sim.of("f2s.msg", lane="user") if e.seq > stop.seq]
    assert relayed and relayed[0].t_ms > asked.t_ms + 3_000
    if behind:
        assert stop.t_ms > asked.t_ms + 3_000
    else:
        assert stop.t_ms < asked.t_ms + 3_000
    return sim


@pytest.mark.parametrize("when", WHEN)
def test_r_h_a_relayed_stop_stales_the_card_before_the_sim_grant(
    tmp_path: Path, when: str
) -> None:
    async def case() -> None:
        sim = await _mind_change(tmp_path, when, REVOKE)
        stop = _one(sim, "user.msg", text=STOP)
        bump = _one(sim, "authority.epoch", reason="f2s_revoke")
        assert stop.seq < _one(sim, "f2s.msg", type="REVOKE").seq < bump.seq
        # the revoke stales the still-pending card: a path to ESCALATED
        stale = _one(
            sim, "status.changed", previous="AWAITING_APPROVAL", status="NEEDS_REPLAN"
        )
        assert stale.cause_ids == (bump.event_id,)
        # the grant waited for the stop's fence, then was refused stale_epoch
        _, cleared = _fence_of(sim, stop)
        denied = _one(sim, "action.denied", intent="approval.post")
        assert denied.payload["reason"] == "stale_epoch"
        assert denied.seq > cleared.seq > stale.seq
        assert denied.cause_ids == (_one(sim, "approval.requested").event_id,)
        assert not sim.of("approval.post") and not sim.of("approval.decided")
        assert sim.accept().startswith("accept_offer: denied:")
        assert not sim.of("action.authorized") and not sim.of(
            "speak.verbatim", kind="accept"
        )
        await sim.stop()
        _offline_ok(sim)

    arun(case())


@pytest.mark.parametrize("when", WHEN)
def test_r_h_a_note_only_stop_is_seen_by_slow_before_the_sim_grant(
    tmp_path: Path, when: str
) -> None:
    """FastU fails to relay the stop as a revoke (measured, a Fast failure):
    the grant still lands, but only after a Slow step saw the stop."""

    async def case() -> None:
        sim = await _mind_change(tmp_path, when, NOTE)
        stop = _one(sim, "user.msg", text=STOP)
        assert not sim.of("authority.epoch")  # nothing restricted authority
        decided = _one(sim, "approval.decided", decision="granted")
        post = _one(sim, "approval.post")
        saw = [
            e
            for e in sim.of("slow.step.completed")
            if int(str(e.payload["basis_seq"])) >= stop.seq and e.seq < post.seq
        ]
        assert saw, "no Slow step saw the stop before the grant"
        _, cleared = _fence_of(sim, stop)
        assert cleared.cause_ids == (saw[0].event_id,) and cleared.seq < post.seq
        assert post.seq < decided.seq
        await sim.stop()
        _offline_ok(sim)

    arun(case())


def test_r_h_the_wait_on_the_stop_ends_at_the_cards_expiry(tmp_path: Path) -> None:
    """Slow never sees the stop: the grant is posted at the card's expiry and
    refused there; nothing is granted."""

    async def case() -> None:
        sim = await _mind_change(tmp_path, "fastu_latency", NOTE, hold_slow=True)
        asked = _one(sim, "approval.requested")
        up = _fence_of_raised(sim, _one(sim, "user.msg", text=STOP))
        assert not sim.of("authority.fence", op="cleared", **_id(up))
        denied = _one(sim, "action.denied", intent="approval.post")
        assert denied.t_ms == asked.payload["expires_ms"]
        assert denied.payload["reason"] == "card_expired"
        assert not sim.of("approval.post") and not sim.of("approval.decided")
        await sim.stop()

    arun(case())


def test_r_h_without_a_stop_the_sim_grant_keeps_its_time(tmp_path: Path) -> None:
    """No stop: the grant is posted at the card plus the approver's delay,
    even with a user fence (a plain chat reply) up at that moment."""

    async def case() -> None:
        scripts = {
            "simuser": [
                reply("Please lower my phone bill."),
                SILENT,  # to "Okay."
                reply(CHAT),  # to the notice, 0.5 s later
                SILENT,
            ],
            "fast_user": ["Okay.", NOTICE, ANSWER],
        }
        task = _family("x-out-of-envelope-approval", 0.5, 3.0)
        sim, fastu = _sim(tmp_path, task, scripts)
        await sim.start()
        await sim.offer(dollars=70)  # above the stated 65, within the card limit
        fastu.on = True
        sim.card()
        await sim.vt.run_for(10_000)
        asked = _one(sim, "approval.requested")
        post = _one(sim, "approval.post")
        assert post.t_ms == asked.t_ms + 3_000
        _one(sim, "approval.decided", decision="granted")
        up, cleared = _fence_of(sim, _one(sim, "user.msg", text=CHAT))
        assert up.seq < post.seq < cleared.seq  # the grant did not wait for it
        await sim.stop()
        _offline_ok(sim)

    arun(case())


# R-l
@pytest.mark.parametrize("wait", ["floor", "partner"])
def test_r_l_a_chat_reply_revokes_a_queued_accept_and_slow_re_accepts(
    tmp_path: Path, wait: str
) -> None:
    """``floor``: the accept waits while the rep composes, and the floor
    frees during FastU's turn on the user's reply (the user fence is up).
    ``partner``: a rep line Slow has not seen fences the accept at its mint
    (Slow's steps held), and the user's reply lands while it waits."""

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
        task = _family("x-out-of-envelope-approval", 6.0, 3.0)
        sim, fastu = _sim(tmp_path, task, scripts)
        await sim.start()
        await sim.offer(dollars=70)  # above the stated 65, within the card limit
        fastu.on = True
        sim.card()
        await sim.vt.run_for(3_500)  # the notice at +2 s, the grant at +3 s
        (grant,) = sim.of("approval.decided", decision="granted")
        gate = None
        if wait == "floor":
            sim.rep_composes()
        else:
            gate = SlowGate(sim)
            gate.let(0)
            sim.rep_says("Anything else I can help with?")
            await sim.vt.run_for(300)
        assert sim.accept().startswith("accept_offer: accept line queued (cap-1)")
        await sim.vt.run_for(5_000)  # the user's reply: 6 s after the notice
        if wait == "floor":
            sim.rep_done()  # the floor frees during FastU's 2 s turn
        else:
            await sim.vt.run_for(1_000)
            assert gate is not None
            gate.let(None)
        await sim.vt.run_for(20_000)
        said = _one(sim, "user.msg", text=CHAT)
        line = _one(sim, "speak.verbatim", kind="accept", cap_id="cap-1")
        # the scenario: a plain chat line while a granted accept is in flight
        assert grant.seq < line.seq < said.seq
        assert not sim.of("f2s.msg", type="REVOKE") and sim.bb.epoch == 0
        assert all("stop" not in e.payload for e in sim.of("user.sim"))
        # fail-closed (#156): revoked under the user fence, the case replans
        up, cleared = _fence_of(sim, said)
        revoked = _one(sim, "speak.revoked", cap_id="cap-1")
        assert revoked.payload["reason"] == "fence"
        assert up.seq < revoked.seq < cleared.seq
        assert not sim.of("speak.released", cap_id="cap-1")
        replan = _one(sim, "status.changed", previous="COMMIT_AUTHORIZED")
        assert replan.payload["status"] == "NEEDS_REPLAN"
        assert replan.cause_ids == (revoked.event_id,)
        # once the fence cleared, Slow's re-accept goes out on the same grant
        assert sim.bb.fences == () and sim.bb.public.status is CaseStatus.IN_CALL
        assert sim.accept().startswith("accept_offer: accept line queued (cap-2)")
        await sim.vt.run_for(15_000)
        released = _one(sim, "speak.released", cap_id="cap-2")
        (heard,) = [
            e
            for e in sim.of("utt.delivered", lane="cp")
            if released.event_id in e.cause_ids
        ]
        assert heard.payload["interrupted"] is False
        committed = _one(sim, "status.changed", status="COMMITTED")
        assert committed.cause_ids == (heard.event_id,)
        await sim.stop()
        _offline_ok(sim)

    arun(case())
