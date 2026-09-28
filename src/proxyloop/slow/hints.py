"""The offers line's per-offer hints (S1-SYS-28, S1-SYS-46, S1-SYS-66,
S1-SYS-82): Guard's verdicts on an open offer (``open_offer``, ``card_blocks``,
``hard_violations``, ``mandate_gap``, ``accept_offer``) and the one next step
they imply, read from the status bar's view and ``state.Bar``. Read-only:
nothing is sent."""

from __future__ import annotations

from proxyloop.contract.state import (
    Blackboard,
    Mandate,
    OfferPublic,
    PrivateState,
    PublicState,
    ReadbackSlot,
)
from proxyloop.contract.views import SlowView
from proxyloop.guard.authorize import (
    CaseRef,
    Denial,
    accept_offer,
    card_blocks,
    open_offer,
)
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
DEFER = "outside mandate; no step for it now: "  # F-e: a better open offer's turn
INSIDE = "inside the granted mandate"  # why an offer comes first (F-e)
DENIED = (
    "no worse on price, term and fees, denied by the user: the after-denial "
    "rule applies"
)
DOMINATES = "no worse on price, term and fees as recorded, better on one"
_CASE = CaseRef("case", "account", "principal")  # a dry run binds nothing


def approval_hint(
    view: SlowView, o: OfferPublic, now_ms: int, more: state.Bar | None = None
) -> str:
    """S1-SYS-28 (run ed5063): an offer Guard would put on a card (its
    ``open_offer`` and ``card_blocks`` rules) that its mandate check finds
    outside the granted mandate needs the user's approval; shown until a card
    or a decision for its terms exists in this epoch. Nothing is sent.
    S1-SYS-66: with the bar (``more``), a lever on its way means wait, and an
    available lever comes first; request_approval once none is left.
    S1-SYS-82 F-d: once the user approved it (``approved``), accept_offer."""
    got = open_offer(o, view.mandate, now_ms, bool(view.fences))
    card = view.pending_approval
    of_card = [x for x in view.offers if card and x.offer_ref == card.offer_ref]
    blocked = card_blocks(card, of_card[0] if of_card else None, view.epoch, now_ms)
    if isinstance(got, Denial) or blocked:  # Guard would refuse the card
        return ""
    if approved(view, o, now_ms):
        return f"{o.offer_ref} confirmed, approved → accept_offer({o.offer_ref})"
    terms = got[1]
    cards = [] if view.pending_approval is None else [view.pending_approval]
    for a in (*cards, *view.approvals):
        if (a.terms_hash, a.authority_epoch) == (o.terms_hash, view.epoch):
            return ""
    if _gap(view, now_ms, terms) != "outside_mandate":
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
    if o.status != "open" or (got := _verdict(view, o)) is None:
        return ""
    terms, m = got
    if hard := hard_violations(terms, m):
        return f"{HARD_LIMIT}: {', '.join(hard)}"
    if _decided(view, o, "denied"):  # round 4: the after-denial rule's
        return ""
    got = open_offer(o, view.mandate, now_ms, bool(view.fences))
    waiting = isinstance(got, Denial) and got.reason == "readback_not_confirmed"
    if not waiting or readback_status(o) == "confirmed":
        return ""  # allowed (approval_hint's), or refused for good
    if _gap(view, now_ms, terms) != "outside_mandate":
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


def _verdict(view: SlowView, o: OfferPublic) -> tuple[Terms, Mandate | None] | None:
    """The terms Guard's verdicts judge (complete, else ``_as_recorded``) and
    the mandate to judge them by: for a revision still incomplete, a required
    feature not yet stated is not yet missing (a read-back may still add it)."""
    m, complete = view.mandate, offer_terms(o)
    terms = complete or _as_recorded(o)
    if terms is None:
        return None
    if complete is None and m is not None:
        have = {s.field for s in o.slots}
        stated = tuple(f for f in m.required_features if f"feature:{f}" in have)
        m = m.model_copy(update={"required_features": stated})
    return terms, m


def _gap(view: SlowView, now_ms: int, terms: Terms) -> str | None:
    """``mandate_gap`` of ``terms`` against the view's mandate, now."""
    mine = PrivateState(mandate=view.mandate)
    bb = Blackboard(t_ms=now_ms, epoch=view.epoch, private=mine)
    return mandate_gap(bb, terms)


def _board(view: SlowView, now_ms: int) -> Blackboard:
    """The view's board as Guard's accept rule reads it. The view holds no
    capabilities: an accept already authorised has moved the case out of
    IN_CALL, which the rule refuses first."""
    public = PublicState(
        status=view.status, offers={x.offer_ref: x for x in view.offers}
    )
    mine = PrivateState(
        mandate=view.mandate,
        pending_approval=view.pending_approval,
        approvals={a.approval_id: a for a in view.approvals},
    )
    return Blackboard(
        t_ms=now_ms, epoch=view.epoch, fences=view.fences, public=public, private=mine
    )


def _decided(view: SlowView, o: OfferPublic, decision: str) -> bool:
    """The user decided ``o``'s terms so in this epoch."""
    return any(
        a.decision == decision
        and (a.terms_hash, a.authority_epoch) == (o.terms_hash, view.epoch)
        for a in view.approvals
    )


def approved(view: SlowView, o: OfferPublic, now_ms: int) -> bool:
    """S1-SYS-82 F-d: the user granted ``o``'s terms in this epoch and Guard's
    ``accept_offer`` rule would pass now (a dry run on ``_board``)."""
    if not _decided(view, o, "granted"):
        return False
    return not isinstance(
        accept_offer(_board(view, now_ms), o.offer_ref, _CASE), Denial
    )


def _open(o: OfferPublic, now_ms: int) -> bool:
    return o.status == "open" and (o.expires_ms is None or o.expires_ms > now_ms)


