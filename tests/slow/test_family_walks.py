"""S1-SYS-82 round 2 (L-CORE, option (a) of the round-1 escalation): an
unconfirmed offer another open offer dominates (no worse on price, term and
fees as recorded, better on one) gets no step of its own; and the four train
families' minimal success trajectories (the packet's audit summary) walk
state by state with exactly one next step in each, across the case, offers,
approvals, levers, request and close lines. The test plays the kernel."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests.slow import test_discount_first as first
from tests.slow.test_authority import Host

from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.views import view_slow
from proxyloop.slow import hints, prompt, state

_bar, _line, _verified = first._bar, first._line, first._verified  # pyright: ignore[reportPrivateUsage]
TENURE, DISCOUNT = first.TENURE, first.DISCOUNT
Fee = tuple[str, int] | None  # (code, dollars) of a one-time fee, or none

# the bar's words for a step, and what it acts on (an offer, a move or a tool)
CALL = re.compile(
    r"guide_fast\(ask_readback, \[\"offer:(?P<read>[^\"]+)\"\]\)"
    r"|(?:request_approval|accept_offer|decline_offer)\((?P<ref>[^)]+)\)"
    r"|guide_fast\((?P<move>[a-z_]+)[,)]"
    r"|(?P<tool>ask_final_offer|propose_mandate)"
    r"|finish\((?P<finish>escalate)"  # S1-SYS-83: the stop act
)
ENTRY = re.compile(r"; (?=[a-z0-9-]+ r\d+ \()")  # where an offer entry starts


def _targets(text: str) -> set[str]:
    out: set[str] = set()
    for m in CALL.finditer(text):
        out.add(next(v for v in m.groupdict().values() if v))
    return out


def next_steps(h: Host) -> set[str]:
    """What each next step the bar names acts on: a read-back, approval,
    accept or decline of an offer is that offer; a guide_fast is its move;
    ask_final_offer and propose_mandate are themselves; each available lever
    is its move. The close line's finish verdict is no step, nor is the
    "required slots not recorded … record them from the rep line that
    states them" clause: a note, conditional on a line that states them
    (round 4, review minor (e))."""
    out: set[str] = set()
    for line in _bar(h).splitlines():
        if line.startswith("offers: "):
            for entry in ENTRY.split(line.removeprefix("offers: ")):
                out |= _targets(entry)
        elif line.startswith("levers: available: "):
            free = line.removeprefix("levers: available: ").split(";", 1)[0]
            out |= {m.split(" ", 1)[0] for m in free.split(", ") if m != "none"}
        elif line.startswith(
            ("case: ", "approvals: ", "request: ", "close: ", "stop: ")
        ):
            out |= _targets(line)
    return out


def _said(price: int, term: int, fee: Fee, whole: bool = True) -> str:
    said = f"It is ${price} a month on a {term}-month term"
    if not whole:
        return f"{said}."
    fees = "no fees" if fee is None else f"a one-time ${fee[1]} {fee[0]} fee"
    return f"{said}, {fees}, no other changes, and the offer does not expire."


def _fields(price: int, term: int, fee: Fee, whole: bool = True) -> dict[str, str]:
    got = {"monthly_price": str(price * 100), "term_months": str(term)}
    if whole:
        got |= (
            {"fees_none": "true"}
            if fee is None
            else {f"fee:{fee[0]}": str(fee[1] * 100)}
        )
        got |= {"changes_none": "true", "expires": "none"}
    return got


def _record(h: Host, ref: str, text: str, fields: dict[str, str]) -> None:
    """The rep says ``text``; Slow records ``ref`` from that line."""
    utt = f"cp-{len(h.bb.channels['cp'].lines) + 1}"
    h.rep(utt, text)
    slots = [{"field": f, "value": v, "utt_ref": utt} for f, v in fields.items()]
    (got,) = h.act({"tool": "record_offer", "offer_ref": ref, "offer_slots": slots})
    assert got.startswith(f"record_offer: recorded {ref} r"), got


def offer(ref: str, price: int, term: int, fee: Fee = None, whole: bool = True) -> Step:
    """The rep, answering the move just sent, states an offer; Slow records it."""

    def go(h: Host) -> None:
        h.voice()
        _record(
            h, ref, _said(price, term, fee, whole), _fields(price, term, fee, whole)
        )

    return go


def ask_readback(ref: str) -> Step:
    def go(h: Host) -> None:
        ask = {"tool": "guide_fast", "move": "ask_readback", "slots": [f"offer:{ref}"]}
        (got,) = h.act(ask)
        assert "read-back asked for" in got, got

    return go


def read_back(ref: str, price: int, term: int, fee: Fee = None) -> Step:
    """The rep reads ``ref`` back as stated: every slot confirmed."""

    def go(h: Host) -> None:
        h.voice()
        h.rep(f"cp-{len(h.bb.channels['cp'].lines) + 1}", _said(price, term, fee))
        h.tools.readback()
        assert {s.status for s in h.bb.public.offers[ref].slots} == {"confirmed"}

    return go


def reveal(ref: str, price: int, term: int, fee: Fee) -> Step:
    """The read-back states a fee not said before: Slow records the new
    revision citing it (it stands confirmed: the read-back was asked)."""

    def go(h: Host) -> None:
        h.voice()
        _record(h, ref, _said(price, term, fee), _fields(price, term, fee))

    return go


def act(call: dict[str, Any]) -> Step:
    def go(h: Host) -> None:
        (got,) = h.act(call)
        assert "denied" not in got and "refused" not in got, got

    return go


Step = Callable[[Host], None]
SENT = act(DISCOUNT)
LEVER = act(TENURE)


def request(ref: str) -> Step:
    return act({"tool": "request_approval", "offer_ref": ref})


def accept(ref: str) -> Step:
    return act({"tool": "accept_offer", "offer_ref": ref})


def granted(h: Host) -> None:
    """The sim approver grants the pending card; the kernel decides it."""
    card = h.bb.private.pending_approval
    assert card is not None
    post = {"subject": "approval", "subject_id": card.approval_id}
    post |= {"decision": "granted", "subject_hash": card.terms_hash}
    posted = h.emit(
        "approval.post",
        "sim_approver",
        post | {"authority_epoch": card.authority_epoch},
    )
    decided = {
        "approval_id": card.approval_id,
        "decision": "granted",
        "by": "sim_approver",
    }
    ev = h.emit("approval.decided", "kernel", decided, [posted.event_id])
    back = {"previous": "AWAITING_APPROVAL", "status": "IN_CALL"}
    h.emit("status.changed", "guard", back, [ev.event_id])


STOP = "Stop, do not accept anything. I will keep my current plan for now."


def stop_relayed(h: Host) -> None:
    """S1-SYS-83: the SimUser's stop after the card; FastU relays it as a
    revoke; the kernel bumps the epoch (f2s_revoke), which stales the
    pending card: NEEDS_REPLAN (kernel/fence.py, played here)."""
    said = h.emit("user.msg", "kernel", {"text": STOP})
    relay = {"msg_id": f"r1:{len(h.bus.events)}", "lane": "user", "gen_id": "u"}
    relay |= {"utt_ref": said.event_id, "type": "REVOKE", "text": "the user said stop"}
    got = h.emit("f2s.msg", "fast.user", relay, [said.event_id])
    h.tools.received.add(str(relay["msg_id"]))
    bump = {"new": h.bb.epoch + 1, "reason": "f2s_revoke"}
    bumped = h.emit("authority.epoch", "kernel", bump, [got.event_id])
    stale = {"previous": "AWAITING_APPROVAL", "status": "NEEDS_REPLAN"}
    h.emit("status.changed", "guard", stale, [bumped.event_id])


TOLD = {"tool": "tell_user", "text": "Nothing was accepted; the case is stopped."}
ESCALATE = {"tool": "finish", "outcome": "escalate", "summary": "the user stopped"}


def escalated(h: Host) -> None:
    """The stop line's one act: tell_user, then finish(escalate)."""
    told, done = h.act(TOLD, ESCALATE)
    assert told.startswith("tell_user: ") and done == "finish: case closed", done
    assert h.bb.public.status.value == "ESCALATED" and h.ended == ["escalate"]


