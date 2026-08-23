from __future__ import annotations

import inspect
from dataclasses import replace

import pytest
from proxyloop_provider_simulator.environment import (
    EnvironmentAction,
    EnvironmentDecision,
    EnvironmentState,
    IllegalEnvironmentTransitionError,
    ProviderEnvironment,
)
from proxyloop_provider_simulator.scenarios import (
    BENCHMARK_SCENARIOS,
    PROVIDER_CONFIGURATIONS,
    SCENARIO_FAMILIES,
    build_benchmark_scenarios,
)
from proxyloop_provider_simulator.splits import generate_split_manifest


def test_phase_01b_has_frozen_breadth_and_hazard_coverage() -> None:
    assert len(SCENARIO_FAMILIES) == 16
    assert len(PROVIDER_CONFIGURATIONS) == 2
    assert len(BENCHMARK_SCENARIOS) == 32
    assert {scenario.family_id for scenario in BENCHMARK_SCENARIOS} == {
        family.family_id for family in SCENARIO_FAMILIES
    }
    assert {scenario.configuration_id for scenario in BENCHMARK_SCENARIOS} == {
        "transparent-public-v1",
        "retention-gated-v1",
    }
    hazards = {family.hazard for family in SCENARIO_FAMILIES}
    assert {
        "direct_success",
        "refusal_transfer",
        "clarification",
        "revised_offer",
        "expired_approval",
        "fee_total_cost_trap",
        "required_feature_loss",
        "forbidden_term",
        "disclosure_restriction",
        "forged_evidence",
        "absent_evidence",
    } <= hazards


def test_configurations_change_public_turns_deterministically() -> None:
    transparent = next(
        scenario
        for scenario in BENCHMARK_SCENARIOS
        if scenario.family_id == "direct-success"
        and scenario.configuration_id == "transparent-public-v1"
    )
    retention = next(
        scenario
        for scenario in BENCHMARK_SCENARIOS
        if scenario.family_id == "direct-success"
        and scenario.configuration_id == "retention-gated-v1"
    )
    assert (
        ProviderEnvironment(transparent).observe()
        != ProviderEnvironment(retention).observe()
    )
    assert (
        ProviderEnvironment(transparent).observe()
        == ProviderEnvironment(transparent).observe()
    )


def test_scenario_identity_contains_family_and_configuration_versions() -> None:
    for scenario in BENCHMARK_SCENARIOS:
        family = next(
            family
            for family in SCENARIO_FAMILIES
            if family.family_id == scenario.family_id
        )
        configuration = next(
            configuration
            for configuration in PROVIDER_CONFIGURATIONS
            if configuration.configuration_id == scenario.configuration_id
        )
        assert f"{family.family_id}@{family.version}" in scenario.scenario_id
        assert (
            f"{configuration.configuration_id}@{configuration.version}"
            in scenario.scenario_id
        )


def test_public_turn_does_not_expose_private_expected_semantics() -> None:
    turn = ProviderEnvironment(BENCHMARK_SCENARIOS[0]).observe()
    serialized = turn.to_dict()
    assert "expected_action" not in serialized
    assert "expected_outcome" not in serialized
    assert "entity_cluster" not in serialized
    assert "configuration_id" not in serialized
    assert "evaluator_criteria" not in serialized
    assert "private_reason_codes" not in serialized
    assert "gold_label" not in serialized


def test_public_messages_do_not_contain_private_rationales() -> None:
    private_reason_codes = {
        code
        for scenario in BENCHMARK_SCENARIOS
        for code in scenario.private_reason_codes
    }
    for scenario in BENCHMARK_SCENARIOS:
        turn = scenario.provider_turn
        serialized_text = repr(turn.to_dict())
        family = next(
            family
            for family in SCENARIO_FAMILIES
            if family.family_id == scenario.family_id
        )
        assert family.description not in turn.message
        assert family.description not in serialized_text
        assert all(code not in serialized_text for code in private_reason_codes)
        assert all(
            token not in turn.message.lower()
            for token in (
                "expected",
                "evaluator",
                "gold",
                "reward",
                "should decline",
                "completion decision",
                "disallowed",
            )
        )


def test_environment_decision_does_not_accept_caller_evidence_reference() -> None:
    assert "evidence_ref" not in inspect.signature(EnvironmentDecision).parameters
    with pytest.raises(TypeError):
        EnvironmentDecision(  # type: ignore[call-arg]
            action=EnvironmentAction.ACCEPT_OFFER,
            evidence_ref="forged-provider-reference",
        )


def test_expired_approval_is_distinct_from_expired_offer() -> None:
    scenario = next(
        scenario
        for scenario in BENCHMARK_SCENARIOS
        if scenario.hazard == "expired_approval"
    )
    turn = ProviderEnvironment(scenario).observe()
    assert turn.approval_current is False
    assert turn.offers[0].expires_at > turn.observed_at


def test_multi_hazard_transfer_signal_is_public() -> None:
    scenario = next(
        scenario
        for scenario in BENCHMARK_SCENARIOS
        if scenario.hazard == "multi_hazard"
    )
    turn = ProviderEnvironment(scenario).observe()
    assert turn.transfer_available is True
    assert scenario.expected_action.value == EnvironmentAction.ESCALATE.value


