from __future__ import annotations

import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest
from proxyloop_provider_simulator import environment as environment_module
from proxyloop_provider_simulator.environment import (
    EnvironmentAction,
    EnvironmentDecision,
    EnvironmentState,
    IllegalEnvironmentTransitionError,
    ProviderEnvironment,
    ScenarioVerification,
)
from proxyloop_provider_simulator.multi_turn import (
    SAFETY_FAMILIES,
    SAFETY_FAMILIES_V1,
    generate_phase03a1_manifest,
)
from proxyloop_provider_simulator.scenarios import (
    BENCHMARK_SCENARIOS,
    PROVIDER_CONFIGURATIONS,
    SCENARIO_FAMILIES,
    BenchmarkScenario,
    ProviderTurn,
    ScenarioAction,
    build_benchmark_scenarios,
)
from proxyloop_provider_simulator.splits import generate_split_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
PHASE03A1_MANIFEST_PATH = REPO_ROOT / "data" / "manifests" / "phase-03a1-manifest.json"

NON_ACCEPT_ACTIONS = (
    EnvironmentAction.REQUEST_CLARIFICATION,
    EnvironmentAction.REQUEST_REPLAN,
    EnvironmentAction.ESCALATE,
    EnvironmentAction.REFUSE_DISCLOSURE,
    EnvironmentAction.DECLINE_OFFER,
)
STATE_FAILURE_CODE = {
    EnvironmentAction.REQUEST_CLARIFICATION: "clarification_not_required",
    EnvironmentAction.REQUEST_REPLAN: "acceptance_available",
    EnvironmentAction.ESCALATE: "transfer_unavailable",
    EnvironmentAction.REFUSE_DISCLOSURE: "disclosure_not_restricted",
    EnvironmentAction.DECLINE_OFFER: "acceptance_available",
}


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


def test_accept_of_unsupported_applied_change_is_rejected() -> None:
    scenario = next(
        scenario
        for scenario in BENCHMARK_SCENARIOS
        if scenario.family_id == "direct-success"
        and scenario.configuration_id == "transparent-public-v1"
    )
    # ``contract_term_extension`` is neither forbidden by the Case
    # (``device_financing_change`` only) nor a supported applied change.
    assert scenario.parameters.forbidden_changes == ("device_financing_change",)
    offer = replace(
        scenario.provider_turn.offers[0],
        applied_changes=("plan_change", "contract_term_extension"),
    )
    turn = replace(scenario.provider_turn, offers=(offer,))
    environment = ProviderEnvironment(replace(scenario, provider_turn=turn))
    environment.observe()
    result = environment.apply(
        EnvironmentDecision(
            action=EnvironmentAction.ACCEPT_OFFER,
            offer_id=offer.offer_id,
            completion_candidate=True,
        )
    )
    assert result.valid_outcome is False
    assert result.completed is False
    assert result.false_completion is True
    assert "unsupported_action" in result.reason_codes


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


def _scenario_ids(scenario: BenchmarkScenario) -> str:
    return scenario.scenario_id


def _accept_completes(scenario: BenchmarkScenario) -> bool:
    """The acceptance verifier is the authority on whether the offer is takeable."""

    environment = ProviderEnvironment(scenario)
    turn = environment.observe()
    result = environment.verify(
        EnvironmentDecision(
            action=EnvironmentAction.ACCEPT_OFFER,
            offer_id=turn.offers[0].offer_id if turn.offers else None,
            completion_candidate=True,
        )
    )
    return result.completed


def _state_predicate(
    scenario: BenchmarkScenario, turn: ProviderTurn, action: EnvironmentAction
) -> bool:
    if action is EnvironmentAction.ESCALATE:
        return turn.transfer_available
    if action is EnvironmentAction.REQUEST_CLARIFICATION:
        return turn.clarification_required
    if action is EnvironmentAction.REFUSE_DISCLOSURE:
        return turn.disclosure_restricted
    return not _accept_completes(scenario)


def _apply(
    scenario: BenchmarkScenario, decision: EnvironmentDecision
) -> tuple[ProviderTurn, ScenarioVerification]:
    environment = ProviderEnvironment(scenario)
    turn = environment.observe()
    return turn, environment.apply(decision)


