"""Evidence-bound verifiers (ARCHITECTURE §9.3): only their ``completion.decided``
leads to a ``VERIFIED_*`` status. Both read agent-observable state only: the
world (hidden ladder, ledger internals) is never consulted, and import-linter
keeps ``proxyloop.env`` out of Guard."""

from __future__ import annotations

from proxyloop.contract.state import Blackboard, Capability, CompletionDecision
from proxyloop.guard.mandate import hard_violations
from proxyloop.guard.readback import has_cue
from proxyloop.guard.terms import offer_terms


def _decision(reasons: list[str]) -> CompletionDecision:
    return CompletionDecision(
        verdict="fail" if reasons else "ok", reasons=tuple(reasons)
    )


def _released(bb: Blackboard) -> list[Capability]:
    caps = bb.capabilities.values()
    return [c for c in caps if c.intent == "accept_offer" and c.consumed]


def verify_completion(bb: Blackboard) -> CompletionDecision:
    """Exactly one released accept, evidence bound to its terms (portal evidence
    also to its business action), and no hard violation in those terms."""
    released = _released(bb)
    if len(released) != 1:
        many = "multiple_released_accepts" if released else "no_released_accept"
        return _decision([many])
    cap, reasons = released[0], list[str]()
    if not any(
        e.terms_hash == cap.terms_hash
        and (e.kind == "ledger" or e.business_action_id == cap.business_action_id)
        for e in bb.evidence
    ):
        reasons.append("no_bound_evidence")
    offers = bb.public.offers.values()
    offer = next((o for o in offers if o.terms_hash == cap.terms_hash), None)
    terms = None if offer is None else offer_terms(offer)
    if terms is None:
        reasons.append("accepted_terms_unknown")
    elif hard_violations(terms, bb.private.mandate):
        reasons.append("policy_violation")
    return _decision(reasons)


def verify_no_deal(bb: Blackboard, asked_final_at: int | None) -> CompletionDecision:
    """(a) every offer declined, denied at approval, or hard-violating; (b) the
    rep's last line since the last ``guide(ask_final_offer)`` matches the
    closing lexicon (``asked_final_at``: the first cp line after the last ask
    the rep heard, ``slow/tools.py`` ``asked_final``), so a concession or
    retraction after a closing line reopens it;
    (c) no accept released. The world's "was a deal reachable" is never read."""
    reasons: list[str] = []
    denied = {
        a.terms_hash for a in bb.private.approvals.values() if a.decision == "denied"
    }
    for ref, offer in sorted(bb.public.offers.items()):
        terms = offer_terms(offer)
        if offer.status == "declined" or (offer.terms_hash in denied):
            continue
        if terms is None or not hard_violations(terms, bb.private.mandate):
            reasons.append(f"offer_open:{ref}")
    lines = bb.channels["cp"].lines
    if asked_final_at is None:
        reasons.append("final_offer_not_asked")
    else:
        said = [x.text for x in lines[asked_final_at:] if x.speaker == "partner"]
        if not (said and has_cue(said[-1], "closing")):
            reasons.append("no_closing_reply")
    if _released(bb):
        reasons.append("accept_released")
    return _decision(reasons)
