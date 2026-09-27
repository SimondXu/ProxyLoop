"""Authority timing in the kernel (ARCHITECTURE §9.4, §9.5, §11).

- **Fence.** Every ``user.msg`` raises one at once, before anything else. It
  clears at the first ``slow.step.completed`` whose ``basis_seq`` is at or after
  the FastU ``fast.turn`` whose request saw the message: Slow has seen whatever
  FastU relayed, even if it relayed nothing (a Fast failure, measured). Binding
  a turn wakes Slow, so a fence never waits on a step that is not coming.
- **Partner fence** (S1-SYS-23). Guard cannot read a rep line, so an accept
  waits (the Speaker) until every rep line before it is **covered**: a FastC
  ``fast.turn`` whose request's ``basis_seq`` is at or after the line, and a
  completed Slow step whose ``basis_seq`` is at or after that turn (Slow has
  seen whatever FastC relayed of it). The accept's ``action.authorized`` raises
  a fence for each rep line not yet covered (caused by the line and the mint;
  bound at once if that turn exists), and a rep line landing while the accept
  is in flight raises one at once. Each clears as a user fence does. The
  guarantee: no accept is released before every rep line that landed before
  the release is covered. The one exception is a cp fence FastC never bound
  when the call closes: it clears at ``chan.closed``, and the line is then
  revoked ``call_closed``, never released.
- ``Fence.utt_id`` is the ``user.msg`` event id for a user fence (that line's
  id on the board) and the rep line's ``utt_id`` for a partner fence.
- **Epochs.** An f2s ``REVOKE`` bumps the epoch at once (models restrict, never
  grant; I6), and so does every ``mandate.decided``.
- **Approvals.** Each ``approval.post`` (the UI endpoint or the sim approver)
  waits in a queue; the kernel re-decides it with ``guard.decide`` on the board
  at the bus clock's now (N-c). A decision is ``approval.post`` then its
  ``approval.decided``/``mandate.decided``; a refusal is the restrict-only
  ``action.denied{intent: approval.post}`` citing the card or proposal (M1).
- **The sim approver** (#143) decides a card at once, then the SimUser's
  ``after_card`` trigger runs; the grant is posted ``delay_s`` after the card
  and never before that stop is delivered (N6).
- **Status.** A decided card moves AWAITING_APPROVAL back to IN_CALL, and
  NEEDS_REPLAN goes back to IN_CALL once Slow completed a step that saw it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any

from proxyloop.contract.base import Lane
from proxyloop.contract.events import ApprovalPost, Approver, Event
from proxyloop.contract.state import ApprovalCard, CaseStatus, Mandate
from proxyloop.env.user.approver import Post
from proxyloop.guard.authorize import Denial, decide
from proxyloop.guard.capability import accept_in_flight
from proxyloop.guard.status import status_change
from proxyloop.kernel.channels import SimUserChannel

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

Stop = Coroutine[Any, Any, asyncio.Event | None]  # set once the stop is delivered
_OFFERED = ("offer", "final_offer")  # rep.policy intents: the after_offer trigger


class Authority:
    def __init__(self, k: Kernel) -> None:
        self._k, self._n = k, 0
        self.queue: asyncio.Queue[tuple[ApprovalPost, Approver]] = asyncio.Queue()
        self.root = ""  # session.started: the cause of a post for no known subject
        # fence_id -> (its lane, its utt, that line's seq, the binding turn's seq)
        self._raised: dict[str, tuple[Lane, str, int, int | None]] = {}
        self._basis: dict[str, int] = {}  # Fast gen_id -> its request's basis
        # rep lines not yet covered: [event id, utt, seq, the first FastC turn
        # whose request saw the line (its seq)]
        self._lines: list[tuple[str, str, int, int | None]] = []
        self._moved = asyncio.Event()  # set (and replaced) as a fence moves
        self.user_fences = 0  # user fences raised so far
        self._asked: dict[str, str] = {}  # card or mandate id -> the asking event
        self._replan: int | None = None  # the NEEDS_REPLAN status.changed seq

    def on_event(self, e: Event) -> None:
        p, k = e.payload, self._k
        if e.type == "user.msg" and k.slow is not None:  # rep-chat has no Slow
            self._raise([e.event_id], e.seq, "user", e.event_id)
        elif e.type == "utt.final" and p["lane"] == "cp" and p["speaker"] == "partner":
            self._rep_line(e)
        elif e.type == "action.authorized" and p["intent"] == "accept_offer":
            self._minted(e)
        elif e.type == "fast.request":
            self._basis[str(p["gen_id"])] = int(str(p["basis_seq"]))
        elif e.type == "fast.cancelled":  # stale: it makes no turn
            self._basis.pop(str(p["gen_id"]), None)
        elif e.type == "fast.turn":
            self._bind(e)
        elif e.type == "chan.closed":
            self._closed(e)
        elif e.type == "authority.epoch":  # a waiting accept revalidates now
            self._move()
        elif e.type == "slow.step.completed":
            self._completed(e)
        elif e.type == "f2s.msg" and p["type"] == "REVOKE":
            bump = {"new": k.bb.epoch + 1, "reason": "f2s_revoke"}
            k.emit("authority.epoch", "kernel", bump, [e.event_id])
        elif e.type in ("approval.requested", "mandate.proposed"):
            self._asked[str(p.get("approval_id") or p["mandate_id"])] = e.event_id
            self._sim(e)
        elif e.type == "rep.policy" and p["intent"] in _OFFERED:
            self._trigger(e)
        elif e.type == "status.changed" and p["status"] == CaseStatus.NEEDS_REPLAN:
            self._replan = e.seq
            self._wake("replan")
        elif e.type in ("approval.decided", "mandate.decided", "speak.revoked"):
            self._wake(e.type)

    def move(self, trigger: str, cause: str) -> bool:
        """The §9.5 move ``trigger`` (a Guard ``status.changed``), if legal now."""
        change = status_change(self._k.bb, trigger)
        if change is not None:
            self._k.emit("status.changed", "guard", change, [cause])
        return change is not None

    def _wake(self, reason: str) -> None:
        if self._k.slow is not None:
            self._k.slow.wake(reason)

    def partner_only(self) -> bool:
        """Fences are raised, and every one is a partner fence."""
        lanes = {lane for lane, *_ in self._raised.values()}
        return lanes == {"cp"}

    def moved(self) -> Coroutine[Any, Any, bool]:
        """Until a fence is raised or cleared, the epoch moves or the call
        closes, after this call: bound to the current event now, not when the
        waiter first runs."""
        return self._moved.wait()

    def _move(self) -> None:
        self._moved.set()
        self._moved = asyncio.Event()

    def _live(self) -> bool:  # a partner fence can bind: a Slow, a live call
        return self._k.slow is not None and not self._k.closed

    def _rep_line(self, said: Event) -> None:
        if not self._live():  # no mint follows: nothing to cover
            return
        utt = str(said.payload["utt_id"])
        self._lines.append((said.event_id, utt, said.seq, None))
        if accept_in_flight(self._k.bus.bb):
            self._raise([said.event_id], said.seq, "cp", utt)

    def _minted(self, auth: Event) -> None:
        """A fence for each rep line not yet covered and not yet fenced."""
        if not self._live():
            return
        fenced = {seq for lane, _, seq, _ in self._raised.values() if lane == "cp"}
        for said, utt, seq, turn in self._lines:
            if seq not in fenced:
                self._raise([said, auth.event_id], seq, "cp", utt, turn)

    def _raise(
        self, causes: list[str], seq: int, lane: Lane, utt: str, at: int | None = None
    ) -> None:
        self._n += 1
        self.user_fences += lane == "user"
        fence = {"op": "raised", "fence_id": f"fence-{self._n}", "utt_id": utt}
        self._raised[fence["fence_id"]] = (lane, utt, seq, at)
        self._k.emit("authority.fence", "kernel", fence, causes)
        self._move()
        if at is not None:  # bound already: a step must see that turn
            self._wake("fence")

    def _bind(self, turn: Event) -> None:
        lane = str(turn.payload["lane"])
        basis = self._basis.pop(str(turn.payload["gen_id"]), -1)
        if lane == "cp":  # the lines this turn's request saw
            self._lines = [
                (e, u, s, t if t is not None or s > basis else turn.seq)
                for e, u, s, t in self._lines
            ]
        for fence, (on, utt, seq, at) in self._raised.items():
            if on == lane and at is None and seq <= basis:  # its request saw the line
                self._raised[fence] = (on, utt, seq, turn.seq)
                self._wake("fence")

    def _clear(self, fence: str, cause: str) -> None:
        utt = self._raised.pop(fence)[1]
        cleared = {"op": "cleared", "fence_id": fence, "utt_id": utt}
        self._k.emit("authority.fence", "kernel", cleared, [cause])
        self._move()

    def _closed(self, closed: Event) -> None:
        """FastC answers nothing more: an unbound cp fence clears (a waiting
        accept is then revoked ``call_closed``)."""
        for fence, (lane, _, _, at) in list(self._raised.items()):
            if lane == "cp" and at is None:
                self._clear(fence, closed.event_id)
        self._move()

    def _completed(self, step: Event) -> None:
        basis = int(str(step.payload["basis_seq"]))
        self._lines = [x for x in self._lines if x[3] is None or x[3] > basis]
        for fence, (*_, at) in list(self._raised.items()):
            if at is not None and at <= basis:
                self._clear(fence, step.event_id)
        if self._replan is not None and self._replan <= basis:
            self._replan = None
            if self.move("replan", step.event_id):  # Slow did not escalate
                self._wake("replan")

    # The approvals queue.
    def post(self, post: ApprovalPost, by: Approver) -> None:
        """Enqueue ``post`` (N-d: this succeeds or raises; it never decides)."""
        self.queue.put_nowait((post, by))

    async def run(self) -> None:
        while True:
            self.decide(*await self.queue.get())

    def decide(self, post: ApprovalPost, by: Approver) -> None:
        k = self._k
        got = decide(k.bb, post, by)
        if isinstance(got, Denial):
            denied = {"intent": "approval.post", "reason": got.reason}
            asked = self._asked.get(post.subject_id, self.root)
            k.emit("action.denied", "kernel", denied, [asked])
            self._wake("approval_denied")
            return
        sim = by == "sim_approver" and post.subject_id in self._asked
        cause = [self._asked[post.subject_id]] if sim else []  # UI posts: exogenous
        body = post.model_dump(mode="json")
        posted = k.emit("approval.post", by, body, cause).event_id
        kind, payload = got
        decided = k.emit(kind, "kernel", payload, [posted]).event_id
        if kind == "approval.decided":
            self.move("approval_decided", decided)
            return
        bump = {"new": k.bb.epoch + 1, "reason": "mandate_decided"}
        k.emit("authority.epoch", "kernel", bump, [decided])
        if post.decision == "granted":
            self.move("mandate_granted", decided)

    # The sim approver and the SimUser's triggers (#143).
    def _sim(self, e: Event) -> None:
        k, user = self._k, self._k.channels.get("user")
        if not isinstance(user, SimUserChannel) or (approver := user.approver) is None:
            return
        if e.type == "mandate.proposed":
            post = approver.decide_mandate(Mandate.model_validate(e.payload))
            k.spawn(self._later(post, e.t_ms, None))
            return
        card = ApprovalCard.model_validate(e.payload)
        post = approver.decide(card, k.bb.public.offers[card.offer_ref])  # first
        k.spawn(
            self._later(post, e.t_ms, user.trigger("after_card", e.event_id, e.t_ms))
        )

    async def _later(self, post: Post, t_ms: int, stop: Stop | None) -> None:
        k = self._k
        delivered = None if stop is None else await stop
        if (wait := t_ms + round(1000 * post.delay_s) - k.now()) > 0:
            await k.sleep(wait / 1000)
        if delivered is not None:
            await delivered.wait()  # N6: the grant never lands before the stop
        self.post(post.post, "sim_approver")

    def _trigger(self, e: Event) -> None:
        user = self._k.channels.get("user")
        if isinstance(user, SimUserChannel):
            stop = user.trigger("after_offer", e.event_id, e.t_ms)

            async def fire() -> None:
                await stop

            self._k.spawn(fire())
