"""The rules (ARCHITECTURE §9.3): pure checks over the blackboard that return
the Guard events to emit, or a ``Denial``. Restrictions (decline, revoke) are
always allowed; grants come only from a UI or sim-approver decision joined to
its card or proposal, bound to terms and epoch. No rule reads a model's text.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from proxyloop.contract.events import ApprovalPost, Approver
from proxyloop.contract.state import (
    Approval,
    ApprovalCard,
    Blackboard,
    Mandate,
    OfferPublic,
    ReadbackBinding,
)
from proxyloop.guard.capability import CAP_TTL_MS, business_action_id, mint
from proxyloop.guard.mandate import hard_violations, mandate_gap
from proxyloop.guard.readback import readback_status, readback_text
from proxyloop.guard.terms import Terms, offer_terms, terms_hash

CARD_TTL_MS = 120_000  # a card for an offer without a known expiry
Effect = tuple[str, dict[str, object]]  # (event type, payload), emitted by guard


@dataclass(frozen=True, slots=True)
class Denial:
    reason: str


@dataclass(frozen=True, slots=True)
class CaseRef:
    """Task data a rule binds to: the case and the read-back binding refs."""

    case_id: str
    account_ref: str
    principal_ref: str


_OFFER = (
    "fence_raised",
    "no_such_offer",
    "offer_not_open",
    "offer_expired",
    "readback_not_confirmed",
    "policy_violation",
)
REASONS: Mapping[str, tuple[str, ...]] = {
    "request_approval": (*_OFFER, "approval_pending"),
    "accept_offer": (
        *_OFFER,
        "approval_denied",
        "approval_stale_epoch",
        "mandate_stale_epoch",
        "mandate_expired",
        "approval_expired",
        "outside_mandate",
        "not_authorized",
        "already_authorized",
    ),
    "decline_offer": ("no_such_offer", "offer_not_open"),
    "share_fact": ("protected", "not_shareable"),
    "decide_approval": (
        "already_decided",
        "no_pending_card",
        "subject_hash_mismatch",
        "stale_epoch",
        "card_expired",
        "card_superseded",
    ),
    "decide_mandate": (
        "already_decided",
        "no_proposal",
        "subject_hash_mismatch",
        "stale_epoch",
    ),
}


def _open_offer(bb: Blackboard, ref: str) -> tuple[OfferPublic, Terms] | Denial:
    """An open, unexpired, confirmed offer without hard violations."""
    if bb.fences:
        return Denial("fence_raised")
    offer = bb.public.offers.get(ref)
    if offer is None:
        return Denial("no_such_offer")
    if offer.status != "open":
        return Denial("offer_not_open")
    if offer.expires_ms is not None and offer.expires_ms <= bb.t_ms:
        return Denial("offer_expired")
    terms = offer_terms(offer)
    bound = terms is not None and offer.terms_hash == terms_hash(terms)
    if terms is None or not bound or readback_status(offer) != "confirmed":
        return Denial("readback_not_confirmed")
    if hard_violations(terms, bb.private.mandate):
        return Denial("policy_violation")
    return offer, terms


def request_approval(
    bb: Blackboard, ref: str, case: CaseRef
) -> tuple[Effect, ...] | Denial:
    """``approval.requested``: a card bound to the terms and the epoch. The
    offer may be outside the mandate: that is what the user decides."""
    got = _open_offer(bb, ref)
    if isinstance(got, Denial):
        return got
    offer, epoch = got[0], bb.epoch
    card = current_card(bb)  # a superseded, stale or expired card does not block
    if card is not None and card.authority_epoch == epoch and card.expires_ms > bb.t_ms:
        return Denial("approval_pending")
    stem = f"apr-{offer.offer_ref}-r{offer.revision}-e{epoch}-"
    n = sum(a.startswith(stem) for a in bb.private.approvals)
    binding = ReadbackBinding(
        offer_ref=offer.offer_ref,
        revision=offer.revision,
        account_ref=case.account_ref,
        principal_ref=case.principal_ref,
        purpose="accept_offer",
        authority_epoch=epoch,
    )
    new = ApprovalCard(
        approval_id=f"{stem}{n}",
        offer_ref=offer.offer_ref,
        revision=offer.revision,
        terms_hash=str(offer.terms_hash),
        readback_text=readback_text(offer),
        authority_epoch=epoch,
        expires_ms=min(
            t for t in (offer.expires_ms, bb.t_ms + CARD_TTL_MS) if t is not None
        ),
        binding=binding,
    )
    return (("approval.requested", new.model_dump(mode="json")),)


def current_card(bb: Blackboard) -> ApprovalCard | None:
    """The pending card, unless a newer revision or terms superseded its offer."""
    card = bb.private.pending_approval
    offer = None if card is None else bb.public.offers.get(card.offer_ref)
    if card is None or offer is None:
        return None
    same = (offer.revision, offer.terms_hash) == (card.revision, card.terms_hash)
    return card if same else None


def _grant(
    bb: Blackboard, offer: OfferPublic, terms: Terms
) -> tuple[Mandate | Approval | None, str]:
    """The covering mandate or a live approval, else why neither. A user's
    denial of these terms in this epoch wins over both, whatever its expiry
    (I6, M3). Expiry filters grants only: the first granted approval with
    ``expires_ms > now``; ``None`` is never live (ADR-0007, fail closed)."""
    approvals = bb.private.approvals.values()
    mine = [a for a in approvals if a.terms_hash == offer.terms_hash]
    now = [a for a in mine if a.authority_epoch == bb.epoch]
    if any(a.decision == "denied" for a in now):
        return None, "approval_denied"
    m, why = bb.private.mandate, mandate_gap(bb, terms)
    if m is not None and why is None:
        return m, ""
    live = [a for a in now if a.expires_ms is not None and a.expires_ms > bb.t_ms]
    if live:  # all granted
        return live[0], ""
    if now:
        return None, "approval_expired"
    return None, "approval_stale_epoch" if mine else why or "not_authorized"


def accept_offer(
    bb: Blackboard, ref: str, case: CaseRef
) -> tuple[Effect, ...] | Denial:
    """``action.authorized`` plus the Guard-written accept line holding the
    capability; the Speaker revalidates it at release."""
    got = _open_offer(bb, ref)
    if isinstance(got, Denial):
        return got
    offer, terms = got
    grant, why = _grant(bb, offer, terms)
    if grant is None:
        return Denial(why)
    th = str(offer.terms_hash)
    by = grant.mandate_hash if isinstance(grant, Mandate) else grant.approval_id
    bid = business_action_id(case.case_id, "accept_offer", ref, offer.revision, th, by)
    if any(c.business_action_id == bid for c in bb.capabilities.values()):
        return Denial("already_authorized")
    # min(grant expiry, offer expiry, TTL); a live approval's is never None
    until = [grant.expires_ms, offer.expires_ms, bb.t_ms + CAP_TTL_MS]
    cap = mint(bb, bid, "accept_offer", th, min(t for t in until if t is not None))
    text = f"Yes, we accept these terms: {readback_text(offer)}."
    line: dict[str, object] = {"lane": "cp", "kind": "accept", "text": text}
    auth: dict[str, object] = {"intent": "accept_offer"}
    auth["capability"] = cap.model_dump(mode="json")
    return ("action.authorized", auth), (
        "speak.verbatim",
        line | {"cap_id": cap.cap_id},
    )


def decline_offer(bb: Blackboard, ref: str) -> tuple[Effect, ...] | Denial:
    """A restriction: allowed under a fence and at any epoch."""
    offer = bb.public.offers.get(ref)
    if offer is None:
        return Denial("no_such_offer")
    if offer.status != "open":
        return Denial("offer_not_open")
    text = "No, thank you: we will not take that offer."
    line: dict[str, object] = {"lane": "cp", "kind": "decline", "text": text}
    line["offer_ref"] = ref
    return (("speak.verbatim", line),)


def share_fact(bb: Blackboard, key: str, shareable: frozenset[str]) -> Denial | None:
    fact = bb.private.case_facts.get(key)
    if fact is not None and fact.protected:
        return Denial("protected")
    return None if key in shareable else Denial("not_shareable")


def decide(bb: Blackboard, post: ApprovalPost, by: Approver) -> Effect | Denial:
    """Join an ``approval.post`` to its pending card or proposed mandate: the
    decision it may become, or why it is refused (a 409 at the endpoint)."""
    if post.subject == "mandate":
        m = bb.private.mandate
        if m is not None and m.mandate_id == post.subject_id and m.status != "proposed":
            return Denial("already_decided")
        if m is None or m.mandate_id != post.subject_id or m.status != "proposed":
            return Denial("no_proposal")
        if post.subject_hash != m.mandate_hash:
            return Denial("subject_hash_mismatch")
        if not post.authority_epoch == m.epoch == bb.epoch:
            return Denial("stale_epoch")
        decided: dict[str, object] = {"mandate_id": m.mandate_id, "by": by}
        decided |= {"mandate_hash": m.mandate_hash, "decision": post.decision}
        return "mandate.decided", decided
    if post.subject_id in bb.private.approvals:
        return Denial("already_decided")
    card = bb.private.pending_approval
    if card is None or card.approval_id != post.subject_id:
        return Denial("no_pending_card")
    if current_card(bb) is None:
        return Denial("card_superseded")
    if post.subject_hash != card.terms_hash:
        return Denial("subject_hash_mismatch")
    if not post.authority_epoch == card.authority_epoch == bb.epoch:
        return Denial("stale_epoch")
    if card.expires_ms <= bb.t_ms:
        return Denial("card_expired")
    decided = {"approval_id": card.approval_id, "decision": post.decision, "by": by}
    return "approval.decided", dict[str, object](decided)
