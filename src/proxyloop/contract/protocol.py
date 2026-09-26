"""The one Fast renderer and the Fast grammar (ARCHITECTURE §6, §12; I3).

Every Fast prompt (teacher, training, evaluation, serving) comes from
``render_messages`` / ``render_prompt``. The parser is tolerant on input
(TalkAct's inline ``@slow:`` and scaffolding echoes) and canonical on output;
``parse_turn(format_turn(t)) == t`` and streaming parse == batch parse (P4).
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Any, Literal, Protocol

from pydantic import Field

from proxyloop.contract.base import (
    FACT_KEY,
    HOLD_REASONS,
    Frozen,
    HoldReason,
    Lane,
    canonical_json,
    sha256_text,
)
from proxyloop.contract.llm import ChatMessage
from proxyloop.contract.messages import Guide
from proxyloop.contract.profiles import Profile, SectionKind, pl_cp_v1, pl_user_v1
from proxyloop.contract.state import OfferPublic, ReadbackSlot
from proxyloop.contract.views import FastView

CONTEXT_BUDGET_CHARS = 12_000  # system + user text; P2 records the worst token count
EMPTY_THINK = "<think>\n\n</think>\n\n"  # the enable_thinking=False generation tail
NONE = "(none)"
OMITTED_LINES = "(earlier conversation omitted)"
OMITTED_ACTIONS = "- (earlier actions omitted)"

PROFILES: Mapping[str, Profile] = MappingProxyType(
    {p.name: p for p in (pl_user_v1.PROFILE, pl_cp_v1.PROFILE)}
)
_BLOCKS: frozenset[SectionKind] = frozenset(
    {"actions", "offers", "guidance", "transcript"}
)


class GuideSlotError(ValueError):
    """A guide slot does not resolve in public state (rejected at render time)."""


class ContextBudgetError(ValueError):
    """The prompt exceeds the budget with no transcript and no action log: a bug."""


class ChatTokenizer(Protocol):
    """Duck-typed HF tokenizer: the contract never imports transformers."""

    def apply_chat_template(
        self, conversation: list[dict[str, str]], /, **kwargs: Any
    ) -> Any: ...


# ---------------------------------------------------------------- rendering


def _value(slot: ReadbackSlot) -> str:
    if slot.unit == "usd_minor" and slot.value.isdigit():
        minor = int(slot.value)
        return f"${minor // 100}.{minor % 100:02d}"
    if slot.unit == "months":
        return f"{slot.value} months"
    return slot.value


def _offer(offer: OfferPublic) -> str:
    slots = "; ".join(f"{s.field} {_value(s)} [{s.status}]" for s in offer.slots)
    return f"- {offer.offer_ref} (revision {offer.revision}, {offer.status}): " + (
        slots or NONE
    )


def _resolve(slot: str, view: FastView) -> str:
    kind, _, rest = slot.partition(":")
    if kind == "fact":
        for fact in view.public_facts:
            if fact.key == rest:
                return fact.value
    else:
        ref, _, field = rest.partition(".")
        offer = next((o for o in view.offers if o.offer_ref == ref), None)
        if offer is not None and not field:
            return f"offer {ref}"
        for s in offer.slots if offer is not None else ():
            if s.field == field:
                return _value(s)
    raise GuideSlotError(f"guide slot {slot!r} does not resolve in public state")


def _guide(guide: Guide, view: FastView, profile: Profile) -> str:
    text = profile.moves[guide.move]
    if guide.slots:
        resolved = "; ".join(f"{s} = {_resolve(s, view)}" for s in guide.slots)
        text = f"{text} ({resolved})"
    return f"- {text}"


def _trigger(view: FastView, profile: Profile) -> str:
    trigger, template = view.trigger, profile.triggers[view.trigger.kind]
    if view.slow_msg is not None:
        return template.format(kind=view.slow_msg.type.lower(), text=view.slow_msg.text)
    if trigger.kind == "approval_card" and view.pending_approval is not None:
        return template.format(readback_text=view.pending_approval.readback_text)
    if trigger.kind == "hold_wait":
        return template.format(n=trigger.wait_s)
    return template


def _block(
    kind: SectionKind, view: FastView, profile: Profile, n_lines: int, n_actions: int
) -> str:
    if kind == "actions":
        rows = [f"- {a}" for a in view.action_log[len(view.action_log) - n_actions :]]
        if n_actions < len(view.action_log):
            rows.insert(0, OMITTED_ACTIONS)
    elif kind == "offers":
        rows = [_offer(o) for o in view.offers]
    elif kind == "guidance":
        rows = [_guide(g, view, profile) for g in view.guidance]
    else:
        labels = {"partner": profile.labels[0], "agent": profile.labels[1]}
        kept = view.transcript[len(view.transcript) - n_lines :]
        rows = [f"{labels[line.speaker]}: {line.text}" for line in kept]
        if n_lines < len(view.transcript):
            rows.insert(0, OMITTED_LINES)
    return "\n".join(rows) or NONE


def _inline(kind: SectionKind, view: FastView, profile: Profile) -> str:
    if kind == "trigger":
        return _trigger(view, profile)
    if kind == "status":
        return view.status.value
    if kind == "hold":
        return f"on hold ({view.hold.reason})" if view.hold is not None else NONE
    card = view.pending_approval
    text = {
        "brief": view.brief,
        "private_summary": view.private_summary,
        "public_summary": view.public_summary,
        "approval": card.readback_text if card is not None else None,
    }[kind]
    return text or NONE


def _content(view: FastView, profile: Profile, n_lines: int, n_actions: int) -> str:
    parts = [
        f"{header}:\n{_block(kind, view, profile, n_lines, n_actions)}"
        if kind in _BLOCKS
        else f"{header}: {_inline(kind, view, profile)}"
        for header, kind in profile.sections
    ]
    return "\n\n".join([*parts, profile.closing])


def render_messages(view: FastView, profile: str) -> tuple[ChatMessage, ChatMessage]:
    """System + user messages under the shared context budget (C17).

    Over budget, the oldest transcript lines go first, then the oldest actions;
    summaries, offers, guidance and the trigger are never dropped.
    """

    spec = PROFILES[profile]
    if spec.lane != view.lane:
        raise ValueError(f"profile {profile} renders the {spec.lane} lane")
    room = CONTEXT_BUDGET_CHARS - len(spec.system)
    n_lines, n_actions = len(view.transcript), len(view.action_log)
    content = _content(view, spec, n_lines, n_actions)
    while len(content) > room and n_lines > 0:
        n_lines -= 1
        content = _content(view, spec, n_lines, n_actions)
    while len(content) > room and n_actions > 0:
        n_actions -= 1
        content = _content(view, spec, n_lines, n_actions)
    if len(content) > room:
        raise ContextBudgetError(f"{len(content)} chars > {room} after trimming")
    return (
        ChatMessage(role="system", content=spec.system),
        ChatMessage(role="user", content=content),
    )


def render_prompt(view: FastView, profile: str, tok: ChatTokenizer) -> str:
    """The pre-rendered completion prompt, thinking off (P2/P3)."""

    messages = [
        {"role": m.role, "content": m.content} for m in render_messages(view, profile)
    ]
    text = tok.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
    )
    if not isinstance(text, str) or not text.endswith(EMPTY_THINK):
        raise ValueError(f"the chat template did not end with {EMPTY_THINK!r}")
    return text


def fingerprint(profile: str) -> str:
    """sha256 of the profile text plus its committed P2 golden ids (§12)."""

    spec = PROFILES[profile]
    if not spec.p2_ids_sha256:
        raise ValueError(f"profile {profile} has no recorded P2 ids")
    body = dataclasses.asdict(spec)
    body["budget"] = CONTEXT_BUDGET_CHARS
    body["empty_think"] = EMPTY_THINK
    return sha256_text(canonical_json(body))


# ---------------------------------------------------------------- grammar


class Speech(Frozen):
    kind: Literal["speech"] = "speech"
    text: str  # one sentence


RelayType = Literal["note", "fact", "correction", "request", "revoke"]


class Relay(Frozen):
    kind: Literal["relay"] = "relay"
    type: RelayType
    text: str = ""  # note, request, revoke
    facts: tuple[tuple[str, str], ...] = ()  # fact, correction


class Hold(Frozen):
    kind: Literal["hold"] = "hold"
    reason: HoldReason


class Wait(Frozen):
    kind: Literal["wait"] = "wait"


class EndCall(Frozen):
    kind: Literal["end_call"] = "end_call"


IssueReason = Literal[
    "wrong_lane",
    "unknown_directive",
    "bad_hold_reason",
    "duplicate_pause",
    "malformed_fact",
    "empty_turn",
]


class ParseIssue(Frozen):
    """Counted, never hidden (``directive_error``)."""

    kind: Literal["issue"] = "issue"
    reason: IssueReason
    text: str = ""


TurnItem = Annotated[
    Speech | Relay | Hold | Wait | EndCall | ParseIssue, Field(discriminator="kind")
]

# TalkAct's tolerant rules (fast_agent.py:168-191), applied line by line.
_SLOW = re.compile(r"@slow:\s*", re.IGNORECASE)
_LEAD = re.compile(r"^(?:FIRST|THEN)\s*:\s*", re.IGNORECASE)
_TRAIL_END = re.compile(r"@end_call\s*$", re.IGNORECASE)
_TRAIL_SCAFFOLD = re.compile(r"\b(?:THEN|FIRST)\s*:\s*$", re.IGNORECASE)
_BREAK = re.compile(r"(?<=[.!?])\s+")
_KEY = re.compile(rf"^{FACT_KEY}$")
_USER_ONLY = ("correction", "request", "revoke")


def _sentences(spoken: str) -> list[str]:
    text = _LEAD.sub("", spoken.strip()).strip()
    text = _TRAIL_END.sub("", text).strip()
    text = _TRAIL_SCAFFOLD.sub("", text).strip()
    return [s for s in _BREAK.split(text) if s]


def _pairs(text: str) -> tuple[tuple[str, str], ...] | None:
    pairs: list[tuple[str, str]] = []
    for piece in text.split(";"):
        key, sep, value = piece.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not _KEY.match(key) or not value:
            return None
        pairs.append((key, value))
    return tuple(pairs)


class StreamParser:
    """Feed model text as it streams; sentences come out as soon as they close."""

    def __init__(self, lane: Lane) -> None:
        self._lane = lane
        self._buf = ""
        self._emitted = 0  # sentences of the current line already returned
        self._paused = False  # one @hold / @wait per turn
        self._any = False
        self._closed = False

    def feed(self, chunk: str) -> list[TurnItem]:
        if self._closed:
            raise ValueError("the parser is closed")
        *lines, self._buf = (self._buf + chunk).split("\n")
        items: list[TurnItem] = []
        for line in lines:
            items += self._line(line, final=True)
        items += self._line(self._buf, final=False)
        return self._seen(items)

    def close(self) -> list[TurnItem]:
        items = self._seen(self._line(self._buf, final=True))
        self._buf, self._closed = "", True
        if not self._any:
            items.append(ParseIssue(reason="empty_turn"))
        return items

    def _seen(self, items: list[TurnItem]) -> list[TurnItem]:
        self._any = self._any or any(not isinstance(i, ParseIssue) for i in items)
        return items

    def _line(self, raw: str, final: bool) -> list[TurnItem]:
        text = raw.strip()
        if text.startswith("@") and not _SLOW.match(text):
            return self._directive(text) if final else []
        parts = _SLOW.split(text)
        sentences = _sentences(parts[0])
        if not final:  # the last sentence may still grow
            ready = sentences[self._emitted : -1]
            self._emitted += len(ready)
            return [Speech(text=s) for s in ready]
        items: list[TurnItem] = [Speech(text=s) for s in sentences[self._emitted :]]
        self._emitted = 0
        for segment in parts[1:]:
            items += self._relay(segment.strip())
        return items

    def _directive(self, text: str) -> list[TurnItem]:
        if text.lower().startswith("@end_call"):
            return [EndCall()]
        words = text.split()
        if words[0] == "@hold":
            if self._lane != "cp":
                return [ParseIssue(reason="wrong_lane", text=text)]
            reason = words[1] if len(words) == 2 else ""
            for known in HOLD_REASONS:
                if reason == known:
                    return self._pause(Hold(reason=known), text)
            return [ParseIssue(reason="bad_hold_reason", text=text)]
        if text == "@wait":
            return self._pause(Wait(), text)
        return [ParseIssue(reason="unknown_directive", text=text)]

    def _pause(self, item: Hold | Wait, text: str) -> list[TurnItem]:
        if self._paused:
            return [ParseIssue(reason="duplicate_pause", text=text)]
        self._paused = True
        return [item]

    def _relay(self, segment: str) -> list[TurnItem]:
        if not segment:
            return []
        head, _, rest = segment.partition(" ")
        rest = rest.strip()
        if head in _USER_ONLY and self._lane != "user":
            return [ParseIssue(reason="wrong_lane", text=segment)]
        if head == "fact" or head == "correction":
            pairs = _pairs(rest)
            if pairs is None or (head == "correction" and len(pairs) != 1):
                return [
                    Relay(type="note", text=segment),
                    ParseIssue(reason="malformed_fact", text=segment),
                ]
            return [Relay(type=head, facts=pairs)]
        if (head == "request" or head == "revoke") and rest:
            return [Relay(type=head, text=rest)]
        return [Relay(type="note", text=segment)]


def parse_turn(text: str, lane: Lane) -> tuple[TurnItem, ...]:
    parser = StreamParser(lane)
    return (*parser.feed(text), *parser.close())


def _relay_text(relay: Relay) -> str:
    if relay.type == "note":
        return relay.text
    if relay.type in ("fact", "correction"):
        return f"{relay.type} " + "; ".join(f"{k}={v}" for k, v in relay.facts)
    return f"{relay.type} {relay.text}"


def format_turn(items: tuple[TurnItem, ...]) -> str:
    """Canonical text: speech on one line, then ``@slow:`` lines, pause, end."""

    speech = " ".join(i.text for i in items if isinstance(i, Speech))
    lines = [speech] if speech else []
    for item in items:
        if isinstance(item, Relay):
            lines.append(f"@slow: {_relay_text(item)}")
        elif isinstance(item, Hold):
            lines.append(f"@hold {item.reason}")
        elif isinstance(item, Wait):
            lines.append("@wait")
        elif isinstance(item, EndCall):
            lines.append("@end_call")
        elif isinstance(item, ParseIssue):
            raise ValueError("a parse issue has no canonical text")
    return "\n".join(lines)
