"""The status bar's ``close:``, ``levers:`` and ``identify:`` lines and the
read-back ask count (ADR-0018 V3-V5, S1-SYS-46, S1-SYS-74). Read-only views of
the board and of Slow's own asks: each calls Guard's own predicates
(``verify_no_deal``, ``has_cue``, the status machine) and the lever check
``_guide`` runs, never a partial copy (the #166
``approval_hint`` pattern). Rep text reaches the close line only through Guard's
closing-cue list, and only as an utt id. The levers line's sent levers are
Slow's own GUIDEs and their fates (``slow.heard``, S1-SYS-66): state, not
transcript text, as is the identify line: the identify's delivery (S1-SYS-74).
The stop line (S1-SYS-83) reads the board: FastU's typed REVOKE relay, the
case status and the released accepts. The close line's unrecorded amounts
read only what Slow's view holds of the closing reply: its line as heard
(``transcript``) and the cp relays citing it (both modes).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from proxyloop.contract.messages import Guide, GuideMove
from proxyloop.contract.state import (
    Blackboard,
    CaseStatus,
    ChannelState,
    Line,
    OfferPublic,
)
from proxyloop.contract.views import SlowView
from proxyloop.guard.capability import released_accept
from proxyloop.guard.declass import spoken
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
    "lever_failed_twice": "failed to reach the rep twice",
}
DIES = 2  # a lever whose guide died this often is unavailable (root, §0.5a)
GROUPS = (  # a sent lever's state, the line's wording (S1-SYS-66)
    ("answered", "heard and answered by the rep"),
    ("heard", "heard, rep not answered yet (wait)"),
    ("waiting", "sent, not heard yet (wait)"),
)
IDENTIFY_SENT = {  # the identify's state, the identify line's wording (S1-SYS-74)
    "answered": "heard by the rep, who has answered since",
    "heard": "heard by the rep, not answered yet (wait)",
    "waiting": "sent, not heard yet (wait; do not send it again)",
}
IDENTIFY_RULES = "while the rep still asks for a fact, the identify rules apply"
ASK_DISCOUNT = (  # S1-SYS-82 F-a: the first request once the account is verified
    "once the rep has verified the account (it moves on to your request): "
    f"guide_fast(ask_discount) (ask for a lower monthly price); {IDENTIFY_RULES}"
)
DISCOUNT_ANSWERED = (  # round 4: a note, not a step (the levers line has it)
    "ask_discount answered: if the rep stated an offer, record_offer it; "
    f"otherwise one lever (levers line); {IDENTIFY_RULES}"
)
ONCE_MOVED_ON = (
    f"available once the rep has moved on to your request ({IDENTIFY_RULES})"
)
STOP = (  # S1-SYS-83 F-i: the one step, and only this step can take it
    "stop: the user said stop and no accept was released: in this one act, "
    "tell_user that nothing was accepted and the case is stopped, then "
    "finish(escalate, summary); once this step completes the case is back "
    "IN_CALL and can no longer be escalated"
)
STOPPED = "not after the user's stop"  # the levers line's label then


@dataclass(frozen=True, slots=True)
class Close:
    """V3: where the close stands, and whether ``finish`` would pass now."""

    kind: Kind
    asked: bool  # the rep heard a guide_fast(ask_final_offer) (tools.asked_final)
    reply: str | None  # the utt id of the rep's closing reply, by Guard's cues
    reasons: tuple[str, ...]  # why the kind's finish is refused; () it passes
    told: bool  # a tell_user went out after the closing reply
    pending: bool  # the newest final ask is not heard yet (final_pending)

    @property
    def outcome(self) -> str:
        return "info_only" if self.kind == "info_only" else "no_deal"

    def line(self, unrecorded: Sequence[str] = (), stopped: bool = False) -> str:
        """``unrecorded``: amounts the closing reply states that no recorded
        offer carries (F-m); ``stopped``: the stop line has the step (F-i)."""
        asked = "final offer asked" if self.asked else "final offer not asked"
        if self.pending:  # M1: queued or playing; asking again would repeat it
            asked = (
                "final offer asked, not yet heard by the rep (wait for it; do not "
                "ask again)"
            )
        if stopped:  # no competing "act on its reasons" (S1-SYS-83)
            return (
                f"close: {asked}; the user stopped the case (stop line): "
                f"finish({self.outcome}) does not apply"
            )
        said = f"the rep's closing reply {self.reply}" if self.reply else ""
        if not self.reasons:
            can = "allowed" if self.kind == "info_only" else "would verify"
        else:
            can = f"blocked: {', '.join(self.reasons)}"
        said = said or "no closing reply"
        final = self.asked and self.reply and not self.reasons  # finish passes
        if final and unrecorded and self.kind == "full":  # F-m: an offer unrecorded
            said += (
                f" states {', '.join(unrecorded)}, which no recorded offer "
                "carries: record_offer it first"
            )
            return f"close: {asked}; {said}; finish({self.outcome}) not before that"
        if final and not self.told:  # user.told_terms: only a final outcome
            said += "; tell_user the terms and the outcome before finish"
        return f"close: {asked}; {said}; finish({self.outcome}) {can}"


def close(
    bb: Blackboard,
    kind: Kind,
    asked_final: int | None,
    told_at: int | None = None,
    pending: bool = False,
) -> Close:
    """The rep's last line since the last ask_final_offer is a closing reply
    iff Guard's cue list says so (none before an ask: verify_no_deal's
    window, M1); the user counts as told once
    a tell_user went out after it (``told_at``: the cp length then). ``full``
    dry-runs ``authority.finish(no_deal)``: its status check, then
    ``verify_no_deal`` with the same ``asked_final``. ``pending``: the newest
    ask_final_offer is sent but not heard yet (``SlowTools.final_pending``)."""
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
    return Close(kind, asked_final is not None, reply, reasons, told, pending)


def stopped(bb: Blackboard) -> bool:
    """S1-SYS-83 F-i: FastU relayed the user's stop as a revoke (a typed
    REVOKE relay: in the view of either mode), the case is NEEDS_REPLAN
    (the revoke staled a pending card, or it replans for another reason) and
    no accept was released: finish(escalate) is open for this one step."""
    revoked = any(r.type == "REVOKE" for r in bb.f2s_pending)
    replan = bb.public.status is CaseStatus.NEEDS_REPLAN
    return replan and revoked and not released_accept(bb)


def closing_said(view: SlowView, reply: str | None) -> list[str]:
    """What Slow's view holds of the rep's closing reply ``reply``: its line
    as heard (``transcript`` mode only) and every cp relay citing it."""
    if reply is None:
        return []
    heard = view.transcripts.get("cp", ())
    said = [x.text for x in heard if x.utt_id == reply and x.speaker == "partner"]
    relays = [r for r in view.relays if r.lane == "cp" and r.utt_ref == reply]
    return said + [" ".join((r.text, *(v for _, v in r.facts))) for r in relays]


def unrecorded(offers: Iterable[OfferPublic], said: Iterable[str]) -> tuple[str, ...]:
    """F-m: the money amounts ``said`` states (Guard's ``spoken``, the one
    money extraction) that no recorded offer's money slot carries."""
    carried = {
        Decimal(s.value) / 100 for o in offers for s in o.slots if s.unit == "usd_minor"
    }
    amounts = {n for text in said for n in spoken(text, "usd_minor")}
    return tuple(f"${n}" for n in sorted(amounts - carried))


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


