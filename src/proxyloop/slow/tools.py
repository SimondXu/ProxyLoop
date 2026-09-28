"""Slow's tools (§8): ``slow.tool`` events citing the step's call and relays, then
``guard`` effects. Bad model output is refused and counted, never repaired (rule 12).
The S1 authority, evidence and close tools are in ``slow.authority``."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from proxyloop.contract import base
from proxyloop.contract import state as st
from proxyloop.contract.base import Lane
from proxyloop.contract.llm import ToolCall
from proxyloop.contract.messages import Guide, GuideMove, SlowToFast
from proxyloop.contract.protocol import GuideMoveError, GuideSlotError, render_messages
from proxyloop.contract.views import Trigger, view_cp
from proxyloop.guard import authorize as guard
from proxyloop.guard import readiness
from proxyloop.guard.authorize import CaseRef, Denial
from proxyloop.guard.declass import declassify, numbers
from proxyloop.guard.readback import readback_update
from proxyloop.kernel.wake import HEARTBEAT_S
from proxyloop.slow import asks, authority, offer_slots, shape
from proxyloop.slow.result import Effect, Result, no, refused

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

SCALE = {"usd_minor": 100, "months": 1}  # = offer_slots' (tests/slow: equality)
CP_PROFILE = "pl_cp_v3"  # = kernel.lanes.PROFILE["cp"] (tests/slow: equality)
_INVALID = (ValidationError, ValueError, KeyError, TypeError, ArithmeticError)
_GUIDE = frozenset({"tool", "move", "slots"})
_LAST4 = re.compile(r"[0-9]{4}")  # ASCII only: no NFKC, no separators
_WORD = r"[A-Za-z]+(?:['\u2019-][A-Za-z]+)*"  # O'Brien, Lee-Smith
_NAME = re.compile(rf"{_WORD}(?: {_WORD}){{0,3}}")  # 1-4 words, single spaces
_YEARS = re.compile(r"[0-9]{1,2}")
_TENURE = re.compile(  # #153 rounds 3-4: first person, in context, one space;
    # S1-SYS-20: "I" starts the message or a sentence ("She said I've..." never)
    r"(?:^|(?<=[.!?])\s+)I(?:'ve|\u2019ve| have) been (?:with you|a customer) "
    r"(?:for )?([0-9]{1,2}) [Yy]ears?(?![\w'\u2019-])"
)
_AGE = re.compile(r"(?i)\b(?:old|age|aged|ago)\b")  # "36 years old": no tenure
_NEGATION = re.compile(r"(?i)\b(?:not|never)\b|n['\u2019]t\b")
_NOT_ASCII = re.compile(r"[^\x00-\x7f\u2018\u2019\u201c\u201d]")  # but quotes
_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_BEFORE = (  # a token start; an opener only where it starts a token (no $"4821")
    r"(?:^|(?<=[\s:])|(?<=(?<![^\s:])[(\"\u201c]))"
)
_AFTER = r"(?=[)\"\u201d]?[.,;:!?]?(?:\s|$))"  # a closer, a mark; a space or the end
_EDGE = r"(?<![\w'\u2019-])", r"(?![\w'\u2019-])"  # a name's word bounds
MAX_NAME_CHARS = 60
_IDENTITY = readiness.IDENTITY  # A6: Guard's table; obs imports it too
NUMBER_WORDS = frozenset(
    """zero one two three four five six seven eight nine ten eleven twelve
    thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty
    forty fifty sixty seventy eighty ninety hundred thousand million billion
    dozen half""".split()  # noqa: SIM905
)
_EMPTY: tuple[object, ...] = (None, "", [])


def case_ref(case_id: str) -> CaseRef:
    """The read-back binding refs of a sim case: the task's own (no run id)."""
    return CaseRef(case_id, f"{case_id}/account", f"{case_id}/principal")


