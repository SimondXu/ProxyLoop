"""The offers line's per-offer hints (S1-SYS-28, S1-SYS-46, S1-SYS-66):
Guard's verdicts on an open offer (``open_offer``, ``card_blocks``,
``hard_violations``, ``mandate_gap``) and the one next step they imply, read
from the status bar's view and ``state.Bar``. Read-only: nothing is sent."""

from __future__ import annotations

from proxyloop.contract.state import (
    Blackboard,
    OfferPublic,
    PrivateState,
    ReadbackSlot,
)
from proxyloop.contract.views import SlowView
from proxyloop.guard.authorize import Denial, card_blocks, open_offer
from proxyloop.guard.mandate import hard_violations, mandate_gap
from proxyloop.guard.policy import UNSUPPORTED_APPLIED_CHANGE
from proxyloop.guard.readback import ROLE_OF, readback_status
from proxyloop.guard.terms import Terms, offer_terms
from proxyloop.slow import state
from proxyloop.slow.authority import UNITS

HARD_LIMITS = {  # guard.mandate.hard_violations's classes: no approval lifts them
    "required_feature_missing": "a feature the user requires is missing",
    "forbidden_change_present": "a change the user forbade is applied",
    UNSUPPORTED_APPLIED_CHANGE: "a change this build cannot support is applied",
}
HARD_LIMIT = "breaks a hard limit"
OUTSIDE_MANDATE = "outside mandate: needs the user's approval once confirmed"


def approval_hint(
    view: SlowView, o: OfferPublic, now_ms: int, more: state.Bar | None = None
) -> str:
    """S1-SYS-28 (run ed5063): an offer Guard would put on a card (its
    ``open_offer`` and ``card_blocks`` rules) that its mandate check finds
    outside the granted mandate needs the user's approval; shown until a card
    or a decision for its terms exists in this epoch. Nothing is sent.
    S1-SYS-66: with the bar (``more``), a lever on its way means wait, and an
    available lever comes first; request_approval once none is left."""
    got = open_offer(o, view.mandate, now_ms, bool(view.fences))
    card = view.pending_approval
    of_card = [x for x in view.offers if card and x.offer_ref == card.offer_ref]
    blocked = card_blocks(card, of_card[0] if of_card else None, view.epoch, now_ms)
    if isinstance(got, Denial) or blocked:  # Guard would refuse the card
        return ""
    terms = got[1]
    cards = [] if view.pending_approval is None else [view.pending_approval]
    for a in (*cards, *view.approvals):
        if (a.terms_hash, a.authority_epoch) == (o.terms_hash, view.epoch):
            return ""
    mine = PrivateState(mandate=view.mandate)
    bb = Blackboard(t_ms=now_ms, epoch=view.epoch, private=mine)
    if mandate_gap(bb, terms) != "outside_mandate":
        return ""
    ref = f"{o.offer_ref} confirmed, outside mandate → "
    if more is not None and more.waiting:  # S1-SYS-66: one lever per rep reply
        return f"{ref}{WAIT_LEVER}"
    if levers := _free(more):
        return f"{ref}{FIRST_LEVER}{levers}; request_approval only once none is left"
    return f"{ref}request_approval({o.offer_ref})"


WAIT_LEVER = "wait for the rep to hear and answer the lever sent (levers line)"
FIRST_LEVER = "first one lever: "  # a hint's lever step (S1-SYS-66)


def _free(more: state.Bar | None) -> str:
    """The available levers as ``guide_fast`` calls, each with the public
    fact slot it needs (N2); empty without the bar or when none is left."""
    if more is None:
        return ""
    slot = {m: f', ["{s}"]' for m, s in more.slots.items()}
    return " or ".join(f"guide_fast({m}{slot.get(m, '')})" for m in more.free)


def mandate_hint(
    view: SlowView, o: OfferPublic, now_ms: int, more: state.Bar | None = None
) -> str:
    """S1-SYS-46 (run cc160a): Guard's verdicts on an open offer's terms.
    Its ``hard_violations`` classes break a hard limit whatever else holds
    (fenced, expired, confirmed or not); for a revision still incomplete, a
    required feature not yet stated is not yet missing. Otherwise, only
    when ``open_offer`` refuses it as not yet confirmed and ``mandate_gap``
    finds it outside the granted mandate, it needs the user's approval once
    confirmed (a confirmed one is ``approval_hint``'s). Read-only.
    S1-SYS-66 (root review, 2026-09-28): with the bar (``more``), an offer
    outside the mandate gets one available lever before its read-back (wait
    while one is on its way or unanswered); only once none is left, its
    read-back, then request_approval; a stuck read-back defers to the
    note's stuck clause (one next step per state)."""
    if o.status != "open":
        return ""
    m = view.mandate
    complete = offer_terms(o)
    terms = complete or _as_recorded(o)
    if terms is None:
        return ""
    if complete is None and m is not None:  # a read-back may still add it
        have = {s.field for s in o.slots}
        stated = tuple(f for f in m.required_features if f"feature:{f}" in have)
        m = m.model_copy(update={"required_features": stated})
    if hard := hard_violations(terms, m):
        return f"{HARD_LIMIT}: {', '.join(hard)}"
    got = open_offer(o, view.mandate, now_ms, bool(view.fences))
    waiting = isinstance(got, Denial) and got.reason == "readback_not_confirmed"
    if not waiting or readback_status(o) == "confirmed":
        return ""  # allowed (approval_hint's), or refused for good
    mine = PrivateState(mandate=view.mandate)
    bb = Blackboard(t_ms=now_ms, epoch=view.epoch, private=mine)
    if mandate_gap(bb, terms) != "outside_mandate":
        return ""
    if more is None:
        return OUTSIDE_MANDATE
    if more.waiting:
        return f"{OUTSIDE_MANDATE} → {WAIT_LEVER}; ask_readback not yet"
    if levers := _free(more):
        return (
            f"{OUTSIDE_MANDATE} → {FIRST_LEVER}{levers}; "
            "ask_readback only once none is left"
        )
    if more.stuck(o):  # the note's stuck clause is the one next step
        return f"{OUTSIDE_MANDATE} → read-back stuck (see note)"
    ref = o.offer_ref
    r = more.readbacks.get((ref, o.revision))
    then = f"request_approval({ref})"
    if r is not None and r.asked:  # one pending: not asked again
        return f"{OUTSIDE_MANDATE} → read-back asked: {then} once confirmed"
    ask = f'guide_fast(ask_readback, ["offer:{ref}"])'
    return f"{OUTSIDE_MANDATE} → {ask}, then {then}"


def _as_recorded(o: OfferPublic) -> Terms | None:
    """``offer_terms`` of the slots recorded so far, each unstated one
    neutral: price and term 0 (above no bound), no fee, no change, no
    expiry. Features are only those recorded."""
    have = {s.field: s.value for s in o.slots}
    listed = {f.partition(":")[0] for f in have if ":" in f}
    changed = {f.partition(":")[0] for f, v in have.items() if v == "true"}
    fill = {"monthly_price": "0", "term_months": "0", "expires": "none"}
    if "fee" not in listed:
        fill["fees_none"] = "true"
    if "applied_change" not in changed:
        fill["changes_none"] = "true"
    extra = [
        ReadbackSlot.model_validate(
            {"field": f, "value": v, "role": ROLE_OF[f], "unit": UNITS.get(f, "bool")}
        )
        for f, v in fill.items()
        if f not in have
    ]
    return offer_terms(o.model_copy(update={"slots": (*o.slots, *extra)}))