# each family: its mandate, then (state, the step to it, the one next step)
# each family (tasks/families/*.yaml): its mandate, then (state, the step to
# it, the one next step). The rep states price and term; the read-back
# states the hidden slots, and Slow records them as a new revision. The
# intake (``_verified``) makes the tenure public first: mention_tenure needs
# fact:tenure_years, and LEVER cites it (S1-SYS-94 reverses n6).
ACTIVATION = ("activation", 20)
WALKS: dict[str, tuple[dict[str, int], list[tuple[str, Step | None, str | None]]]] = {
    "cp-direct-discount": (
        {"cap": 7000, "max_term_months": 24, "max_one_time_fees_minor": 2500},
        [
            ("verified", None, "ask_discount"),
            ("discount asked", SENT, None),
            (
                "loyal-1 outside",
                offer("loyal-1", 75, 12, None, False),
                "mention_tenure",
            ),
            ("tenure sent", LEVER, None),
            ("loyal-2 inside", offer("loyal-2", 68, 24, None, False), "loyal-2"),
            ("loyal-2 read-back asked", ask_readback("loyal-2"), "loyal-2"),
            ("loyal-2 read back", reveal("loyal-2", 68, 24, ACTIVATION), "loyal-2"),
            ("accept queued", accept("loyal-2"), None),
        ],
    ),
    "cp-hidden-fee-readback": (
        {"cap": 6500, "max_term_months": 12, "max_one_time_fees_minor": 0},
        [
            ("verified", None, "ask_discount"),
            ("discount asked", SENT, None),
            ("promo-1 inside", offer("promo-1", 55, 12, None, False), "promo-1"),
            ("promo-1 read-back asked", ask_readback("promo-1"), "promo-1"),
            (
                "promo-1 fee revealed",
                reveal("promo-1", 55, 12, ("installation", 99)),
                "mention_tenure",
            ),
            ("tenure sent", LEVER, None),
            ("promo-2 inside", offer("promo-2", 62, 12, None, False), "promo-2"),
            ("promo-2 read-back asked", ask_readback("promo-2"), "promo-2"),
            ("promo-2 read back", reveal("promo-2", 62, 12, None), "promo-2"),
            # Guard leaves r2 unconfirmed here: its own read-back confirms it
            ("promo-2 r2 read-back asked", ask_readback("promo-2"), "promo-2"),
            ("promo-2 r2 read back", read_back("promo-2", 62, 12), "promo-2"),
            ("accept queued", accept("promo-2"), None),
        ],
    ),
    "x-out-of-envelope-approval": (
        {"cap": 6500, "max_term_months": 24, "max_one_time_fees_minor": 0},
        [
            ("verified", None, "ask_discount"),
            ("discount asked", SENT, None),
            ("save-1 outside", offer("save-1", 78, 24, None, False), "mention_tenure"),
            ("tenure sent", LEVER, None),
            ("save-2 dominates", offer("save-2", 69, 24, None, False), "save-2"),
            ("save-2 read-back asked", ask_readback("save-2"), "save-2"),
            ("save-2 read back", reveal("save-2", 69, 24, None), "save-2"),
            ("card pending", request("save-2"), None),
            ("approval granted", granted, "save-2"),
            ("accept queued", accept("save-2"), None),
        ],
    ),
    "x-user-mind-change": (
        {"cap": 7000, "max_term_months": 12, "max_one_time_fees_minor": 0},
        [
            ("verified", None, "ask_discount"),
            ("discount asked", SENT, None),
            ("keep-1 outside", offer("keep-1", 76, 12, None, False), "mention_tenure"),
            ("tenure sent", LEVER, None),
            ("keep-2 dominates", offer("keep-2", 73, 12, None, False), "keep-2"),
            ("keep-2 read-back asked", ask_readback("keep-2"), "keep-2"),
            ("keep-2 read back", reveal("keep-2", 73, 12, None), "keep-2"),
            ("card pending", request("keep-2"), None),
            ("stop relayed, card stale", stop_relayed, "escalate"),
            ("escalated", escalated, None),
        ],
    ),
}


