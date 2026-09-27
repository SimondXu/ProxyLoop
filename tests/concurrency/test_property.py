"""The authority property under 500 interleavings (S1-SYS-02): a hypothesis
state machine drives one real session on virtual time (offers, cards, UI posts,
accepts, stops, revokes, barge-ins, FastU latency, time) and the log must show:

- no ``speak.released{accept}`` under a raised fence, at a stale epoch, past its
  capability's ``expires_ms`` or with its line ending past it;
- at most one released accept per ``terms_hash``;
- no ``speak.released{cap_id}`` while a partner turn is pending (queued, its
  ``utt.final`` not yet in the log) or the rep composes one (option A);
- a partner fence (S1-SYS-23) raised only while an accept is in flight (by
  a rep line landing, or at the mint for lines after the minting Slow step's
  basis), and an accept revoked ``fence`` only under a user fence or after one
  rose while it waited (under partner fences only it waits);
- no accept released before a Slow step completed whose basis is at or after
  every rep line landed after the minting step's basis (review M1: Slow's
  latency varies, so its calls often land while a step is in flight);
- every accept line ending in exactly one ``speak.released`` or
  ``speak.revoked``, by its expiry at the latest (none wedges on
  ``accept_in_flight``: the teardown runs past ``CAP_TTL_MS``);
- the same while Slow declines or re-records the offer under an accept line in
  flight (revoked ``offer_closed`` / ``terms_changed``);
- ``accept_revoked``/``accept_truncated`` only after a real ``speak.revoked`` /
  a real cut delivery; ``seq`` dense.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections import Counter
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, cast

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, rule
from tests.concurrency.harness import (
    LONG,
    Sim,
    SlowGate,
    settle,
    slots,
    terms,
)
from tests.concurrency.test_cases import Valve

from proxyloop.contract.events import ApprovalPost
from proxyloop.contract.state import Blackboard
from proxyloop.core.fold import apply
from proxyloop.guard.capability import CAP_TTL_MS, accept_in_flight, released_accept


class Interleavings(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.dir = tempfile.TemporaryDirectory()
        self.loop = asyncio.new_event_loop()
        self.valve, self.fastc = Valve.__new__(Valve), Valve.__new__(Valve)
        self.run(self._open())
        self.dollars = 60

    async def _open(self) -> None:
        self.valve.__init__()
        self.fastc.__init__()
        gates = {"fast_user": self.valve, "fast_cp": self.fastc}  # FastC: at length
        self.sim = Sim(Path(self.dir.name), {"fast_cp": [LONG]}, gates=gates)
        await self.sim.start()
        self.slow = SlowGate(self.sim)

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
        self._rep("Sorry, can you say that again?")
        self.run(settle())

    def _rep(self, text: str) -> None:  # a composing rep's line is its reply
        (self.sim.rep_done if self.sim.rep.busy else self.sim.rep_says)(text)

    @rule()
    def the_rep_starts_composing(self) -> None:  # a reply to an older line
        if not self.sim.rep.busy:
            self.sim.rep_composes()
        self.run(settle())

    @rule(speaks=st.booleans())
    def the_rep_is_done(self, speaks: bool) -> None:
        if self.sim.rep.busy:
            self.sim.rep_done("Correction: that offer is gone." if speaks else None)
        self.run(settle())

    @rule(answering=st.booleans())
    def fastu_latency(self, answering: bool) -> None:
        (self.valve.open.set if answering else self.valve.open.clear)()
        self.run(settle())

    @rule(answering=st.booleans())
    def slow_latency(self, answering: bool) -> None:
        """Slow's calls answer, or a step starts (a relay, a timer) and is held
        in flight while the rep talks and Slow's tools act (review M1)."""
        self.slow.let(None if answering else 0)
        if not answering:
            assert self.sim.k.slow is not None
            self.sim.k.slow.wake("timer")
        self.run(settle())

    @rule(answering=st.booleans())
    def fastc_latency(self, answering: bool) -> None:  # a partner fence stays up
        (self.fastc.open.set if answering else self.fastc.open.clear)()
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

    @rule(change=st.sampled_from(["decline", "revise"]))
    def the_offer_changes_mid_accept(self, change: str) -> None:
        """While an accept line waits for the floor, Slow declines the offer
        (``offer_closed``) or re-records it (``terms_changed``)."""
        if not accept_in_flight(self.sim.k.bb):
            return
        if change == "decline":
            self.sim.act({"tool": "decline_offer", "offer_ref": "o1"})
        else:
            said = [
                x
                for x in self.sim.bb.channels["cp"].lines
                if x.speaker == "partner" and x.text == terms(self.dollars)
            ]
            if not said:  # the rep's line has not landed yet
                return
            record: dict[str, object] = {"tool": "record_offer", "offer_ref": "o1"}
            record["offer_slots"] = slots(self.dollars, said[-1].utt_id)
            self.sim.act(record)
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
        self._rep(terms(self.dollars))
        self.run(self.sim.vt.run_for(1_500))  # the rep's line lands (a barge-in)
        rep = [x for x in self.sim.bb.channels["cp"].lines if x.speaker == "partner"]
        record: dict[str, object] = {"tool": "record_offer", "offer_ref": "o1"}
        record["offer_slots"] = slots(self.dollars, rep[-1].utt_id)
        ask = {"tool": "guide_fast", "move": "ask_readback", "slots": ["offer:o1"]}
        self.sim.act(record, ask)
        self._rep(terms(self.dollars))  # the read-back
        self.run(self.sim.vt.run_for(1_500))
        self.sim.tools.readback()

    def teardown(self) -> None:
        try:
            self.valve.open.set()  # FastU and FastC answer; every fence can clear
            self.fastc.open.set()
            self.slow.let(None)
            if self.sim.rep.busy:  # the rep's turn ends: every line can go out
                self.sim.rep_done()
            # every queued line gets the floor, or expires waiting for it
            self.run(self.sim.vt.run_for(CAP_TTL_MS + 30_000))
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
    by_user: dict[str, bool] = {}  # fence_id -> raised by a user.msg
    users: list[int] = []  # the seqs of user fences raised
    for e in events:
        if e.type == "authority.fence" and e.payload["op"] == "raised":
            (said,) = [by_id[c] for c in e.cause_ids]
            by_user[str(e.payload["fence_id"])] = said.type == "user.msg"
            users += [e.seq] if said.type == "user.msg" else []
            if said.type == "utt.final":  # a partner fence: an accept in flight
                assert accept_in_flight(bb), f"{e.event_id}: no accept in flight"
            else:
                assert said.type == "user.msg", e
        if e.type == "speak.revoked" and e.payload["reason"] == "fence":
            (line,) = [by_id[c] for c in e.cause_ids]
            up = [f for f in bb.fences if by_user[f.fence_id]]
            rose = [u for u in users if u > line.seq]
            assert up or rose, f"{e.event_id}: revoked under partner fences only"
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
    _partner_first(sim)
    _slow_saw_it(sim)
    accepts = [
        e.event_id
        for e in events
        if e.type == "speak.verbatim" and e.payload["kind"] == "accept"
    ]
    assert all(ends[a] == 1 for a in accepts), f"accept lines' endings: {ends}"
    assert not any(
        c.intent == "accept_offer" and not c.consumed for c in bb.capabilities.values()
    )