Sent = Literal["answered", "heard", "waiting", "failed"]
LIVE: tuple[Sent, ...] = ("answered", "heard", "waiting")  # in precedence order


def sent(bb: Blackboard, tools: SlowTools) -> dict[str, Sent]:
    """S1-SYS-66: each lever Slow sent, by its GUIDEs' fates (``slow.heard``):
    answered once a send was heard and a rep line follows its delivery (at or
    after its ``Fate.at``: one lever per rep reply); heard while the rep has
    not answered yet; waiting while one is queued (``s2f_pending``) or voiced
    by a turn still playing; failed once ``DIES`` voicings died (cancelled,
    cut, no speech) and none is live. A send never voiced (superseded by a
    later GUIDE, S1-SYS-67, though the fold keeps it queued; or neither
    queued nor voiced) was never tried: no death. A lever dead fewer times
    is left out: available again."""
    mine = {msg: move.value for msg, move in tools.guides if move in LEVERS}
    seen: dict[str, list[str]] = {}
    for msg, now in _states(bb, tools, list(mine)).items():
        seen.setdefault(mine[msg], []).append(now)
    out: dict[str, Sent] = {}
    for move, got in seen.items():
        live: list[Sent] = [s for s in LIVE if s in got]
        if live:
            out[move] = live[0]
        elif got.count("dead") >= DIES:
            out[move] = "failed"
    return out


