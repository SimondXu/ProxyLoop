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

Round 2 (review rev-269): a stop from IN_CALL (no card, or a granted one)
plays the SYSTEM clause's other branch (revoke, a truthful tell_user, no
finish); a stop while an accept waits replans through the revoked accept,
so no stop line shows (case (e), pinned).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
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

from proxyloop.contract.llm import (
    LLMCallRecord,
    TextRequest,
    ToolRequest,
    ToolResponse,
    request_content,
)
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
    # both paths: the card was staled before the grant waited out the stop's
    # fence, so the post is refused on its epoch (the case is closed by then)
    assert denied.payload["reason"] == "stale_epoch"


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


# rev-269 M3: a stop from IN_CALL (before any card, or after a granted one):
# finish(escalate) cannot pass there, so the SYSTEM clause's act is revoke and
# a truthful tell_user, with no finish and no "stopped" claim (F-j deferred)
WITHDRAWN = {
    "tool": "tell_user",
    "text": "Every grant is withdrawn; nothing will be accepted without your new "
    "approval.",
}
IN_CALL_ACT = act("The user withdrew; grants revoked.", REVOKED, WITHDRAWN)


def _in_call(tmp_path: Path, until: dict[str, tuple[str, str]]) -> Sim:
    """x-user-mind-change with the user a channel the test speaks for (no
    SimUser, so no sim approver: the UI decides a card)."""
    task = _family("x-user-mind-change", 20.0, 3.0)
    return Sim(tmp_path, {"fast_user": ["Okay."]}, task, until=until)


class Once:
    """Slow's scripted client plays ``said`` once, at the first request that
    holds ``marker``, and its own script (NOTED) otherwise: an act repeated on
    every step would loop FastU and Slow (the harness's ``until`` repeats)."""

    def __init__(self, sim: Sim, marker: str, said: str) -> None:
        loud = sim.k.clients["slow"]
        self.inner, self.ref = loud.inner, loud.inner.ref
        loud.inner = self
        self.script = sim.llms["slow"]  # the RepeatingLLM inside ``inner``
        self.marker, self.said, self.fired = marker, said, False

    def stream_text(self, request: TextRequest) -> AsyncIterator[str | LLMCallRecord]:
        return self.inner.stream_text(request)

    async def chat_tools(self, request: ToolRequest) -> ToolResponse:
        if not self.fired and self.marker in request_content(request):
            self.fired = True
            left = self.script._responses  # pyright: ignore[reportPrivateUsage]
            left[self.script.calls :] = [self.said, *left[-1:]]
        return await self.inner.chat_tools(request)


@pytest.mark.parametrize("when", ["no_card", "granted_card"])
def test_a_stop_in_call_revokes_and_tells_the_truth(tmp_path: Path, when: str) -> None:
    async def case() -> None:
        sim = _in_call(tmp_path, {"fast_user": ("do not accept anything", REVOKE)})
        Once(sim, NOTED, IN_CALL_ACT)
        await sim.start()
        await sim.offer(dollars=76)
        if when == "granted_card":
            sim.post(sim.card())
            await sim.vt.run_for(100)
            _one(sim, "approval.decided", decision="granted")
        assert sim.bb.public.status is CaseStatus.IN_CALL
        sim.user_says(STOP)
        await sim.vt.run_for(20_000)
        stop = _one(sim, "user.msg", text=STOP)
        bumps = [e.payload["reason"] for e in sim.of("authority.epoch")]
        after = [
            e.payload["reason"] for e in sim.of("authority.epoch") if e.seq > stop.seq
        ]
        # then FastU's scripted revoke again on the TELL_USER turn (``until``)
        assert after[:2] == ["f2s_revoke", "slow_revoke"], bumps
        tools = [e for e in sim.of("slow.tool") if e.seq > stop.seq]
        assert all(e.payload["ok"] for e in tools), [e.payload for e in tools]
        assert not [e for e in tools if e.payload["name"] == "finish"]
        (told,) = [e for e in tools if e.payload["name"] == "tell_user"]
        assert "stopped" not in json.dumps(told.payload["args"])
        assert sim.bb.public.status is CaseStatus.IN_CALL  # F-j: no terminal edge
        assert not sim.of("status.changed", status="ESCALATED")
        assert not sim.of("action.authorized")
        await sim.stop()
        _offline_ok(sim)

    arun(case())


# case (e): the stop while an accept is queued. The stop's fence or the
# revoke's epoch bump revokes the queued accept (accept_revoked): that
# NEEDS_REPLAN is caused by speak.revoked, not by the f2s revoke, so the bar
# shows no stop line and the scripted Slow following the bar never escalates.


def test_e_a_stop_while_an_accept_waits_shows_no_stop_line(tmp_path: Path) -> None:
    async def case() -> None:
        until = {"fast_user": ("do not accept anything", REVOKE)}
        sim = _in_call(tmp_path, until | {"slow": (STOP_LINE, BAR_ACT)})
        await sim.start()
        await sim.offer(dollars=76)
        sim.post(sim.card())
        await sim.vt.run_for(100)
        sim.rep_composes()  # the accept waits for the floor
        assert sim.accept().startswith("accept_offer: accept line queued (cap-1)")
        sim.user_says(STOP)
        await sim.vt.run_for(10_000)
        sim.rep_done()
        await sim.vt.run_for(10_000)
        revoked = _one(sim, "speak.revoked", cap_id="cap-1")
        replan = _one(sim, "status.changed", previous="COMMIT_AUTHORIZED")
        assert replan.payload["status"] == "NEEDS_REPLAN"
        assert replan.cause_ids == (revoked.event_id,)
        assert _one(sim, "authority.epoch", reason="f2s_revoke")
        assert not sim.of("speak.released", cap_id="cap-1")
        assert all(STOP_LINE not in p.content for p in sim.k.prompts.values())
        assert not sim.of("status.changed", status="ESCALATED")
        assert sim.bb.public.status is CaseStatus.IN_CALL  # Slow's step replanned
        await sim.stop()
        _offline_ok(sim)

    arun(case())
