"""A live case handle for the serve tests (tests only, I8). A real ``Bus``
writes ``events.jsonl`` and folds it, so ``guard.decide`` runs on a real
Blackboard whose card ``guard.request_approval`` minted. The calls the API
makes are recorded; ``post_approval`` also emits ``approval.post`` (actor
``ui``) the way the kernel's ingress will (S1-SYS-05). Nothing here decides:
``decided`` stands in for the kernel's own ``approval.decided``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from tests.guard.build import CASE, offer
from tests.support.manual_clock import ManualClock

from proxyloop.contract.bundle import EVENTS
from proxyloop.contract.events import ApprovalPost, Event, Stream
from proxyloop.contract.state import ApprovalCard, Blackboard
from proxyloop.core.bus import Bus
from proxyloop.guard.authorize import Denial, request_approval
from proxyloop.guard.terms import offer_terms_hash

_KEYS = "cfg_hash task_ref instance_hash models renderer_fp contract_version git_sha"
_STARTED = dict.fromkeys([*_KEYS.split(), "attest", "parity"], "x")


class ApiCase:
    """Implements ``proxyloop.serve.cases.Case`` for one run under ``root``."""

    def __init__(self, root: Path, run_id: str) -> None:
        self.run_id = run_id
        self.clock = ManualClock()
        (root / run_id).mkdir(parents=True)
        self.bus = Bus(root / run_id / EVENTS, run_id, self.clock)
        self.posts: list[ApprovalPost] = []
        self.messages: list[str] = []
        self.utterances: list[str] = []
        self._last: str | None = None

    # The Case protocol.
    def blackboard(self) -> Blackboard:
        return self.bus.bb

    def post_approval(self, post: ApprovalPost) -> None:
        self.posts.append(post)
        self.emit("approval.post", post.model_dump(mode="json"), "ui", causes=())

    def user_message(self, text: str) -> None:
        self.messages.append(text)

    def rep_utterance(self, text: str) -> None:
        self.utterances.append(text)

    # Test setup: real events through the bus.
    def emit(
        self,
        type_: str,
        payload: Mapping[str, object],
        actor: str = "guard",
        stream: Stream = "agent",
        causes: Sequence[str] | None = None,
    ) -> Event:
        cited = ([self._last] if self._last else []) if causes is None else causes
        event = self.bus.emit(type_, actor, stream, payload, cited)
        self._last = event.event_id
        return event

    def start(self, split: str = "train") -> ApiCase:
        self.emit("session.started", _STARTED | {"split": split}, "kernel", "ops")
        return self

    def card(self, ref: str = "o1", revision: int = 1) -> ApprovalCard:
        """Record and confirm offer ``ref``, then the card Guard mints for it."""
        raw = offer(ref, revision=revision)
        kept = raw.model_dump(mode="json", include={"offer_ref", "revision", "slots"})
        self.emit("offer.recorded", kept | {"terms_hash": None})
        slots = tuple(s.model_copy(update={"status": "confirmed"}) for s in raw.slots)
        bound = offer_terms_hash(raw.model_copy(update={"slots": slots}))
        statuses = {s.field: "confirmed" for s in raw.slots}
        update = {"offer_ref": ref, "revision": revision, "slot_statuses": statuses}
        self.emit("readback.updated", update | {"terms_hash": bound})
        effects = request_approval(self.bus.bb, ref, CASE)
        assert not isinstance(effects, Denial), effects
        ((kind, payload),) = effects
        self.emit(kind, payload)
        return ApprovalCard.model_validate(payload)

    def bump_epoch(self) -> None:
        new = self.bus.bb.epoch + 1
        self.emit("authority.epoch", {"new": new, "reason": "slow_revoke"})

    def revise(self, ref: str = "o1") -> None:
        """A new revision of the offer: the pending card is superseded."""
        now = self.bus.bb.public.offers[ref].revision + 1
        raw = offer(ref, revision=now, monthly="6500")
        kept = raw.model_dump(mode="json", include={"offer_ref", "revision", "slots"})
        self.emit("offer.recorded", kept | {"terms_hash": None})

    def expire(self, card: ApprovalCard) -> None:
        """Move the clock past the card's expiry; an event carries it into bb."""
        self.clock.advance(card.expires_ms - self.clock.monotonic_ms())
        self.emit("user.msg", {"text": "later"}, "kernel")

    def decided(self) -> None:
        """What the kernel does after the post: its own approval.decided."""
        post = self.posts[-1]
        done = {"approval_id": post.subject_id, "decision": post.decision, "by": "ui"}
        self.emit("approval.decided", done, "kernel", causes=[str(self._last)])

    def posted(self) -> int:
        """How many approval.post events the log holds."""
        return sum(e.type == "approval.post" for e in self.bus.events)

    def close(self) -> None:
        self.bus.close()


class StoredCase:
    """A case handle over a run written by hand (the rep-stream fixture): only
    its run_id is used; any call the stream should never make fails."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id

    def blackboard(self) -> Blackboard:
        raise AssertionError("the rep stream never reads the blackboard")

    def post_approval(self, post: ApprovalPost) -> None:
        raise AssertionError("not called by a stream")

    def user_message(self, text: str) -> None:
        raise AssertionError("not called by a stream")

    def rep_utterance(self, text: str) -> None:
        raise AssertionError("not called by a stream")