class SlowTools:
    def __init__(
        self,
        host: Kernel,
        shareable_keys: frozenset[str],
        case: CaseRef,
        *,
        transcript: bool = True,  # Slow reads the conversations (ADR-0016)
    ) -> None:
        self._host, self._shareable_keys, self._case = host, shareable_keys, case
        self._transcript, self._basis = transcript, None  # the step's view
        self.shareable: dict[str, str] = {}  # recorded shareable values (declass)
        self.finished, self._n, self._mandates = False, 0, 0
        # the cp transcript length when a read-back was first asked for an
        # offer revision, and when the final offer was last asked (§9.2, §9.3)
        self.asked: dict[tuple[str, int], int] = {}
        self.asked_final: int | None = None
        self.told_at: int | None = None  # the cp length at the last tell_user
        # every read-back ask of an offer revision: the cp transcript length
        # and the slots then unconfirmed (ADR-0018 V4, slow.state)
        self.readbacks: dict[tuple[str, int], list[tuple[int, frozenset[str]]]] = {}
        self.received: set[str] = set()  # the relay ids SlowLoop handed to Slow

    def act(
        self, call: ToolCall, causes: Sequence[str], *, basis: int
    ) -> str:  # the text Slow reads; ``basis``: the step's view (its basis_seq)
        self.readback()
        self._basis = basis
        try:
            raw: Any = json.loads(call.arguments)
            if call.name != "act" or not isinstance(raw, dict):
                raise ValueError(f"expected one act call, not {call.name}")
            args = cast(dict[str, Any], raw)
            if problem := shape.act_problem(args):  # f828f1: refused whole
                raise ValueError(problem)
            summaries = {k: args.get(k) for k in ("private_summary", "public_summary")}
            private = summaries["private_summary"]
            if not isinstance(private, str) or len(private) > base.MAX_PRIVATE_SUMMARY:
                raise ValueError(
                    "private_summary must be text of at most 1200 characters"
                )
        except ValueError as err:  # JSON and schema errors: the whole act
            whole = refused("act_shape", str(err))
            return self._apply("act", {"raw": call.arguments}, whole, causes)
        out: list[str] = []
        for n, c in enumerate(cast(list[Any], args.get("calls") or [])):
            if missing := shape.item_problem(n, c):  # never "unknown tool 'None'"
                out.append(self._apply("act", c, refused("act_shape", missing), causes))
                continue
            a = cast(dict[str, Any], c)
            try:
                result = self._run(str(a["tool"]), a)
            except GuideMoveError:  # a move the cp profile cannot render: a bug
                raise
            except _INVALID as err:  # aeab91: one line, not a pydantic dump
                result = refused(
                    "invalid_args", f"invalid arguments: {shape.invalid(err)}"
                )
            out.append(self._apply(str(a["tool"]), a, result, causes))
        head = self._summaries(summaries)  # R3b: after the calls it may cite
        return "\n".join([self._apply("act", summaries, head, causes), *out])

    def _apply(self, name: str, args: object, r: Result, causes: Sequence[str]) -> str:
        done = {"name": name, "args": args, "result_text": r.text, "ok": r.ok}
        done["code"] = r.code  # A1: a refusal's class; None on success
        tool = self._host.emit("slow.tool", "slow", done, causes).event_id
        for type_, payload in r.effects:
            self._host.emit(type_, "guard", payload, [tool, *r.causes])
        if r.then is not None:
            r.then()
        return f"{name}: {r.text}"

    def readback(self) -> None:
        """Guard's slot statuses and terms hash of each open offer, from the cp
        transcript and the tracked read-back request (``readback.updated``,
        citing the last rep line and the offer's record)."""
        bb, events = self._host.bb, self._host.bus.events
        lines = bb.channels["cp"].lines
        rep = [x.utt_id for x in lines if x.speaker == "partner"]
        heard = authority.last(events, "utt.final", "utt_id", rep[-1]) if rep else None
        for ref, o in sorted(bb.public.offers.items()):
            if o.status != "open":
                continue
            update = readback_update(o, lines, self.asked.get((ref, o.revision)))
            now = {s.field: s.status for s in o.slots}
            if (update["slot_statuses"], update["terms_hash"]) == (now, o.terms_hash):
                continue
            made = authority.last(events, "offer.recorded", "offer_ref", ref)
            causes = [c for c in (made, heard) if c is not None]
            self._host.emit("readback.updated", "guard", update, causes)

    def _summaries(self, s: Mapping[str, object]) -> Result:
        private, public = str(s["private_summary"]), s["public_summary"]
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
        bb, host, case = self._host.bb, self._host, self._case
        if name == "ask_user":  # A1: a pending key is not asked again
            keys, needs = self._shareable_keys, host.calls.needs
            if problem := asks.ask_problem(a, keys, needs):
                return problem
            if not a.get("keys"):
                host.counts["keyless_ask"] += 1  # counted, not deduped
            return self._s2f(lane="user", type="ASK_USER", text=str(a["text"]))
        if name == "tell_user":
            self.told_at = len(bb.channels["cp"].lines)  # V3: told after a reply
            return self._s2f(lane="user", type="TELL_USER", text=str(a["text"]))
        if name == "start_call":  # Guard-checked (ADR-0012 R1)
            return asks.start_call(host)
        if name == "wait":  # its slow.tool arms the timer (kernel.wake)
            seconds = a["seconds"]  # a JSON integer, never coerced (rule 12)
            if type(seconds) is not int or not 1 <= seconds <= HEARTBEAT_S:
                beat = f"in a call a heartbeat wakes you every {HEARTBEAT_S} s anyway"
                why = f"seconds must be an integer 1-{HEARTBEAT_S}: {beat}"
                return refused("invalid_args", why)
            return Result(True, f"waking in {seconds} s")
        if name == "guide_fast":
            return self._guide(bb, a)
        if name == "record_fact":
            return self.fact(bb, str(a["key"]), str(a["value"]), a.get("utt_ref"))
        if name == "record_offer":
            t_ms, wall = host.now(), host.clock.wall()  # one instant
            ref, slots = str(a["offer_ref"]), a["offer_slots"]
            return offer_slots.record_offer(bb, ref, slots, t_ms, wall)
        if name == "share_fact":
            return self._share(bb, str(a["key"]))
        if name == "request_approval":
            self._n += 1
            ref = str(a["offer_ref"])
            return authority.request_approval(bb, ref, case, f"s2f-{self._n}")
        if name == "accept_offer":
            return authority.accept_offer(
                bb, str(a["offer_ref"]), case, host.bus.events
            )
        if name == "decline_offer":
            return authority.decline_offer(bb, str(a["offer_ref"]))
        if name in ("propose_mandate", "tighten_mandate"):
            self._mandates += 1
            mid = f"mandate-{self._mandates}"
            if name == "propose_mandate":
                return authority.propose_mandate(bb, a["envelope"], mid)
            return authority.tighten_mandate(bb, a["changes"], mid)
        if name == "revoke":
            return authority.revoke(bb)
        if name == "check_account":
            told = [r for r in bb.f2s_pending if r.msg_id in self.received]
            conf, line = str(a["confirmation_id"]), a.get("utt_ref")
            cited = str(line) if self._transcript and line else None  # a REP line
            events, seen = host.bus.events, self._basis
            return authority.check_account(bb, conf, told, events, cited, seen)
        if name != "finish":
            return refused("unknown_tool", f"unknown tool {name!r}")
        outcome = str(a.get("outcome"))
        r = authority.finish(bb, outcome, self.asked_final)
        if not r.ok:
            return r
        self.finished = True
        return Result(True, r.text, r.effects, lambda: host.finish(outcome))

    def _share(self, bb: st.Blackboard, key: str) -> Result:
        """``share_fact(key)``: Guard's rule, then the one publication path of
        ``record_fact`` for the recorded private value (never wider, I4)."""
        got = guard.share_fact(bb, key, self._shareable_keys)
        if isinstance(got, Denial):
            return authority.denied("share_fact", got)
        mine = bb.private.case_facts.get(key)
        if mine is None:
            return no(f"{key} is not recorded: record_fact it from the user's message")
        r = self.fact(bb, key, mine.value, mine.source_ref)
        if r.effects[0][1]["scope"] != "public":
            why = r.text.removeprefix("recorded private").lstrip(":, ")
            return no(f"{key} stays private" + (f": {why}" if why else ""))
        return r

    def _guide(self, bb: st.Blackboard, a: Mapping[str, Any]) -> Result:  # I4
        extra = sorted(k for k, v in a.items() if k not in _GUIDE and v not in _EMPTY)
        if extra:  # e.g. free text: refused whole, never dropped (ROOT-05 g)
            denied = {"intent": "guide_fast", "reason": "guide_extra_fields"}
            text = (
                f"guide_fast takes only move and slots, not {', '.join(extra)}: the "
                "phone voice never gets free text; use ask_user/tell_user for the user"
            )
            return no(text, ("action.denied", denied))
        guide = Guide(move=a["move"], slots=tuple(a.get("slots") or ()))
        if lever := lever_denial(bb, guide):
            reason, text = lever
            return no(
                text, ("action.denied", {"intent": "guide_fast", "reason": reason})
            )
        if public_guide(bb, guide):
            sent = self._s2f(lane="cp", type="GUIDE", guide=guide)
            if guide.move == GuideMove.ASK_READBACK:
                return self._asked(bb, guide, sent)
            if guide.move == GuideMove.ASK_FINAL_OFFER:  # the last ask (S1-SYS-57)
                self.asked_final = len(bb.channels["cp"].lines)
            if guide.move != "deflect_fact_request":
                return sent
            text = f"{sent.text}; the rep hears a refusal to share"
            return Result(True, text, sent.effects)  # sent as asked: Slow decides
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
        return no(text, ("action.denied", denied))

    def _asked(self, bb: st.Blackboard, guide: Guide, sent: Result) -> Result:
        """Track the read-back request of each cited offer's current revision:
        only rep lines from here on can confirm its slots (§9.2)."""
        refs = {s[6:].partition(".")[0] for s in guide.slots if s.startswith("offer:")}
        at, tracked = len(bb.channels["cp"].lines), list[str]()
        for ref in sorted(refs):
            if (o := bb.public.offers.get(ref)) is not None:
                self.asked.setdefault((ref, o.revision), at)
                left = frozenset(s.field for s in o.slots if s.status != "confirmed")
                self.readbacks.setdefault((ref, o.revision), []).append((at, left))
                tracked.append(f"{ref} r{o.revision}")
        if tracked:
            return Result(
                True,
                f"{sent.text}; read-back asked for {', '.join(tracked)}",
                sent.effects,
            )
        text = f"{sent.text}; no recorded offer cited: cite offer:<ref> to confirm one"
        return Result(True, text, sent.effects)

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
        mine = key in self._shareable_keys and told
        span = _user_span(key, value, told, bb) if mine else None  # user's words
        hits = [msg_id] if span is not None else []
        leaks = _leaks(key, span, bb) if span is not None else []  # never protected
        shareable = key in self._shareable_keys and hits and not leaks
        in_line = bool(line) and _said(value, line)
        source = "cp_utt" if in_line else "shareable" if shareable else "user"
        ref = str(ref) if source == "cp_utt" else hits[0] if shareable else ref
        ref = None if ref is None else str(ref)  # the rep line or user message
        if source == "shareable" and span is not None:
            value = span  # the user's words, not Slow's string
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
            can = sorted(self._shareable_keys & FORMATS.keys())
            text += (
                f": only {', '.join(can) or 'no key'} can go public from the user, "
                "by citing the utt of the user message that contains exactly the "
                "value (a last4 as 4 digits, a holder name as the user wrote it, "
                "tenure as 'I've been with you for N years'); other keys stay private"
            )
        return Result(True, text, tuple(effects))


