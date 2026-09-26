"""The blackboard is a pure fold of the log (I2; ARCHITECTURE §5).

Every registered type has a reducer or is a world/ops type (``WORLD_OPS``;
no view reads the world). ``RECORD_ONLY`` types change nothing yet: their
semantics belong to later tasks (Guard/authority: S1-SYS-01/02; channel,
Slow-tool and relay consumption: S0-SYS-06) or the registry fixes no payload
keys for them. ``_with`` re-validates, unlike ``model_copy(update=...)``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from types import MappingProxyType

from pydantic import BaseModel

from proxyloop.contract.base import Lane
from proxyloop.contract.events import EVENT_TYPES, EpochBump, Event, StatusChanged
from proxyloop.contract.messages import FastToSlow, SlowToFast
from proxyloop.contract.state import (
    Blackboard,
    ChannelState,
    CompletionDecision,
    Fence,
    Line,
)

Reducer = Callable[[Blackboard, Event], Blackboard]

WORLD_OPS: frozenset[str] = frozenset(
    name for name, spec in EVENT_TYPES.items() if set(spec.streams) <= {"world", "ops"}
)
RECORD_ONLY: frozenset[str] = frozenset(
    """llm.call fast.request fast.turn fast.sentence fast.cancelled
    slow.step.started slow.step.completed slow.tool declass.denied fact.recorded
    readback.updated chan.opened chan.closed chan.hold chan.strike chan.barge_in
    approval.post mandate.proposed mandate.decided approval.requested
    approval.decided action.authorized action.denied speak.verbatim speak.released
    speak.revoked screen.redacted evidence.recorded""".split()  # noqa: SIM905
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
    return _with(bb, s2f_pending=pending)


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
    offer = {k: e.payload[k] for k in ("offer_ref", "revision", "slots", "terms_hash")}
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
    new = EpochBump.model_validate(e.payload).new
    if new <= bb.epoch:  # epochs only move forward (§9.4)
        raise ValueError(f"epoch {new} does not follow {bb.epoch}")
    return _with(bb, epoch=new)


def _status(bb: Blackboard, e: Event) -> Blackboard:
    status = StatusChanged.model_validate(e.payload).status
    return _with(bb, public=_with(bb.public, status=status))


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
        "summary.updated": _summary,
        "offer.recorded": _offer,
        "authority.fence": _fence,
        "authority.epoch": _epoch,
        "status.changed": _status,
        "completion.decided": _completion,
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
