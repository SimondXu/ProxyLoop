from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from proxyloop_contracts import (
    Case,
    CompletionDecision,
    CompletionOutcome,
    LineItem,
    LineItemCategory,
    Money,
    ProviderOffer,
)
from proxyloop_provider_simulator.episode import Phase01AEpisode
from proxyloop_telecom_domain import (
    CompletionVerification,
    OfferComplianceContext,
    OfferComplianceTerms,
    case_offer_violations,
    offer_compliance_violations,
    verify_completion,
)
from pydantic import BaseModel

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def make_context(
    *,
    evaluated_at: datetime = NOW,
    current_monthly_minor: int = 9_000,
    currency: str = "USD",
    target_monthly_minor: int | None = 7_500,
    target_currency: str | None = "USD",
    required_features: tuple[str, ...] = ("mobile_hotspot",),
    forbidden_changes: tuple[str, ...] = ("device_financing_change",),
) -> OfferComplianceContext:
    return OfferComplianceContext(
        evaluated_at=evaluated_at,
        current_monthly_minor=current_monthly_minor,
        currency=currency,
        target_monthly_minor=target_monthly_minor,
        target_currency=target_currency,
        required_features=required_features,
        forbidden_changes=forbidden_changes,
    )


def make_terms(
    *,
    monthly_price_minor: int = 7_200,
    total_cost_12_months_minor: int = 86_400,
    currency: str = "USD",
    fees_minor: int = 0,
    features: tuple[str, ...] = ("mobile_hotspot",),
    applied_changes: tuple[str, ...] = ("plan_change",),
    expires_at: datetime = NOW + timedelta(hours=1),
) -> OfferComplianceTerms:
    return OfferComplianceTerms(
        monthly_price_minor=monthly_price_minor,
        total_cost_12_months_minor=total_cost_12_months_minor,
        currency=currency,
        fees_minor=fees_minor,
        features=features,
        applied_changes=applied_changes,
        expires_at=expires_at,
    )


def test_direct_success_has_no_policy_violations() -> None:
    assert offer_compliance_violations(make_context(), make_terms()) == ()


def test_fee_total_trap_is_rejected_with_explicit_fee_consistency() -> None:
    violations = offer_compliance_violations(
        make_context(),
        make_terms(fees_minor=30_000, total_cost_12_months_minor=116_400),
    )

    assert violations == ("total_cost_target_exceeded",)

    inconsistent = offer_compliance_violations(
        make_context(),
        make_terms(fees_minor=30_000, total_cost_12_months_minor=86_400),
    )
    assert inconsistent == ("fee_total_mismatch",)


def test_promotion_credit_uses_only_the_bounded_catalogued_amount() -> None:
    exact = offer_compliance_violations(
        make_context(),
        make_terms(
            total_cost_12_months_minor=81_400,
            applied_changes=("predefined_promotion_credit",),
        ),
    )
    assert exact == ()

    zero_credit = offer_compliance_violations(
        make_context(),
        make_terms(
            total_cost_12_months_minor=86_400,
            applied_changes=("predefined_promotion_credit",),
        ),
    )
    assert zero_credit == ("fee_total_mismatch",)

    unknown_credit = offer_compliance_violations(
        make_context(),
        make_terms(
            total_cost_12_months_minor=81_400,
            applied_changes=("unknown_promotion_credit",),
        ),
    )
    assert unknown_credit == ("fee_total_mismatch",)

    fees_included = offer_compliance_violations(
        make_context(),
        make_terms(
            total_cost_12_months_minor=82_400,
            fees_minor=1_000,
            applied_changes=("predefined_promotion_credit",),
        ),
    )
    assert fees_included == ()


