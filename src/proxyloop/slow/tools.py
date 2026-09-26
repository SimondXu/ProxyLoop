"""Slow's S0 tools (ARCHITECTURE §8). Each ``act`` call is one ``slow.tool``
for its summaries plus one per listed call, each citing the step's ``llm.call``
and the relays it read; effects are ``guard`` events citing their ``slow.tool``.
Invalid model output is refused and counted, never repaired (AGENTS rule 12).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from proxyloop.contract import base
from proxyloop.contract import state as st
from proxyloop.contract.llm import ToolCall
from proxyloop.contract.messages import Guide, SlowToFast
from proxyloop.contract.protocol import GuideSlotError, render_messages
from proxyloop.contract.views import Trigger, view_cp
from proxyloop.guard.declass import declassify, numbers, rep_numbers

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

Effect = tuple[str, Mapping[str, object]]
_INVALID = (ValidationError, ValueError, KeyError, TypeError, ArithmeticError)


@dataclass(frozen=True)
class Result:
    ok: bool
    text: str
    effects: tuple[Effect, ...] = ()
    then: Callable[[], None] | None = None


def _no(text: str, *effects: Effect) -> Result:
    return Result(False, text, effects)


class SlowTools:
    def __init__(self, host: Kernel, shareable_keys: frozenset[str]) -> None:
        self._host, self._shareable_keys = host, shareable_keys
        self.shareable: dict[str, str] = {}  # recorded shareable values (declass)
        self.finished, self._n = False, 0

    def act(self, call: ToolCall, causes: Sequence[str]) -> str:
        """Run one ``act`` call; the result text Slow reads next."""

        try:
            raw: Any = json.loads(call.arguments)
            if call.name != "act" or not isinstance(raw, dict):
                raise ValueError(f"expected one act call, not {call.name}")
            args = cast(dict[str, Any], raw)
            summaries = {k: args.get(k) for k in ("private_summary", "public_summary")}
            head = self._summaries(summaries)
        except ValueError as err:  # JSON and schema errors: the whole act
            return self._apply("act", {"raw": call.arguments}, _no(str(err)), causes)
        out = [self._apply("act", summaries, head, causes)]
        for c in cast(list[Any], args.get("calls") or []):
            a = cast(dict[str, Any], c if isinstance(c, dict) else {})
            try:
                result = self._run(str(a.get("tool")), a)
            except _INVALID as err:
                result = _no(f"invalid arguments: {err}")
            out.append(self._apply(str(a.get("tool")), a, result, causes))
        return "\n".join(out)

    def _apply(self, name: str, args: object, r: Result, causes: Sequence[str]) -> str:
        done = {"name": name, "args": args, "result_text": r.text, "ok": r.ok}
        tool = self._host.emit("slow.tool", "slow", done, causes).event_id
        for type_, payload in r.effects:
            self._host.emit(type_, "guard", payload, [tool])
        if r.then is not None:
            r.then()
        return f"{name}: {r.text}"

    def _summaries(self, s: Mapping[str, object]) -> Result:
        private, public = s["private_summary"], s["public_summary"]
        if not isinstance(private, str) or len(private) > base.MAX_PRIVATE_SUMMARY:
            raise ValueError("private_summary must be text of at most 1200 characters")
        mine: Effect = ("summary.updated", {"scope": "private", "text": private})
        if public is None:
            return Result(True, "private summary updated", (mine,))
        if violations := declassify(str(public), self._host.bb, self.shareable):
            denied: Effect = ("declass.denied", {"violations": list(violations)})
            refused = "public summary refused: " + "; ".join(violations)
            return Result(False, refused, (mine, denied))
        shared: Effect = ("summary.updated", {"scope": "public", "text": str(public)})
        return Result(True, "summaries updated", (mine, shared))

    def _run(self, name: str, a: Mapping[str, Any]) -> Result:
        bb, host = self._host.bb, self._host
        if name in ("ask_user", "tell_user"):
            return self._s2f(lane="user", type=name.upper(), text=str(a["text"]))
        if name == "wait":
            if not 1 <= (seconds := int(a["seconds"])) <= 15:
                return _no("seconds must be 1-15")
            then = lambda: host.wake_slow("timer", seconds)  # noqa: E731
            return Result(True, f"waking in {seconds} s", then=then)
        if name == "guide_fast":
            guide = Guide(move=a["move"], slots=tuple(a.get("slots") or ()))
            if public_guide(bb, guide):
                return self._s2f(lane="cp", type="GUIDE", guide=guide)
            denied = {"intent": "guide_fast", "reason": "guide_slot_not_public"}
            return _no("a slot is not public", ("action.denied", denied))
        if name == "record_fact":
            return self._fact(bb, str(a["key"]), str(a["value"]), a.get("utt_ref"))
        if name == "record_offer":
            return record_offer(bb, str(a["offer_ref"]), a["offer_slots"])
        if name != "finish":
            return _no(f"unknown tool {name!r}")
        if a.get("outcome") != "info_only":
            return _no("only finish(info_only) exists in this stage")
        self.finished = True
        status = {
            "previous": bb.public.status,
            "status": st.CaseStatus.CLOSED_NO_ACTION,
        }
        then = lambda: host.finish("info_only")  # noqa: E731
        return Result(True, "case closed", (("status.changed", status),), then)

    def _s2f(self, **fields: Any) -> Result:
        self._n += 1
        msg = SlowToFast(msg_id=f"s2f-{self._n}", **fields)
        return Result(
            True, f"sent {msg.msg_id}", (("s2f.msg", msg.model_dump(mode="json")),)
        )

    def _fact(self, bb: st.Blackboard, key: str, value: str, ref: object) -> Result:
        """Public iff the rep said it in ``ref``, or shareable and user-relayed."""

        said = {
            x.utt_id: x.text for x in bb.channels["cp"].lines if x.speaker == "partner"
        }
        line, digits = said.get(str(ref), ""), numbers(value)
        in_line = (
            digits <= numbers(line) if digits else value.casefold() in line.casefold()
        )
        relays = [r for r in bb.f2s_pending if r.lane == "user"]
        relayed = any((key, value) in r.facts or value in r.text for r in relays)
        shareable = key in self._shareable_keys and relayed
        source = "cp_utt" if line and in_line else "shareable" if shareable else "user"
        if source == "user":
            st.Fact(key=key, value=value)  # validates
        else:
            st.PublicFact(key=key, value=value, source=source, source_ref=str(ref))
            self.shareable |= {key: value} if source == "shareable" else {}
        fact = {"key": key, "value": value, "source": source, "source_ref": ref}
        where = "private" if source == "user" else "public"
        return Result(True, f"recorded {where}", (("fact.recorded", fact),))


def public_guide(bb: st.Blackboard, guide: Guide) -> bool:
    """Every slot resolves in public state; the renderer is the judge."""

    public = bb.public.model_copy(update={"guidance_cp": (guide,)})
    view = view_cp(
        bb.model_copy(update={"public": public}), Trigger(kind="guidance"), ""
    )
    try:
        render_messages(view, "pl_cp_v1")
    except GuideSlotError:
        return False
    return True


def record_offer(
    bb: st.Blackboard, ref: str, raw: Sequence[Mapping[str, Any]]
) -> Result:
    """An offer as the rep said it: every money or term value is one the rep said."""

    slots = [st.ReadbackSlot(source_utt=s.get("utt_ref"), **_slot(s)) for s in raw]
    heard, scale = rep_numbers(bb), {"usd_minor": 100, "months": 1}
    unbound = [
        f"{s.field}={s.value} was not said by the rep"
        for s in slots
        if s.unit in scale and Decimal(s.value) / scale[s.unit] not in heard
    ]
    if unbound:
        return _no("; ".join(unbound), ("declass.denied", {"violations": unbound}))
    prev = bb.public.offers.get(ref)
    if prev is None and len(bb.public.offers) >= base.MAX_OFFERS:
        return _no("too many offers")
    revision = prev.revision + 1 if prev else 1
    offer = st.OfferPublic(offer_ref=ref, revision=revision, slots=tuple(slots))
    recorded = offer.model_dump(mode="json", include={"offer_ref", "revision", "slots"})
    recorded["terms_hash"] = None  # pl.terms/2 needs confirmed slots (S1)
    return Result(True, f"recorded {ref} r{revision}", (("offer.recorded", recorded),))


def _slot(s: Mapping[str, Any]) -> dict[str, Any]:
    return {k: s[k] for k in ("field", "value", "unit", "role")}