def _costs(o: OfferPublic, terms: Terms) -> tuple[int, int, int] | None:
    """(monthly price, term, one-time fees) as recorded; None until the
    price and the term are recorded (an unstated fee counts as none)."""
    have = {s.field for s in o.slots}
    if not {"monthly_price", "term_months"} <= have:
        return None
    fees = sum(f.amount_minor for f in terms.fees)
    return terms.monthly_price_minor, terms.term_months, fees


def _dominates(b: tuple[int, int, int], o: tuple[int, int, int]) -> bool:
    return all(x <= y for x, y in zip(b, o, strict=True)) and b != o


def better(
    view: SlowView, o: OfferPublic, now_ms: int
) -> tuple[OfferPublic, str] | None:
    """S1-SYS-82 F-e: the open offer that beats ``o``, an open offer outside
    the granted mandate (breaking no hard limit, not approved), and why: the
    cheapest open offer inside it (its price recorded, no hard limit
    broken); else (L-CORE, rounds 2 and 4) the cheapest one no worse than
    ``o`` on price, term and fees as recorded and better on one (dominance,
    confirmed or not: a fee a read-back reveals can end it). An offer whose
    terms the user denied in this epoch beats nothing, but when it dominates
    ``o``, ``o`` gets no step either: the after-denial rule applies."""
    got = _verdict(view, o)
    if not _open(o, now_ms) or got is None or approved(view, o, now_ms):
        return None
    terms, m = got
    if hard_violations(terms, m) or _gap(view, now_ms, terms) != "outside_mandate":
        return None
    others = [b for b in view.offers if b.offer_ref != o.offer_ref and _open(b, now_ms)]
    rivals = [b for b in others if not _decided(view, b, "denied")]
    inside = [(p, b) for b in rivals if (p := _inside(view, b, now_ms)) is not None]
    if inside:
        return min(inside, key=lambda x: x[0])[1], INSIDE
    mine = _costs(o, terms)
    beats: list[tuple[tuple[int, int, int], OfferPublic]] = []
    for b in others:
        v = _verdict(view, b)
        if mine is None or v is None or hard_violations(*v):
            continue
        if (theirs := _costs(b, v[0])) is not None and _dominates(theirs, mine):
            beats.append((theirs, b))
    if not beats:
        return None
    b = min(beats, key=lambda x: x[0])[1]
    return b, DENIED if _decided(view, b, "denied") else DOMINATES


def needs_lever(view: SlowView, now_ms: int) -> bool:
    """S1-SYS-82 round 3: a lever can be the next step: an open offer the
    granted mandate does not cover (no mandate granted counts), breaking no
    hard limit, not approved, and with no better open offer before it."""
    for o in view.offers:
        got = _verdict(view, o)
        if not _open(o, now_ms) or got is None or hard_violations(*got):
            continue
        if _gap(view, now_ms, got[0]) is None or approved(view, o, now_ms):
            continue
        if better(view, o, now_ms) is None:
            return True
    return False


def _inside(view: SlowView, b: OfferPublic, now_ms: int) -> int | None:
    """``b``'s monthly price when it is inside the granted mandate as
    recorded (its price recorded, no hard limit broken), else None."""
    v = _verdict(view, b)
    priced = any(s.field == "monthly_price" for s in b.slots)
    if v is None or not priced or hard_violations(*v):
        return None
    return v[0].monthly_price_minor if _gap(view, now_ms, v[0]) is None else None


def inside_hint(view: SlowView, o: OfferPublic, now_ms: int, more: state.Bar) -> str:
    """S1-SYS-82 e1 (root, 2026-09-29): the cheapest open offer inside the
    granted mandate, not yet confirmed, names its own read-back step (the
    one ``defer_hint`` names for it)."""
    if not _open(o, now_ms) or readback_status(o) == "confirmed":
        return ""
    live = [
        b for b in view.offers if _open(b, now_ms) and not _decided(view, b, "denied")
    ]
    inside = [(p, b) for b in live if (p := _inside(view, b, now_ms)) is not None]
    if not inside or min(inside, key=lambda x: x[0])[1] is not o:
        return ""
    return f"{INSIDE} → {_inside_step(view, o, now_ms, more)}"


def _inside_step(view: SlowView, b: OfferPublic, now_ms: int, more: state.Bar) -> str:
    """An inside offer's step: its read-back, then accept_offer; or
    accept_offer once confirmed (Guard's accept rule passing; otherwise
    none: the case has moved on)."""
    ref = b.offer_ref
    then = f"accept_offer({ref})"
    r = more.readbacks.get((ref, b.revision))
    if readback_status(b) == "confirmed":
        dry = accept_offer(_board(view, now_ms), ref, _CASE)
        return "" if isinstance(dry, Denial) else then
    if r is not None and r.asked:
        return f"read-back asked: {then} once confirmed"
    return f'guide_fast(ask_readback, ["offer:{ref}"]), then {then}'


def defer_hint(
    view: SlowView, b: OfferPublic, why: str, now_ms: int, more: state.Bar
) -> str:
    """S1-SYS-82 F-e: a worse offer's one hint, naming the offer ``b`` that
    comes first, and for one inside the mandate its step (``_inside_step``);
    any other ``b`` names its own step on its entry."""
    ref = b.offer_ref
    if why == DENIED:  # round 4: no step comes first; the playbook's rule
        return f"{DEFER}{ref} {why}"
    if why != INSIDE:  # b's own entry names its step
        return f"{DEFER}{ref} ({why}) comes first"
    first = f"{DEFER}{ref} ({INSIDE}) comes first"
    step = _inside_step(view, b, now_ms, more)
    return f"{first} → {step}" if step else first


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
