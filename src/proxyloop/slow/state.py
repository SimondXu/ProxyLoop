"""The status bar's ``close:`` and ``levers:`` lines and the read-back ask count
(ADR-0018 V3-V5, S1-SYS-46). Read-only views of the board and of Slow's own asks:
each calls Guard's own predicates (``verify_no_deal``, ``has_cue``, the status
machine) and the lever check ``_guide`` runs, never a partial copy (the #166
``approval_hint`` pattern). Rep text reaches the close line only through Guard's
closing-cue list, and only as an utt id."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from proxyloop.contract.messages import Guide, GuideMove
from proxyloop.contract.state import Blackboard, ChannelState, Line, OfferPublic
from proxyloop.guard.readback import has_cue
from proxyloop.guard.status import status_change
from proxyloop.guard.verify import verify_no_deal
from proxyloop.slow.tools import SlowTools, lever_denial, public_guide

Kind = Literal["info_only", "full"]  # the task's ``mode`` (task data)
Ask = tuple[int, frozenset[str]]  # a read-back ask: cp lines then, slots unconfirmed
STOP_AFTER = 2  # read-backs leaving the same slots unconfirmed (V4)
LEVERS = (GuideMove.CITE_COMPETITOR, GuideMove.MENTION_TENURE, GuideMove.CANCEL_LEVER)
TENURE = "tenure_years"  # the one lever fact a user can make public (FORMATS)
WHY = {  # one clause per refusal class (V5)
    "competitor_quote_not_shareable": "no competitor quote the user shared is public",
    "cancel_lever_not_authorized": "the user has not authorised cancelling",
    "guide_slot_not_public": f"{TENURE} is private: use the move without that slot",
}


@dataclass(frozen=True, slots=True)
class Close:
    """V3: where the close stands, and whether ``finish`` would pass now."""

    kind: Kind
    asked: bool  # guide_fast(ask_final_offer) went out
    reply: str | None  # the utt id of the rep's closing reply, by Guard's cues
    reasons: tuple[str, ...]  # why the kind's finish is refused; () it passes

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
        return f"close: {asked}; {said}; finish({self.outcome}) {can}"


def close(bb: Blackboard, kind: Kind, asked_final: int | None) -> Close:
    """The rep's last line since the last ask (the whole call before one) is
    a closing reply iff Guard's cue list says so; ``full`` dry-runs
    ``authority.finish(no_deal)``: its status check, then ``verify_no_deal``
    with the same ``asked_final``."""
    lines = bb.channels.get("cp", ChannelState()).lines
    rep = [x for x in lines[asked_final or 0 :] if x.speaker == "partner"]
    reply = rep[-1].utt_id if rep and has_cue(rep[-1].text, "closing") else None
    trigger = "info_only" if kind == "info_only" else "no_deal_verified"
    if status_change(bb, trigger) is None:
        reasons: tuple[str, ...] = (f"case_is:{bb.public.status.value}",)
    elif kind == "info_only":
        reasons = ()
    else:
        reasons = verify_no_deal(bb, asked_final).reasons
    return Close(kind, asked_final is not None, reply, reasons)


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
    said = "; ".join(f"{m} unavailable ({c}: {WHY.get(c, c)})" for m, c in levers)
    return f"levers: {said or 'all available'}"


def unconfirmed(o: OfferPublic) -> frozenset[str]:
    return frozenset(s.field for s in o.slots if s.status != "confirmed")


def stuck(
    o: OfferPublic, asks: Sequence[Ask], lines: Sequence[Line]
) -> tuple[str, ...]:
    """V4: the slots the last two read-backs both left unconfirmed, once the
    rep has spoken after the last one; () while the rule does not apply."""
    if len(asks) < STOP_AFTER or o.status != "open":
        return ()
    at, before = asks[-1]
    if not any(x.speaker == "partner" for x in lines[at:]):
        return ()
    return tuple(sorted(before & unconfirmed(o)))


@dataclass(frozen=True, slots=True)
class Bar:
    """What the status bar adds beyond the view (ADR-0018 F-a: close, levers,
    and each offer revision's read-back count)."""

    close: Close
    levers: tuple[tuple[str, str], ...]
    readbacks: Mapping[tuple[str, int], tuple[int, tuple[str, ...]]]  # k, stuck

    def offer_note(self, o: OfferPublic) -> str:
        asked, left = self.readbacks.get((o.offer_ref, o.revision), (0, ()))
        if not asked:
            return ""
        said = f"read-back asked {asked}×"  # noqa: RUF001
        if not left:
            return said
        then = ", then decline_offer and guide_fast(ask_final_offer)"
        return (
            f"{said}, still unconfirmed after {asked}: {', '.join(left)} → stop "
            "asking; report them to the user as not stated"
            + (then if self.close.kind == "full" else "")
        )

    def lines(self) -> list[str]:
        return [self.close.line(), levers_line(self.levers)]


def bar(bb: Blackboard, kind: Kind, tools: SlowTools) -> Bar:
    lines = bb.channels.get("cp", ChannelState()).lines
    readbacks = {
        key: (len(asks), stuck(o, asks, lines))
        for key, asks in tools.readbacks.items()
        if (o := bb.public.offers.get(key[0])) is not None and o.revision == key[1]
    }
    return Bar(close(bb, kind, tools.asked_final), unavailable(bb), readbacks)
