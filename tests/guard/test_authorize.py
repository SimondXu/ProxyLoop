"""The rules (ARCHITECTURE §9.3): every rule x every denial reason, then the grants."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from tests.guard.build import (
    CASE,
    FENCE,
    approval,
    board,
    card,
    confirm,
    mandate,
    offer,
)

from proxyloop.contract.events import ApprovalPost
from proxyloop.contract.state import (
    ApprovalCard,
    Blackboard,
    Capability,
    Fact,
    OfferPublic,
)
from proxyloop.guard.authorize import (
    CARD_TTL_MS,
    REASONS,
    Denial,
    accept_offer,
    decide,
    decline_offer,
    request_approval,
    share_fact,
)
from proxyloop.guard.capability import business_action_id
from proxyloop.guard.mandate import mandate_hash, proposal

O1 = confirm(offer())
PIN = Fact(key="account.pin", value="1234", protected=True)
Rule = Callable[[Blackboard], object]


def _accept(ref: str = "o1") -> Rule:
    return lambda bb: accept_offer(bb, ref, CASE)


def _request(ref: str = "o1") -> Rule:
    return lambda bb: request_approval(bb, ref, CASE)


def _post(subject: str, sid: str, h: str, epoch: int = 0) -> ApprovalPost:
    return ApprovalPost.model_validate(
        {
            "subject": subject,
            "subject_id": sid,
            "decision": "granted",
            "subject_hash": h,
            "authority_epoch": epoch,
        }
    )


def _decide(post: ApprovalPost) -> Rule:
    return lambda bb: decide(bb, post, "ui")


def _cap(bid: str, consumed: bool = False) -> Capability:
    assert O1.terms_hash is not None
    return Capability(
        cap_id="cap-9",
        business_action_id=bid,
        intent="accept_offer",
        terms_hash=O1.terms_hash,
        epoch=0,
        expires_ms=9_000,
        consumed=consumed,
    )


assert O1.terms_hash is not None
_BID = business_action_id("case-1", "accept_offer", "o1", 1, O1.terms_hash, "apr-1")
_EXPIRED: OfferPublic = O1.model_copy(update={"expires_ms": 500})
_CLOSED: OfferPublic = O1.model_copy(update={"status": "declined"})
_UNSUPPORTED = confirm(offer(change="free_phone"))
_GOOD = approval(O1)
_CARD: ApprovalCard = card(O1)
_OFFER_REASONS: list[tuple[str, Blackboard]] = [
    ("fence_raised", board(O1, fences=(FENCE,), approvals=(_GOOD,))),
    ("no_such_offer", board(approvals=(_GOOD,))),
    ("offer_not_open", board(_CLOSED, approvals=(_GOOD,))),
    ("offer_expired", board(_EXPIRED, approvals=(_GOOD,))),
    ("readback_not_confirmed", board(offer(), approvals=(_GOOD,))),
    ("policy_violation", board(_UNSUPPORTED, approvals=(approval(_UNSUPPORTED),))),
]
CASES: list[tuple[str, str, Rule, Blackboard]] = [
    *(("accept_offer", r, _accept(), bb) for r, bb in _OFFER_REASONS),
    *(("request_approval", r, _request(), bb) for r, bb in _OFFER_REASONS),
    ("request_approval", "approval_pending", _request(), board(O1, pending=_CARD)),
    (
        "accept_offer",
        "approval_denied",
        _accept(),
        board(O1, approvals=(approval(O1, "denied"),)),
    ),
    (
        "accept_offer",
        "approval_stale_epoch",
        _accept(),
        board(O1, approvals=(_GOOD,), epoch=1),
    ),
    (
        "accept_offer",
        "mandate_stale_epoch",
        _accept(),
        board(O1, mandate=mandate(), epoch=1),
    ),
    (
        "accept_offer",
        "mandate_expired",
        _accept(),
        board(O1, mandate=mandate(expires_ms=900)),
    ),
    (
        "accept_offer",
        "outside_mandate",
        _accept(),
        board(O1, mandate=mandate(max_monthly_price_minor=6500)),
    ),
    ("accept_offer", "not_authorized", _accept(), board(O1)),
    (
        "accept_offer",
        "not_authorized",
        _accept(),
        board(O1, mandate=mandate("proposed")),
    ),
    (
        "accept_offer",
        "already_authorized",
        _accept(),
        board(O1, approvals=(_GOOD,), caps=(_cap(_BID),)),
    ),
    ("decline_offer", "no_such_offer", lambda bb: decline_offer(bb, "zz"), board(O1)),
    (
        "decline_offer",
        "offer_not_open",
        lambda bb: decline_offer(bb, "o1"),
        board(_CLOSED),
    ),
    (
        "share_fact",
        "protected",
        lambda bb: share_fact(bb, "account.pin", frozenset({"account.pin"})),
        board(facts=(PIN,)),
    ),
    (
        "share_fact",
        "not_shareable",
        lambda bb: share_fact(bb, "tenure_years", frozenset()),
        board(),
    ),
    (
        "decide_approval",
        "already_decided",
        _decide(_post("approval", "apr-1", O1.terms_hash)),
        board(O1, approvals=(_GOOD,)),
    ),
    (
        "decide_approval",
        "no_pending_card",
        _decide(_post("approval", "apr-1", O1.terms_hash)),
        board(O1),
    ),
    (
        "decide_approval",
        "no_pending_card",
        _decide(_post("approval", "apr-2", O1.terms_hash)),
        board(O1, pending=_CARD),
    ),
    (
        "decide_approval",
        "subject_hash_mismatch",
        _decide(_post("approval", "apr-1", "x")),
        board(O1, pending=_CARD),
    ),
    (
        "decide_approval",
        "stale_epoch",
        _decide(_post("approval", "apr-1", O1.terms_hash, 1)),
        board(O1, pending=_CARD),
    ),
    (
        "decide_approval",
        "stale_epoch",
        _decide(_post("approval", "apr-1", O1.terms_hash)),
        board(O1, pending=_CARD, epoch=1),
    ),
    (
        "decide_approval",
        "card_expired",
        _decide(_post("approval", "apr-1", O1.terms_hash)),
        board(O1, pending=card(O1, expires_ms=1_000)),
    ),
    (
        "decide_approval",
        "card_superseded",
        _decide(_post("approval", "apr-1", O1.terms_hash)),
        board(confirm(offer(monthly="6500")), pending=_CARD),
    ),
    (
        "decide_mandate",
        "already_decided",
        _decide(_post("mandate", "m1", "mh1")),
        board(mandate=mandate()),
    ),
    ("decide_mandate", "no_proposal", _decide(_post("mandate", "m1", "mh1")), board()),
    (
        "decide_mandate",
        "no_proposal",
        _decide(_post("mandate", "m9", "mh1")),
        board(mandate=mandate("proposed")),
    ),
    (
        "decide_mandate",
        "subject_hash_mismatch",
        _decide(_post("mandate", "m1", "x")),
        board(mandate=mandate("proposed")),
    ),
    (
        "decide_mandate",
        "stale_epoch",
        _decide(_post("mandate", "m1", "mh1")),
        board(mandate=mandate("proposed"), epoch=1),
    ),
    (
        "decide_mandate",
        "stale_epoch",
        _decide(_post("mandate", "m1", "mh1")),
        board(mandate=mandate("proposed", epoch=1), epoch=1),
    ),
]


@pytest.mark.parametrize(("rule", "reason", "call", "bb"), CASES)
def test_each_denial(rule: str, reason: str, call: Rule, bb: Blackboard) -> None:
    assert reason in REASONS[rule]
    assert call(bb) == Denial(reason)


def test_the_table_covers_every_rule_and_reason() -> None:
    covered = {(rule, reason) for rule, reason, _, _ in CASES}
    assert covered == {(r, x) for r, reasons in REASONS.items() for x in reasons}


def test_an_approval_grants_an_accept_only_in_its_own_epoch() -> None:
    same = accept_offer(
        board(O1, approvals=(approval(O1, epoch=2),), epoch=2), "o1", CASE
    )
    assert not isinstance(same, Denial)
    (authorized, auth), (verbatim, line) = same
    assert (authorized, verbatim) == ("action.authorized", "speak.verbatim")
    cap = Capability.model_validate(auth["capability"])
    assert (cap.epoch, cap.terms_hash, cap.consumed) == (2, O1.terms_hash, False)
    assert line["kind"] == "accept" and line["cap_id"] == cap.cap_id
    assert "$68.00" in str(line["text"])
    later = board(O1, approvals=(approval(O1, epoch=2),), epoch=3)
    assert accept_offer(later, "o1", CASE) == Denial("approval_stale_epoch")


def test_a_covering_mandate_grants_without_an_approval() -> None:
    effects = accept_offer(board(O1, mandate=mandate()), "o1", CASE)
    assert not isinstance(effects, Denial)
    cap = Capability.model_validate(effects[0][1]["capability"])
    assert cap.business_action_id == business_action_id(
        "case-1", "accept_offer", "o1", 1, str(O1.terms_hash), "mh1"
    )


def test_request_approval_mints_a_bound_card_even_outside_the_mandate() -> None:
    bb = board(O1, mandate=mandate(max_monthly_price_minor=6500), epoch=1)
    effects = request_approval(bb, "o1", CASE)
    assert not isinstance(effects, Denial)
    ((kind, payload),) = effects
    got = ApprovalCard.model_validate(payload)
    assert kind == "approval.requested"
    assert (got.offer_ref, got.revision, got.terms_hash) == ("o1", 1, O1.terms_hash)
    assert got.authority_epoch == got.binding.authority_epoch == 1
    assert got.expires_ms > bb.t_ms and "$68.00" in got.readback_text


def test_decisions_join_their_card_or_proposal() -> None:
    effect = decide(
        board(O1, pending=_CARD),
        _post("approval", "apr-1", str(O1.terms_hash)),
        "sim_approver",
    )
    assert effect == (
        "approval.decided",
        {"approval_id": "apr-1", "decision": "granted", "by": "sim_approver"},
    )
    m = mandate("proposed")
    m = m.model_copy(update={"mandate_hash": mandate_hash(m)})
    got = decide(board(mandate=m), _post("mandate", "m1", m.mandate_hash), "ui")
    assert got == (
        "mandate.decided",
        {
            "mandate_id": "m1",
            "mandate_hash": m.mandate_hash,
            "decision": "granted",
            "by": "ui",
        },
    )


def test_a_proposal_is_bound_to_its_hash_and_epoch() -> None:
    kind, payload = proposal(board(epoch=3), "m2", max_term_months=12)
    assert kind == "mandate.proposed"
    assert payload["status"] == "proposed" and payload["epoch"] == 3
    other = proposal(board(epoch=3), "m2", max_term_months=24)[1]
    assert payload["mandate_hash"] != other["mandate_hash"]


def test_restrictions_pass_while_a_fence_is_raised() -> None:
    effects = decline_offer(board(O1, fences=(FENCE,)), "o1")
    assert effects == (
        (
            "speak.verbatim",
            {
                "lane": "cp",
                "kind": "decline",
                "text": "No, thank you: we will not take that offer.",
                "offer_ref": "o1",
            },
        ),
    )
    assert share_fact(board(), "tenure_years", frozenset({"tenure_years"})) is None


def test_a_card_expires_with_its_offer_or_its_ttl_whichever_is_first() -> None:
    far = O1.model_copy(update={"expires_ms": 10**9})
    soon = O1.model_copy(update={"expires_ms": 5_000})
    for o, until in (
        (far, 1_000 + CARD_TTL_MS),
        (soon, 5_000),
        (O1, 1_000 + CARD_TTL_MS),
    ):
        effects = request_approval(board(o), "o1", CASE)
        assert not isinstance(effects, Denial)
        assert ApprovalCard.model_validate(effects[0][1]).expires_ms == until


def test_a_denial_is_checked_before_the_mandate() -> None:
    """A user's denial of these terms overrides a covering mandate in its epoch."""
    denied = board(O1, mandate=mandate(), approvals=(approval(O1, "denied"),))
    assert accept_offer(denied, "o1", CASE) == Denial("approval_denied")
    later = denied.model_copy(
        update={
            "epoch": 1,
            "private": denied.private.model_copy(update={"mandate": mandate(epoch=1)}),
        }
    )
    assert not isinstance(accept_offer(later, "o1", CASE), Denial)  # a new epoch
