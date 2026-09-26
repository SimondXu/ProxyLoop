"""Allow-list views of the blackboard (ARCHITECTURE §5).

``view_cp`` reads only ``bb.public`` and ``bb.channels`` (an AST test holds it
to that), so ``FastView[cp]`` is a function of public state, the cp
transcript, the trigger and the task's public brief (I4). The brief is task
data, not state, so the views take it as an argument (ADR-0004).
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from proxyloop.contract.base import Frozen, Lane
from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.messages import FastToSlow, Guide, SlowToFast
from proxyloop.contract.state import (
    Approval,
    ApprovalCard,
    Blackboard,
    CaseStatus,
    ChannelState,
    Fact,
    Fence,
    HoldState,
    Line,
    Mandate,
    OfferPublic,
    PublicFact,
)

TriggerKind = Literal[
    "user_msg",
    "slow_msg",
    "approval_card",
    "session_start",
    "rep_spoke",
    "hold_wait",
    "guidance",
    "call_connected",
]
TRIGGER_LANE: dict[TriggerKind, Lane] = {
    "user_msg": "user",
    "slow_msg": "user",
    "approval_card": "user",
    "session_start": "user",
    "rep_spoke": "cp",
    "hold_wait": "cp",
    "guidance": "cp",
    "call_connected": "cp",
}


class Trigger(Frozen):
    kind: TriggerKind
    msg_id: str | None = None  # slow_msg: the pending s2f message it voices
    wait_s: int | None = Field(default=None, ge=0)  # hold_wait

    @model_validator(mode="after")
    def _args(self) -> Self:
        if (self.msg_id is not None) != (self.kind == "slow_msg"):
            raise ValueError("msg_id is set iff kind is slow_msg")
        if (self.wait_s is not None) != (self.kind == "hold_wait"):
            raise ValueError("wait_s is set iff kind is hold_wait")
        return self


class FastView(Frozen):
    """Everything one Fast generation may see; stored in ``prompts.jsonl``."""

    lane: Lane
    brief: str
    private_summary: str | None = None  # user lane only
    public_summary: str
    action_log: tuple[str, ...]
    offers: tuple[OfferPublic, ...]
    public_facts: tuple[PublicFact, ...] = ()  # cp lane: resolves guide slots
    pending_approval: ApprovalCard | None = None  # user lane only
    guidance: tuple[Guide, ...] = ()  # cp lane only
    hold: HoldState | None = None  # cp lane only
    status: CaseStatus
    transcript: tuple[Line, ...]
    trigger: Trigger
    slow_msg: SlowToFast | None = None  # user lane: the message to convey

    @model_validator(mode="after")
    def _lane_fields(self) -> Self:
        if TRIGGER_LANE[self.trigger.kind] != self.lane:
            raise ValueError(
                f"trigger {self.trigger.kind} is not a {self.lane} trigger"
            )
        if self.lane == "cp":
            private = (self.private_summary, self.pending_approval, self.slow_msg)
            if any(value is not None for value in private):
                raise ValueError("FastView[cp] carries no private or Slow text")
        elif self.guidance or self.hold is not None or self.public_facts:
            raise ValueError("guidance, hold and facts are cp-lane fields")
        if (self.slow_msg is not None) != (self.trigger.kind == "slow_msg"):
            raise ValueError("slow_msg is set iff the trigger is slow_msg")
        if self.trigger.kind == "approval_card" and self.pending_approval is None:
            raise ValueError("an approval_card trigger needs the pending card")
        return self


class SlowView(Frozen):
    """Relay-only by default: no transcripts unless ``raw_transcript`` (I5)."""

    mode: SlowViewMode
    brief: str
    public_summary: str
    private_summary: str
    relays: tuple[FastToSlow, ...]
    offers: tuple[OfferPublic, ...]
    public_facts: tuple[PublicFact, ...]
    case_facts: tuple[Fact, ...]
    mandate: Mandate | None
    pending_approval: ApprovalCard | None
    approvals: tuple[Approval, ...]
    status: CaseStatus
    epoch: int
    fences: tuple[Fence, ...]
    cp_hold: HoldState | None
    cp_strikes: int
    transcripts: dict[Lane, tuple[Line, ...]] = Field(
        default_factory=dict[Lane, tuple[Line, ...]]
    )


def view_user(bb: Blackboard, trigger: Trigger, brief: str) -> FastView:
    slow_msg = None
    if trigger.kind == "slow_msg":
        pending = bb.s2f_pending.get("user", ())
        found = [m for m in pending if m.msg_id == trigger.msg_id]
        if not found or found[0].type not in ("ASK_USER", "TELL_USER"):
            raise ValueError(f"no pending ASK_USER/TELL_USER {trigger.msg_id!r}")
        slow_msg = found[0]
    return FastView(
        lane="user",
        brief=brief,
        private_summary=bb.private.summary,
        public_summary=bb.public.summary,
        action_log=bb.public.action_log,
        offers=tuple(bb.public.offers.values()),
        pending_approval=bb.private.pending_approval,
        status=bb.public.status,
        transcript=bb.channels.get("user", ChannelState()).lines,
        trigger=trigger,
        slow_msg=slow_msg,
    )


def view_cp(bb: Blackboard, trigger: Trigger, brief: str) -> FastView:
    public = bb.public
    return FastView(
        lane="cp",
        brief=brief,
        public_summary=public.summary,
        action_log=public.action_log,
        offers=tuple(public.offers.values()),
        public_facts=tuple(public.facts.values()),
        guidance=public.guidance_cp,
        hold=public.cp_hold,
        status=public.status,
        transcript=bb.channels.get("cp", ChannelState()).lines,
        trigger=trigger,
    )


def view_slow(bb: Blackboard, mode: SlowViewMode, brief: str) -> SlowView:
    transcripts: dict[Lane, tuple[Line, ...]] = {}
    if mode is SlowViewMode.RAW_TRANSCRIPT:
        transcripts = {lane: channel.lines for lane, channel in bb.channels.items()}
    return SlowView(
        mode=mode,
        brief=brief,
        public_summary=bb.public.summary,
        private_summary=bb.private.summary,
        relays=bb.f2s_pending,
        offers=tuple(bb.public.offers.values()),
        public_facts=tuple(bb.public.facts.values()),
        case_facts=tuple(bb.private.case_facts.values()),
        mandate=bb.private.mandate,
        pending_approval=bb.private.pending_approval,
        approvals=tuple(bb.private.approvals.values()),
        status=bb.public.status,
        epoch=bb.epoch,
        fences=bb.fences,
        cp_hold=bb.public.cp_hold,
        cp_strikes=bb.channels.get("cp", ChannelState()).strikes,
        transcripts=transcripts,
    )
