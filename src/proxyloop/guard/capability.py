"""Capabilities (ARCHITECTURE §9.4): one-use release tokens, and their
revalidation at release time. On the cp lane a capability is a release token
for our own Speaker ("guarded release"), not complete mediation."""

from __future__ import annotations

from proxyloop.contract.base import canonical_json, sha256_text
from proxyloop.contract.state import Blackboard, Capability, Intent

CAP_TTL_MS = 60_000  # an offer without a known expiry: the line must go out soon


def business_action_id(
    case_id: str,
    intent: str,
    offer_id: str,
    offer_revision: int,
    terms_hash: str,
    grant: str,  # the approval_id, or the mandate_hash
) -> str:
    """Stable across runs and restarts: no run id, seq or time goes in (C5)."""
    parts = [case_id, intent, offer_id, offer_revision, terms_hash, grant]
    return sha256_text(canonical_json(parts))


def mint(
    bb: Blackboard, bid: str, intent: Intent, terms_hash: str, expires_ms: int
) -> Capability:
    return Capability(
        cap_id=f"cap-{len(bb.authorizations) + 1}",
        business_action_id=bid,
        intent=intent,
        terms_hash=terms_hash,
        epoch=bb.epoch,
        expires_ms=expires_ms,
    )


def released_accept(bb: Blackboard, terms_hash: str | None = None) -> bool:
    """An accept of these terms (one offer revision), or with ``None`` of any
    terms, was released: at most one ever is per revision (I6); a retry needs a
    new revision, so new terms, and a new approval."""
    return any(
        c.intent == "accept_offer" and c.consumed and terms_hash in (None, c.terms_hash)
        for c in bb.capabilities.values()
    )


def accept_in_flight(bb: Blackboard) -> bool:
    """An accept capability neither released nor revoked (revoked ones leave the
    blackboard): one accept in flight per case."""
    return any(
        c.intent == "accept_offer" and not c.consumed for c in bb.capabilities.values()
    )


def revalidate(bb: Blackboard, cap_id: str, t_release_end: int) -> str | None:
    """Why the line holding ``cap_id`` may not be released now (``None``: it
    may): the ``speak.revoked`` reason."""
    cap = bb.capabilities.get(cap_id)
    if cap is None:
        return "unknown_capability"
    if cap.consumed:
        return "consumed"
    if cap.epoch != bb.epoch:
        return "epoch"
    if bb.fences:
        return "fence"
    auth = next((a for a in bb.authorizations if a.cap_id == cap_id), None)
    offer = bb.public.offers.get(auth.offer_ref or "") if auth else None
    if offer is None or offer.status != "open":
        return "offer_closed"
    if offer.terms_hash != cap.terms_hash:
        return "terms_changed"
    ends = (cap.expires_ms, offer.expires_ms)
    return "expired" if min(t for t in ends if t is not None) <= t_release_end else None