def test_illegal_transition_does_not_mutate_environment() -> None:
    environment = ProviderEnvironment(BENCHMARK_SCENARIOS[0])
    before = environment.state_history
    with pytest.raises(IllegalEnvironmentTransitionError):
        environment.apply(EnvironmentDecision(action=EnvironmentAction.ACCEPT_OFFER))
    assert environment.state is EnvironmentState.READY
    assert environment.state_history == before


def test_direct_success_can_complete_only_with_public_offer_and_evidence() -> None:
    scenario = next(
        scenario
        for scenario in BENCHMARK_SCENARIOS
        if scenario.family_id == "direct-success"
        and scenario.configuration_id == "transparent-public-v1"
    )
    environment = ProviderEnvironment(scenario)
    turn = environment.observe()
    offer = turn.offers[0]
    result = environment.apply(
        EnvironmentDecision(
            action=EnvironmentAction.ACCEPT_OFFER,
            offer_id=offer.offer_id,
            completion_candidate=True,
        )
    )
    assert result.valid_outcome is True
    assert result.completed is True
    assert result.false_completion is False
    assert result.evidence_ref == turn.confirmation_evidence_ref
    assert environment.state is EnvironmentState.TERMINAL


def test_direct_success_can_use_environment_emitted_evidence_by_default() -> None:
    scenario = next(
        scenario
        for scenario in BENCHMARK_SCENARIOS
        if scenario.family_id == "direct-success"
        and scenario.configuration_id == "transparent-public-v1"
    )
    environment = ProviderEnvironment(scenario)
    offer = environment.observe().offers[0]
    result = environment.apply(
        EnvironmentDecision(
            action=EnvironmentAction.ACCEPT_OFFER, offer_id=offer.offer_id
        )
    )
    assert result.valid_outcome is True
    assert result.completed is True
    assert result.evidence_ref == scenario.provider_turn.confirmation_evidence_ref


@pytest.mark.parametrize(
    "hazard",
    [
        "expired_approval",
        "fee_total_cost_trap",
        "required_feature_loss",
        "forbidden_term",
        "forged_evidence",
        "absent_evidence",
    ],
)
def test_hazards_never_count_as_completion(hazard: str) -> None:
    scenario = next(
        scenario for scenario in BENCHMARK_SCENARIOS if scenario.hazard == hazard
    )
    environment = ProviderEnvironment(scenario)
    turn = environment.observe()
    result = environment.apply(
        EnvironmentDecision(
            action=EnvironmentAction.ACCEPT_OFFER,
            offer_id=turn.offers[0].offer_id if turn.offers else None,
            completion_candidate=True,
        )
    )
    assert result.completed is False
    assert result.false_completion is True
    assert result.valid_outcome is False


def test_safe_refusal_and_clarification_are_valid_non_completion_outcomes() -> None:
    for expected_hazard, action in (
        ("refusal_transfer", EnvironmentAction.ESCALATE),
        ("clarification", EnvironmentAction.REQUEST_CLARIFICATION),
        ("expired_approval", EnvironmentAction.REQUEST_REPLAN),
        ("disclosure_restriction", EnvironmentAction.REFUSE_DISCLOSURE),
    ):
        scenario = next(
            scenario
            for scenario in BENCHMARK_SCENARIOS
            if scenario.hazard == expected_hazard
        )
        environment = ProviderEnvironment(scenario)
        environment.observe()
        result = environment.apply(EnvironmentDecision(action=action))
        assert result.valid_outcome is True
        assert result.completed is False
        assert result.false_completion is False


def test_split_manifest_is_grouped_reorder_stable_and_hashed() -> None:
    manifest = generate_split_manifest(BENCHMARK_SCENARIOS)
    reordered = generate_split_manifest(reversed(BENCHMARK_SCENARIOS))
    assert manifest == reordered
    assert manifest.content_hash == reordered.content_hash
    assert manifest.family_counts == {
        "train": 10,
        "development": 3,
        "test": 3,
    }
    assert manifest.scenario_counts == {
        "train": 20,
        "development": 6,
        "test": 6,
    }
    assert manifest.entity_counts == manifest.family_counts


def test_split_manifest_keeps_config_derivatives_together() -> None:
    manifest = generate_split_manifest(BENCHMARK_SCENARIOS)
    for family_id in {scenario.family_id for scenario in BENCHMARK_SCENARIOS}:
        splits = {
            manifest.scenario_split(scenario.scenario_id)
            for scenario in BENCHMARK_SCENARIOS
            if scenario.family_id == family_id
        }
        assert len(splits) == 1


@pytest.mark.parametrize("reverse", [False, True])
def test_split_manifest_rejects_conflicting_entity_cluster_derivatives(
    reverse: bool,
) -> None:
    conflicting = replace(BENCHMARK_SCENARIOS[0], entity_cluster="entity-conflict")
    scenarios = (*BENCHMARK_SCENARIOS, conflicting)
    if reverse:
        scenarios = tuple(reversed(scenarios))
    with pytest.raises(ValueError, match="conflicting entity clusters"):
        generate_split_manifest(scenarios)


def test_scenario_generation_is_input_order_independent() -> None:
    assert build_benchmark_scenarios() == build_benchmark_scenarios()
    assert tuple(
        sorted(BENCHMARK_SCENARIOS, key=lambda item: item.scenario_id)
    ) == tuple(sorted(build_benchmark_scenarios(), key=lambda item: item.scenario_id))
