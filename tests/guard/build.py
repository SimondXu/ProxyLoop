"""Blackboard builders for the Guard tests (plain state, not fakes)."""

from __future__ import annotations

from proxyloop.contract.state import (
    Approval,
    ApprovalCard,
    Blackboard,
    Capability,
    ChannelState,
    Fact,
    Fence,
    Line,
    Mandate,
    OfferPublic,
    PrivateState,
    PublicState,
    ReadbackBinding,
    ReadbackSlot,
)
from proxyloop.guard.authorize import CaseRef
from proxyloop.guard.terms import offer_terms_hash

CASE = CaseRef(case_id="case-1", account_ref="acct-4821", principal_ref="dana")
# The rep reads offer o1 back: $68 a month, 24 months, a $20 activation fee.
READBACK = (
    "It is $68 a month on a 24-month term, with a $20 activation fee, "
    "no other changes, and the offer does not expire."
)


def slot(field: str, value: str, unit: str, role: str, **kw: object) -> ReadbackSlot:
    return ReadbackSlot.model_validate(
        {"field": field, "value": value, "unit": unit, "role": role} | kw
    )


def offer(
    ref: str = "o1",
    *,
    monthly: str = "6800",
    term: str = "24",
    fee: str | None = "2000",
    change: str | None = None,
    expires: str = "none",
    **kw: object,
) -> OfferPublic:
    """An offer whose slots are all ``unknown`` and whose terms are unbound."""
    slots = [
        slot("monthly_price", monthly, "usd_minor", "recurring"),
        slot("term_months", term, "months", "recurring"),
        slot("fee:activation", fee, "usd_minor", "one_time")
        if fee is not None
        else slot("fees_none", "true", "bool", "one_time"),
        slot(f"applied_change:{change}", "true", "bool", "change")
        if change is not None
        else slot("changes_none", "true", "bool", "change"),
        slot("expires", expires, "iso", "expiry"),
    ]
    return OfferPublic.model_validate(
        {"offer_ref": ref, "revision": 1, "slots": slots} | kw
    )


def confirm(o: OfferPublic) -> OfferPublic:
    """``o`` with every slot confirmed and its terms bound, as Guard folds it."""
    slots = tuple(s.model_copy(update={"status": "confirmed"}) for s in o.slots)
    done = o.model_copy(update={"slots": slots})
    return done.model_copy(update={"terms_hash": offer_terms_hash(done)})


def rep(utt_id: str, text: str) -> Line:
    return Line(utt_id=utt_id, speaker="partner", text=text)


def agent(utt_id: str, text: str) -> Line:
    return Line(utt_id=utt_id, speaker="agent", text=text)


def mandate(status: str = "granted", **kw: object) -> Mandate:
    base: dict[str, object] = {
        "mandate_id": "m1",
        "mandate_hash": "mh1",
        "status": status,
        "epoch": 0,
        "max_monthly_price_minor": 7000,
        "max_term_months": 24,
        "max_one_time_fees_minor": 2500,
    }
    if status in ("granted", "denied"):
        base["decided_by"] = "ui"
    return Mandate.model_validate(base | kw)


def approval(
    o: OfferPublic,
    decision: str = "granted",
    epoch: int = 0,
    expires_ms: int | None = 60_000,  # the card's; None: a pre-ADR-0007 record
    approval_id: str = "apr-1",
) -> Approval:
    assert o.terms_hash is not None
    return Approval.model_validate(
        {
            "approval_id": approval_id,
            "decision": decision,
            "by": "ui",
            "terms_hash": o.terms_hash,
            "authority_epoch": epoch,
            "expires_ms": expires_ms,
        }
    )


def card(o: OfferPublic, epoch: int = 0, expires_ms: int = 60_000) -> ApprovalCard:
    assert o.terms_hash is not None
    binding = ReadbackBinding(
        offer_ref=o.offer_ref,
        revision=o.revision,
        account_ref=CASE.account_ref,
        principal_ref=CASE.principal_ref,
        purpose="accept_offer",
        authority_epoch=epoch,
    )
    return ApprovalCard(
        approval_id="apr-1",
        offer_ref=o.offer_ref,
        revision=o.revision,
        terms_hash=o.terms_hash,
        readback_text="the terms",
        authority_epoch=epoch,
        expires_ms=expires_ms,
        binding=binding,
    )


def board(
    *offers: OfferPublic,
    mandate: Mandate | None = None,
    approvals: tuple[Approval, ...] = (),
    pending: ApprovalCard | None = None,
    fences: tuple[Fence, ...] = (),
    epoch: int = 0,
    t_ms: int = 1_000,
    seq: int = 10,
    caps: tuple[Capability, ...] = (),
    facts: tuple[Fact, ...] = (),
    cp: tuple[Line, ...] = (),
) -> Blackboard:
    return Blackboard(
        seq=seq,
        t_ms=t_ms,
        epoch=epoch,
        fences=fences,
        public=PublicState(offers={o.offer_ref: o for o in offers}),
        private=PrivateState(
            mandate=mandate,
            pending_approval=pending,
            approvals={a.approval_id: a for a in approvals},
            case_facts={f.key: f for f in facts},
        ),
        channels={"user": ChannelState(), "cp": ChannelState(lines=cp)},
        capabilities={c.cap_id: c for c in caps},
    )


FENCE = Fence(fence_id="f1", utt_id="u1", raised_seq=3)
