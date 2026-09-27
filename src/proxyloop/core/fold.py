"""The blackboard is a pure fold of the log (I2; ARCHITECTURE §5).

Each registered type has a reducer or is world/ops (``WORLD_OPS``, unread by
views). ``RECORD_ONLY`` types change no state (ingress posts, denials,
redactions, model and channel bookkeeping). The authority reducers join each
event to what it decides or uses (a decision to its card or proposal, a line
or release to its capability), so the bus never writes one that does not
join. ``_with`` re-validates.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from types import MappingProxyType
from typing import Literal, cast

from pydantic import BaseModel

from proxyloop.contract.base import MAX_GUIDES, Frozen, Lane
from proxyloop.contract.events import (
    EVENT_TYPES,
    ActionAuthorized,
    ApprovalDecided,
    ApprovalPost,
    EpochBump,
    Event,
    MandateDecided,
    StatusChanged,
)
from proxyloop.contract.messages import FastToSlow, SlowToFast
from proxyloop.contract.state import (
    Approval,
    ApprovalCard,
    Authorization,
    Blackboard,
    CaseStatus,
    ChannelState,
    CompletionDecision,
    Evidence,
    Fact,
    Fence,
    HoldState,
    Line,
    Mandate,
    PublicFact,
    ReadbackSlot,
)
from proxyloop.guard.capability import accept_in_flight, released_accept
from proxyloop.guard.status import TERMINAL, TRANSITIONS

Reducer = Callable[[Blackboard, Event], Blackboard]

WORLD_OPS: frozenset[str] = frozenset(
    name for name, spec in EVENT_TYPES.items() if set(spec.streams) <= {"world", "ops"}
)
RECORD_ONLY: frozenset[str] = frozenset(
    """llm.call fast.request fast.turn fast.sentence fast.cancelled
    slow.step.started slow.step.completed slow.tool declass.denied
    chan.opened chan.closed chan.barge_in action.denied
    screen.redacted""".split()  # noqa: SIM905
)


def _with[M: BaseModel](model: M, **changes: object) -> M:
    return type(model).model_validate({**dict(model), **changes})


def _lane(value: object) -> Lane:
    if value not in ("user", "cp"):
        raise ValueError(f"not a lane: {value!r}")
    return value


def _append_line(bb: Blackboard, lane: Lane, line: Line) -> Blackboard:
    channel = bb.channels.get(lane, ChannelState())
    channel = _with(channel, lines=(*channel.lines, line))
    return _with(bb, channels={**bb.channels, lane: channel})


def _user_msg(bb: Blackboard, e: Event) -> Blackboard:
    line = {"utt_id": e.event_id, "speaker": "partner", "text": e.payload["text"]}
    return _append_line(bb, "user", Line.model_validate(line))


def _utt_final(bb: Blackboard, e: Event) -> Blackboard:
    p = e.payload
    line = {"utt_id": p["utt_id"], "speaker": p["speaker"], "text": p["text"]}
    return _append_line(bb, _lane(p["lane"]), Line.model_validate(line))


def _utt_delivered(bb: Blackboard, e: Event) -> Blackboard:
    """The transcript holds what the listener heard (§5), if anything."""
    p = e.payload
    if not p["text_heard"]:
        return bb
    line = {"utt_id": p["utt_id"], "speaker": "agent", "text": p["text_heard"]}
    return _append_line(bb, _lane(p["lane"]), Line.model_validate(line))


def _f2s(bb: Blackboard, e: Event) -> Blackboard:
    return _with(
        bb, f2s_pending=(*bb.f2s_pending, FastToSlow.model_validate(e.payload))
    )


def _s2f(bb: Blackboard, e: Event) -> Blackboard:
    msg = SlowToFast.model_validate(e.payload)
    pending = {**bb.s2f_pending, msg.lane: (*bb.s2f_pending.get(msg.lane, ()), msg)}
    guides = (*bb.public.guidance_cp, *([msg.guide] if msg.guide else []))
    public = _with(bb.public, guidance_cp=guides[-MAX_GUIDES:])  # the last 3
    return _with(bb, s2f_pending=pending, public=public)


def _fact(bb: Blackboard, e: Event) -> Blackboard:
    p = e.payload
    fact = {"key": p["key"], "value": p["value"], "source_ref": p["source_ref"]}
    if p["scope"] == "private":
        facts = {**bb.private.case_facts, str(p["key"]): Fact.model_validate(fact)}
        return _with(bb, private=_with(bb.private, case_facts=facts))
    said = [x.utt_id for x in bb.channels["cp"].lines if x.speaker == "partner"]
    if p["source"] == "cp_utt" and p["source_ref"] not in said:
        raise ValueError(f"public fact {p['key']}: {p['source_ref']} is no rep line")
    told = [x.utt_id for x in bb.channels["user"].lines if x.speaker == "partner"]
    if p["source"] == "shareable" and p["source_ref"] not in told:  # I4 (#133)
        raise ValueError(f"public fact {p['key']}: {p['source_ref']} is no user msg")
    public = PublicFact.model_validate(fact | {"source": p["source"]})
    facts = {**bb.public.facts, public.key: public}
    return _with(bb, public=_with(bb.public, facts=facts))


def _hold(bb: Blackboard, e: Event) -> Blackboard:
    reason = e.payload["reason"]
    hold = None if reason is None else {"reason": reason, "since_ms": e.t_ms}
    held = None if hold is None else HoldState.model_validate(hold)
    return _with(bb, public=_with(bb.public, cp_hold=held))


def _strike(bb: Blackboard, e: Event) -> Blackboard:
    cp = bb.channels.get("cp", ChannelState())
    return _with(bb, channels={**bb.channels, "cp": _with(cp, strikes=cp.strikes + 1)})


def _s2f_voiced(bb: Blackboard, e: Event) -> Blackboard:
    done = e.payload["msg_id"]
    pending = {
        lane: tuple(m for m in msgs if m.msg_id != done)
        for lane, msgs in bb.s2f_pending.items()
    }
    return _with(bb, s2f_pending=pending)


def _summary(bb: Blackboard, e: Event) -> Blackboard:
    scope, text = e.payload["scope"], e.payload["text"]
    if scope == "public":
        return _with(bb, public=_with(bb.public, summary=text))
    if scope == "private":
        return _with(bb, private=_with(bb.private, summary=text))
    raise ValueError(f"summary scope {scope!r}")


def _offer(bb: Blackboard, e: Event) -> Blackboard:
    """A new revision: its slots start ``unknown`` and its terms unbound; only
    ``readback.updated`` (Guard) sets statuses and ``terms_hash``."""
    p = e.payload
    prev = bb.public.offers.get(str(p["offer_ref"]))
    if prev is not None and cast(int, p["revision"]) <= prev.revision:
        raise ValueError(f"offer {p['offer_ref']}: revision {p['revision']} is not new")
    slots = [
        ReadbackSlot.model_validate(s).model_copy(update={"status": "unknown"})
        for s in cast(list[object], p["slots"])
    ]
    offer = {"offer_ref": p["offer_ref"], "revision": p["revision"], "slots": slots}
    offer |= {"expires_ms": p.get("expires_ms"), "terms_hash": None}
    offers = {**bb.public.offers, str(offer["offer_ref"]): offer}
    return _with(bb, public=_with(bb.public, offers=offers))


def _fence(bb: Blackboard, e: Event) -> Blackboard:
    p = e.payload
    if p["op"] == "raised":
        fence = {"fence_id": p["fence_id"], "utt_id": p["utt_id"], "raised_seq": e.seq}
        return _with(bb, fences=(*bb.fences, Fence.model_validate(fence)))
    if p["op"] == "cleared":  # cleared fences leave the blackboard
        return _with(
            bb, fences=tuple(f for f in bb.fences if f.fence_id != p["fence_id"])
        )
    raise ValueError(f"fence op {p['op']!r}")


def _epoch(bb: Blackboard, e: Event) -> Blackboard:
    bump = EpochBump.model_validate(e.payload)
    if bump.new <= bb.epoch:  # epochs only move forward (§9.4)
        raise ValueError(f"epoch {bump.new} does not follow {bb.epoch}")
    m = bb.private.mandate  # decided in this epoch, it carries the new one
    this = m is not None and m.status != "proposed" and m.epoch == bb.epoch
    if bump.reason == "mandate_decided" and m and this:
        bb = _private(bb, mandate=_with(m, epoch=bump.new))
    return _with(bb, epoch=bump.new)  # every other grant is now stale


_EDGES = {(was, to) for (was, _), to in TRANSITIONS.items()}
_VERIFIED = {CaseStatus.VERIFIED_COMPLETE: 1, CaseStatus.VERIFIED_NO_DEAL: 0}


def _status(bb: Blackboard, e: Event) -> Blackboard:
    """The §9.5 machine. A ``VERIFIED_*`` status needs a ``completion.decided(ok)``
    of its kind: exactly one released accept for COMPLETE, none for NO_DEAL."""
    change = StatusChanged.model_validate(e.payload)
    was, status = change.previous, change.status
    if was != bb.public.status:
        raise ValueError(
            f"status.changed from {was}, but the case is {bb.public.status}"
        )
    hang_up = status is CaseStatus.ABANDONED and was not in TERMINAL
    if (was, status) not in _EDGES and not hang_up:
        raise ValueError(f"{was} -> {status} is not a status transition")
    if status in _VERIFIED:
        caps = bb.capabilities.values()
        released = sum(c.intent == "accept_offer" and c.consumed for c in caps)
        ok = bb.completion is not None and bb.completion.verdict == "ok"
        if not ok or released != _VERIFIED[status]:
            raise ValueError(f"{status} needs a completion.decided(ok) of its kind")
    return _with(bb, public=_with(bb.public, status=status))


def _private(bb: Blackboard, **changes: object) -> Blackboard:
    return _with(bb, private=_with(bb.private, **changes))


def _mandate_proposed(bb: Blackboard, e: Event) -> Blackboard:
    m = Mandate.model_validate(e.payload)
    if m.epoch != bb.epoch:
        raise ValueError(f"mandate {m.mandate_id}: epoch {m.epoch}, not {bb.epoch}")
    return _private(bb, mandate=m)


def _mandate_decided(bb: Blackboard, e: Event) -> Blackboard:
    d, m = MandateDecided.model_validate(e.payload), bb.private.mandate
    if m is None or (m.mandate_id, m.mandate_hash, m.status, m.epoch) != (
        d.mandate_id,
        d.mandate_hash,
        "proposed",
        bb.epoch,
    ):
        raise ValueError(f"mandate.decided {d.mandate_id}: no such proposed mandate")
    return _private(bb, mandate=_with(m, status=d.decision, decided_by=d.by))


def _post(bb: Blackboard, e: Event) -> Blackboard:
    """An ``approval.post`` binds to the pending card or proposed mandate (id,
    hash, epoch). The log makes its decision cite exactly this post (id,
    decision, actor), so the decision is bound to the card's terms too."""
    p, card, m = ApprovalPost.model_validate(e.payload), None, bb.private.mandate
    subject: tuple[object, ...] | None = None
    if p.subject == "approval" and (card := bb.private.pending_approval):
        subject = (card.approval_id, card.terms_hash, card.authority_epoch)
    elif p.subject == "mandate" and m is not None and m.status == "proposed":
        subject = (m.mandate_id, m.mandate_hash, m.epoch)
    if subject != (p.subject_id, p.subject_hash, bb.epoch) or p.authority_epoch != (
        bb.epoch
    ):
        raise ValueError(f"approval.post {p.subject_id}: not the pending {p.subject}")
    return bb


