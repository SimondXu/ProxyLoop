"""The status bar's ``close:`` and ``levers:`` lines and the read-back ask count
(ADR-0018 V3-V5, S1-SYS-46). Read-only views of the board and of Slow's own asks:
each calls Guard's own predicates (``verify_no_deal``, ``has_cue``, the status
machine) and the lever check ``_guide`` runs, never a partial copy (the #166
``approval_hint`` pattern). Rep text reaches the close line only through Guard's
closing-cue list, and only as an utt id."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from proxyloop.contract.messages import Guide, GuideMove
from proxyloop.contract.state import Blackboard, ChannelState, Line, OfferPublic
from proxyloop.guard.readback import has_cue, slot_statuses
from proxyloop.guard.status import status_change
from proxyloop.guard.verify import verify_no_deal
from proxyloop.slow.tools import SlowTools, lever_denial, public_guide

Kind = Literal["info_only", "full"]  # the task's ``mode`` (task data)
STOP_AFTER = 2  # read-back replies omitting the same slots (V4, D2)
LEVERS = (GuideMove.CITE_COMPETITOR, GuideMove.MENTION_TENURE, GuideMove.CANCEL_LEVER)
TENURE = "tenure_years"  # the one lever fact a user can make public (FORMATS)
WHY = {  # one clause per refusal class (V5)
    "competitor_quote_not_shareable": "no competitor quote the user shared is public",
    "cancel_lever_not_authorized": "cancelling cannot be authorised in this build",
    "guide_slot_not_public": f"{TENURE} is private; the move works without it",
}


@dataclass(frozen=True, slots=True)
class Close:
    """V3: where the close stands, and whether ``finish`` would pass now."""

    kind: Kind
    asked: bool  # guide_fast(ask_final_offer) went out
    reply: str | None  # the utt id of the rep's closing reply, by Guard's cues
    reasons: tuple[str, ...]  # why the kind's finish is refused; () it passes
    told: bool  # a tell_user went out after the closing reply

    @property
    def outcome(self) -> str:
        return "info_only" if self.kind == "info_only" else "no_deal"

    def line(self) -> str:
        asked = "final offer asked" if self.asked else "final offer not asked"
        said = f"the rep's closing reply {self.reply}" if self.reply else ""
        if not self.reasons:
            can = "allowed" if self.kind == "info_only" else "would verify"
        else:
            can = f"blocked: {', '.join(self.reasons)}"
        said = said or "no closing reply"
        if self.asked and self.reply and not self.told:  # user.told_terms
            said += "; tell_user the terms and the outcome before finish"
        return f"close: {asked}; {said}; finish({self.outcome}) {can}"


def close(
    bb: Blackboard, kind: Kind, asked_final: int | None, told_at: int | None = None
) -> Close:
    """The rep's last line since the last ask_final_offer is a closing reply
    iff Guard's cue list says so (none before an ask: verify_no_deal's
    window, M1); the user counts as told once
    a tell_user went out after it (``told_at``: the cp length then). ``full``
    dry-runs ``authority.finish(no_deal)``: its status check, then
    ``verify_no_deal`` with the same ``asked_final``."""
    lines = bb.channels.get("cp", ChannelState()).lines
    since = () if asked_final is None else range(asked_final, len(lines))
    rep = [n for n in since if lines[n].speaker == "partner"]
    last = lines[rep[-1]] if rep else None
    reply = last.utt_id if last and has_cue(last.text, "closing") else None
    told = reply is not None and told_at is not None and told_at > rep[-1]
    trigger = "info_only" if kind == "info_only" else "no_deal_verified"
    if status_change(bb, trigger) is None:
        reasons: tuple[str, ...] = (f"case_is:{bb.public.status.value}",)
    elif kind == "info_only":
        reasons = ()
    else:
        reasons = verify_no_deal(bb, asked_final).reasons
    return Close(kind, asked_final is not None, reply, reasons, told)


def unavailable(bb: Blackboard) -> tuple[tuple[str, str], ...]:
    """V5: (lever move, refusal class) for each lever ``guide_fast`` would
    refuse now: ``lever_denial`` over each public fact as its slot, and
    ``mention_tenure`` citing a tenure the user gave that stays private."""
    out: list[tuple[str, str]] = []
    slots = [(f"fact:{k}",) for k in sorted(bb.public.facts)] or [()]
    for move in LEVERS:
        denials = [lever_denial(bb, Guide(move=move, slots=s)) for s in slots]
        if all(denials) and (first := denials[0]) is not None:
            out.append((move.value, first[0]))
    tenure = Guide(move=GuideMove.MENTION_TENURE, slots=(f"fact:{TENURE}",))
    if TENURE in bb.private.case_facts and not public_guide(bb, tenure):
        out.append((tenure.move.value, "guide_slot_not_public"))
    return tuple(out)


def levers_line(levers: Sequence[tuple[str, str]]) -> str:
    def what(move: str, code: str) -> str:  # n6: only the slot is unavailable
        slot = f" with fact:{TENURE}" if code == "guide_slot_not_public" else ""
        return f"{move}{slot} unavailable ({code}: {WHY.get(code, code)})"

    said = "; ".join(what(m, c) for m, c in levers)
    return f"levers: {said or 'all available'}"


def unconfirmed(o: OfferPublic) -> frozenset[str]:
    return frozenset(s.field for s in o.slots if s.status != "confirmed")


def restated(o: OfferPublic, line: Line) -> frozenset[str]:
    """The slots of ``o`` a rep line states with their recorded values:
    Guard's read-back predicate on that line alone, as if asked before it."""
    got = slot_statuses(o, (line,), 0)
    return frozenset(f for f, status in got.items() if status == "confirmed")


