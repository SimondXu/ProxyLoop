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
    CaseStatus,
    Fact,
    OfferPublic,
)
from proxyloop.guard.authorize import (
    CARD_TTL_MS,
    REASONS,
    Denial,
    Effect,
    accept_offer,
    decide,
    decline_offer,
    request_approval,
    share_fact,
)
from proxyloop.guard.capability import CAP_TTL_MS, business_action_id
from proxyloop.guard.mandate import mandate_hash, proposal
from proxyloop.guard.status import TERMINAL

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


def _status(status: CaseStatus) -> Blackboard:
    bb = board(O1, approvals=(_GOOD,))
    return bb.model_copy(
        update={"public": bb.public.model_copy(update={"status": status})}
    )


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
    (
        "accept_offer",
        "approval_expired",
        _accept(),
        board(O1, approvals=(approval(O1, expires_ms=1_000),)),  # t_ms 1_000
    ),
    (
        "accept_offer",
        "already_accepted",  # another grant's capability was released
        _accept(),
        board(O1, approvals=(_GOOD,), caps=(_cap("other", consumed=True),)),
    ),
    ("accept_offer", "already_committed", _accept(), _status(CaseStatus.COMMITTED)),
    ("accept_offer", "case_closed", _accept(), _status(CaseStatus.VERIFIED_NO_DEAL)),
    ("accept_offer", "not_in_call", _accept(), _status(CaseStatus.NEEDS_REPLAN)),
    (
        "accept_offer",
        "accept_in_flight",
        _accept(),
        board(O1, approvals=(_GOOD,), caps=(_cap("other"),)),
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


def _cap_of(effects: tuple[Effect, ...] | Denial) -> Capability:
    assert not isinstance(effects, Denial), effects
    return Capability.model_validate(effects[0][1]["capability"])


def test_a_denial_blocks_whatever_its_expiry() -> None:
    """ADR-0007 regression: card0 denied (expires 120), card1 granted (expires
    126), same terms and epoch: at t=121 no capability is minted."""
    for denied_until in (120, None):
        bb = board(
            O1,
            approvals=(
                approval(O1, "denied", expires_ms=denied_until, approval_id="c0"),
                approval(O1, expires_ms=126, approval_id="c1"),
            ),
            t_ms=121,
        )
        assert accept_offer(bb, "o1", CASE) == Denial("approval_denied")


def test_any_unexpired_grant_counts_not_only_the_first() -> None:
    bb = board(
        O1,
        approvals=(
            approval(O1, expires_ms=500, approval_id="old"),  # expired at t=1_000
            approval(O1, expires_ms=None, approval_id="unknown"),  # never counts
            approval(O1, expires_ms=5_000, approval_id="live"),
        ),
    )
    cap = _cap_of(accept_offer(bb, "o1", CASE))
    assert cap.business_action_id == business_action_id(
        "case-1", "accept_offer", "o1", 1, str(O1.terms_hash), "live"
    )
    assert cap.expires_ms == 5_000


@pytest.mark.parametrize("expires_ms", [None, 999, 1_000])
def test_a_grant_without_a_live_expiry_mints_nothing(expires_ms: int | None) -> None:
    """ADR-0007: ``None`` is expired for a grant (fail closed); expiry at t is
    past (t_ms 1_000)."""
    bb = board(O1, approvals=(approval(O1, expires_ms=expires_ms),))
    assert accept_offer(bb, "o1", CASE) == Denial("approval_expired")
    earlier = accept_offer(bb.model_copy(update={"t_ms": 998}), "o1", CASE)
    assert isinstance(earlier, Denial) == (expires_ms is None)  # None: never live


TTL_END = 1_000 + CAP_TTL_MS  # board t_ms 1_000


@pytest.mark.parametrize(
    ("approval_until", "offer_until", "cap_until"),
    [
        (1_001, None, 1_001),  # the approval, one ms after now
        (5_000, None, 5_000),  # the approval
        (5_000, 4_000, 4_000),  # the offer
        (5_000, 5_000, 5_000),  # a tie
        (TTL_END, None, TTL_END),  # the approval equals the TTL
        (TTL_END + 1, None, TTL_END),  # the TTL
        (10**9, TTL_END + 5, TTL_END),  # the TTL, before the offer
        (10**9, TTL_END - 5, TTL_END - 5),  # the offer, before the TTL
    ],
)
def test_capability_expiry_is_the_min_of_approval_offer_and_ttl(
    approval_until: int, offer_until: int | None, cap_until: int
) -> None:
    o = O1.model_copy(update={"expires_ms": offer_until})
    bb = board(o, approvals=(approval(o, expires_ms=approval_until),))
    assert _cap_of(accept_offer(bb, "o1", CASE)).expires_ms == cap_until


def test_a_mandate_grant_ignores_approval_expiry() -> None:
    """A covering mandate grants on its own; its expiry, not an approval's."""
    bb = board(
        O1,
        mandate=mandate(expires_ms=7_000),
        approvals=(approval(O1, expires_ms=3_000),),
    )
    assert _cap_of(accept_offer(bb, "o1", CASE)).expires_ms == 7_000


@pytest.mark.parametrize("status", list(CaseStatus))
def test_only_in_call_mints_an_accept(status: CaseStatus) -> None:
    """ARCHITECTURE §9.5: accept_authorized leaves IN_CALL only; NEEDS_REPLAN
    replans to IN_CALL first."""
    got = accept_offer(_status(status), "o1", CASE)
    if status in (CaseStatus.COMMITTED, CaseStatus.EVIDENCE_PENDING):
        assert got == Denial("already_committed")
    elif status in TERMINAL:
        assert got == Denial("case_closed")
    elif status is CaseStatus.IN_CALL:
        assert not isinstance(got, Denial), got
    else:
        assert got == Denial("not_in_call")


def test_one_accept_in_flight_per_case() -> None:
    """A queued (unreleased, unrevoked) accept of any offer blocks another."""
    bb = board(O1, approvals=(_GOOD,), caps=(_cap("other"),))
    assert accept_offer(bb, "o1", CASE) == Denial("accept_in_flight")


def test_after_a_released_accept_a_mandate_no_longer_grants() -> None:
    """A retry needs a new revision and a new approval (main root decision)."""
    o2 = confirm(offer(monthly="6500").model_copy(update={"revision": 2}))
    done = board(o2, mandate=mandate(), caps=(_cap("r1", consumed=True),))
    assert accept_offer(done, "o1", CASE) == Denial("not_authorized")
    approved = board(
        o2,
        mandate=mandate(),
        caps=(_cap("r1", consumed=True),),
        approvals=(approval(o2),),
    )
    assert not isinstance(accept_offer(approved, "o1", CASE), Denial)
