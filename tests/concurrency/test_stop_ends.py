"""S1-SYS-83: a stop ends cleanly, on a real ``Kernel`` in virtual time
(x-user-mind-change, as S1-SYS-84's R-h scenario sets it up). The SimUser
stops after the card; the grant waits for the stop's user fence (#262).

- ``revoke``: FastU relays ``@slow: revoke`` -> ``authority.epoch{f2s_revoke}``
  -> the pending card stales -> NEEDS_REPLAN. The scripted Slow answers
  NOTED until its request shows the bar's stop line, then plays that line's
  one act (tell_user, finish(escalate)): ESCALATED, tier S.
- ``note``: FastU relays the stop only as a NOTE (a Fast failure, measured):
  no revoke, no NEEDS_REPLAN, so the bar shows no stop line. The scripted
  Slow plays the SYSTEM stop clause once the note reaches it: revoke, which
  stales the card and replans the case within the same act (delivery on the
  bus is synchronous), then tell_user and finish(escalate): ESCALATED, but
  tier F ``escalated`` (``obs.tiers`` counts only a user's f2s revoke).

Neither run releases an accept or decides the card after the stop.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.concurrency.harness import Sim
from tests.concurrency.test_cases import arun
from tests.concurrency.test_user_fence_grant import (
    NOTE,
    NOTICE,
    REVOKE,
    SILENT,
    _family,  # pyright: ignore[reportPrivateUsage]
    _offline_ok,  # pyright: ignore[reportPrivateUsage]
    _one,  # pyright: ignore[reportPrivateUsage]
    _sim,  # pyright: ignore[reportPrivateUsage]
)
from tests.concurrency.test_world import STOP
from tests.support.sessions import act, reply

from proxyloop.contract.state import CaseStatus
from proxyloop.obs import detectors
from proxyloop.slow import state

TOLD = {"tool": "tell_user", "text": "Nothing was accepted; the case is stopped."}
ESCALATE = {"tool": "finish", "outcome": "escalate", "summary": "the user stopped"}
REVOKED = {"tool": "revoke", "reason": "the user said stop"}
BAR_ACT = act("The user stopped; nothing accepted.", TOLD, ESCALATE)
CLAUSE_ACT = act("The user stopped; nothing accepted.", REVOKED, TOLD, ESCALATE)
STOP_LINE = state.STOP[:60]  # the bar's stop line, as Slow's request holds it
NOTED = "the user said stop"  # FastU's NOTE text, as Slow's request holds it
SLOW = {"revoke": (STOP_LINE, BAR_ACT), "note": (NOTED, CLAUSE_ACT)}
FASTU = {"revoke": REVOKE, "note": NOTE}


async def _stopped(tmp_path: Path, how: str) -> Sim:
    scripts = {
        "simuser": [
            reply("Please get my cable bill down."),
            SILENT,
            reply(STOP),  # after_card
            SILENT,
        ],
        "fast_user": ["Okay.", NOTICE],
    }
    until = {"fast_user": ("do not accept anything", FASTU[how]), "slow": SLOW[how]}
    task = _family("x-user-mind-change", 20.0, 3.0)
    sim, fastu = _sim(tmp_path, task, scripts, until=until)
    await sim.start()
    await sim.offer(dollars=76)  # above the stated 70, within the card limit
    fastu.on = True
    sim.card()
    await sim.vt.run_for(30_000)
    return sim


def _tier(sim: Sim) -> dict[str, object]:
    x = detectors.Inputs(sim.events, None, lambda _: None)
    value = detectors.DETECTORS["tier"](x)
    assert isinstance(value, dict)
    return value  # type: ignore[return-value]


def _no_accept_after(sim: Sim, stop_seq: int) -> None:
    assert not sim.of("approval.decided") and not sim.of("approval.post")
    assert not sim.of("action.authorized")
    assert not [e for e in sim.of("speak.verbatim", kind="accept") if e.seq > stop_seq]
    denied = _one(sim, "action.denied", intent="approval.post")  # the sim grant
    assert denied.payload["reason"] in ("stale_epoch", "not_awaiting")


@pytest.mark.parametrize("how", ["revoke", "note"])
def test_the_stop_after_the_card_escalates(tmp_path: Path, how: str) -> None:
    async def case() -> None:
        sim = await _stopped(tmp_path, how)
        stop = _one(sim, "user.msg", text=STOP)
        asked = _one(sim, "approval.requested")
        assert asked.seq < stop.seq
        # the scripted FastU relays its stop again on the TELL_USER turn: a
        # second revoke, after the case is closed (a script artifact)
        bump, *again = sim.of("authority.epoch")
        reason = "f2s_revoke" if how == "revoke" else "slow_revoke"
        assert bump.payload["reason"] == reason and bump.seq > stop.seq
        stale = _one(
            sim, "status.changed", previous="AWAITING_APPROVAL", status="NEEDS_REPLAN"
        )
        assert stale.cause_ids == (bump.event_id,)
        escalated = _one(sim, "status.changed", status="ESCALATED")
        assert escalated.payload["previous"] == "NEEDS_REPLAN"
        assert all(e.seq > escalated.seq for e in again)
        # one act: the finish that escalated is the stop act's own
        (finish,) = [e for e in sim.of("slow.tool") if e.payload["name"] == "finish"]
        (told,) = [e for e in sim.of("slow.tool") if e.payload["name"] == "tell_user"]
        assert told.seq < finish.seq < escalated.seq
        assert finish.event_id in escalated.cause_ids
        if how == "note":  # the same act revoked, and that staled the card
            (revoked,) = [
                e for e in sim.of("slow.tool") if e.payload["name"] == "revoke"
            ]
            assert revoked.seq < bump.seq < stale.seq < told.seq
        else:  # no Slow revoke: FastU's staled the card first
            assert not [e for e in sim.of("slow.tool") if e.payload["name"] == "revoke"]
        between = [
            e
            for e in sim.of("slow.step.completed")
            if stale.seq < e.seq < escalated.seq
        ]
        assert not between  # the stop act is the first step after NEEDS_REPLAN
        assert sim.bb.public.status is CaseStatus.ESCALATED
        _no_accept_after(sim, stop.seq)
        tier = _tier(sim)
        want = ("S", "user_stop") if how == "revoke" else ("F", "escalated")
        assert (tier["tier"], tier["reason"]) == want, tier
        await sim.stop()
        _offline_ok(sim)

    arun(case())