def _approval_requested(bb: Blackboard, e: Event) -> Blackboard:
    card = ApprovalCard.model_validate(e.payload)
    offer = bb.public.offers.get(card.offer_ref)
    if offer is None or (offer.revision, offer.terms_hash) != (
        card.revision,
        card.terms_hash,
    ):
        raise ValueError(f"card {card.approval_id}: not the recorded offer")
    if card.authority_epoch != bb.epoch:
        raise ValueError(f"card {card.approval_id}: not minted in epoch {bb.epoch}")
    return _private(bb, pending_approval=card)


def _approval_decided(bb: Blackboard, e: Event) -> Blackboard:
    d, card = ApprovalDecided.model_validate(e.payload), bb.private.pending_approval
    if card is None or card.approval_id != d.approval_id:
        raise ValueError(f"approval.decided {d.approval_id}: no such pending card")
    offer = bb.public.offers.get(card.offer_ref)
    current = offer is not None and (offer.revision, offer.terms_hash) == (
        card.revision,
        card.terms_hash,
    )
    if not current or card.authority_epoch != bb.epoch or card.expires_ms <= e.t_ms:
        raise ValueError(f"card {d.approval_id} is superseded, stale or expired")
    approval = Approval(
        approval_id=d.approval_id,
        decision=d.decision,
        by=d.by,
        terms_hash=card.terms_hash,
        authority_epoch=card.authority_epoch,
        expires_ms=card.expires_ms,  # the card's window (ADR-0007)
    )
    approvals = {**bb.private.approvals, d.approval_id: approval}
    return _private(bb, pending_approval=None, approvals=approvals)