def lever_denial(bb: st.Blackboard, guide: Guide) -> tuple[str, str] | None:
    """The lever checks (§7, I11, C14): a competitor is cited only with a quote
    the user shared, and the cancellation lever only with the user's public
    authorisation. ``(reason, text)`` of a denial, else None."""
    facts = bb.public.facts
    if guide.move == GuideMove.CITE_COMPETITOR:  # a name alone is no quote
        keys = [s[5:] for s in guide.slots if s.startswith("fact:")]
        quotes = [k for k in keys if k in ("competitor_quote", "competitor.price_usd")]
        if not any((f := facts.get(k)) and f.source == "shareable" for k in quotes):
            return "competitor_quote_not_shareable", (
                "cite_competitor needs a fact:competitor.price_usd (or "
                "fact:competitor_quote) slot the user shared (source shareable); "
                "none is public, so the lever is denied: no fabricated quotes. "
                "Use another move"
            )
    lever = facts.get("authorization.cancel_lever")
    granted = lever and lever.value == "granted" and lever.source == "shareable"
    if guide.move == GuideMove.CANCEL_LEVER and not granted:
        return "cancel_lever_not_authorized", (
            "cancel_lever needs the public fact authorization.cancel_lever=granted "
            "from the user; it is not, so the lever is denied"
        )
    return None


