from __future__ import annotations

from dataclasses import replace

from proxyloop_agent_core import (
    SafeObservationAdapter,
    SafeOffer,
    ScriptedOracleConsumer,
)
from proxyloop_provider_simulator.environment import (
    EnvironmentAction,
    EnvironmentDecision,
    ProviderEnvironment,
)
from proxyloop_provider_simulator.episode import Phase01AEpisode
from proxyloop_provider_simulator.scenarios import (
    BENCHMARK_SCENARIOS,
    CASE_CURRENCY,
    CASE_CURRENT_MONTHLY_TOTAL_MINOR,
    CASE_FORBIDDEN_CHANGES,
    CASE_REQUIRED_FEATURES,
    CASE_TARGET_MONTHLY_TOTAL_MINOR,
    BenchmarkScenario,
    ProviderTurn,
    PublicOffer,
)
from proxyloop_telecom_domain import (
    OfferComplianceContext,
    OfferComplianceTerms,
    offer_compliance_violations,
)


def _scenario(hazard: str) -> BenchmarkScenario:
    return next(item for item in BENCHMARK_SCENARIOS if item.hazard == hazard)


def _policy_for_turn(
    turn: ProviderTurn, *, offer: PublicOffer | None = None
) -> tuple[str, ...]:
    selected_offer = offer if offer is not None else turn.offers[0]
    return offer_compliance_violations(
        OfferComplianceContext(
            evaluated_at=turn.observed_at,
            current_monthly_minor=CASE_CURRENT_MONTHLY_TOTAL_MINOR,
            currency=CASE_CURRENCY,
            target_monthly_minor=CASE_TARGET_MONTHLY_TOTAL_MINOR,
            target_currency=CASE_CURRENCY,
            required_features=CASE_REQUIRED_FEATURES,
            forbidden_changes=CASE_FORBIDDEN_CHANGES,
        ),
        OfferComplianceTerms(
            monthly_price_minor=selected_offer.monthly_price_minor,
            total_cost_12_months_minor=selected_offer.total_cost_12_months_minor,
            currency=selected_offer.currency,
            fees_minor=selected_offer.fees_minor,
            features=selected_offer.features,
            applied_changes=selected_offer.applied_changes,
            expires_at=selected_offer.expires_at,
        ),
    )


def _safe_offers(turn: ProviderTurn) -> tuple[SafeOffer, ...]:
    return tuple(
        SafeOffer(
            offer_id=offer.offer_id,
            provider_id=turn.provider_id,
            monthly_price_minor=offer.monthly_price_minor,
            total_cost_12_months_minor=offer.total_cost_12_months_minor,
            currency=offer.currency,
            features=offer.features,
            fees_minor=offer.fees_minor,
            term_months=offer.term_months,
            applied_changes=offer.applied_changes,
            expires_at=offer.expires_at,
        )
        for offer in turn.offers
    )


def test_direct_success_matches_policy_oracle_and_environment() -> None:
    scenario = _scenario("direct_success")
    environment = ProviderEnvironment(scenario)
    turn = environment.observe()
    case = Phase01AEpisode.success().case
    observation = SafeObservationAdapter.build(
        case,
        provider_id=turn.provider_id,
        provider_message=turn.message,
        offers=_safe_offers(turn),
        observed_at=turn.observed_at,
        approval_current=turn.approval_current,
        confirmation_evidence_available=turn.confirmation_evidence_available,
    )

    assert _policy_for_turn(turn) == ()
    decision = ScriptedOracleConsumer(offer_policy=offer_compliance_violations).decide(
        observation
    )
    result = environment.apply(
        EnvironmentDecision(
            action=decision.action.value,
            offer_id=decision.offer_id,
            completion_candidate=True,
        )
    )
    assert decision.action.value == EnvironmentAction.ACCEPT_OFFER.value
    assert result.completed is True


def test_fee_trap_matches_policy_oracle_and_environment_rejection() -> None:
    scenario = _scenario("fee_total_cost_trap")
    environment = ProviderEnvironment(scenario)
    turn = environment.observe()
    case = Phase01AEpisode.success().case
    observation = SafeObservationAdapter.build(
        case,
        provider_id=turn.provider_id,
        provider_message=turn.message,
        offers=_safe_offers(turn),
        observed_at=turn.observed_at,
        approval_current=turn.approval_current,
        confirmation_evidence_available=turn.confirmation_evidence_available,
    )

    assert "total_cost_target_exceeded" in _policy_for_turn(turn)
    decision = ScriptedOracleConsumer(offer_policy=offer_compliance_violations).decide(
        observation
    )
    result = environment.apply(
        EnvironmentDecision(
            action=EnvironmentAction.ACCEPT_OFFER,
            offer_id=turn.offers[0].offer_id,
            completion_candidate=True,
        )
    )
    assert decision.action.value == EnvironmentAction.DECLINE.value
    assert result.completed is False
    assert "total_cost_target_exceeded" in result.reason_codes


def test_current_and_target_monthly_inputs_remain_distinct() -> None:
    scenario = _scenario("direct_success")
    turn = ProviderEnvironment(scenario).observe()
    candidate = replace(
        turn.offers[0],
        monthly_price_minor=8_000,
        total_cost_12_months_minor=96_000,
    )

    violations = _policy_for_turn(turn, offer=candidate)

    assert "target_monthly_total_not_met" in violations
    assert "recurring_price_not_reduced" not in violations