@pytest.mark.parametrize("family", list(WALKS))
def test_each_family_walks_with_one_next_step_per_state(
    tmp_path: Path, family: str
) -> None:
    mandate, states = WALKS[family]
    bounds = dict(mandate)
    cap = bounds.pop("cap")
    h = _verified(tmp_path, cap, **bounds)
    for name, step, want in states:
        if step is not None:
            step(h)
        got = next_steps(h)
        assert got == ({want} if want else set()), (family, name, got, _bar(h))


# dominance (round 2): the x-out-of-envelope-approval and x-user-mind-change
# states the round-1 bar showed with two read-backs


def _two(
    tmp_path: Path,
    one: tuple[str, int, int],
    two: tuple[str, int, int],
    cap: int,
    term: int,
) -> Host:
    """``one`` then ``two`` recorded outside the mandate, mention_tenure
    answered (no lever left), neither read back."""
    h = _verified(tmp_path, cap, max_term_months=term, max_one_time_fees_minor=0)
    h.act(DISCOUNT)
    offer(*one)(h)
    h.act(TENURE)
    offer(*two)(h)
    return h


def _entry(h: Host, ref: str) -> str:
    line = _line(h, "offers: ").removeprefix("offers: ")
    (got,) = [e for e in ENTRY.split(line) if e.startswith(f"{ref} r")]
    return got