def _partner(bb: st.Blackboard, lane: Lane) -> dict[str, str]:  # utt id -> text
    lines = bb.channels.get(lane, st.ChannelState()).lines
    return {x.utt_id: x.text for x in lines if x.speaker == "partner"}


def _said(value: str, line: str) -> bool:  # its digits, else its text verbatim
    digits = numbers(value)
    return digits <= numbers(line) if digits else value.casefold() in line.casefold()


def _user_span(key: str, value: str, message: str, bb: st.Blackboard) -> str | None:
    """I4, the user-message path (#133, S1-SYS-15): the span of the raw
    ``message`` to publish under ``key``, or None. Only a key in ``FORMATS``
    can go public, and only in its format; every other key stays private
    (safety over coverage). ASCII only: no NFKC widening."""
    match = FORMATS.get(key)
    return None if match is None else match(value, message, bb)


def _digits4(value: str, message: str, _: st.Blackboard) -> str | None:
    """Exactly four ASCII digits, a standalone token of the message: after the
    start, whitespace or ``:``, or an opener ``( " “`` that itself follows one
    of them; then at most one closer ``) " ”``, at most one of
    ``. , ; : ! ?`` and whitespace or the end (S1-SYS-26: "(ending in 4821),")."""
    if not _LAST4.fullmatch(value):
        return None
    return value if re.search(_BEFORE + value + _AFTER, message) else None


