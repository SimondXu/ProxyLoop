"""``FsmTalker``: the capable FSM Fast, condition F (EVAL §4.1; ``baseline``).

"Can a script do it?" It reads only what the contract renderer put in front of
a Fast (``render_messages`` of a ``FastView``, I3) and writes through
``format_turn``, so its text is exactly what the contract parser accepts. It
relays every number and key it can parse, asks for the read-back on offers,
holds at decisions, and never claims completion unless CASE STATUS is
``VERIFIED_COMPLETE``. It imports no world module (import-linter).
"""

from __future__ import annotations

import re
import string
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass

from proxyloop.contract.base import Lane, sha256_text
from proxyloop.contract.llm import (
    AdapterKind,
    ChatMessage,
    LLMCallRecord,
    ModelRef,
    TextRequest,
    ToolRequest,
    ToolResponse,
    request_content,
)
from proxyloop.contract.profiles import Profile, SectionKind
from proxyloop.contract.protocol import (
    NONE,
    OMITTED_LINES,
    PROFILES,
    EndCall,
    Hold,
    ParseIssue,
    Relay,
    Speech,
    TurnItem,
    Wait,
    format_turn,
    parse_turn,
)
from proxyloop.models import cues

Clock = Callable[[], int]  # ms on the session clock
RecordSink = Callable[[LLMCallRecord], None]
NOTE_MAX = 200  # below FastToSlow's 240-character text bound

READBACK = (
    "Could you read back every term of that offer: the monthly price, the term, "
    "any fees, any changes and when it expires?"
)
CHECKING = "I need to check with my customer before agreeing to anything."
MOVES: dict[str, str] = {  # GuideMove -> what the FSM says ({} = slot values)
    "open_call": "I'm calling on behalf of my customer about their account.",
    # a fixed tail after the value: a split or cut fragment never matches it
    "identify": "The account details are {}, for verification.",
    "ask_discount": "Is there any way you could lower the monthly price?",
    "cite_competitor": "My customer has a competing quote of {}.",
    "mention_tenure": "My customer has been with you for {}.",
    "cancel_lever": "My customer is prepared to cancel without a better offer.",
    "ask_readback": READBACK,
    "hold_for_decision": "I need to check with my customer before we go further.",
    "decline_offer": "Thank you, but my customer will have to decline that offer.",
    "ask_final_offer": "Is this your best and final offer?",
    "deflect_fact_request": "I'm sorry, I can't share that detail.",
    "close_call": "Thank you for your help today. Goodbye.",
    "hold_for_fact": "I'm getting that detail from my customer; please hold a moment.",
}
NOTED = "I've noted that; I need to check before agreeing to anything."
# A sentence that reads as work finished; unspoken unless VERIFIED_COMPLETE (I6).
_COMPLETE = re.compile(
    r"\b(?:complete[ds]?|done|finished|all set|accepted|switched|changed"
    r"|cancell?ed|locked in|confirmed|processed|applied|set up|activated"
    r"|upgraded|downgraded|updated|renewed|signed (?:you )?up)\b",
    re.I,
)
_STATUS_Q = re.compile(r"\b(?:done|finished|complete|status|progress|accepted)\b", re.I)
_APPROVE = re.compile(r"\b(?:approve|accept|go ahead|yes,? do it|take it)\b", re.I)


@dataclass(frozen=True)
class Offer:
    ref: str
    status: str
    slots: tuple[tuple[str, str, str], ...]  # (field, value as rendered, status)


@dataclass(frozen=True)
class Seen:
    """The fields of a rendered ``FastView`` the FSM acts on."""

    lane: Lane
    trigger: str  # the TriggerKind
    args: dict[str, str]  # the trigger template's fields (text, readback_text, n)
    status: str
    hold: str | None
    offers: tuple[Offer, ...]
    guides: tuple[tuple[str, tuple[str, ...]], ...]  # (GuideMove, slot values)
    lines: tuple[tuple[str, str], ...]  # (partner | agent, text)

    def last(self, speaker: str) -> str:
        return next((t for s, t in reversed(self.lines) if s == speaker), "")


def _sections(content: str, profile: Profile) -> dict[SectionKind, str]:
    tail = f"\n\n{profile.closing}"
    if not content.endswith(tail):
        raise ValueError("not a rendered Fast view")
    content, marks = content[: -len(tail)], list[tuple[int, int, SectionKind]]()
    for n, (header, kind) in enumerate(profile.sections):
        mark = f"{header}:" if n == 0 else f"\n\n{header}:"
        at = content.find(mark, marks[-1][1] if marks else 0)
        if at < 0 or (n == 0 and at != 0):
            raise ValueError(f"no {header} section")
        marks.append((at, at + len(mark), kind))
    ends = [at for at, _, _ in marks[1:]] + [len(content)]
    return {
        kind: content[b:e].lstrip(" \n")
        for (_, b, kind), e in zip(marks, ends, strict=True)
    }


