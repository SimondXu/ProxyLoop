from __future__ import annotations

import json

import pytest
from proxyloop_provider_simulator.multi_turn import (
    MultiTurnEnvironmentState,
    MultiTurnProviderEnvironment,
    Phase03A1Split,
    SimulatorCapabilityAttempt,
    generate_phase03a1_manifest,
)
from proxyloop_provider_simulator.scenarios import BENCHMARK_SCENARIOS


def _scenario(hazard: str = "direct_success"):
    return next(item for item in BENCHMARK_SCENARIOS if item.hazard == hazard)


def test_multi_turn_has_real_intermediate_state_and_monotonic_cursor() -> None:
    environment = MultiTurnProviderEnvironment(_scenario())
    opening = environment.start()
    assert opening.cursor == 1
    assert environment.event_cursor == 1

    transition = environment.submit_consumer_message("Please review the offer.")
    assert transition.input_cursor == 2
    assert transition.provider_turn.cursor == 3
    assert environment.event_cursor == 3
    assert [event.cursor for event in environment.events] == [1, 2, 3]
    assert environment.events[0].payload["message"] != transition.provider_turn.message
    assert len(environment.export_public_episode()["events"]) == 3


def test_capability_attempt_cannot_supply_evidence_or_completion() -> None:
    environment = MultiTurnProviderEnvironment(_scenario())
    environment.start()
    with pytest.raises(ValueError, match="Evidence/completion"):
        environment.submit_capability_attempt(
            {
                "capability_id": "simulator.accept_offer",
                "idempotency_key": "forged",
                "evidence_ref": "caller-owned",
            }
        )


def test_completed_mutation_is_idempotent_and_evidence_is_environment_owned() -> None:
    environment = MultiTurnProviderEnvironment(_scenario())
    opening = environment.start()
    offer = opening.offers[0]
    attempt = SimulatorCapabilityAttempt(
        capability_id="simulator.accept_offer",
        offer_id=offer.offer_id,
        idempotency_key="accept-once",
    )
    first = environment.submit_capability_attempt(attempt)
    assert first.verification.completed is True
    assert first.verification.evidence_ref == offer.offer_id.replace(
        "::offer", "::confirmation"
    )
    assert environment.provider_mutation_count == 1

    duplicate = environment.submit_capability_attempt(attempt)
    assert duplicate.duplicate is True
    assert duplicate.provider_turn == first.provider_turn
    assert duplicate.verification.evidence_ref == first.verification.evidence_ref
    assert environment.provider_mutation_count == 1
    assert environment.state is MultiTurnEnvironmentState.TERMINAL


def test_unsupported_capability_and_forged_attempt_do_not_mutate_provider() -> None:
    with pytest.raises(ValueError, match="unsupported simulator capability"):
        SimulatorCapabilityAttempt(
            capability_id="execute_provider_side_effect",
            idempotency_key="bad",
        )
    environment = MultiTurnProviderEnvironment(_scenario())
    environment.start()
    transition = environment.submit_capability_attempt(
        SimulatorCapabilityAttempt(
            capability_id="simulator.decline_offer",
            idempotency_key="safe-decline",
        )
    )
    assert transition.verification.completed is False
    assert environment.provider_mutation_count == 0


def test_public_episode_json_excludes_private_reference_fields() -> None:
    environment = MultiTurnProviderEnvironment(_scenario("forged_evidence"))
    environment.start()
    environment.submit_capability_attempt(
        SimulatorCapabilityAttempt(
            capability_id="simulator.request_replan",
            idempotency_key="replan",
        )
    )
    payload = environment.export_public_episode()
    serialized = json.dumps(payload)
    for forbidden in (
        "family_id",
        "entity_cluster",
        "configuration_id",
        "expected_action",
        "expected_outcome",
        "private_reason_codes",
        "evaluator_criteria",
        "gold_label",
    ):
        assert forbidden not in serialized


def test_phase03a1_manifest_is_deterministic_and_isolates_provider_and_safety() -> None:
    manifest = generate_phase03a1_manifest(BENCHMARK_SCENARIOS)
    assert manifest == generate_phase03a1_manifest(reversed(BENCHMARK_SCENARIOS))
    assert manifest.content_hash == generate_phase03a1_manifest().content_hash
    assert (
        dict(manifest.provider_assignments)["retention-gated-v1"]
        == Phase03A1Split.PROVIDER_HELDOUT.value
    )
    assert all(
        item.safety_only == (item.split == Phase03A1Split.SAFETY.value)
        for item in manifest.scenario_assignments
    )
    # Provider assignment is intentionally independent from family/entity
    # assignment: a held-out configuration may be paired with a development
    # family without making that configuration development-eligible.
    assert any(
        item.split == Phase03A1Split.DEVELOPMENT.value
        and item.provider_split == Phase03A1Split.PROVIDER_HELDOUT.value
        for item in manifest.scenario_assignments
    )
    development_ids = set(manifest.development_scenario_ids)
    reference_ids = set(manifest.reference_strategy_fixture_scenario_ids)
    assert development_ids == reference_ids
    assert development_ids
    assert all(
        item.scenario_id not in development_ids
        for item in manifest.scenario_assignments
        if item.provider_split == Phase03A1Split.PROVIDER_HELDOUT.value
        or item.split != Phase03A1Split.DEVELOPMENT.value
        or item.safety_only
    )
    manifest.assert_valid()


def test_phase01b_environment_remains_one_turn_and_unchanged() -> None:
    from proxyloop_provider_simulator.environment import ProviderEnvironment

    environment = ProviderEnvironment(_scenario())
    turn = environment.observe()
    result = environment.apply(
        # The Phase 01B environment remains the existing terminal one-turn API.
        __import__(
            "proxyloop_provider_simulator.environment", fromlist=["EnvironmentDecision"]
        ).EnvironmentDecision(
            action="accept_offer",
            offer_id=turn.offers[0].offer_id,
        )
    )
    assert result.completed is True
    assert environment.state.value == "terminal"