def _name(value: str, message: str, _: st.Blackboard) -> str | None:
    """1-4 ASCII words (``O'Brien``, ``Lee-Smith``), no number word, found
    case-insensitively with word bounds; the user's own spelling is published."""
    if not _NAME.fullmatch(value) or len(value) > MAX_NAME_CHARS:
        return None
    if any(_number_word(w) for w in _words(value).split()):
        return None
    found = re.search(_EDGE[0] + re.escape(value) + _EDGE[1], message, re.IGNORECASE)
    return found.group() if found and _NAME.fullmatch(found.group()) else None


def _years(value: str, message: str, _: st.Blackboard) -> str | None:
    """1-2 ASCII digits in an allow-listed first-person tenure context ("I've
    been with you for 6 years", "I have been a customer 12 years"), in a
    message with no age word and no negation."""
    if not _YEARS.fullmatch(value) or _AGE.search(message):
        return None
    if _NEGATION.search(message):  # "I haven't been with you for 6 years"
        return None
    if _NOT_ASCII.search(message):  # no confusable hides an age word
        return None
    said = {m.group(1) for m in _TENURE.finditer(message)}
    return value if value in said else None


def _number_word(word: str) -> bool:  # "sixty", "sixties", "sixes", "hundreds"
    stems = {word, word.removesuffix("s"), word.removesuffix("es")}
    stems |= {word[:-3] + "y"} if word.endswith("ies") else set()
    return bool(stems & NUMBER_WORDS)


Match = Callable[[str, str, st.Blackboard], str | None]  # (value, message, bb)
FORMATS: dict[str, Match] = {  # the one per-key format table (S1-SYS-15)
    "account.last4": _digits4,
    "account.holder_name": _name,
    "tenure_years": _years,  # competitor facts never (#153 round 3, I11)
}


def _words(text: str) -> str:  # "O'Brien" -> "o brien"
    return " ".join(re.findall(r"[a-z]+", text.casefold()))


def _letters(text: str) -> str:  # "O'Brien" -> "obrien"
    return re.sub(r"[^a-z]", "", text.casefold())


def _digits(text: str) -> str:  # "(555) 482-1999" -> "5554821999"; any script
    text = unicodedata.normalize("NFKC", text)
    return "".join(str(unicodedata.decimal(c)) for c in text if c.isdecimal())


def _leaks(key: str, span: str, bb: st.Blackboard) -> list[str]:
    """The span to publish against every protected case-fact value (word,
    letter and digit forms, either containing the other) and, for a number of
    any format, the mandate bounds in minor units, dollars and months."""
    out, words, digits = list[str](), _words(span), _digits(span)
    letters = _letters(span)
    for name, f in sorted(bb.private.case_facts.items()):
        theirs, their_digits = _words(f.value), _digits(f.value)
        same_words = words and theirs and (words in theirs or theirs in words)
        their_letters = _letters(f.value)  # "Obrien" is "O'Brien"
        same_words = same_words or (
            letters
            and their_letters
            and (letters in their_letters or their_letters in letters)
        )
        same_digits = (
            digits
            and their_digits
            and (digits in their_digits or their_digits in digits)
        )
        if f.protected and (same_words or same_digits):
            out.append(f"the protected value of {name}")
    m = bb.private.mandate
    minor = () if m is None else (m.max_monthly_price_minor, m.max_one_time_fees_minor)
    bounds = {Decimal(v) for v in minor if v is not None}
    bounds |= {Decimal(v) / 100 for v in minor if v is not None}  # dollars
    bounds |= {Decimal(m.max_term_months)} if m and m.max_term_months else set()
    if _NUMBER.fullmatch(span) and Decimal(span) in bounds:  # every format
        out.append(f"{span} is a mandate bound")
    return out


def public_guide(bb: st.Blackboard, guide: Guide) -> bool:  # the renderer judges
    public = bb.public.model_copy(update={"guidance_cp": (guide,)})
    view = view_cp(
        bb.model_copy(update={"public": public}), Trigger(kind="guidance"), ""
    )
    try:
        render_messages(view, CP_PROFILE)
    except GuideSlotError:
        return False
    return True