def _states(bb: Blackboard, tools: SlowTools, msgs: Sequence[str]) -> dict[str, str]:
    """The state of each GUIDE in ``msgs``, in order (``sent``): answered,
    heard, waiting, dead or unvoiced; a superseded one (Slow replaced it
    before any turn: never tried) is left out."""
    fates = tools.fates if msgs else {}
    lines = bb.channels.get("cp", ChannelState()).lines
    queued = {m.msg_id for m in bb.s2f_pending.get("cp", ())}
    out: dict[str, str] = {}
    for msg in msgs:
        fate = fates.get(msg)
        if fate is not None and fate.superseded:
            continue
        now = fate.state if fate else "playing" if msg in queued else "unvoiced"
        if now == "heard" and fate is not None:
            rest = lines[fate.at :]
            now = "answered" if any(x.speaker == "partner" for x in rest) else now
        out[msg] = "waiting" if now == "playing" else now
    return out


def identify_sent(
    bb: Blackboard, tools: SlowTools, move: GuideMove = GuideMove.IDENTIFY
) -> Sent | None:
    """S1-SYS-74 D2: the newest identify Slow sent (not superseded), alone: a
    second one on its way after the first was answered shows as on its way.
    ``move``: the same for another move (``ask_discount``, S1-SYS-82)."""
    mine = [msg for msg, m in tools.guides if m == move]
    now = list(_states(bb, tools, mine).values())[-1:]
    return next((s for s in LIVE if s in now), None)


def lever_slots(bb: Blackboard) -> dict[str, str]:
    """N2: the public fact slot each lever ``lever_denial`` refuses without,
    the first one it lets through (the same checks ``unavailable`` runs)."""
    out: dict[str, str] = {}
    for move in LEVERS:
        if lever_denial(bb, Guide(move=move)) is None:
            continue
        for key in sorted(bb.public.facts):
            if lever_denial(bb, Guide(move=move, slots=(f"fact:{key}",))) is None:
                out[move.value] = f"fact:{key}"
                break
    return out


def _gone(levers: Sequence[tuple[str, str]]) -> set[str]:
    """The moves ``guide_fast`` refuses whole (n6: a private tenure slot
    leaves the move itself usable)."""
    return {m for m, c in levers if c != "guide_slot_not_public"}


def free_levers(
    levers: Sequence[tuple[str, str]], sends: Mapping[str, Sent] | None = None
) -> tuple[str, ...]:
    """The levers neither refused nor sent (heard or on its way)."""
    gone = _gone(levers) | set(sends or {})
    return tuple(m.value for m in LEVERS if m.value not in gone)


def levers_line(
    levers: Sequence[tuple[str, str]],
    sends: Mapping[str, Sent] | None = None,
    slots: Mapping[str, str] | None = None,
    label: str = "available",
) -> str:
    """Available (with the slot one needs), answered, heard, on its way,
    then each refusal with its clause and each lever that failed twice; an
    unavailable lever is only that, whatever was sent. ``label``: how the
    free ones are listed ("available" is a next step; ``Bar.lines``)."""

    def what(move: str, code: str) -> str:  # n6: only the slot is unavailable
        slot = f" with fact:{TENURE}" if code == "guide_slot_not_public" else ""
        return f"{move}{slot} unavailable ({code}: {WHY.get(code, code)})"

    sends, slots = sends or {}, slots or {}
    usable = [m.value for m in LEVERS if m.value not in _gone(levers)]
    free = [
        f"{m} with {slots[m]}" if m in slots else m for m in free_levers(levers, sends)
    ]
    groups = [f"{label}: {', '.join(free) or 'none'}"]
    for kind, label in GROUPS:
        if said := [m for m in usable if sends.get(m) == kind]:
            groups.append(f"{label}: {', '.join(said)}")
    groups += [what(m, c) for m, c in levers]
    groups += [
        what(m, "lever_failed_twice") for m in usable if sends.get(m) == "failed"
    ]
    return f"levers: {'; '.join(groups)}"


def identify_line(state: Sent | None) -> str | None:
    """S1-SYS-74: the identify's delivery, only once one is on its way or
    heard; none sent, or none heard (``failed``), shows no line."""
    said = IDENTIFY_SENT.get(state or "")
    return None if said is None else f"identify: {said}"