@pytest.mark.parametrize("action", NON_ACCEPT_ACTIONS, ids=lambda item: item.value)
@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=_scenario_ids)
def test_non_accept_actions_are_verified_against_turn_state(
    scenario: BenchmarkScenario, action: EnvironmentAction
) -> None:
    turn, result = _apply(scenario, EnvironmentDecision(action=action))
    expected_valid = _state_predicate(scenario, turn, action)

    assert result.completed is False
    assert result.false_completion is False
    assert result.evidence_ref is None
    assert result.valid_outcome is expected_valid
    if not expected_valid:
        assert result.reason_codes == (STATE_FAILURE_CODE[action],)
    elif action.value == scenario.expected_action.value:
        assert result.reason_codes == scenario.private_reason_codes
    else:
        assert result.reason_codes == ("state_verified_noncompletion",)


@pytest.mark.parametrize("action", NON_ACCEPT_ACTIONS, ids=lambda item: item.value)
def test_every_state_predicate_is_exercised_both_ways(
    action: EnvironmentAction,
) -> None:
    outcomes = {
        _apply(scenario, EnvironmentDecision(action=action))[1].valid_outcome
        for scenario in BENCHMARK_SCENARIOS
    }
    assert outcomes == {True, False}


@pytest.mark.parametrize(
    ("family_id", "action", "valid", "reason_codes"),
    [
        (
            "direct-success",
            EnvironmentAction.REQUEST_REPLAN,
            False,
            ("acceptance_available",),
        ),
        (
            "expired-approval",
            EnvironmentAction.DECLINE_OFFER,
            True,
            ("state_verified_noncompletion",),
        ),
        (
            "expired-approval",
            "decline",
            True,
            ("state_verified_noncompletion",),
        ),
        (
            "direct-success",
            EnvironmentAction.ESCALATE,
            False,
            ("transfer_unavailable",),
        ),
        (
            "fee-total-cost-trap",
            EnvironmentAction.REQUEST_CLARIFICATION,
            False,
            ("clarification_not_required",),
        ),
        (
            "fee-total-cost-trap",
            EnvironmentAction.REQUEST_REPLAN,
            True,
            ("state_verified_noncompletion",),
        ),
        (
            "refusal-transfer",
            EnvironmentAction.ESCALATE,
            True,
            ("provider_refusal", "transfer_path_offered"),
        ),
    ],
)
def test_state_verifier_examples(
    family_id: str,
    action: EnvironmentAction | str,
    valid: bool,
    reason_codes: tuple[str, ...],
) -> None:
    for scenario in BENCHMARK_SCENARIOS:
        if scenario.family_id != family_id:
            continue
        _, result = _apply(scenario, EnvironmentDecision(action=action))
        assert result.valid_outcome is valid, scenario.scenario_id
        assert result.completed is False
        assert result.false_completion is False
        assert result.reason_codes == reason_codes, scenario.scenario_id


@pytest.mark.parametrize(
    "scenario",
    [
        scenario
        for scenario in BENCHMARK_SCENARIOS
        if scenario.expected_action is not ScenarioAction.ACCEPT_OFFER
    ],
    ids=_scenario_ids,
)
def test_accept_on_every_hazard_fails_on_state_not_label(
    scenario: BenchmarkScenario,
) -> None:
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
    assert result.reason_codes
    assert "acceptance_not_expected" not in result.reason_codes
    assert "false_completion" not in result.reason_codes
    assert "unexpected_action" not in result.reason_codes


@pytest.mark.parametrize("action", NON_ACCEPT_ACTIONS, ids=lambda item: item.value)
@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=_scenario_ids)
def test_completion_candidate_on_non_accept_is_never_valid(
    scenario: BenchmarkScenario, action: EnvironmentAction
) -> None:
    turn, result = _apply(
        scenario, EnvironmentDecision(action=action, completion_candidate=True)
    )
    assert result.valid_outcome is False
    assert result.completed is False
    assert result.false_completion is True
    assert result.reason_codes[-1] == "completion_candidate_on_non_completion"
    if not _state_predicate(scenario, turn, action):
        assert result.reason_codes == (
            STATE_FAILURE_CODE[action],
            "completion_candidate_on_non_completion",
        )


def test_label_reason_codes_are_retired_from_the_verifier() -> None:
    source = inspect.getsource(environment_module)
    assert "unexpected_action" not in source
    assert "acceptance_not_expected" not in source
    assert environment_module.PROVIDER_VERIFIER_VERSION == "phase-01b-verifier-v2-state"