@pytest.mark.parametrize(
    ("context", "terms", "expected"),
    [
        (
            make_context(),
            make_terms(expires_at=NOW),
            "offer_expired",
        ),
        (
            make_context(),
            make_terms(currency="EUR"),
            "currency_mismatch",
        ),
        (
            make_context(),
            make_terms(monthly_price_minor=9_000),
            "recurring_price_not_reduced",
        ),
        (
            make_context(target_monthly_minor=None),
            make_terms(total_cost_12_months_minor=108_000),
            "total_cost_exceeds_current",
        ),
        (
            make_context(),
            make_terms(features=()),
            "required_feature_missing",
        ),
        (
            make_context(),
            make_terms(applied_changes=("device_financing_change",)),
            "forbidden_change_present",
        ),
    ],
)
def test_policy_reason_codes_cover_each_constraint(
    context: OfferComplianceContext,
    terms: OfferComplianceTerms,
    expected: str,
) -> None:
    assert expected in offer_compliance_violations(context, terms)


def test_target_currency_is_part_of_context_currency_check() -> None:
    violations = offer_compliance_violations(
        make_context(target_currency="EUR"), make_terms()
    )

    assert violations == ("currency_mismatch",)


def test_completion_verifier_uses_policy_for_total_cost_trap() -> None:
    episode = Phase01AEpisode.success()
    episode.issue_offer()
    episode.request_approval()
    episode.approve()
    episode.execute()
    episode.verify()
    assert episode.completion_decision is not None
    assert episode.offer is not None
    assert episode.action_intent is not None
    assert episode.approval_request is not None
    assert episode.confirmation is not None
    assert episode.confirmation_evidence is not None
    trap_offer = episode.offer.model_copy(
        update={
            "total_cost": Money(amount_minor=116_400, currency="USD"),
        }
    )
    decision = verify_completion(
        CompletionVerification(
            completion_id=episode.completion_decision.completion_id,
            case=episode.case,
            offer=trap_offer,
            action_intent=episode.action_intent,
            approval_request=episode.approval_request,
            confirmation=episode.confirmation,
            evidence=episode.confirmation_evidence,
            confirmation_authority=episode.provider,
            executed_at=episode.confirmation.confirmed_at,
            evaluated_at=episode.completion_decision.evaluated_at,
        )
    )

    assert "total_cost_target_exceeded" in decision.reason_codes


def test_completion_verifier_rejects_an_offer_from_another_case() -> None:
    # B1-8: every other binding in the request names the case; the offer must
    # too, or a confirmation could be verified against a foreign offer.
    episode = Phase01AEpisode.success()
    episode.issue_offer()
    episode.request_approval()
    episode.approve()
    episode.execute()
    episode.verify()
    assert episode.completion_decision is not None
    assert episode.offer is not None
    assert episode.action_intent is not None
    assert episode.approval_request is not None
    assert episode.confirmation is not None
    assert episode.confirmation_evidence is not None
    foreign_offer = episode.offer.model_copy(
        update={"case_id": UUID("0f0f0f0f-0f0f-4f0f-8f0f-0f0f0f0f0f0f")}
    )
    decision = verify_completion(
        CompletionVerification(
            completion_id=episode.completion_decision.completion_id,
            case=episode.case,
            offer=foreign_offer,
            action_intent=episode.action_intent,
            approval_request=episode.approval_request,
            confirmation=episode.confirmation,
            evidence=episode.confirmation_evidence,
            confirmation_authority=episode.provider,
            executed_at=episode.confirmation.confirmed_at,
            evaluated_at=episode.completion_decision.evaluated_at,
        )
    )

    assert decision.decision is CompletionOutcome.NEEDS_REPLAN
    assert decision.reason_codes == ("offer_case_mismatch",)


# B1-9: the Case-vs-offer policy check is total. ``LineItem.amount`` may be
# negative by contract (a credit line) and contract tuples may repeat a token;
# neither may raise out of the check. Each fails closed as a reason code.

NEGATIVE_CREDIT = LineItem(
    name="Loyalty credit",
    category=LineItemCategory.CREDIT,
    amount=Money(amount_minor=-1_000, currency="USD"),
)