DOMINATED = f"{hints.DEFER}save-2 ({hints.DOMINATES}) comes first"


def test_i_the_dominated_offer_gets_no_step(tmp_path: Path) -> None:
    h = _two(tmp_path, ("save-1", 78, 24), ("save-2", 69, 24), 6500, 24)
    assert _entry(h, "save-1").endswith(DOMINATED), _entry(h, "save-1")
    assert _entry(h, "save-2").endswith(
        'guide_fast(ask_readback, ["offer:save-2"]), then request_approval(save-2)'
    ), _entry(h, "save-2")
    assert next_steps(h) == {"save-2"}


def test_ii_with_the_read_back_asked_the_dominated_offer_still_waits(
    tmp_path: Path,
) -> None:
    h = _two(tmp_path, ("save-1", 78, 24), ("save-2", 69, 24), 6500, 24)
    ask_readback("save-2")(h)
    assert _entry(h, "save-1").endswith(DOMINATED), _entry(h, "save-1")
    assert "read-back asked: request_approval(save-2) once confirmed" in _entry(
        h, "save-2"
    )
    assert next_steps(h) == {"save-2"}


def test_iii_mind_change_keep_2_comes_first(tmp_path: Path) -> None:
    h = _two(tmp_path, ("keep-1", 76, 12), ("keep-2", 73, 12), 7000, 12)
    assert _entry(h, "keep-1").endswith(
        f"{hints.DEFER}keep-2 ({hints.DOMINATES}) comes first"
    )
    assert next_steps(h) == {"keep-2"}


def test_iv_a_worse_term_is_no_dominance_but_inside_comes_first(
    tmp_path: Path,
) -> None:
    """loyal-1 75/12 vs loyal-2 68/24: loyal-2's term is longer, so it does
    not dominate; it is inside the $70/24/$25 mandate, so it comes first."""
    h = _verified(tmp_path, 7000, max_term_months=24, max_one_time_fees_minor=2500)
    h.act(DISCOUNT)
    offer("loyal-1", 75, 12, ("activation", 20))(h)
    h.act(TENURE)
    offer("loyal-2", 68, 24, ("activation", 20))(h)
    view_terms = {"loyal-1": (7500, 12, 2000), "loyal-2": (6800, 24, 2000)}
    assert not hints._dominates(view_terms["loyal-2"], view_terms["loyal-1"])  # pyright: ignore[reportPrivateUsage]
    assert f"loyal-2 ({hints.INSIDE}) comes first" in _entry(h, "loyal-1")
    assert next_steps(h) == {"loyal-2"}