def _authorized(bb: Blackboard, e: Event) -> Blackboard:
    a = ActionAuthorized.model_validate(e.payload)
    cap = a.capability
    if (cap.intent, cap.epoch, cap.consumed) != (a.intent, bb.epoch, False) or (
        cap.cap_id in bb.capabilities
    ):
        raise ValueError(f"capability {cap.cap_id}: not a new one of this epoch")
    if cap.expires_ms <= e.t_ms:
        raise ValueError(f"capability {cap.cap_id}: expired when minted")
    if a.intent == "accept_offer" and released_accept(bb, cap.terms_hash):
        raise ValueError(f"capability {cap.cap_id}: an accept was already released")
    if a.intent == "accept_offer" and accept_in_flight(bb):  # one per case
        raise ValueError(f"capability {cap.cap_id}: another accept is in flight")
    offers = bb.public.offers.items()
    ref = next((r for r, o in offers if o.terms_hash == cap.terms_hash), None)
    if ref is None and a.intent == "accept_offer":
        raise ValueError(f"capability {cap.cap_id}: no offer has these terms")
    auth = Authorization(
        intent=a.intent,
        offer_ref=ref,
        terms_hash=cap.terms_hash,
        cap_id=cap.cap_id,
        epoch=cap.epoch,
    )
    return _with(
        bb,
        authorizations=(*bb.authorizations, auth),
        capabilities={**bb.capabilities, cap.cap_id: cap},
    )