@dataclass(frozen=True, slots=True)
class Readback:
    """V4 (amended, D2) for one offer revision."""

    asked: int  # read-back asks
    stuck: tuple[str, ...]  # unconfirmed slots two read-back replies omitted
    unread: bool  # the rep spoke after the last ask but read nothing back


def readback(o: OfferPublic, asks: Sequence[int], lines: Sequence[Line]) -> Readback:
    """Each ask's window runs to the next ask; a read-back reply is a rep line
    in it that restates at least one slot. A slot is stuck once the replies
    of two windows restated others but not it; ``unread``: the last window
    has rep lines but no read-back reply."""
    left, omitted, replied = unconfirmed(o), Counter[str](), False
    for at, end in zip(asks, [*asks[1:], len(lines)], strict=True):
        said = [restated(o, x) for x in lines[at:end] if x.speaker == "partner"]
        replies = [s for s in said if s]
        omitted.update(left - frozenset().union(*replies) if replies else ())
        replied = bool(replies)
    if o.status != "open" or not left or not asks:
        return Readback(len(asks), (), False)
    stuck = tuple(sorted(f for f in left if omitted[f] >= STOP_AFTER))
    spoke = any(x.speaker == "partner" for x in lines[asks[-1] :])
    return Readback(len(asks), stuck, spoke and not replied and not stuck)


@dataclass(frozen=True, slots=True)
class Bar:
    """What the status bar adds beyond the view (ADR-0018 F-a: close, levers,
    and each offer revision's read-back count)."""

    close: Close
    levers: tuple[tuple[str, str], ...]
    readbacks: Mapping[tuple[str, int], Readback]

    def offer_note(self, o: OfferPublic) -> str:
        r = self.readbacks.get((o.offer_ref, o.revision))
        if r is None or not r.asked:
            return ""
        asked, left = r.asked, r.stuck
        said = f"read-back asked {asked}×"  # noqa: RUF001
        if r.unread:
            not_read = "the rep has not read the offer back"
            return f"{said}; {not_read}; ask again or ask_final_offer"
        if not left:
            return said
        then = ", then decline_offer and guide_fast(ask_final_offer)"
        return (
            f"{said}, omitted from {STOP_AFTER} read-backs: {', '.join(left)} → "
            "not stated as recorded: if a reply states another value for them, "
            "record_offer a new revision citing that line; otherwise stop asking, "
            "report them to the user as not stated"
            + (then if self.close.kind == "full" else "")
        )

    def lines(self) -> list[str]:
        return [self.close.line(), levers_line(self.levers)]


def bar(bb: Blackboard, kind: Kind, tools: SlowTools) -> Bar:
    lines = bb.channels.get("cp", ChannelState()).lines
    readbacks = {
        key: readback(o, asks, lines)
        for key, asks in tools.readbacks.items()
        if (o := bb.public.offers.get(key[0])) is not None and o.revision == key[1]
    }
    shut = close(bb, kind, tools.asked_final, tools.told_at)
    return Bar(shut, unavailable(bb), readbacks)