def test_v_a_fee_revealed_on_the_read_back_ends_the_dominance(
    tmp_path: Path,
) -> None:
    """keep-2 (73/12) dominates keep-1 (76/12) until its read-back reveals a
    $40 fee (above keep-1's none as recorded): keep-2 r2 is recorded from
    that line, not yet confirmed (a new revision needs its own read-back),
    and neither dominates, so neither comes first and both entries show
    their read-back. Once keep-2 r2 is read back and confirmed, still
    neither dominates (round 4, review M1: no cheaper-by-price rule, the
    approver would deny the fee): both keep a step until one is decided."""
    h = _two(tmp_path, ("keep-1", 76, 12), ("keep-2", 73, 12), 7000, 12)
    ask_readback("keep-2")(h)
    assert _entry(h, "keep-1").endswith(
        f"{hints.DEFER}keep-2 ({hints.DOMINATES}) comes first"
    )
    reveal("keep-2", 73, 12, ("setup", 40))(h)
    assert "comes first" not in _line(h, "offers: ")
    # known two-step state, on no family trajectory: §0.9, no fix in this PR
    assert next_steps(h) == {"keep-1", "keep-2"}
    ask_readback("keep-2")(h)
    read_back("keep-2", 73, 12, ("setup", 40))(h)
    assert "comes first" not in _line(h, "offers: ")
    step = "keep-2 confirmed, outside mandate → request_approval(keep-2)"
    assert step in _entry(h, "keep-2"), _entry(h, "keep-2")
    # known two-step state until one offer is decided: §0.9, no fix in this PR
    assert next_steps(h) == {"keep-1", "keep-2"}


def test_v_neither_dominates_neither_comes_first(tmp_path: Path) -> None:
    """keep-2 (73/12, a $40 fee said up front) against keep-1 (76/12, no
    fee): cheaper but with a fee, neither confirmed: neither comes first."""
    h = _verified(tmp_path, 7000, max_term_months=12, max_one_time_fees_minor=0)
    h.act(DISCOUNT)
    offer("keep-1", 76, 12)(h)
    h.act(TENURE)
    offer("keep-2", 73, 12, ("setup", 40))(h)
    assert "comes first" not in _line(h, "offers: ")


# round 3 (L-CORE): the levers line lists free levers as "available" (a step)
# only while an open offer outside the mandate has no better offer before it


def _levers(h: Host) -> str:
    return _line(h, "levers: ")


FOR_OUTSIDE = (
    "levers: for an offer outside the mandate: mention_tenure with fact:tenure_years; "
)


def test_l_an_inside_offer_alone_lists_no_lever_step(tmp_path: Path) -> None:
    """cp-hidden-fee-readback: promo-1 55/12, no fee said yet, is inside."""
    h = _verified(tmp_path, 6500, max_term_months=12, max_one_time_fees_minor=0)
    h.act(DISCOUNT)
    offer("promo-1", 55, 12, None, False)(h)
    assert _levers(h).startswith(FOR_OUTSIDE), _levers(h)
    step = (  # e1 (round 5): the step; the required-slots note stays a note
        'inside the granted mandate → guide_fast(ask_readback, ["offer:promo-1"]), '
        "then accept_offer(promo-1); required slots not recorded"
    )
    assert step in _entry(h, "promo-1"), _entry(h, "promo-1")
    assert next_steps(h) == {"promo-1"}


def test_l_inside_and_outside_open_the_inside_one_comes_first(
    tmp_path: Path,
) -> None:
    """loyal-1 outside, loyal-2 inside, mention_tenure never sent: no lever."""
    h = _verified(tmp_path, 7000, max_term_months=24, max_one_time_fees_minor=2500)
    h.act(DISCOUNT)
    offer("loyal-1", 75, 12, ("activation", 20))(h)
    fee = ("activation", 20)
    _record(h, "loyal-2", _said(68, 24, fee), _fields(68, 24, fee))
    assert _levers(h).startswith(FOR_OUTSIDE), _levers(h)
    assert next_steps(h) == {"loyal-2"}


def test_l_a_lever_on_its_way_is_unchanged(tmp_path: Path) -> None:
    h = _verified(tmp_path, 6500, max_term_months=24, max_one_time_fees_minor=0)
    h.act(DISCOUNT)
    offer("save-1", 78, 24)(h)
    assert _levers(h).startswith(
        "levers: available: mention_tenure with fact:tenure_years; "
    )
    h.act(TENURE)
    line = _levers(h)
    assert line.startswith("levers: available: none; ") and "(wait)" in line, line
    assert next_steps(h) == set()