def request_line(
    identify: Sent | None, offered: bool, discount: Sent | None
) -> str | None:
    """S1-SYS-82 F-a: until an offer is recorded, the ask_discount's delivery
    once one is on its way or heard; before that, once the identify is
    answered, the discount ask as the one next phone step. No line after the
    first offer, or before the identify is answered and none is sent."""
    if offered:
        return None
    if discount == "answered":
        return f"request: {DISCOUNT_ANSWERED}"
    if (said := IDENTIFY_SENT.get(discount or "")) is not None:
        return f"request: ask_discount {said}"
    return f"request: {ASK_DISCOUNT}" if identify == "answered" else None


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
    sends: Mapping[str, Sent] = field(default_factory=dict[str, Sent])
    slots: Mapping[str, str] = field(default_factory=dict[str, str])  # N2
    identify: Sent | None = None  # the identify's delivery (S1-SYS-74)
    offered: bool = True  # an offer was recorded (S1-SYS-82 F-a)
    discount: Sent | None = None  # the ask_discount's delivery (S1-SYS-82)
    stop: bool = False  # the user's stop replanned the case (S1-SYS-83)

    @property
    def free(self) -> tuple[str, ...]:  # the levers to try, in order
        return free_levers(self.levers, self.sends)

    @property
    def waiting(self) -> bool:  # a lever the rep has not answered: one per reply
        gone = _gone(self.levers)
        live = ("heard", "waiting")
        return any(v in live and m not in gone for m, v in self.sends.items())

    def stuck(self, o: OfferPublic) -> bool:
        """``o``'s revision has slots ``STOP_AFTER`` read-backs omitted: the
        state ``offer_note``'s stuck clause names (S1-SYS-66 follow-up)."""
        r = self.readbacks.get((o.offer_ref, o.revision))
        return r is not None and bool(r.asked and r.stuck)

    def offer_note(self, o: OfferPublic, lever: bool = False) -> str:
        """V4 for ``o``'s revision. ``lever``: the offer's hint already names
        its next step, a lever or a wait (#238 D2: one next step per state),
        so an unread or stuck read-back keeps its facts but not "ask again"
        or the stuck clause's decline (#242 D1)."""
        r = self.readbacks.get((o.offer_ref, o.revision))
        if r is None or not r.asked:
            return ""
        asked, left = r.asked, r.stuck
        said = f"read-back asked {asked}×"  # noqa: RUF001
        if r.unread:
            not_read = f"{said}; the rep has not read the offer back"
            return not_read if lever else f"{not_read}; ask again or ask_final_offer"
        if not left:
            return said
        omitted = f"{said}, omitted from {STOP_AFTER} read-backs: {', '.join(left)}"
        if lever:
            return omitted
        then = ", then decline_offer and guide_fast(ask_final_offer)"
        return (
            f"{omitted} → not stated as recorded: if a reply states another "
            "value for them, record_offer a new revision citing that line; "
            "otherwise stop asking, report them to the user as not stated"
            + (then if self.close.kind == "full" else "")
        )

    def lines(self, outside: bool = True, unrecorded: Sequence[str] = ()) -> list[str]:
        """The free levers are "available" (a next step) once the discount
        ask was answered without an offer (round 4) or, after an offer,
        while ``outside``: an open offer outside the mandate has no better
        offer before it (round 3); otherwise "after the first offer" or "for
        an offer outside the mandate" (S1-SYS-82). After the user's stop,
        the stop line is the one step (S1-SYS-83). ``unrecorded``: the
        close line's F-m amounts."""
        label = "available" if outside else "for an offer outside the mandate"
        if not self.offered:
            opened = self.discount == "answered"  # round 5: conditional
            label = ONCE_MOVED_ON if opened else "after the first offer"
        if self.stop:
            label = STOPPED
        levers = levers_line(self.levers, self.sends, self.slots, label)
        ident = identify_line(self.identify)
        ask = request_line(self.identify, self.offered, self.discount)
        close = self.close.line(unrecorded, self.stop)
        head = [STOP] if self.stop else []
        return [*head, close, levers, *(x for x in (ident, ask) if x)]


def bar(bb: Blackboard, kind: Kind, tools: SlowTools) -> Bar:
    lines = bb.channels.get("cp", ChannelState()).lines
    readbacks = {
        key: readback(o, asks, lines)
        for key, asks in tools.readbacks.items()
        if (o := bb.public.offers.get(key[0])) is not None and o.revision == key[1]
    }
    shut = close(bb, kind, tools.asked_final, tools.told_at, tools.final_pending)
    ident = identify_sent(bb, tools)
    sends, slots = sent(bb, tools), lever_slots(bb)
    offered = bool(bb.public.offers)
    asked = identify_sent(bb, tools, GuideMove.ASK_DISCOUNT)
    return Bar(
        shut, unavailable(bb), readbacks, sends, slots, ident, offered, asked,
        stopped(bb),
    )  # fmt: skip
