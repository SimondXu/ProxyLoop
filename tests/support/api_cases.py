"""A live case handle for the serve tests (tests only, I8). A real ``Bus``
writes ``events.jsonl`` and folds it, so ``guard.decide`` runs on a real
Blackboard whose card ``guard.request_approval`` minted, or whose mandate
``propose`` put there the way Slow's ``propose_mandate`` does. The calls the
API makes are recorded. An approval post only emits ``approval.post`` (actor
``ui``); ``decided`` stands in for the kernel's own ``approval.decided``. A
mandate post is decided at once, roughly as the kernel's ``Authority.decide``
does: ``guard.decide`` on the board, then ``approval.post`` (ui),
``mandate.decided`` (kernel, by ui) and ``authority.epoch``. Unlike the kernel
it emits no ``status.changed`` (mandate_granted), and its ``action.denied`` on
a Denial cites the proposal, never the kernel's root fallback; neither is
reachable through the route, whose pre-check denies first.
``FakeStarter`` starts such cases the way the kernel's starter will."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path

from tests.guard.build import CASE, offer
from tests.support.manual_clock import ManualClock

from proxyloop.contract.bundle import EVENTS
from proxyloop.contract.events import ApprovalPost, Event, Stream
from proxyloop.contract.state import ApprovalCard, Blackboard, Mandate
from proxyloop.core.bus import Bus
from proxyloop.guard.authorize import Denial, decide, request_approval
from proxyloop.guard.mandate import proposal
from proxyloop.guard.terms import offer_terms_hash
from proxyloop.serve.cases import (
    LaneKey,
    ModelOption,
    RoleCard,
    RoleFact,
    StartRefused,
)

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
        self._proposed = ""  # the last mandate.proposed event
        self.unavailable = False  # every ingress raises, as a dead kernel would

    # The Case protocol.
    def blackboard(self) -> Blackboard:
        return self.bus.bb

    def post_approval(self, post: ApprovalPost) -> None:
        if self.unavailable:
            raise RuntimeError("the case's kernel is gone")
        self.posts.append(post)
        if post.subject == "mandate":
            return self._decide_mandate(post)
        self.emit("approval.post", post.model_dump(mode="json"), "ui", causes=())

    def _decide_mandate(self, post: ApprovalPost) -> None:
        """As the kernel's ``Authority.decide`` does for a UI mandate post."""
        got = decide(self.bus.bb, post, "ui")
        if isinstance(got, Denial):
            denied = {"intent": "approval.post", "reason": got.reason}
            self.emit("action.denied", denied, "kernel", causes=[self._proposed])
            return
        sent = self.emit("approval.post", post.model_dump(mode="json"), "ui", causes=())
        kind, payload = got
        done = self.emit(kind, payload, "kernel", causes=[sent.event_id])
        bump = {"new": self.bus.bb.epoch + 1, "reason": "mandate_decided"}
        self.emit("authority.epoch", bump, "kernel", causes=[done.event_id])

    def user_message(self, text: str) -> None:
        if self.unavailable:
            raise RuntimeError("the case's kernel is gone")
        self.messages.append(text)

    def rep_utterance(self, text: str) -> None:
        if self.unavailable:
            raise RuntimeError("the case's kernel is gone")
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

    def end(self, reason: str = "stopped") -> None:
        """The run's last event, as the kernel writes it."""
        self.emit("session.ended", {"reason": reason}, "kernel", "ops", causes=())

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

    def propose(self, mandate_id: str = "mandate-1", **bounds: object) -> Mandate:
        """A mandate proposed as Slow's ``propose_mandate`` does (Guard's
        ``proposal``, at the current epoch); by default a price cap."""
        bounds = bounds or {"max_monthly_price_minor": 7000}
        kind, payload = proposal(self.bus.bb, mandate_id, **bounds)
        self._proposed = self.emit(kind, payload).event_id
        return Mandate.model_validate(payload)

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


class FakeStarter:
    """Implements ``proxyloop.serve.cases.Starter`` over the ``runs`` root
    ``runs``, with the kernel's start semantics: a missing lane gets its
    default, an unknown task, unknown model or model of another lane is
    refused, and a case is returned only after its seq 0 exists, at
    ``runs/live/<run_id>/<run_id>``. ``refuse`` or ``fail`` make the next
    starts refuse or raise; ``returns`` makes them return that case (a run_id
    twice); ``delay_s`` holds each start open (to see the lock); ``hang``
    makes a start never return (``cancelled`` counts the CancelledErrors it
    saw); ``split`` is the seq-0 split of the cases it starts."""

    def __init__(
        self, runs: Path, options: Sequence[ModelOption], tasks: Sequence[str]
    ) -> None:
        self.runs, self.options, self.tasks = runs, options, tasks
        self.calls: list[tuple[str, dict[LaneKey, str], str]] = []
        self.resolved: list[dict[LaneKey, str]] = []  # defaults filled in
        self.cases: list[ApiCase] = []
        self.refuse: str | None = None
        self.fail = False
        self.returns: ApiCase | None = None
        self.delay_s = 0.0
        self.hang = False
        self.cancelled = 0
        self.split = "train"
        self.inside = self.most = 0  # starts in flight now, and at most

    def model_options(self) -> Sequence[ModelOption]:
        return self.options

    def task_options(self) -> Sequence[str]:
        return self.tasks

    def role_card(self, task_ref: str) -> RoleCard:
        """A card that names its task_ref (in its goal), for an offered one."""
        if task_ref not in self.tasks:
            raise StartRefused("unknown_task")
        fact = RoleFact(
            key="account.last4", value="0000", identity=True, shareable=True
        )
        return RoleCard(
            company="Fake Mobile",
            persona="A fake principal.",
            goal=f"The goal of {task_ref}.",
            facts=[fact],
            approval=None,
            stop=None,
        )

    async def start_case(
        self, task_ref: str, models: Mapping[LaneKey, str], rep: str = "sim"
    ) -> ApiCase:
        self.calls.append((task_ref, dict(models), rep))
        self.inside += 1
        self.most = max(self.most, self.inside)
        try:
            await asyncio.sleep(self.delay_s)
            if self.hang:
                await asyncio.Event().wait()  # never set
            return self._start(task_ref, models)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.inside -= 1

    def _start(self, task_ref: str, models: Mapping[LaneKey, str]) -> ApiCase:
        if self.fail:
            raise RuntimeError("the kernel is gone")
        if self.refuse is not None:
            raise StartRefused(self.refuse)
        if task_ref not in self.tasks:
            raise StartRefused("unknown_task")
        by_id = {option.id: option for option in self.options}
        for lane, option_id in models.items():
            if option_id not in by_id:
                raise StartRefused("unknown_model")
            if by_id[option_id].lane != lane:
                raise StartRefused("wrong_lane")
        defaults: dict[LaneKey, str] = {o.lane: o.id for o in self.options if o.default}
        self.resolved.append(defaults | dict(models))
        if self.returns is not None:
            return self.returns
        run_id = f"live-{len(self.cases) + 1}"
        case = ApiCase(self.runs / "live" / run_id, run_id).start(self.split)
        self.cases.append(case)
        return case