def _slow_saw_it(sim: Sim) -> None:
    """Every rep line after the minting step's basis (or the mint, outside a
    step) and before the release: a Slow step completed before the release
    with its basis at or after the line."""
    step: int | None = None  # the basis of the Slow step in flight
    since: dict[str, int] = {}  # cap_id -> the seq after which lines count
    lines: list[int] = []
    done: list[tuple[int, int]] = []  # (seq, basis) of completed steps
    for e in sim.events:
        p = e.payload
        if e.type == "slow.step.started":
            step = int(str(p["basis_seq"]))
        elif e.type == "slow.step.completed":
            step = None
            done.append((e.seq, int(str(p["basis_seq"]))))
        elif e.type == "utt.final" and p["speaker"] == "partner":
            lines.append(e.seq)
        elif e.type == "action.authorized" and p["intent"] == "accept_offer":
            cap = cast(dict[str, object], p["capability"])
            since[str(cap["cap_id"])] = e.seq if step is None else step
        elif e.type == "speak.released" and "cap_id" in p:
            after = since[str(p["cap_id"])]
            for line in [x for x in lines if after < x]:
                seen = [s for s, b in done if b >= line]
                assert seen, f"{e.event_id}: released before Slow saw line {line}"


def _partner_first(sim: Sim) -> None:
    """A rep turn is pending from its queueing until its ``utt.final``, and
    the rep is busy while it composes one: no accept is released in either
    window (it is revalidated after the turn)."""
    events = sim.events
    said = [
        e.seq
        for e in events
        if e.type == "utt.final" and e.payload["speaker"] == "partner"
    ]
    ends = said + [len(events)] * (len(sim.rep_turns) - len(said))
    spans = list(zip(sim.rep_turns, ends, strict=True))
    spans += [(a, len(events) if b < 0 else b) for a, b in sim.rep_busy]
    for e in events:
        if e.type == "speak.released" and "cap_id" in e.payload:
            pending = [(a, b) for a, b in spans if a <= e.seq < b]
            assert not pending, f"{e.event_id}: released with the rep mid-turn"


TestInterleavings = Interleavings.TestCase  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
TestInterleavings.settings = settings(  # 500 interleavings
    max_examples=500, stateful_step_count=16, deadline=None
)
