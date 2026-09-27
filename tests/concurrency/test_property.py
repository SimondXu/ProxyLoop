"""The authority property under 500 interleavings (S1-SYS-02): a hypothesis
state machine drives one real session on virtual time (offers, cards, UI posts,
accepts, stops, revokes, barge-ins, FastU latency, time) and the log must show:

- no ``speak.released{accept}`` under a raised fence, at a stale epoch, past its
  capability's ``expires_ms`` or with its line ending past it;
- at most one released accept per ``terms_hash``;
- every accept line ending in exactly one ``speak.released`` or
  ``speak.revoked`` (none wedges on ``accept_in_flight``);
- ``accept_revoked``/``accept_truncated`` only after a real ``speak.revoked`` /
  a real cut delivery; ``seq`` dense.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections import Counter
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, rule
from tests.concurrency.harness import LONG, Sim, settle, slots, terms
from tests.concurrency.test_cases import Valve

from proxyloop.contract.events import ApprovalPost
from proxyloop.contract.state import Blackboard
from proxyloop.core.fold import apply
from proxyloop.guard.capability import released_accept


class Interleavings(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.dir = tempfile.TemporaryDirectory()
        self.loop = asyncio.new_event_loop()
        self.valve = Valve.__new__(Valve)
        self.run(self._open())
        self.dollars = 60

    async def _open(self) -> None:
        self.valve.__init__()
        gates = {"fast_user": self.valve}  # FastC answers the rep at length
        self.sim = Sim(Path(self.dir.name), {"fast_cp": [LONG]}, gates=gates)
        await self.sim.start()

    def run(self, step: Coroutine[Any, Any, None]) -> None:
        self.loop.run_until_complete(step)

    @initialize()
    def a_granted_offer(self) -> None:  # most interleavings start at the accept
        self._offer()
        self.sim.act({"tool": "request_approval", "offer_ref": "o1"})
        self.the_ui_posts("granted", stale=False)

    # The world and the UI.
    @rule(ms=st.sampled_from([50, 700, 4_000, 15_000, 60_000]))
    def time_passes(self, ms: int) -> None:
        self.run(self.sim.vt.run_for(ms))

    @rule(margin=st.sampled_from([1_000, 6_000, 20_000]))
    def a_grant_nears_its_expiry(self, margin: int) -> None:
        now, bb = self.sim.vt.monotonic_ms(), self.sim.bb
        ends = [a.expires_ms for a in bb.private.approvals.values() if a.expires_ms]
        if live := [t for t in ends if t - margin > now]:
            self.run(self.sim.vt.run_for(min(live) - margin - now))

    @rule(fastu_answers=st.booleans())
    def the_user_writes(self, fastu_answers: bool) -> None:
        if not fastu_answers:  # the fence stays up until FastU answers
            self.valve.open.clear()
        self.sim.user_says("Wait, stop: do not accept anything yet.")
        self.run(settle())

    @rule()
    def the_rep_talks(self) -> None:
        self.sim.rep_says("Sorry, can you say that again?")
        self.run(settle())

    @rule(answering=st.booleans())
    def fastu_latency(self, answering: bool) -> None:
        (self.valve.open.set if answering else self.valve.open.clear)()
        self.run(settle())

    @rule(
        decision=st.sampled_from(["granted", "granted", "denied"]), stale=st.booleans()
    )
    def the_ui_posts(self, decision: str, stale: bool) -> None:
        card = self.sim.bb.private.pending_approval
        if card is None:
            return
        post = {"subject": "approval", "subject_id": card.approval_id}
        post |= {"decision": decision, "subject_hash": card.terms_hash}
        post |= {"authority_epoch": card.authority_epoch - int(stale)}
        self.sim.k.post_approval(ApprovalPost.model_validate(post))
        self.run(settle())

    # Slow's tools, whatever Guard answers.
    @rule(step=st.sampled_from(["next", "next", "next", "accept", "revoke"]))
    def slow_acts(self, step: str) -> None:
        self._act(step)

    @rule()
    def slow_makes_progress(self) -> None:  # weights Slow's next call up
        self._act("next")

    def _act(self, step: str) -> None:
        """``next``: what a Slow making progress calls next (a new offer, a
        card, or the accept); Guard decides each call on ``Kernel.bb``."""
        if step == "next":
            step = self._next()
        if step == "offer":
            self._offer()
        elif step == "card":
            self.sim.act({"tool": "request_approval", "offer_ref": "o1"})
        elif step == "accept":
            self.sim.act({"tool": "accept_offer", "offer_ref": "o1"})
        else:
            self.sim.act({"tool": "revoke"})
        self.run(settle())

    def _next(self) -> str:
        bb = self.sim.k.bb
        offer = bb.public.offers.get("o1")
        if (
            offer is None
            or offer.terms_hash is None
            or released_accept(bb, offer.terms_hash)
        ):
            return "offer"
        now = [
            a for a in bb.private.approvals.values() if a.terms_hash == offer.terms_hash
        ]
        if any(a.authority_epoch == bb.epoch and a.decision == "granted" for a in now):
            return "accept"
        return "offer" if any(a.decision == "denied" for a in now) else "card"

    def _offer(self) -> None:
        self.dollars += 1
        self.sim.rep_says(terms(self.dollars))
        self.run(self.sim.vt.run_for(1_500))  # the rep's line lands (a barge-in)
        rep = [x for x in self.sim.bb.channels["cp"].lines if x.speaker == "partner"]
        record: dict[str, object] = {"tool": "record_offer", "offer_ref": "o1"}
        record["offer_slots"] = slots(self.dollars, rep[-1].utt_id)
        ask = {"tool": "guide_fast", "move": "ask_readback", "slots": ["offer:o1"]}
        self.sim.act(record, ask)
        self.sim.rep_says(terms(self.dollars))  # the read-back
        self.run(self.sim.vt.run_for(1_500))
        self.sim.tools.readback()

    def teardown(self) -> None:
        try:
            self.valve.open.set()  # FastU answers; every fence can clear
            self.run(self.sim.vt.run_for(30_000))  # every queued line gets the floor
            self.run(self._stop())
            _check(self.sim)
        finally:
            left = asyncio.all_tasks(self.loop)  # the Speaker's timer futures
            for task in left:
                task.cancel()
            self.run(_gather(left))
            self.loop.close()
            self.dir.cleanup()

    async def _stop(self) -> None:
        await self.sim.stop()


async def _gather(tasks: set[asyncio.Task[Any]]) -> None:
    await asyncio.gather(*tasks, return_exceptions=True)


def _check(sim: Sim) -> None:
    events = sim.events
    assert [e.seq for e in events] == list(range(len(events))), "seq is not dense"
    by_id, bb = {e.event_id: e for e in events}, Blackboard()
    released: Counter[str] = Counter()
    ends: Counter[str] = Counter()  # accept line -> its releases and revokes
    for e in events:
        if e.type in ("speak.released", "speak.revoked"):
            lines = [by_id[c] for c in e.cause_ids if by_id[c].type == "speak.verbatim"]
            for line in lines:
                if line.payload["kind"] == "accept":
                    ends[line.event_id] += 1
        if e.type == "speak.released" and "cap_id" in e.payload:
            cap = bb.capabilities[str(e.payload["cap_id"])]
            assert not bb.fences, f"{e.event_id}: released under a fence"
            assert cap.epoch == bb.epoch, f"{e.event_id}: released at a stale epoch"
            assert e.t_ms < cap.expires_ms, f"{e.event_id}: released past expiry"
            released[cap.terms_hash] += 1
            heard = [
                d
                for d in events
                if d.type == "utt.delivered" and e.event_id in d.cause_ids
            ]
            assert all(d.t_ms <= cap.expires_ms for d in heard), "heard past expiry"
        if e.type == "status.changed" and e.payload["status"] == "NEEDS_REPLAN":
            why = [by_id[c] for c in e.cause_ids]
            real = [c for c in why if c.type == "speak.revoked"] + [
                c for c in why if c.type == "utt.delivered" and c.payload["interrupted"]
            ]
            assert real or e.payload["previous"] != "COMMIT_AUTHORIZED", e
        bb = apply(bb, e)
    assert all(n == 1 for n in released.values()), f"accepts per terms: {released}"
    accepts = [
        e.event_id
        for e in events
        if e.type == "speak.verbatim" and e.payload["kind"] == "accept"
    ]
    assert all(ends[a] == 1 for a in accepts), f"accept lines' endings: {ends}"
    assert not any(
        c.intent == "accept_offer" and not c.consumed for c in bb.capabilities.values()
    )


TestInterleavings = Interleavings.TestCase  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
TestInterleavings.settings = settings(  # 500 interleavings
    max_examples=500, stateful_step_count=16, deadline=None
)