def _trigger(text: str, profile: Profile) -> tuple[str, dict[str, str]]:
    for kind, template in profile.triggers.items():
        pattern = "".join(
            re.escape(lit) + (f"(?P<{name}>.*)" if name else "")
            for lit, name, _, _ in string.Formatter().parse(template)
        )
        if found := re.fullmatch(pattern, text, re.S):
            return kind, found.groupdict()
    raise ValueError(f"unknown trigger {text!r}")


def _rows(block: str) -> list[str]:
    return [] if block == NONE else block.split("\n")


def _offers(block: str) -> tuple[Offer, ...]:
    out: list[Offer] = []
    for row in _rows(block):
        head = re.fullmatch(r"- (\S+) \(revision \d+, (\w+)\): (.*)", row)
        if head is None:
            continue
        slots = re.findall(
            r"(\S+) (.+?) \[(unknown|heard|confirmed)\](?:; |$)", head[3]
        )
        out.append(Offer(head[1], head[2], tuple(slots)))
    return tuple(out)


def _guides(
    block: str, moves: Sequence[tuple[str, str]]
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    out: list[tuple[str, tuple[str, ...]]] = []
    for row in _rows(block):
        for move, text in moves:
            if row.startswith(f"- {text}"):
                rest = row[len(text) + 2 :].strip()
                inner = rest[1:-1] if rest.startswith("(") else ""
                values = re.split(r"(?:^|; )(?:fact|offer):\S+ = ", inner)[1:]
                out.append((move, tuple(values)))
                break
    return tuple(out)


def read_view(messages: Sequence[ChatMessage]) -> Seen:
    """Invert the contract rendering of a ``FastView`` into ``Seen``."""

    if len(messages) != 2 or messages[0].role != "system":
        raise ValueError("the FSM takes render_messages output: system + user")
    system, user = messages[0].content, messages[1].content
    # Profiles may share a system text (pl_cp_v1, pl_cp_v2; ADR-0011): they must
    # agree on the layout, and guides parse against all their move texts.
    matches = [p for p in PROFILES.values() if p.system == system]
    if not matches:
        raise ValueError("the system message is not a contract Fast profile")
    layouts = {
        (p.lane, p.sections, p.labels, tuple(p.triggers.items()), p.closing)
        for p in matches
    }
    if len(layouts) != 1:
        raise ValueError("profiles sharing this system text disagree on the layout")
    profile = matches[0]
    moves = tuple(dict.fromkeys(pair for p in matches for pair in p.moves.items()))
    part = _sections(user, profile)
    trigger, args = _trigger(part["trigger"], profile)
    lines: list[tuple[str, str]] = []
    for row in _rows(part["transcript"]):
        label, sep, text = row.partition(": ")
        if sep and row != OMITTED_LINES and label in profile.labels:
            lines.append(("partner" if label == profile.labels[0] else "agent", text))
    hold = re.fullmatch(r"on hold \((\w+)\)", part.get("hold", NONE))
    return Seen(
        lane=profile.lane,
        trigger=trigger,
        args=args,
        status=part["status"],
        hold=hold[1] if hold else None,
        offers=_offers(part["offers"]),
        guides=_guides(part.get("guidance", NONE), moves),
        lines=tuple(lines),
    )


def _say(lane: Lane, *texts: str) -> list[TurnItem]:
    """Canonical sentences only: anything the parser would not re-read as the
    same sentence is dropped (the FSM's own text; never a model's)."""

    out: list[TurnItem] = []
    for text in texts:
        flat = re.sub(r"\s+", " ", text.replace("@", "")).strip()
        for sentence in re.split(r"(?<=[.!?])\s+", flat):
            if sentence and parse_turn(sentence, lane) == (Speech(text=sentence),):
                out.append(Speech(text=sentence))
    return out


def _note(who: str, text: str) -> Relay:
    flat = re.sub(r"\s+", " ", text.replace("@", "")).strip()
    return Relay(type="note", text=f"{who} said: {flat}"[:NOTE_MAX].rstrip())


def _relay(who: str, heard: str) -> list[TurnItem]:
    pairs = cues.facts(heard)
    if pairs:
        return [Relay(type="fact", facts=pairs)]
    return [_note(who, heard)] if heard.strip() else []


def _guide(lane: Lane, move: str, values: tuple[str, ...]) -> list[TurnItem]:
    text = MOVES[move]
    if "{}" in text and not values:
        return []  # a slot move without slot values: nothing to say, skipped
    items = _say(lane, text.format(", ".join(values)))
    if move == "hold_for_decision":
        items.append(Hold(reason="decision"))
    if move == "hold_for_fact":
        items.append(Hold(reason="fact_request"))
    if move == "close_call":
        items.append(EndCall())
    return items


def _unvoiced(v: Seen) -> tuple[str, tuple[str, ...]] | None:
    """The newest guide, if the agent has not said its words yet. Older guides
    are history, not guidance (ADR-0013 A): never read."""

    said = {t for s, t in v.lines if s == "agent"}
    for move, values in v.guides[-1:]:
        texts = [i.text for i in _guide("cp", move, values) if isinstance(i, Speech)]
        if texts and not any(t in said for t in texts):
            return move, values
    return None


def _identity(v: Seen) -> tuple[str, ...]:
    """The identity values the FSM may say: the newest guide if it is
    ``identify``, else its own newest identify line in the transcript, parsed
    back through the template and kept only if ``_guide`` re-says it exactly.
    The template's fixed tail means a fragment of a split line ("... Dana J.")
    never matches: no partial identity, the FSM deflects. Partner lines and
    older guides are never a source."""

    if v.guides and v.guides[-1][0] == "identify" and v.guides[-1][1]:
        return v.guides[-1][1]
    head, tail = MOVES["identify"].split("{}")
    for speaker, text in reversed(v.lines):
        if speaker != "agent" or not (text.startswith(head) and text.endswith(tail)):
            continue
        values = tuple(text[len(head) : len(text) - len(tail)].split(", "))
        said = [
            i.text for i in _guide("cp", "identify", values) if isinstance(i, Speech)
        ]
        if said == [text]:
            return values
    return ()


def _cp(v: Seen) -> list[TurnItem]:
    if v.trigger == "hold_wait":
        if v.hold is None:
            return [Wait()]
        still = "Thank you for waiting; I'm still checking with my customer."
        return [*_say("cp", still), _hold(v.hold)]
    if v.trigger in ("guidance", "call_connected"):
        if v.guides:
            return _guide("cp", *v.guides[-1])
        return (
            _say("cp", MOVES["open_call"])
            if v.trigger == "call_connected"
            else [Wait()]
        )
    rep = v.last("partner")
    relay = _relay("rep", rep)
    identify = _identity(v)
    confirmed = any(
        o.status == "open" and o.slots and all(s[2] == "confirmed" for s in o.slots)
        for o in v.offers
    )
    if cues.PROTECTED.search(rep) or (cues.IDENTITY.search(rep) and not identify):
        return [
            *_say("cp", MOVES["deflect_fact_request"]),
            *relay,
            _hold("fact_request"),
        ]
    if cues.IDENTITY.search(rep):
        return [*_guide("cp", "identify", identify), *relay]
    if cues.ACCEPT.search(rep) or cues.PRESSURE.search(rep):
        why = "pressure" if cues.PRESSURE.search(rep) else "decision"
        return [*_say("cp", CHECKING), *relay, _hold(why)]
    if cues.offer(rep):
        if confirmed or v.last("agent") == READBACK:
            noted = "Thank you, I've noted every term."
            return [*_say("cp", noted, CHECKING), *relay, _hold("offer")]
        return [*_say("cp", READBACK), *relay, _hold("offer")]
    question = rep.rstrip().endswith("?")
    if question and any(o.status == "open" for o in v.offers):
        return [*_say("cp", CHECKING), *relay, _hold("decision")]
    if (guide := _unvoiced(v)) is not None:
        return [*_guide("cp", *guide), *relay]
    if v.hold is not None:
        still = "I'm still checking with my customer."
        return [*_say("cp", still), *relay, _hold(v.hold)]
    if question:
        return [*_say("cp", "Let me check that with my customer."), *relay]
    return [*_say("cp", NOTED), *relay]


def _hold(reason: str) -> Hold:
    return Hold.model_validate({"reason": reason})


def _status(status: str) -> str:
    if status == "VERIFIED_COMPLETE":
        return "Your case is verified complete."
    if status == "VERIFIED_NO_DEAL":
        return "The case is closed without a deal."
    return "The case is still in progress, and nothing is complete yet."


def _term(field: str, value: str) -> str:
    named = {"monthly_price": "monthly price", "term_months": "term"}
    named |= {"fees_none": "no fees:", "changes_none": "no other changes:"}
    kind, _, name = field.partition(":")  # fee:activation -> activation fee
    label = named.get(field) or f"{name} {kind}".strip().replace("_", " ")
    return f"{label} {value}"


def _offer_text(offer: Offer) -> str:
    terms = ", ".join(_term(field, value) for field, value, _ in offer.slots)
    return f"Offer {offer.ref} is {offer.status}: {terms or 'no terms yet'}."


def _user(v: Seen) -> list[TurnItem]:
    verified = v.status == "VERIFIED_COMPLETE"
    if v.trigger == "session_start":
        return _say("user", "Hi, I'm your assistant; I'll keep you updated here.")
    if v.trigger == "slow_msg":
        text = v.args.get("text", "")
        if not verified and _COMPLETE.search(text):  # the whole message implies it
            return _say("user", _status(v.status))
        return _say("user", text)
    if v.trigger == "approval_card":
        card = v.args.get("readback_text", "")
        mine = "Please review it in the app; I can't approve anything for you."
        return _say("user", f"An approval card is waiting for you: {card}.", mine)
    msg = v.last("partner")
    pairs = cues.facts(msg)
    if cues.STOP.search(msg):
        flat = re.sub(r"\s+", " ", msg.replace("@", "")).strip()[:NOTE_MAX]
        said = _say("user", "Understood, I've asked the case agent to stop.")
        return [*said, Relay(type="revoke", text=flat)]
    if cues.CORRECTION.search(msg) and pairs:
        said = _say("user", "Thanks for the correction; I've passed it on.")
        rest = [Relay(type="fact", facts=pairs[1:])] if pairs[1:] else []
        return [*said, Relay(type="correction", facts=pairs[:1]), *rest]
    if _APPROVE.search(msg):
        mine = "I can't approve anything myself; please use the approval card."
        return [*_say("user", mine), *_relay("user", msg)]
    if pairs:
        return [*_say("user", "Thanks, I've passed that on."), *_relay("user", msg)]
    if msg.rstrip().endswith("?"):
        if cues.OFFER.search(msg) and v.offers:
            texts = [_offer_text(o) for o in v.offers]
            return _say("user", *texts, _status(v.status))
        if _STATUS_Q.search(msg):
            return _say("user", _status(v.status))
        flat = re.sub(r"\s+", " ", msg.replace("@", "")).strip()[:NOTE_MAX]
        said = _say("user", "Let me check on that for you.")
        return [*said, Relay(type="request", text=flat)]
    return [*_say("user", "Got it, I've passed that on."), *_relay("user", msg)]


def respond(seen: Seen) -> str:
    """The FSM's turn for one rendered view, as canonical Fast text."""

    items = (_cp(seen) if seen.lane == "cp" else _user(seen)) or [Wait()]
    text = format_turn(tuple(items))
    issues = [i for i in parse_turn(text, seen.lane) if isinstance(i, ParseIssue)]
    if issues:  # the FSM's own templates: a bug, never hidden
        raise AssertionError(f"the FSM wrote unparseable text: {issues}")
    return text


class FsmTalker:
    """``LLMClient`` of kind ``baseline``: in process, deterministic, no endpoint."""

    def __init__(self, ref: ModelRef, clock: Clock, on_record: RecordSink) -> None:
        if ref.kind is not AdapterKind.BASELINE:
            raise ValueError(f"the FSM is a baseline adapter, not {ref.kind}")
        self._ref, self._clock, self._on_record = ref, clock, on_record

    @property
    def ref(self) -> ModelRef:
        return self._ref

    async def stream_text(
        self, request: TextRequest
    ) -> AsyncIterator[str | LLMCallRecord]:
        start = self._clock()
        text = respond(read_view(request.messages))
        end = self._clock()
        record = LLMCallRecord(
            call_id=request.call_id,
            role=request.role,
            model_ref=self._ref,
            adapter_kind=self._ref.kind,
            requested_model=self._ref.model_id,
            served_model_echo=None,
            request_id=None,
            prompt_sha=sha256_text(request_content(request)),
            response_sha=sha256_text(text),
            usage=None,
            t_start=start,
            t_first_token=end if text else None,
            t_end=end,
            finish_reason="stop",
            attempt=0,
        )
        self._on_record(record)
        if text:
            yield text
        yield record

    async def chat_tools(self, request: ToolRequest) -> ToolResponse:
        raise TypeError("the FSM talker serves text only")