def _wire_valid[T: BaseModel](value: T) -> T:
    """Round-trip the strict JSON wire form so the input is contract-valid."""

    return type(value).model_validate_json(value.model_dump_json())


def _completed_episode() -> Phase01AEpisode:
    episode = Phase01AEpisode.success()
    episode.issue_offer()
    episode.request_approval()
    episode.approve()
    episode.execute()
    episode.verify()
    return episode


def _verify_with_offer(
    episode: Phase01AEpisode, offer: ProviderOffer
) -> CompletionDecision:
    assert episode.completion_decision is not None
    assert episode.action_intent is not None
    assert episode.approval_request is not None
    assert episode.confirmation is not None
    assert episode.confirmation_evidence is not None
    return verify_completion(
        CompletionVerification(
            completion_id=episode.completion_decision.completion_id,
            case=episode.case,
            offer=offer,
            action_intent=episode.action_intent,
            approval_request=episode.approval_request,
            confirmation=episode.confirmation,
            evidence=episode.confirmation_evidence,
            confirmation_authority=episode.provider,
            executed_at=episode.confirmation.confirmed_at,
            evaluated_at=episode.completion_decision.evaluated_at,
        )
    )


def test_completion_verifier_fails_closed_on_a_negative_fee_sum() -> None:
    episode = _completed_episode()
    assert episode.offer is not None
    credited = _wire_valid(
        episode.offer.model_copy(update={"fees": (NEGATIVE_CREDIT,)})
    )

    decision = _verify_with_offer(episode, credited)

    assert decision.decision is CompletionOutcome.NEEDS_REPLAN
    assert "offer_terms_invalid" in decision.reason_codes
    assert decision.evidence_ids == ()


def test_completion_verifier_fails_closed_on_duplicate_offer_features() -> None:
    episode = _completed_episode()
    assert episode.offer is not None
    features = episode.offer.features
    repeated = _wire_valid(
        episode.offer.model_copy(update={"features": (*features, features[0])})
    )

    decision = _verify_with_offer(episode, repeated)

    assert decision.decision is CompletionOutcome.NEEDS_REPLAN
    assert "offer_terms_invalid" in decision.reason_codes


def test_case_offer_violations_returns_a_reason_code_for_each_invalid_input() -> None:
    episode = Phase01AEpisode.success()
    offer = episode.issue_offer()
    case = episode.case
    at = offer.created_at

    credited = _wire_valid(offer.model_copy(update={"fees": (NEGATIVE_CREDIT,)}))
    assert case_offer_violations(case, credited, evaluated_at=at) == (
        "offer_terms_invalid",
    )
    assert case_offer_violations(
        case, offer, evaluated_at=at, applied_changes=("plan_change", "plan_change")
    ) == ("offer_terms_invalid",)

    required = case.goal.required_features
    repeated_goal = case.goal.model_copy(
        update={"required_features": (*required, *required)}
    )
    repeated_case = _wire_valid(case.model_copy(update={"goal": repeated_goal}))
    assert case_offer_violations(repeated_case, offer, evaluated_at=at) == (
        "compliance_context_invalid",
    )

    billless = _wire_valid(case.model_copy(update={"bill_snapshot": None}))
    assert case_offer_violations(billless, offer, evaluated_at=at) == (
        "missing_bill_snapshot",
    )


@pytest.mark.parametrize(
    "evaluated_at",
    [
        datetime(2026, 8, 24, 12, 0),
        datetime(2026, 8, 24, 14, 0, tzinfo=timezone(timedelta(hours=2))),
    ],
    ids=["naive", "non_utc_offset"],
)
def test_case_offer_violations_raises_on_a_non_utc_evaluation_time(
    evaluated_at: datetime,
) -> None:
    # A non-UTC clock is a caller bug, not offer data: it must not be masked
    # as ``compliance_context_invalid``, even before the bill check.
    episode = Phase01AEpisode.success()
    offer = episode.issue_offer()
    billless = _wire_valid(episode.case.model_copy(update={"bill_snapshot": None}))

    for case in (episode.case, billless):
        with pytest.raises(ValueError, match="evaluated_at must be timezone-aware"):
            case_offer_violations(case, offer, evaluated_at=evaluated_at)