def _live_cap(bb: Blackboard, e: Event) -> str:
    cap = bb.capabilities.get(str(e.payload.get("cap_id")))
    if cap is None or cap.consumed:
        raise ValueError(
            f"{e.type}: capability {e.payload.get('cap_id')} is unknown or used"
        )
    return cap.cap_id


def _verbatim(bb: Blackboard, e: Event) -> Blackboard:
    kind = e.payload["kind"]
    if kind == "accept":  # only a live capability queues an accept line
        _live_cap(bb, e)
    if kind != "decline":
        return bb
    ref = str(e.payload.get("offer_ref"))
    offer = bb.public.offers.get(ref)
    if offer is None:
        raise ValueError(f"decline of unknown offer {ref!r}")
    offers = {**bb.public.offers, ref: _with(offer, status="declined")}
    return _with(bb, public=_with(bb.public, offers=offers))


def _released(bb: Blackboard, e: Event) -> Blackboard:
    """The time-free part of ``guard.revalidate``: a replayed log never
    releases under a fence, at a stale epoch, or for changed or closed terms."""
    if "cap_id" not in e.payload:  # a line that needs no authority
        return bb
    cap = bb.capabilities[_live_cap(bb, e)]
    auth = next(a for a in bb.authorizations if a.cap_id == cap.cap_id)
    offer = bb.public.offers.get(auth.offer_ref or "")
    if cap.epoch != bb.epoch or bb.fences or offer is None or offer.status != "open":
        raise ValueError(f"release of {cap.cap_id}: stale epoch, fence or closed offer")
    if offer.terms_hash != cap.terms_hash:
        raise ValueError(f"release of {cap.cap_id}: the terms changed")
    if cap.intent == "accept_offer" and released_accept(bb, cap.terms_hash):
        raise ValueError(f"release of {cap.cap_id}: an accept was already released")
    return _with(
        bb, capabilities={**bb.capabilities, cap.cap_id: _with(cap, consumed=True)}
    )


