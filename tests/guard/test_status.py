"""The status machine (§9.5) and the speech screen (§9.3)."""

from __future__ import annotations

import pytest
from tests.guard.build import board, confirm, mandate, offer, rep

from proxyloop.contract.state import Blackboard, CaseStatus, Fact, PublicFact
from proxyloop.guard.screen import screen
from proxyloop.guard.status import TERMINAL, TRANSITIONS, next_status, status_change

S = CaseStatus


@pytest.mark.parametrize(
    ("path", "end"),
    [
        (["mandate_granted", "call_opened"], S.IN_CALL),
        (["call_opened", "info_only"], S.CLOSED_NO_ACTION),  # S0
        (
            [
                "call_opened",
                "approval_requested",
                "approval_decided",
                "accept_authorized",
                "accept_heard",
                "evidence_recorded",
                "completion_ok",
            ],
            S.VERIFIED_COMPLETE,
        ),
        (["call_opened", "accept_authorized", "accept_truncated", "replan"], S.IN_CALL),
        (
            ["call_opened", "accept_authorized", "accept_revoked", "escalate"],
            S.ESCALATED,
        ),
        (
            [
                "call_opened",
                "accept_authorized",
                "accept_heard",
                "evidence_recorded",
                "completion_fail",
            ],
            S.NEEDS_REPLAN,
        ),
        (["call_opened", "no_deal_verified"], S.VERIFIED_NO_DEAL),
        (["call_opened", "approval_requested", "hang_up"], S.ABANDONED),
        (  # S1-SYS-38: a stale card replans, then any IN_CALL outcome
            ["call_opened", "approval_requested", "approval_stale", "replan"],
            S.IN_CALL,
        ),
        (
            ["call_opened", "approval_requested", "approval_expired", "escalate"],
            S.ESCALATED,
        ),
    ],
)
def test_paths(path: list[str], end: CaseStatus) -> None:
    status = S.INTAKE
    for trigger in path:
        nxt = next_status(status, trigger)
        assert nxt is not None, (status, trigger)
        status = nxt
    assert status is end


def test_illegal_and_terminal_moves_are_refused() -> None:
    assert next_status(S.INTAKE, "accept_authorized") is None
    assert next_status(S.AWAITING_APPROVAL, "accept_authorized") is None
    assert next_status(S.IN_CALL, "completion_ok") is None  # only via evidence
    for status in TERMINAL:
        assert all(next_status(status, t) is None for _, t in TRANSITIONS)
        assert next_status(status, "hang_up") is None
    verified = {S.VERIFIED_COMPLETE, S.VERIFIED_NO_DEAL}
    into = {to: t for (_, t), to in TRANSITIONS.items() if to in verified}
    assert into == {
        S.VERIFIED_COMPLETE: "completion_ok",
        S.VERIFIED_NO_DEAL: "no_deal_verified",
    }


def test_a_pending_card_leaves_only_by_a_decision_staleness_or_a_hang_up() -> None:
    """S1-SYS-38 (I6, restrict-only): a stale or expired card moves
    AWAITING_APPROVAL to NEEDS_REPLAN, never toward a commitment; the two
    triggers move nothing else, and a decided card keeps its IN_CALL edge."""
    out = {t: to for (was, t), to in TRANSITIONS.items() if was is S.AWAITING_APPROVAL}
    assert out == {
        "approval_decided": S.IN_CALL,
        "approval_stale": S.NEEDS_REPLAN,
        "approval_expired": S.NEEDS_REPLAN,
    }
    for status in S:
        if status is not S.AWAITING_APPROVAL:
            assert next_status(status, "approval_stale") is None, status
            assert next_status(status, "approval_expired") is None, status
    assert next_status(S.AWAITING_APPROVAL, "hang_up") is S.ABANDONED
    bb = board(status=S.AWAITING_APPROVAL)
    assert status_change(bb, "approval_stale") == {
        "previous": "AWAITING_APPROVAL",
        "status": "NEEDS_REPLAN",
    }


def test_status_change_payload() -> None:
    bb = board(status=CaseStatus.INTAKE)
    assert status_change(bb, "call_opened") == {
        "previous": "INTAKE",
        "status": "IN_CALL",
    }
    assert status_change(bb, "accept_heard") is None


def test_the_screen_exempts_a_value_that_is_public_and_a_private_bound() -> None:
    bound = mandate(max_monthly_price_minor=6500)
    said = board(mandate=bound, cp=(rep("c1", "I can do $65 a month."),))
    assert screen("We could do $65 a month.", said) == ()
    offered = board(confirm(offer(monthly="6500")), mandate=bound)
    assert screen("So that is 65 dollars a month?", offered) == ()
    assert screen("We can pay up to $65.00.", board(mandate=bound)) == ("mandate:65",)
    assert screen("Twelve months is fine.", board(mandate=bound)) == ()


def test_the_screen_flags_protected_values_always() -> None:
    pin = Fact(key="account.pin", value="1234", protected=True)
    bb = board(facts=(pin,), cp=(rep("c1", "Is it 1234?"),))
    assert screen("The PIN is 1234.", bb) == ("protected:account.pin",)
    public = PublicFact(
        key="tenure_years", value="24", source="shareable", source_ref="u1"
    )
    bb = board(mandate=mandate()).model_copy(update={})
    bb = bb.model_copy(
        update={
            "public": bb.public.model_copy(update={"facts": {"tenure_years": public}})
        }
    )
    # a shareable fact equal to a bound never makes the bound speakable (#126)
    assert screen("I have been a customer 24 months.", bb) == ("mandate:24",)
    assert screen("I can sign for 24 months.", board(mandate=mandate())) == (
        "mandate:24",
    )


def _with_facts(bb: Blackboard, *facts: PublicFact) -> Blackboard:
    public = bb.public.model_copy(update={"facts": {f.key: f for f in facts}})
    return bb.model_copy(update={"public": public})


def test_a_shareable_fact_never_exempts_a_bound_or_a_protected_value() -> None:
    """Reviewer probe: max $70 and a public shareable last4 "0070"."""
    last4 = PublicFact(
        key="account.last4", value="0070", source="shareable", source_ref="u1"
    )
    bb = _with_facts(board(mandate=mandate(max_monthly_price_minor=7000)), last4)
    assert screen("I can go up to 70 dollars", bb) == ("mandate:70",)
    pin = Fact(key="account.pin", value="2400", protected=True)
    tenure = PublicFact(
        key="tenure_years", value="6", source="shareable", source_ref="u1"
    )
    bb = _with_facts(board(mandate=mandate(), facts=(pin,)), tenure)
    assert screen("Six years, so 6 it is.", bb) == ()  # not a bound: public
    said = PublicFact(key="offer.term", value="24", source="cp_utt", source_ref="c1")
    rep_said = _with_facts(board(mandate=mandate()), said)
    assert screen("So 24 months, as you said.", rep_said) == ()  # the rep's number


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("O'Brien", "Is that OBRIEN?"),
        ("Lee-Smith", "The holder is lee smith."),
        ("7777", "The code is 77-77."),
        ("7777", "The code is " + "\N{FULLWIDTH DIGIT SEVEN}" * 4 + "."),
        ("王小明", "Holder 王小明."),  # any script
    ],
)
def test_the_screen_flags_protected_values_in_any_spelling(
    value: str, text: str
) -> None:
    """The same canonical forms as declass: words, letters, any-script digits."""
    secret = Fact(key="account.secret", value=value, protected=True)
    assert screen(text, board(facts=(secret,))) == ("protected:account.secret",)
