"""Blackboard: public and private state (ARCHITECTURE §5, §9.2-§9.5).

``PublicState`` is everything ``FastView[cp]`` may see. ``PrivateState`` is
principal-facing and never reaches the cp lane. Guard logic lives in SYS.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from proxyloop.contract import base
from proxyloop.contract.base import FACT_KEY, Frozen, HoldReason, Lane
from proxyloop.contract.messages import OFFER_REF, FastToSlow, Guide, SlowToFast


class CaseStatus(StrEnum):
    INTAKE = "INTAKE"
    MANDATED = "MANDATED"
    IN_CALL = "IN_CALL"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMMIT_AUTHORIZED = "COMMIT_AUTHORIZED"
    COMMITTED = "COMMITTED"
    EVIDENCE_PENDING = "EVIDENCE_PENDING"
    NEEDS_REPLAN = "NEEDS_REPLAN"
    VERIFIED_COMPLETE = "VERIFIED_COMPLETE"
    VERIFIED_NO_DEAL = "VERIFIED_NO_DEAL"
    ESCALATED = "ESCALATED"
    ABANDONED = "ABANDONED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"


READBACK_FIELD = (
    r"^(?:monthly_price|term_months|fees_none|changes_none|expires"
    r"|(?:fee|credit|applied_change|feature):[A-Za-z0-9_.:-]+)$"
)


class ReadbackSlot(Frozen):
    """One read-back slot of an offer (§9.2). ``value`` is normalised text."""

    field: str = Field(pattern=READBACK_FIELD, max_length=40)
    value: str = Field(max_length=base.MAX_SLOT_VALUE)
    unit: Literal["usd_minor", "months", "bool", "iso"]
    role: Literal["recurring", "one_time", "credit", "change", "feature", "expiry"]
    source_utt: str | None = None
    span: tuple[int, int] | None = None
    status: Literal["unknown", "heard", "confirmed"] = "unknown"


class ReadbackBinding(Frozen):
    offer_ref: str
    revision: int
    account_ref: str
    principal_ref: str
    purpose: str
    authority_epoch: int


class OfferPublic(Frozen):
    offer_ref: str = Field(pattern=rf"^{OFFER_REF}$")
    revision: int = Field(ge=1)
    slots: tuple[ReadbackSlot, ...] = Field(default=(), max_length=base.MAX_SLOTS)
    status: Literal["open", "withdrawn", "expired", "declined", "accepted"] = "open"
    expires_ms: int | None = None
    terms_hash: str | None = None


class PublicFact(Frozen):
    """A source-bound public fact: said by the rep, or allow-listed shareable."""

    key: str = Field(pattern=rf"^{FACT_KEY}$")
    value: str = Field(max_length=base.MAX_FACT_VALUE)
    source: Literal["cp_utt", "shareable"]
    source_ref: str


class Fact(Frozen):
    """A user-provided case fact; ``protected`` marks PINs, account numbers."""

    key: str = Field(pattern=rf"^{FACT_KEY}$")
    value: str
    protected: bool = False
    source_ref: str | None = None


class Mandate(Frozen):
    """The principal's envelope. Its bounds live in private state only."""

    mandate_id: str
    mandate_hash: str
    status: Literal["proposed", "granted", "denied", "revoked"]
    epoch: int
    max_monthly_price_minor: int | None = None
    max_term_months: int | None = None
    max_one_time_fees_minor: int | None = None
    required_features: tuple[str, ...] = ()
    forbidden_changes: tuple[str, ...] = ()
    expires_ms: int | None = None
    decided_by: Literal["ui", "sim_approver"] | None = None

    @model_validator(mode="after")
    def _decided(self) -> Self:
        if self.status in ("granted", "denied") and self.decided_by is None:
            raise ValueError(f"a {self.status} mandate needs decided_by")
        return self


