"""S1-SYS-84 phase 1: the sim grant and the card notice against the user's
fence, on virtual time (red tests, ``xfail(strict=True)`` until phase 2).

R-h (F-h, x-user-mind-change). The sim approver decides a card at once and
posts its grant ``delay_s`` after the card, but no earlier than the stop's
delivery (N6, ``Authority._later``). The stop becomes authority only when
FastU relays it (``@slow: revoke`` -> ``authority.epoch{f2s_revoke}``), one
FastU turn after its ``user.msg``. A grant that lands in that gap is decided
in the old epoch, moves the case back to IN_CALL, and the later bump stales
nothing (only a still-pending card is staled): no NEEDS_REPLAN. Intended: no
grant in the old epoch after the stop's ``user.msg``; the bump stales the card.

R-l (F-l, x-out-of-envelope-approval). The card is granted and Slow's accept
waits for the floor; the SimUser's plain chat reply to FastU's card notice
raises a user fence, and the Speaker revokes the accept ``fence`` (``floor``:
the floor frees while the fence is up; ``partner``: the accept waits on a
partner fence when the user fence rises). The intended outcome (the accept
is released and heard) is pinned pending the root's ruling on F-l.
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
from proxyloop.env.tasks.loader import load_task
from proxyloop.env.tasks.schema import Task

FASTU_S = 2.0  # FastU's latency per turn from the card on (live: 1-2 s)
REVOKE = "Understood, I will not accept anything.\n@slow: revoke the user said stop"
NOTICE = "Please review the approval card in the app."
ANSWER = "Thanks, I will let you know how it goes."  # no relay
CHAT = "Okay, I will look at it now."  # the user's plain reply to the notice
_QUIET = {
    "call_id": "t",
    "name": "reply",
    "arguments": '{"silent": true, "revealed": {}}',
}
SILENT = json.dumps({"text": "", "tool_calls": [_QUIET]})  # the SimUser says nothing
PHASE_2 = "S1-SYS-84 phase 2"


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


# R-h
@pytest.mark.xfail(strict=True, raises=AssertionError, reason=PHASE_2)
@pytest.mark.parametrize("when", ["fastu_latency", "stop_behind_reply"])
def test_r_h_no_sim_grant_lands_between_the_stop_and_its_revoke(
    tmp_path: Path, when: str
) -> None:
    """``fastu_latency``: the stop lands 0.5-2.5 s after the card, the grant
    3 s after it, FastU's revoke 2 s after its turn on the stop starts.
    ``stop_behind_reply``: the stop queues behind the user's reply due 20 s
    after "Okay." (the N6 case): the grant is posted as the stop lands."""

    async def case() -> None:
        behind = when == "stop_behind_reply"  # the user answers "Okay." late
        first = reply("Thanks.") if behind else SILENT
        scripts = {
            "simuser": [
                reply("Please get my cable bill down."),
                first,
                reply(STOP),  # after_card
                SILENT,
            ],
            "fast_user": ["Okay.", NOTICE],
        }
        until = {"fast_user": ("do not accept anything", REVOKE)}
        task = _family("x-user-mind-change", 20.0, 3.0)
        sim, fastu = _sim(tmp_path, task, scripts, until=until)
        await sim.start()
        await sim.offer(dollars=76)  # above the stated 70, within the card limit
        fastu.on = True
        sim.card()
        await sim.vt.run_for(30_000)
        asked = _one(sim, "approval.requested")
        stop = _one(sim, "user.msg", text=STOP)
        bump = _one(sim, "authority.epoch", reason="f2s_revoke")
        assert _one(sim, "f2s.msg", type="REVOKE").seq < bump.seq
        # the scenario: the approver's 3 s fall between the stop and its revoke
        assert bump.t_ms > asked.t_ms + 3_000 and stop.seq < bump.seq
        if not behind:
            assert stop.t_ms < asked.t_ms + 3_000
        # intended: no grant in the old epoch after the stop's user.msg ...
        late = [
            e
            for e in sim.of("approval.decided", decision="granted")
            if e.seq > stop.seq
        ]
        assert late == [], [(e.seq, e.t_ms) for e in late]
        # ... so the revoke stales the pending card (a path to ESCALATED)
        stale = _one(
            sim, "status.changed", previous="AWAITING_APPROVAL", status="NEEDS_REPLAN"
        )
        assert stale.cause_ids == (bump.event_id,)
        denied = sim.of("action.denied", intent="approval.post")
        assert all(d.payload["reason"] == "stale_epoch" for d in denied)
        assert sim.accept().startswith("accept_offer: denied:")
        assert not sim.of("action.authorized") and not sim.of("speak.released")
        await sim.stop()

    arun(case())


# R-l
@pytest.mark.xfail(strict=True, raises=AssertionError, reason=f"{PHASE_2}: F-l ruling")
@pytest.mark.parametrize("wait", ["floor", "partner"])
def test_r_l_a_chat_reply_to_the_notice_keeps_a_granted_accept(
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
        # intended (pending the ruling): the accept is released and heard
        assert not sim.of("speak.revoked", cap_id="cap-1")
        _one(sim, "speak.released", cap_id="cap-1")
        assert not sim.of("status.changed", status="NEEDS_REPLAN")
        _one(sim, "status.changed", status="COMMITTED")
        await sim.stop()

    arun(case())
