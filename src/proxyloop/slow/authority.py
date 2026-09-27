"""Slow's S1 authority, evidence and close tools (ARCHITECTURE §8, §9.3). Each
calls Guard and returns Guard's effects, or its denial as text: Slow never
decides a rule itself. Models may restrict authority (revoke, tighten) but never
grant it (I6): a proposed mandate grants nothing until a ``mandate.decided``
from the UI or the sim approver, and an accept needs a decided grant."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, cast

from proxyloop.contract.events import Event
from proxyloop.contract.messages import FastToSlow, SlowToFast
from proxyloop.contract.state import (
    Blackboard,
    Capability,
    ChannelState,
    OfferPublic,
    ReadbackSlot,
)
from proxyloop.guard import authorize as guard
from proxyloop.guard.authorize import CaseRef, Denial
from proxyloop.guard.capability import business_action_id
from proxyloop.guard.mandate import proposal
from proxyloop.guard.readback import ROLE_OF
from proxyloop.guard.status import status_change
from proxyloop.guard.terms import offer_terms_hash
from proxyloop.guard.verify import verify_completion, verify_no_deal
from proxyloop.slow.result import Effect, Result, no

HINTS = {  # what Slow can do about a denial; the reason itself is Guard's
    "fence_raised": "a new user message or rep turn is not reflected in your view "
    "yet: wait for the next step",
    "readback_not_confirmed": "every required slot must be confirmed: record the "
    "offer as read back, then guide_fast(ask_readback, [offer:<ref>]) for that "
    "revision; the rep's next read-back confirms it",
    "outside_mandate": "request_approval(offer_ref) and wait for the user",
    "not_authorized": "no granted mandate covers it and no approval is granted: "
    "request_approval(offer_ref)",
    "approval_denied": "the user denied these terms: never accept them",
    "approval_pending": "a card is pending: wait for the user's decision",
    "not_in_call": "an accept is authorised only while the case is IN_CALL",
}
BOUNDS = ("max_monthly_price_minor", "max_term_months", "max_one_time_fees_minor")
LISTS = ("required_features", "forbidden_changes")
UNITS = {  # a ledger term's unit, by field kind; any other kind is a bool
    "monthly_price": "usd_minor",
    "fee": "usd_minor",
    "credit": "usd_minor",
    "term_months": "months",
    "expires": "iso",
}


def moved(bb: Blackboard, trigger: str) -> tuple[Effect, ...]:
    change = status_change(bb, trigger)
    return () if change is None else (("status.changed", change),)


def denied(intent: str, d: Denial) -> Result:
    hint = HINTS.get(d.reason)
    text = f"denied: {d.reason}" + (f" ({hint})" if hint else "")
    return no(text, ("action.denied", {"intent": intent, "reason": d.reason}))


def request_approval(bb: Blackboard, ref: str, case: CaseRef, msg_id: str) -> Result:
    """A card for the user, and the notice FastU voices (APPROVAL_NOTICE)."""
    got = guard.request_approval(bb, ref, case)
    if isinstance(got, Denial):
        return denied("request_approval", got)
    approval_id = str(got[0][1]["approval_id"])
    notice = SlowToFast(
        msg_id=msg_id, lane="user", type="APPROVAL_NOTICE", approval_id=approval_id
    )
    effects = (*got, *moved(bb, "approval_requested"))
    text = f"card {approval_id} sent to the user: wait for [APPROVAL] {approval_id}"
    return Result(True, text, (*effects, ("s2f.msg", notice.model_dump(mode="json"))))


def accept_offer(
    bb: Blackboard, ref: str, case: CaseRef, events: Sequence[Event]
) -> Result:
    """The Guard-written accept line; its effects cite the decision that
    granted it (the ``approval.decided`` or ``mandate.decided``)."""
    got = guard.accept_offer(bb, ref, case)
    if isinstance(got, Denial):
        return denied("accept_offer", got)
    cap = Capability.model_validate(got[0][1]["capability"])
    grant = _grant_event(bb, case, bb.public.offers[ref], cap, events)
    text = (
        f"accept line queued ({cap.cap_id}): the phone voice says it once revalidated"
    )
    effects = (*got, *moved(bb, "accept_authorized"))
    return Result(True, text, effects, causes=(grant,) if grant else ())


def _grant_event(
    bb: Blackboard,
    case: CaseRef,
    offer: OfferPublic,
    cap: Capability,
    events: Sequence[Event],
) -> str | None:
    """The decision event behind ``cap``: the grant whose business action id
    it carries (Guard chose it; this only finds its event)."""

    def bid(grant: str) -> str:
        return business_action_id(
            case.case_id, "accept_offer", offer.offer_ref, offer.revision,
            cap.terms_hash, grant,
        )  # fmt: skip

    wanted: tuple[str, str, str] | None = None
    for a in bb.private.approvals.values():
        if bid(a.approval_id) == cap.business_action_id:
            wanted = ("approval.decided", "approval_id", a.approval_id)
    m = bb.private.mandate
    if m is not None and bid(m.mandate_hash) == cap.business_action_id:
        wanted = ("mandate.decided", "mandate_hash", m.mandate_hash)
    return None if wanted is None else last(events, *wanted)


def last(events: Sequence[Event], type_: str, key: str, value: str) -> str | None:
    found = [e for e in events if e.type == type_ and e.payload.get(key) == value]
    return found[-1].event_id if found else None


def decline_offer(bb: Blackboard, ref: str) -> Result:
    got = guard.decline_offer(bb, ref)
    if isinstance(got, Denial):
        return denied("decline_offer", got)
    return Result(True, f"decline line queued for {ref}", got)


def propose_mandate(bb: Blackboard, envelope: Mapping[str, Any], mid: str) -> Result:
    """Any envelope is only proposed: the user decides it (I6)."""
    numbers, lists = _envelope(envelope)
    if not numbers and not lists:
        return no(f"an envelope needs at least one of {', '.join(BOUNDS + LISTS)}")
    kind, payload = proposal(bb, mid, **numbers, **lists)
    text = f"mandate {mid} proposed: it grants nothing until the user decides it"
    return Result(True, text, ((kind, payload),))


def tighten_mandate(bb: Blackboard, changes: Mapping[str, Any], mid: str) -> Result:
    """Restrict only: a new epoch, and the tighter mandate proposed in it, so
    it grants nothing until the user re-grants it (M7)."""
    m, (numbers, lists) = bb.private.mandate, _envelope(changes)
    if m is None or m.status in ("denied", "revoked"):
        return no("there is no mandate to tighten")
    old: dict[str, int | None] = {k: getattr(m, k) for k in BOUNDS}
    looser = [k for k, v in numbers.items() if (was := old[k]) is not None and v > was]
    if looser or not (numbers or lists):
        why = f"{', '.join(looser)} would loosen" if looser else "no change"
        text = f"tighten_mandate only restricts: {why}; propose_mandate asks the user"
        denial = {"intent": "tighten_mandate", "reason": "loosen" if looser else "none"}
        return no(text, ("action.denied", denial))
    kept: dict[str, tuple[str, ...]] = {k: getattr(m, k) for k in LISTS}
    joined = {k: tuple(sorted({*kept[k], *lists.get(k, ())})) for k in LISTS}
    epoch = bb.epoch + 1
    bump = {"new": epoch, "reason": "tighten_mandate"}
    later = bb.model_copy(update={"epoch": epoch})
    bounds = old | numbers
    kind, payload = proposal(later, mid, expires_ms=m.expires_ms, **bounds, **joined)
    text = f"mandate tightened as {mid}, epoch {epoch}: the user must re-grant it"
    return Result(True, text, (("authority.epoch", bump), (kind, payload)))


def _envelope(
    raw: Mapping[str, Any],
) -> tuple[dict[str, int], dict[str, tuple[str, ...]]]:
    if unknown := sorted(set(raw) - set(BOUNDS) - set(LISTS)):
        raise ValueError(f"unknown envelope fields {unknown}")
    numbers: dict[str, int] = {}
    for k in BOUNDS:
        if (v := raw.get(k)) is not None:
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise ValueError(f"{k} must be a whole number >= 0")
            numbers[k] = v
    lists: dict[str, tuple[str, ...]] = {}
    for k in LISTS:  # a restriction is never dropped: malformed is refused
        if (v := raw.get(k)) is None:
            continue
        items = cast(list[object], v) if isinstance(v, list) else None
        if items is None or not all(isinstance(x, str) and x for x in items):
            raise ValueError(f"{k} must be a list of names")
        if items:
            lists[k] = tuple(sorted({str(x) for x in items}))
    return numbers, lists


def revoke(bb: Blackboard) -> Result:
    """Restrict only, always allowed: every grant, card and capability of the
    old epoch is stale (§9.4)."""
    bump = {"new": bb.epoch + 1, "reason": "slow_revoke"}
    text = f"revoked: epoch {bb.epoch + 1}; earlier grants and cards are stale"
    return Result(True, text, (("authority.epoch", bump),))


def check_account(
    bb: Blackboard,
    conf: str,
    relays: Sequence[FastToSlow],
    events: Sequence[Event],
    cited: str | None = None,
    seen: int | None = None,
) -> Result:
    """``Ledger.lookup(conf)`` for a confirmation id the rep said: in the rep
    line ``cited`` (``transcript`` mode, ADR-0016), else in a cp relay FastC
    sent Slow (I5: Slow looks up only an id it was told; a cited line must be
    at or before ``seen``, the step's basis, when given). Its binding is
    recorded once as evidence, hashed as the accepted offer's revision; while
    the case is COMMITTED, that evidence moves it to EVIDENCE_PENDING, whenever
    it was recorded. ``verify_completion`` compares the hashes."""
    said = re.compile(rf"(?<![0-9A-Za-z]){re.escape(conf)}(?![0-9A-Za-z])")
    if cited is not None:  # the same boundary rule, on the line itself
        lines = bb.channels.get("cp", ChannelState()).lines
        line = next((x for x in lines if x.utt_id == cited), None)
        if line is None or line.speaker != "partner":  # none, or a self-binding
            return no(f"{cited!r} is no rep line: cite the REP line that said {conf}")
        if not conf or not said.search(line.text):
            return no(f"rep line {cited} does not say {conf!r}: cite it as said")
        said_at = [e for e in events if e.type == "utt.final" and e.payload.get(
            "utt_id") == cited]  # fmt: skip
        if seen is not None and said_at[-1].seq > seen:
            return no(f"rep line {cited} came after your view: cite a line shown")
        heard = [said_at[-1].event_id]
    else:
        told = [
            r for r in relays
            if r.lane == "cp" and conf and any(
                said.search(t) for t in (r.text, *(v for _, v in r.facts))
            )
        ]  # fmt: skip
        if not told:
            return no(
                f"no such confirmation relayed: {conf!r}; cite the id the rep said"
            )
        heard = [r.msg_id for r in told]
    writes = [
        e for e in events
        if e.type == "ledger.write" and e.payload.get("confirmation_id") == conf
    ]  # fmt: skip
    if not writes:
        return no(f"the account shows no confirmation {conf}")
    effects: list[Effect] = []
    if f"ledger:{conf}" in {e.evidence_id for e in bb.evidence}:
        text = f"{conf} is already recorded"
    else:
        evidence, text = _evidence(bb, conf, writes[-1].payload["binding"])
        effects.append(("evidence.recorded", evidence))
    # COMMITTED -> EVIDENCE_PENDING, whenever the evidence was recorded (M1);
    # evidence that binds nothing then fails verification: NEEDS_REPLAN
    effects += moved(bb, "evidence_recorded")
    causes = [writes[-1].event_id, *heard]
    return Result(True, text, tuple(effects), causes=tuple(causes))


def _evidence(
    bb: Blackboard, conf: str, binding: object
) -> tuple[dict[str, object], str]:
    """The ledger evidence of ``conf``: its terms hashed as the one released
    accept's offer revision (``None`` without one, or if unreadable)."""
    caps = bb.capabilities.values()
    released = [c for c in caps if c.intent == "accept_offer" and c.consumed]
    cap = released[0] if len(released) == 1 else None
    offers = bb.public.offers.values()
    offer = next((o for o in offers if cap and o.terms_hash == cap.terms_hash), None)
    bound = None if offer is None else _ledger_hash(binding, offer)
    evidence: dict[str, object] = {"evidence_id": f"ledger:{conf}", "kind": "ledger"}
    evidence |= {"confirmation_id": conf, "terms_hash": bound or None}
    if bound == "":
        return evidence, f"{conf}: evidence unreadable, it binds nothing"
    same = cap is not None and bound == cap.terms_hash
    return evidence, f"{conf} {'binds' if same else 'does not bind'} the accepted terms"


def _ledger_hash(binding: object, offer: OfferPublic) -> str:
    """The ``pl.terms/3`` hash of the ledger's bound terms (the rep says money
    in dollars, exact to the cent), as a revision of ``offer``; ``""`` if the
    world's value is unreadable, or it leaves fee or change completeness
    unstated or contradicts it (fail closed: it binds nothing)."""
    b: Mapping[str, Any] = {}
    if isinstance(binding, Mapping):
        b = cast(Mapping[str, Any], binding)
    try:
        terms = cast(dict[str, object], dict(b.get("terms") or {}))
        terms["term_months"] = b.get("term_months")
        slots: list[ReadbackSlot] = []
        for field, value in sorted(terms.items()):
            kind = field.partition(":")[0]
            unit = UNITS.get(kind, "bool")
            text = _minor(str(value)) if unit == "usd_minor" else str(value)
            slot = {"field": field, "value": text, "unit": unit}
            role = ROLE_OF.get(kind, "feature")
            slots.append(ReadbackSlot.model_validate(slot | {"role": role}))
    except (ValueError, TypeError, ArithmeticError):  # pydantic's too
        return ""
    return offer_terms_hash(offer.model_copy(update={"slots": tuple(slots)})) or ""


def _minor(dollars: str) -> str:
    cents = Decimal(dollars) * 100
    if not cents.is_finite() or cents != cents.to_integral_value():
        raise ValueError(f"{dollars} is not a whole number of cents")
    return str(int(cents))


def finish(bb: Blackboard, outcome: str, asked_final_at: int | None) -> Result:
    """``completed`` and ``no_deal`` go through the verifiers; only their
    ``completion.decided(ok)`` reaches a VERIFIED status (§9.5)."""
    now = bb.public.status
    if outcome == "completed":
        if (fail := status_change(bb, "completion_fail")) is None:
            return no(f"finish(completed) needs EVIDENCE_PENDING; the case is {now}")
        d = verify_completion(bb)
        decided: Effect = ("completion.decided", d.model_dump(mode="json"))
        if d.verdict == "fail":
            why = f"not verified: {', '.join(d.reasons)}; the case needs a replan"
            return Result(False, why, (decided, ("status.changed", fail)))
        return Result(True, "verified complete", (decided, *moved(bb, "completion_ok")))
    if outcome == "no_deal":
        if status_change(bb, "no_deal_verified") is None:
            return no(f"finish(no_deal) needs IN_CALL; the case is {now}")
        d = verify_no_deal(bb, asked_final_at)
        if d.verdict == "fail":
            return no(f"no deal not verified: {', '.join(d.reasons)}")
        decided = ("completion.decided", d.model_dump(mode="json"))
        return Result(
            True, "verified no deal", (decided, *moved(bb, "no_deal_verified"))
        )
    trigger = {"escalate": "escalate", "info_only": "info_only"}.get(outcome)
    if trigger is None:
        return no(f"unknown outcome {outcome!r}")
    if not (effects := moved(bb, trigger)):
        return no(f"finish({outcome}) is not possible while the case is {now}")
    return Result(True, "case closed", effects)