def test_l_after_a_denial_with_no_inside_offer_the_lever_is_available(
    tmp_path: Path,
) -> None:
    h = first.auth._confirmed(tmp_path)  # pyright: ignore[reportPrivateUsage]
    first._mandate(h, 6500)  # pyright: ignore[reportPrivateUsage]
    first.auth.tenure_public(h)
    h.act({"tool": "request_approval", "offer_ref": "save-2"})
    first._deny(h)  # pyright: ignore[reportPrivateUsage]
    assert _levers(h).startswith(
        "levers: available: mention_tenure with fact:tenure_years; "
    )
    assert next_steps(h) == {"mention_tenure"}


def _no_grant(tmp_path: Path, propose: bool) -> Host:
    """The call open and verified with no mandate granted (``propose``: one
    proposed, the user has not decided it), the tenure public (S1-SYS-94),
    then save-1 recorded."""
    h = Host(tmp_path)
    first.auth.tenure_public(h)
    if propose:
        envelope = {"max_monthly_price_minor": 6500, "max_term_months": 24}
        h.act({"tool": "propose_mandate", "envelope": envelope})
    said = h.emit("user.msg", "kernel", {"text": "My last 4 are 4821."})
    record = {"tool": "record_fact", "key": "account.last4", "value": "4821"}
    h.act(record | {"utt_ref": said.event_id})
    h.call()
    h.act(first.LAST4)
    h.voice()
    h.rep("cp-1", "Thank you, the account is verified. How can I help?")
    h.act(DISCOUNT)
    offer("save-1", 78, 24)(h)
    return h


def test_l_no_mandate_granted_keeps_the_lever_available(tmp_path: Path) -> None:
    """No granted mandate covers the offer, so a lever stays a step, as
    before round 3: with a proposal pending it is the one step; with none,
    the case line's propose_mandate shows too (unchanged by round 3)."""
    h = _no_grant(tmp_path, propose=True)
    assert _levers(h).startswith(
        "levers: available: mention_tenure with fact:tenure_years; "
    )
    assert next_steps(h) == {"mention_tenure"}


def test_l_no_mandate_at_all_shows_the_lever_and_propose_mandate(
    tmp_path: Path,
) -> None:
    h = _no_grant(tmp_path, propose=False)
    assert _levers(h).startswith(
        "levers: available: mention_tenure with fact:tenure_years; "
    )
    # two steps as before round 3, on no family trajectory (the mandate is
    # granted in the intake): reported, no fix in this PR
    assert next_steps(h) == {"mention_tenure", "propose_mandate"}


# round 4 (review rev-263 with L-CORE decisions)


def test_m2_the_discount_ask_answered_without_an_offer_frees_the_levers(
    tmp_path: Path,
) -> None:
    h = _verified(tmp_path, 6500, max_term_months=24, max_one_time_fees_minor=0)
    h.act(DISCOUNT)
    h.voice()
    h.rep("cp-2", "Let me see what I can do for you.")  # answered, no offer
    assert _line(h, "request: ") == f"request: {state.DISCOUNT_ANSWERED}"
    # round 5 (D1): the lever is the step once the rep has moved on; the bar
    # cannot tell that from a rep still asking for a fact, so it is
    # conditional (not counted as an unconditional step)
    assert _levers(h).startswith(
        f"levers: {state.ONCE_MOVED_ON}: mention_tenure with fact:tenure_years; "
    )
    assert next_steps(h) == set()


def test_d1_a_rep_still_asking_for_a_fact_makes_no_lever_a_step(
    tmp_path: Path,
) -> None:
    """Review D1 probe: verified, the rep asks for another fact, the discount
    ask is heard, and the rep says it still needs the name: the lever is not
    the one step (an identity strike); the identify rules apply."""
    h = _verified(tmp_path, 6500, max_term_months=24, max_one_time_fees_minor=0)
    h.rep("cp-2", "Can you also confirm the account holder's full name?")
    h.act(DISCOUNT)
    h.voice()
    h.rep("cp-3", "I still need the account holder's full name first.")
    ask = _line(h, "request: ")
    assert ask.endswith("while the rep still asks for a fact, the identify rules apply")
    assert not _levers(h).startswith("levers: available: "), _levers(h)
    assert next_steps(h) == set()


