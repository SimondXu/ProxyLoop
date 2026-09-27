"""Slow's S0 tools (§8): ``slow.tool`` events citing the step's call and relays, then
``guard`` effects. Bad model output is refused and counted, never repaired (rule 12)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from proxyloop.contract import base
from proxyloop.contract import state as st
from proxyloop.contract.base import Lane
from proxyloop.contract.llm import ToolCall
from proxyloop.contract.messages import Guide, SlowToFast
from proxyloop.contract.protocol import GuideSlotError, render_messages
from proxyloop.contract.views import Trigger, view_cp
from proxyloop.guard.declass import declassify, numbers, spoken

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

Effect = tuple[str, Mapping[str, object]]
SCALE = {"usd_minor": 100, "months": 1}  # minor units and months, as spoken
_INVALID = (ValidationError, ValueError, KeyError, TypeError, ArithmeticError)
_GUIDE = frozenset({"tool", "move", "slots"})
_DIGITS, _SEP = re.compile(r"\d+(?:[ -]\d+)*"), re.compile(r"[ -]")  # "48-21"
_WORD = re.compile(r"[^\W_]+")  # "I'd" is two words
MAX_WORDS, MAX_CHARS = 6, 60  # a shareable text value the user said
_EMPTY: tuple[object, ...] = (None, "", [])


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

    def act(self, call: ToolCall, causes: Sequence[str]) -> str:  # the text Slow reads
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
            return self._guide(bb, a)
        if name == "record_fact":
            return self.fact(bb, str(a["key"]), str(a["value"]), a.get("utt_ref"))
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

    def _guide(self, bb: st.Blackboard, a: Mapping[str, Any]) -> Result:  # I4
        extra = sorted(k for k, v in a.items() if k not in _GUIDE and v not in _EMPTY)
        if extra:  # e.g. free text: refused whole, never dropped (ROOT-05 g)
            denied = {"intent": "guide_fast", "reason": "guide_extra_fields"}
            text = (
                f"guide_fast takes only move and slots, not {', '.join(extra)}: the "
                "phone voice never gets free text; use ask_user/tell_user for the user"
            )
            return _no(text, ("action.denied", denied))
        guide = Guide(move=a["move"], slots=tuple(a.get("slots") or ()))
        if public_guide(bb, guide):
            return self._s2f(lane="cp", type="GUIDE", guide=guide)
        hidden = [
            s
            for s in guide.slots
            if not public_guide(bb, Guide(move=guide.move, slots=(s,)))
        ]
        facts = [f"fact:{k}" for k in sorted(bb.public.facts)]
        offers = [
            f"offer:{o.offer_ref}.{s.field}"
            for o in bb.public.offers.values()
            for s in o.slots
        ]
        text = (
            f"not public: {', '.join(hidden)}; public slots: "
            f"{', '.join(facts + offers) or 'none'}. A shareable fact becomes public "
            "with record_fact(<canonical key>, value, utt_ref of the user's message)"
        )
        denied = {"intent": "guide_fast", "reason": "guide_slot_not_public"}
        return _no(text, ("action.denied", denied))

    def _s2f(self, **fields: Any) -> Result:
        self._n += 1
        msg = SlowToFast(msg_id=f"s2f-{self._n}", **fields)
        return Result(
            True, f"sent {msg.msg_id}", (("s2f.msg", msg.model_dump(mode="json")),)
        )

    def fact(self, bb: st.Blackboard, key: str, value: str, ref: object) -> Result:
        """Public iff the rep said it in ``ref``, or shareable and said by the user
        in the ``user.msg`` that ``ref`` names, directly or through the user-lane
        relay it cites (a relay is Fast's claim, never the source; I4)."""
        line = _partner(bb, "cp").get(str(ref), "")
        relayed = {r.msg_id: r.utt_ref for r in bb.f2s_pending if r.lane == "user"}
        msg_id = relayed.get(str(ref)) or str(ref)  # the user's own message
        told = _partner(bb, "user").get(msg_id, "")
        hits = [msg_id] if told and _user_said(value, told) else []
        leaks = _leaks(value, bb) if hits else []  # never a protected value or bound
        shareable = key in self._shareable_keys and hits and not leaks
        in_line = bool(line) and _said(value, line)
        source = "cp_utt" if in_line else "shareable" if shareable else "user"
        ref = str(ref) if source == "cp_utt" else hits[0] if shareable else ref
        ref = None if ref is None else str(ref)  # the rep line or user message
        fact = {"key": key, "value": value, "source_ref": ref}
        where = "private" if source == "user" else "public"
        if source == "user":
            st.Fact.model_validate(fact)
        else:
            st.PublicFact.model_validate(fact | {"source": source})
            self.shareable |= {key: value} if source == "shareable" else {}
        recorded = fact | {"source": source, "scope": where}
        effects: list[Effect] = [("fact.recorded", recorded)]
        text = f"recorded {where}"
        if where == "private" and key in self._shareable_keys and leaks:
            text += ", never public: " + "; ".join(leaks)  # counted as declass
            effects.append(("declass.denied", {"violations": leaks}))
        elif where == "private" and key in self._shareable_keys:  # how to share it
            text += (
                ": to make it public, cite the utt of the user message that says "
                "exactly this value (whole digits or whole words)"
            )
        return Result(True, text, tuple(effects))


def _partner(bb: st.Blackboard, lane: Lane) -> dict[str, str]:  # utt id -> text
    lines = bb.channels.get(lane, st.ChannelState()).lines
    return {x.utt_id: x.text for x in lines if x.speaker == "partner"}


def _said(value: str, line: str) -> bool:  # its digits, else its text verbatim
    digits = numbers(value)
    return digits <= numbers(line) if digits else value.casefold() in line.casefold()


def _user_said(value: str, message: str) -> bool:
    """I4, the user-message path: a value with a digit is only digits in groups
    and equals one whole digit run of ``message`` ("48-21" says 4821; "14821"
    and "555 482 1999" do not); any other value is at most ``MAX_WORDS`` whole
    words in a row (casefold) and ``MAX_CHARS`` characters."""
    if any(c.isdigit() for c in value):
        if not _DIGITS.fullmatch(value):
            return False
        runs = _DIGITS.findall(message)
        return any(_SEP.sub("", run) == _SEP.sub("", value) for run in runs)
    want, heard = _WORD.findall(value.casefold()), _WORD.findall(message.casefold())
    if not want or len(want) > MAX_WORDS or len(value) > MAX_CHARS:
        return False
    n = len(want)
    return any(heard[i : i + n] == want for i in range(len(heard) - n + 1))


def _leaks(value: str, bb: st.Blackboard) -> list[str]:  # guard.declass decides
    """A protected case-fact value or an unsaid mandate bound in ``value``."""
    return [v for v in declassify(value, bb, {}) if not v.endswith("source-bound")]


def public_guide(bb: st.Blackboard, guide: Guide) -> bool:  # the renderer judges
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
) -> Result:  # every money or term value is one the rep said
    slots = [st.ReadbackSlot(source_utt=s.get("utt_ref"), **_slot(s)) for s in raw]
    said = {x.utt_id: x.text for x in bb.channels["cp"].lines if x.speaker == "partner"}
    unbound = [
        f"{s.field}={s.value} is not in rep line {s.source_utt}"
        for s in slots
        if (line := said.get(str(s.source_utt))) is None
        or (s.unit in SCALE and not s.value.isdigit())  # plain integers only
        or not _value(s) <= spoken(line, s.unit)
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


def _value(s: st.ReadbackSlot) -> set[Decimal]:  # in the unit as spoken
    if s.unit in SCALE:
        return {Decimal(s.value) / SCALE[s.unit]}
    return numbers(s.value)


def _slot(s: Mapping[str, Any]) -> dict[str, Any]:
    return {k: s[k] for k in ("field", "value", "unit", "role")}