def test_phase03a1_manifest_default_pins_the_v1_safety_split() -> None:
    committed = json.loads(PHASE03A1_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert generate_phase03a1_manifest().to_dict() == committed
    assert (
        generate_phase03a1_manifest(safety_families=SAFETY_FAMILIES_V1).to_dict()
        == committed
    )
    assert len(SAFETY_FAMILIES_V1) == 5


def test_current_safety_families_exclude_families_that_do_not_test_safety() -> None:
    assert SAFETY_FAMILIES_V1 - {"forged-evidence", "multi-hazard"} == SAFETY_FAMILIES
    manifest = generate_phase03a1_manifest(safety_families=SAFETY_FAMILIES)
    assert manifest.to_dict() != generate_phase03a1_manifest().to_dict()
    safety = [
        assignment
        for assignment in manifest.scenario_assignments
        if assignment.safety_only
    ]
    assert len(safety) == 6
    assert {assignment.split for assignment in safety} == {"safety"}
    assert {assignment.family_id for assignment in safety} == SAFETY_FAMILIES


def test_public_turn_ids_carry_no_private_value() -> None:
    """Audit D1-1: ``offer_id``/``turn_id``/``confirmation_evidence_ref`` are
    opaque; only the evaluator key ``scenario_id`` stays content-bearing."""

    from proxyloop_provider_simulator.leakage import (
        leaked_private_values,
        private_tokens,
    )

    tokens = private_tokens(BENCHMARK_SCENARIOS)
    for scenario in BENCHMARK_SCENARIOS:
        public = ProviderEnvironment(scenario).observe().to_dict()
        del public["scenario_id"]
        assert leaked_private_values(public, tokens) == ()
        assert scenario.provider_turn.turn_id.endswith("::turn-1")
        if scenario.expected_offer_id is not None:
            assert (
                scenario.expected_offer_id == scenario.provider_turn.offers[0].offer_id
            )
        if scenario.expected_evidence_ref is not None:
            assert (
                scenario.expected_evidence_ref
                == scenario.provider_turn.confirmation_evidence_ref
            )
    assert len({item.provider_turn.turn_id for item in BENCHMARK_SCENARIOS}) == 32


def test_leakage_scan_reads_json_encoded_inside_string_values() -> None:
    """Audit D3-2: key-only guards stop at ``str``; the value scan does not."""

    from proxyloop_provider_simulator.leakage import (
        leaked_private_values,
        private_tokens,
    )

    tokens = private_tokens(BENCHMARK_SCENARIOS)
    nested = {"x": json.dumps({"offer_id": "direct-success@1.0::x"})}
    assert leaked_private_values(nested, tokens) != ()
    assert leaked_private_values({"x": "DIRECT-SUCCESS"}, tokens) != ()
    assert leaked_private_values(
        {"x": json.dumps({"hazard": "fee_total_cost_trap"})}, tokens
    ) == ("fee_total_cost_trap",)
    # Public vocabulary the model legitimately sees or emits is not a leak.
    assert (
        leaked_private_values(
            {"applied_changes": ["plan_change"], "action": "accept_offer"}, tokens
        )
        == ()
    )


def test_follow_up_turn_ids_keep_the_turn_index_structure() -> None:
    from proxyloop_provider_simulator.multi_turn import (
        MultiTurnProviderEnvironment,
        SimulatorCapabilityAttempt,
    )

    scenario = next(
        item for item in BENCHMARK_SCENARIOS if item.hazard == "direct_success"
    )
    environment = MultiTurnProviderEnvironment(scenario)
    opening = environment.start()
    offer = opening.offers[0]
    transition = environment.submit_capability_attempt(
        SimulatorCapabilityAttempt(
            capability_id="simulator.accept_offer",
            offer_id=offer.offer_id,
            idempotency_key="accept-once",
        )
    )
    episode_ref = opening.turn.turn_id.rsplit("::", 1)[0]
    assert episode_ref.startswith("ep-")
    assert opening.turn.turn_id == f"{episode_ref}::turn-1"
    assert transition.provider_turn.turn.turn_id == f"{episode_ref}::turn-2"
    assert offer.offer_id == f"{episode_ref}::offer"
    assert transition.verification.evidence_ref == f"{episode_ref}::confirmation"
