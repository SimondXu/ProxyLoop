"""The deterministic sim approver (ARCHITECTURE §10.2): cards and mandates from
the principal's hidden constraints, as the posts the endpoint would receive."""

from __future__ import annotations

from typing import Any

import pytest
from tests.env.cards import card as _card
from tests.env.cards import offer as _offer

from proxyloop.contract.state import Mandate, OfferPublic
from proxyloop.env.tasks.loader import load_task
from proxyloop.env.user.approver import Approver

TASK = load_task("x-out-of-envelope-approval")  # envelope $65, limits $72, no fees


def _mandate(**bounds: int | None) -> Mandate:
    fields: dict[str, Any] = {"mandate_id": "m1", "mandate_hash": "mh", "epoch": 2}
    fields |= {"status": "proposed", "max_monthly_price_minor": 6500}
    fields |= {"max_term_months": 24, "max_one_time_fees_minor": 0}
    return Mandate.model_validate(fields | bounds)


def test_a_card_within_the_limits_is_granted_bound_to_the_card() -> None:
    out = Approver(TASK, seed=1).decide(_card(), _offer(6900))  # above the envelope
    assert out.post.model_dump() == {
        "subject": "approval",
        "subject_id": "apr-1",
        "decision": "granted",
        "subject_hash": "h1",
        "authority_epoch": 3,
    }
    assert out.reasons == ()
    lo, hi = TASK.principal.approver_delay_s.range if TASK.principal else (0, 0)
    assert lo <= out.delay_s <= hi


@pytest.mark.parametrize(
    ("offer", "reason"),
    [
        (_offer(7300), "monthly_price_over"),
        (_offer(6900, months=36), "term_months_over"),
        (_offer(6900, activation=1), "one_time_fees_over"),
    ],
)
def test_a_card_over_a_limit_is_denied(offer: OfferPublic, reason: str) -> None:
    out = Approver(TASK, seed=1).decide(_card(), offer)
    assert out.post.decision == "denied" and out.reasons == (reason,)


def test_the_delay_is_seeded_and_its_own_stream() -> None:
    a, b = Approver(TASK, seed=5), Approver(TASK, seed=5)
    delays = [a.decide(_card(), _offer(6900)).delay_s for _ in range(3)]
    assert delays == [b.decide(_card(), _offer(6900)).delay_s for _ in range(3)]
    assert len(set(delays)) == 3


def test_a_card_must_come_with_its_offer_and_readable_slots() -> None:
    with pytest.raises(ValueError, match="card's offer and revision"):
        newer = _offer(6900).model_copy(update={"revision": 2})
        Approver(TASK, seed=1).decide(_card(), newer)
    bad = _offer(6900).model_copy(update={"slots": _offer(6900).slots[1:]})
    with pytest.raises(ValueError, match="monthly_price"):
        Approver(TASK, seed=1).decide(_card(), bad)


def test_a_mandate_is_granted_only_no_looser_than_the_stated_envelope() -> None:
    a = Approver(TASK, seed=1)
    ok = a.decide_mandate(_mandate())
    assert ok.post.decision == "granted"
    assert (ok.post.subject, ok.post.subject_hash, ok.post.authority_epoch) == (
        "mandate",
        "mh",
        2,
    )
    tighter = a.decide_mandate(_mandate(max_monthly_price_minor=6000))
    assert tighter.post.decision == "granted"
    looser = a.decide_mandate(_mandate(max_monthly_price_minor=7000))  # < limits
    assert looser.reasons == ("monthly_minor_looser",)
    unbounded = a.decide_mandate(_mandate(max_one_time_fees_minor=None))
    assert unbounded.reasons == ("fees_minor_looser",)


def test_after_a_stop_everything_is_denied() -> None:
    a = Approver(TASK, seed=1)
    a.stop(None)
    assert a.decide(_card(), _offer(6900)).reasons == ("stopped",)
    assert a.decide_mandate(_mandate()).reasons == ("stopped",)


def test_after_a_mind_change_the_limits_drop_to_the_changed_envelope() -> None:
    a = Approver(TASK, seed=1)
    a.stop({"budget.max_monthly_usd": "68"})
    assert a.decide(_card(), _offer(6900)).reasons == ("monthly_price_over",)
    assert a.decide(_card(), _offer(6800)).post.decision == "granted"
    assert a.decide_mandate(_mandate(max_monthly_price_minor=6800)).reasons == ()


def test_a_task_without_a_principal_has_no_approver() -> None:
    with pytest.raises(ValueError, match="no principal"):
        Approver(load_task("cp-direct-discount"), seed=1)