def _revoked(bb: Blackboard, e: Event) -> Blackboard:
    if "cap_id" not in e.payload:
        return bb
    dead = _live_cap(bb, e)  # a revoked capability can never be released
    return _with(
        bb, capabilities={k: c for k, c in bb.capabilities.items() if k != dead}
    )


class _Readback(Frozen):
    offer_ref: str
    revision: int
    slot_statuses: dict[str, Literal["unknown", "heard", "confirmed"]]
    terms_hash: str | None


def _readback(bb: Blackboard, e: Event) -> Blackboard:
    r = _Readback.model_validate(e.payload)
    offer = bb.public.offers.get(r.offer_ref)
    fields = None if offer is None else {s.field for s in offer.slots}
    if offer is None or offer.revision != r.revision or fields != set(r.slot_statuses):
        raise ValueError(f"readback for {r.offer_ref} r{r.revision}: not the offer")
    slots = tuple(_with(s, status=r.slot_statuses[s.field]) for s in offer.slots)
    offer = _with(offer, slots=slots, terms_hash=r.terms_hash)
    offers = {**bb.public.offers, r.offer_ref: offer}
    return _with(bb, public=_with(bb.public, offers=offers))


def _evidence(bb: Blackboard, e: Event) -> Blackboard:
    return _with(bb, evidence=(*bb.evidence, Evidence.model_validate(e.payload)))


def _completion(bb: Blackboard, e: Event) -> Blackboard:
    return _with(bb, completion=CompletionDecision.model_validate(e.payload))


def _record_only(bb: Blackboard, e: Event) -> Blackboard:
    return bb


REDUCERS: MappingProxyType[str, Reducer] = MappingProxyType(
    {name: _record_only for name in RECORD_ONLY}
    | {
        "user.msg": _user_msg,
        "utt.final": _utt_final,
        "utt.delivered": _utt_delivered,
        "f2s.msg": _f2s,
        "s2f.msg": _s2f,
        "s2f.voiced": _s2f_voiced,
        "fact.recorded": _fact,
        "chan.hold": _hold,
        "chan.strike": _strike,
        "summary.updated": _summary,
        "offer.recorded": _offer,
        "authority.fence": _fence,
        "authority.epoch": _epoch,
        "status.changed": _status,
        "completion.decided": _completion,
        "approval.post": _post,
        "mandate.proposed": _mandate_proposed,
        "mandate.decided": _mandate_decided,
        "approval.requested": _approval_requested,
        "approval.decided": _approval_decided,
        "action.authorized": _authorized,
        "speak.verbatim": _verbatim,
        "speak.released": _released,
        "speak.revoked": _revoked,
        "readback.updated": _readback,
        "evidence.recorded": _evidence,
    }
)


def apply(bb: Blackboard, e: Event) -> Blackboard:
    reducer = REDUCERS.get(e.type)
    if reducer is None and e.type not in WORLD_OPS:
        raise ValueError(f"no reducer for {e.type}")
    if reducer is not None:
        bb = reducer(bb, e)
    return _with(bb, seq=e.seq, t_ms=e.t_ms)


def fold(events: Iterable[Event], bb: Blackboard | None = None) -> Blackboard:
    state = Blackboard() if bb is None else bb
    for e in events:
        state = apply(state, e)
    return state
