"""Evidence-bound verifiers (ARCHITECTURE §9.3): only their ``completion.decided``
leads to a ``VERIFIED_*`` status. Both read agent-observable state only: the
world (hidden ladder, ledger internals) is never consulted, and import-linter
keeps ``proxyloop.env`` out of Guard."""

from __future__ import annotations

import re
from collections.abc import Set
from decimal import Decimal

from proxyloop.contract.state import (
    Blackboard,
    Capability,
    ChannelState,
    CompletionDecision,
)
from proxyloop.guard.declass import spoken
from proxyloop.guard.mandate import hard_violations
from proxyloop.guard.readback import has_cue
from proxyloop.guard.terms import offer_terms

_PER_MONTH = re.compile(  # a bare amount said per month: "70 a month"
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:a|per|each|every|/)\s*mo(?:nth)?\b", re.I
)


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


def carried(bb: Blackboard) -> set[Decimal]:
    """The money amounts (dollars) of every recorded offer's slots."""
    offers = bb.public.offers.values()
    return {
        Decimal(s.value) / 100 for o in offers for s in o.slots if s.unit == "usd_minor"
    }


def reopens(text: str, amounts: Set[Decimal]) -> bool:
    """A rep line after the closing reply reopens it (S1-SYS-113, ADR-0033)
    iff it states a money amount that no recorded offer carries (``amounts``;
    $0 is none), or has a ``reopen`` cue: it makes or names an offer, or takes
    the close back. Filler ("How can I help with the account today?") does
    not; nor does a line that withdraws an offer."""
    said = spoken(text, "usd_minor") | {
        Decimal(m.group(1)) for m in _PER_MONTH.finditer(text)
    }
    return bool(said - set(amounts) - {Decimal(0)}) or has_cue(text, "reopen")


def closing_at(bb: Blackboard, asked_final_at: int | None) -> int | None:
    """The cp index of the rep's closing reply, or ``None``: the last rep line
    since ``asked_final_at`` that matches the closing lexicon, if no later rep
    line ``reopens`` it (those later lines match no closing cue, else they
    would be the last). Slow's close line reads the same (``slow.state``)."""
    if asked_final_at is None:
        return None
    lines = bb.channels.get("cp", ChannelState()).lines
    rep = [
        n for n in range(asked_final_at, len(lines)) if lines[n].speaker == "partner"
    ]
    closing = [n for n in rep if has_cue(lines[n].text, "closing")]
    if not closing:
        return None
    have = carried(bb)
    later = [lines[n].text for n in rep if n > closing[-1]]
    return None if any(reopens(text, have) for text in later) else closing[-1]


def verify_no_deal(bb: Blackboard, asked_final_at: int | None) -> CompletionDecision:
    """(a) every offer declined, denied at approval, or hard-violating; (b) a
    rep line since the last ``guide(ask_final_offer)`` matches the closing
    lexicon and no later rep line reopens it (``closing_at``;
    ``asked_final_at``: the first cp line after the last ask the rep heard,
    ``slow/tools.py`` ``asked_final``), so a concession or retraction after a
    closing line reopens it and filler does not (S1-SYS-113);
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
    if asked_final_at is None:
        reasons.append("final_offer_not_asked")
    elif closing_at(bb, asked_final_at) is None:
        reasons.append("no_closing_reply")
    if _released(bb):
        reasons.append("accept_released")
    return _decision(reasons)