# Every input of the policy tables above, lifted into contract-valid Case and
# offer objects: on valid input the Case-level check returns exactly what the
# policy returns, so no existing decision or reason code moves.
POLICY_TABLE_INPUTS: list[tuple[OfferComplianceContext, OfferComplianceTerms]] = [
    (make_context(), make_terms()),
    (make_context(), make_terms(fees_minor=30_000, total_cost_12_months_minor=116_400)),
    (make_context(), make_terms(fees_minor=30_000, total_cost_12_months_minor=86_400)),
    *(
        (
            make_context(),
            make_terms(
                total_cost_12_months_minor=total,
                fees_minor=fees,
                applied_changes=(change,),
            ),
        )
        for total, fees, change in (
            (81_400, 0, "predefined_promotion_credit"),
            (86_400, 0, "predefined_promotion_credit"),
            (81_400, 0, "unknown_promotion_credit"),
            (82_400, 1_000, "predefined_promotion_credit"),
        )
    ),
    (make_context(), make_terms(expires_at=NOW)),
    (make_context(), make_terms(currency="EUR")),
    (make_context(), make_terms(monthly_price_minor=9_000)),
    (
        make_context(target_monthly_minor=None),
        make_terms(total_cost_12_months_minor=108_000),
    ),
    (make_context(), make_terms(features=())),
    (make_context(), make_terms(applied_changes=("device_financing_change",))),
    (make_context(target_currency="EUR"), make_terms()),
]


def _money(amount_minor: int, currency: str) -> Money:
    return Money(amount_minor=amount_minor, currency=currency)


def _lift(
    context: OfferComplianceContext, terms: OfferComplianceTerms
) -> tuple[Case, ProviderOffer]:
    episode = Phase01AEpisode.success()
    offer = episode.issue_offer()
    case = episode.case
    assert case.bill_snapshot is not None
    current = _money(context.current_monthly_minor, context.currency)
    bill = case.bill_snapshot.model_copy(
        update={
            "monthly_total": current,
            "line_items": (
                LineItem(
                    name="Current plan",
                    category=LineItemCategory.SERVICE,
                    amount=current,
                ),
            ),
        }
    )
    target = (
        None
        if context.target_monthly_minor is None
        else _money(
            context.target_monthly_minor, context.target_currency or context.currency
        )
    )
    goal = case.goal.model_copy(
        update={
            "target_monthly_total": target,
            "required_features": context.required_features,
            "forbidden_changes": context.forbidden_changes,
        }
    )
    fees = (
        (
            LineItem(
                name="Activation fee",
                category=LineItemCategory.FEE,
                amount=_money(terms.fees_minor, terms.currency),
            ),
        )
        if terms.fees_minor
        else ()
    )
    lifted_offer = offer.model_copy(
        update={
            "created_at": terms.expires_at - timedelta(hours=1),
            "expires_at": terms.expires_at,
            "monthly_price": _money(terms.monthly_price_minor, terms.currency),
            "total_cost": _money(terms.total_cost_12_months_minor, terms.currency),
            "fees": fees,
            "features": terms.features,
        }
    )
    return (
        _wire_valid(case.model_copy(update={"bill_snapshot": bill, "goal": goal})),
        _wire_valid(lifted_offer),
    )


@pytest.mark.parametrize(("context", "terms"), POLICY_TABLE_INPUTS)
def test_case_offer_violations_matches_the_policy_on_every_valid_table_input(
    context: OfferComplianceContext,
    terms: OfferComplianceTerms,
) -> None:
    case, offer = _lift(context, terms)

    assert case_offer_violations(
        case,
        offer,
        evaluated_at=context.evaluated_at,
        applied_changes=terms.applied_changes,
    ) == offer_compliance_violations(context, terms)
