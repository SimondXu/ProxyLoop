"""Authority timing in the kernel (ARCHITECTURE §9.4, §9.5, §11).

- **Fence.** Every ``user.msg`` raises one at once, before anything else. It
  clears at the first ``slow.step.completed`` whose ``basis_seq`` is at or after
  the FastU ``fast.turn`` whose request saw the message: Slow has seen whatever
  FastU relayed, even if it relayed nothing (a Fast failure, measured). Binding
  a turn wakes Slow, so a fence never waits on a step that is not coming.
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

from proxyloop.contract.events import ApprovalPost, Approver, Event
from proxyloop.contract.state import ApprovalCard, CaseStatus, Mandate
from proxyloop.env.user.approver import Post
from proxyloop.guard.authorize import Denial, decide
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
        # fence_id -> (its user.msg, that message's seq, the binding turn's seq)
        self._raised: dict[str, tuple[str, int, int | None]] = {}
        self._basis: dict[str, int] = {}  # FastU gen_id -> its request's basis
        self._asked: dict[str, str] = {}  # card or mandate id -> the asking event
        self._replan: int | None = None  # the NEEDS_REPLAN status.changed seq

    def on_event(self, e: Event) -> None:
        p, k = e.payload, self._k
        if e.type == "user.msg" and k.slow is not None:  # rep-chat has no Slow
            self._raise(e)
        elif e.type == "fast.request" and p["lane"] == "user":
            self._basis[str(p["gen_id"])] = int(str(p["basis_seq"]))
        elif e.type == "fast.turn" and p["lane"] == "user":
            self._bind(e)
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

    def _raise(self, msg: Event) -> None:
        self._n += 1
        fence = {"op": "raised", "fence_id": f"fence-{self._n}", "utt_id": msg.event_id}
        self._raised[fence["fence_id"]] = (msg.event_id, msg.seq, None)
        self._k.emit("authority.fence", "kernel", fence, [msg.event_id])

    def _bind(self, turn: Event) -> None:
        basis = self._basis.pop(str(turn.payload["gen_id"]), -1)
        for fence, (msg, seq, at) in self._raised.items():
            if at is None and seq <= basis:  # this turn's request saw the message
                self._raised[fence] = (msg, seq, turn.seq)
                self._wake("fence")

    def _completed(self, step: Event) -> None:
        basis, k = int(str(step.payload["basis_seq"])), self._k
        for fence, (msg, _, at) in list(self._raised.items()):
            if at is not None and at <= basis:
                del self._raised[fence]
                cleared = {"op": "cleared", "fence_id": fence, "utt_id": msg}
                k.emit("authority.fence", "kernel", cleared, [step.event_id])
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