def test_b_while_the_rep_still_asks_for_a_fact_the_identify_rules_apply(
    tmp_path: Path,
) -> None:
    """Any rep line answers the identify; the request line is conditional on
    the rep moving on. Here it asks for the holder's name: Slow records it
    and identifies again (the identify rules), and no ask_discount shows."""
    h = _verified(tmp_path, 6500)
    h.rep("cp-2", "Can you also confirm the account holder's full name?")
    ask = _line(h, "request: ")
    assert ask.endswith("while the rep still asks for a fact, the identify rules apply")
    said = h.emit("user.msg", "kernel", {"text": "The name is Dana Reyes."})
    name = {"tool": "record_fact", "key": "account.holder_name", "value": "Dana Reyes"}
    h.act(name | {"utt_ref": said.event_id})
    slots = ["fact:account.last4", "fact:account.holder_name"]
    h.act({"tool": "guide_fast", "move": "identify", "slots": slots})
    bar = _bar(h)
    assert "identify: sent, not heard yet (wait; do not send it again)" in bar
    assert "request: " not in bar and "ask_discount" not in bar, bar
    assert next_steps(h) == set()


CHANGE = ("plan_change", "with a plan change")


def _changed(h: Host, ref: str, price: int, term: int) -> None:
    """The rep states ``ref`` with a plan change the user forbade."""
    text = f"It is ${price} a month on a {term}-month term, {CHANGE[1]}."
    fields = _fields(price, term, None, False) | {f"applied_change:{CHANGE[0]}": "true"}
    _record(h, ref, text, fields)


def _forbidding(tmp_path: Path) -> Host:
    h = Host(tmp_path)
    first._mandate(h, 6500, max_term_months=24, forbidden_changes=[CHANGE[0]])  # pyright: ignore[reportPrivateUsage]
    h.call()
    _record(h, "save-1", _said(78, 24, None, False), _fields(78, 24, None, False))
    return h


def test_c1_a_rival_breaking_a_hard_limit_is_not_inside(tmp_path: Path) -> None:
    h = _forbidding(tmp_path)
    _changed(h, "save-2", 60, 24)  # $60 is under the cap, but forbidden
    assert "comes first" not in _entry(h, "save-1"), _entry(h, "save-1")


def test_c2_a_rival_breaking_a_hard_limit_dominates_nothing(tmp_path: Path) -> None:
    h = _forbidding(tmp_path)
    _changed(h, "save-2", 69, 24)  # outside by price, dominant, but forbidden
    assert "comes first" not in _entry(h, "save-1"), _entry(h, "save-1")


def test_c3_an_approved_offer_is_not_deferred(tmp_path: Path) -> None:
    """save-3 62/24 inside the mandate is open; save-2 69/24 is confirmed and
    approved: its accept is the step, it does not defer to save-3."""
    h = Host(tmp_path)
    first._mandate(h, 6500, max_term_months=24, max_one_time_fees_minor=0)  # pyright: ignore[reportPrivateUsage]
    h.call()
    _record(h, "save-3", _said(62, 24, None, False), _fields(62, 24, None, False))
    _record(h, "save-2", _said(69, 24, None), _fields(69, 24, None))
    ask_readback("save-2")(h)
    read_back("save-2", 69, 24)(h)
    request("save-2")(h)
    granted(h)
    entry = _entry(h, "save-2")
    assert "save-2 confirmed, approved → accept_offer(save-2)" in entry, entry
    assert "comes first" not in entry


def test_d_the_readiness_mandate_rule_is_for_full_cases_only(
    tmp_path: Path,
) -> None:
    for mode in SlowViewMode:
        flat = " ".join(prompt.system(mode).split())
        (at,) = [m.start() for m in re.finditer("propose_mandate with every", flat)]
        assert flat[at - 120 : at].count("In a full case (TASK KIND full)") == 1
    h = Host(tmp_path)
    h.emit("user.msg", "kernel", {"text": "At most $65 a month, no fees."})
    more = state.bar(h.bb, "info_only", h.tools)
    view = view_slow(h.bb, SlowViewMode.RELAY_ONLY, "b")
    assert "propose_mandate" not in prompt.status_bar(view, h.now(), None, more)
