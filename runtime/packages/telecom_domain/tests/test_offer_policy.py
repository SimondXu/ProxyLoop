from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from proxyloop_contracts import Money
from proxyloop_provider_simulator.episode import Phase01AEpisode
from proxyloop_telecom_domain import (
    CompletionVerification,
    OfferComplianceContext,
    OfferComplianceTerms,
    offer_compliance_violations,
    verify_completion,
)

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