class ApprovalCard(Frozen):
    """``approval.requested`` (§9.3). ``readback_text`` is Guard-written."""

    approval_id: str
    offer_ref: str
    revision: int
    terms_hash: str
    readback_text: str = Field(max_length=base.MAX_READBACK_TEXT)
    authority_epoch: int
    expires_ms: int
    binding: ReadbackBinding

    @model_validator(mode="after")
    def _bound(self) -> Self:
        b = self.binding
        if (b.offer_ref, b.revision, b.authority_epoch) != (
            self.offer_ref,
            self.revision,
            self.authority_epoch,
        ):
            raise ValueError("the binding must name this card's offer and epoch")
        return self


class Approval(Frozen):
    approval_id: str
    decision: Literal["granted", "denied"]
    by: Literal["ui", "sim_approver"]
    terms_hash: str
    authority_epoch: int


Intent = Literal["accept_offer", "submit_transaction"]


class Capability(Frozen):
    """A one-use release token (§9.4)."""

    cap_id: str
    business_action_id: str
    intent: Intent
    terms_hash: str
    epoch: int
    expires_ms: int
    consumed: bool = False


class Authorization(Frozen):
    intent: Intent
    offer_ref: str | None
    terms_hash: str | None
    cap_id: str
    epoch: int


class Fence(Frozen):
    """A raised ingress fence (§9.4); cleared fences leave the blackboard."""

    fence_id: str
    utt_id: str
    raised_seq: int


class HoldState(Frozen):
    reason: HoldReason
    since_ms: int


class Line(Frozen):
    utt_id: str
    speaker: Literal["partner", "agent"]
    text: str


class ChannelState(Frozen):
    lines: tuple[Line, ...] = ()
    open: bool = False
    floor: Literal["free", "agent", "partner"] = "free"
    strikes: int = 0


class Evidence(Frozen):
    evidence_id: str
    kind: Literal["ledger", "portal"]
    confirmation_id: str
    terms_hash: str | None = None
    business_action_id: str | None = None


class CompletionDecision(Frozen):
    verdict: Literal["ok", "fail"]
    reasons: tuple[str, ...] = ()


class Spend(Frozen):
    micro_usd: int = 0
    by_role: dict[str, int] = Field(default_factory=dict[str, int])


class PublicState(Frozen):
    summary: str = Field(default="", max_length=base.MAX_PUBLIC_TEXT)  # declassified
    facts: dict[str, PublicFact] = Field(default_factory=dict[str, PublicFact])
    offers: dict[str, OfferPublic] = Field(
        default_factory=dict[str, OfferPublic], max_length=base.MAX_OFFERS
    )
    guidance_cp: tuple[Guide, ...] = Field(default=(), max_length=3)
    action_log: tuple[str, ...] = Field(default=(), max_length=12)  # value-free
    status: CaseStatus = CaseStatus.INTAKE
    cp_hold: HoldState | None = None


class PrivateState(Frozen):
    summary: str = Field(default="", max_length=base.MAX_PRIVATE_SUMMARY)
    case_facts: dict[str, Fact] = Field(default_factory=dict[str, Fact])
    mandate: Mandate | None = None
    pending_approval: ApprovalCard | None = None
    approvals: dict[str, Approval] = Field(default_factory=dict[str, Approval])


def _channels() -> dict[Lane, ChannelState]:
    return {"user": ChannelState(), "cp": ChannelState()}


class Blackboard(Frozen):
    """The pure fold of the event log (I2)."""

    seq: int = 0
    t_ms: int = 0
    epoch: int = 0
    fences: tuple[Fence, ...] = ()
    public: PublicState = PublicState()
    private: PrivateState = PrivateState()
    channels: dict[Lane, ChannelState] = Field(default_factory=_channels)
    f2s_pending: tuple[FastToSlow, ...] = ()
    s2f_pending: dict[Lane, tuple[SlowToFast, ...]] = Field(
        default_factory=dict[Lane, tuple[SlowToFast, ...]]
    )
    authorizations: tuple[Authorization, ...] = ()
    capabilities: dict[str, Capability] = Field(default_factory=dict[str, Capability])
    evidence: tuple[Evidence, ...] = ()
    completion: CompletionDecision | None = None
    spend: Spend = Spend()
