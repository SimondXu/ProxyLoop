from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from datetime import timedelta

import pytest
from proxyloop_contracts import Case, ConstraintClassification
from proxyloop_provider_simulator.environment import (
    EnvironmentDecision,
    ProviderEnvironment,
)
from proxyloop_provider_simulator.episode import Phase01AEpisode, build_case
from proxyloop_provider_simulator.scenarios import (
    BENCHMARK_SCENARIOS,
    CASE_OBSERVED_AT,
    DEFAULT_PARAMS,
    PROVIDER_CONFIGURATIONS,
    SCENARIO_FAMILIES,
    BenchmarkScenario,
    ScenarioParameters,
    build_benchmark_scenarios,
    build_parameterised_scenarios,
    build_scenario,
    parameters_from_seed,
)

# SHA-256 of the 32 frozen scenarios (ids, provider turns, private expected
# semantics) as of main 120e102, before Stage 1a. DEFAULT_PARAMS must keep it.
FROZEN_CATALOGUE_FINGERPRINT = (
    "425c7afbf64a8506afca8a855f75f9ac7d3d2e124b04237efe2f1fdc46f21d1f"
)
# SHA-256 of ``Phase01AEpisode.success().case.model_dump_json()``: the
# historical Phase 01A Case that ``build_case(DEFAULT_PARAMS)`` must reproduce.
FROZEN_CASE_FINGERPRINT = (
    "37d8e149f01daa19007ed93231312559c89f6cb774711013d35ca97eaea7bb5b"
)
# Full draws of ``parameters_from_seed`` pinned as literals; any change to the
# generator's draw sequence must be a deliberate, visible diff here.
PINNED_SEEDED_PARAMETERS = {
    1: {
        "seed": 1,
        "current_monthly_minor": 8_700,
        "target_monthly_minor": 7_100,
        "base_price_minor": 6_820,
        "trap_fee_minor": 3_560,
        "promo_credit_minor": 5_000,
        "required_features": ("mobile_hotspot", "unlimited_talk_text"),
        "forbidden_changes": ("contract_term_extension",),
        "expires_in_minutes": 120,
        "message_variant": 0,
    },
    42: {
        "seed": 42,
        "current_monthly_minor": 14_700,
        "target_monthly_minor": 9_900,
        "base_price_minor": 9_430,
        "trap_fee_minor": 23_640,
        "promo_credit_minor": 5_000,
        "required_features": ("unlimited_talk_text",),
        "forbidden_changes": ("contract_term_extension",),
        "expires_in_minutes": 240,
        "message_variant": 2,
    },
    999: {
        "seed": 999,
        "current_monthly_minor": 10_700,
        "target_monthly_minor": 8_400,
        "base_price_minor": 6_580,
        "trap_fee_minor": 56_040,
        "promo_credit_minor": 5_000,
        "required_features": ("mobile_hotspot", "unlimited_talk_text"),
        "forbidden_changes": ("device_financing_change", "contract_term_extension"),
        "expires_in_minutes": 5,
        "message_variant": 1,
    },
}


def _case_fingerprint(case: Case) -> str:
    return hashlib.sha256(case.model_dump_json().encode("utf-8")).hexdigest()


def _turn_without_message_and_ids(item: BenchmarkScenario) -> dict[str, object]:
    """Public turn fields with the message dropped and the scenario id masked."""

    turn = item.provider_turn.to_dict()
    turn.pop("message")
    masked = json.dumps(turn).replace(item.scenario_id, "<scenario-id>")
    result: dict[str, object] = json.loads(masked)
    return result


def _catalogue_fingerprint(scenarios: tuple[BenchmarkScenario, ...]) -> str:
    rows = [
        {
            "scenario_id": item.scenario_id,
            "family_id": item.family_id,
            "hazard": item.hazard,
            "family_version": item.family_version,
            "entity_cluster": item.entity_cluster,
            "configuration_id": item.configuration_id,
            "configuration_version": item.configuration_version,
            "observed_at": item.observed_at.isoformat(),
            "provider_turn": item.provider_turn.to_dict(),
            "expected_action": item.expected_action.value,
            "expected_outcome": item.expected_outcome.value,
            "expected_offer_id": item.expected_offer_id,
            "expected_evidence_ref": item.expected_evidence_ref,
            "private_reason_codes": list(item.private_reason_codes),
        }
        for item in scenarios
    ]
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_default_params_reproduce_the_frozen_catalogue_byte_for_byte() -> None:
    assert len(BENCHMARK_SCENARIOS) == 32
    assert _catalogue_fingerprint(BENCHMARK_SCENARIOS) == FROZEN_CATALOGUE_FINGERPRINT
    assert _catalogue_fingerprint(build_benchmark_scenarios()) == (
        FROZEN_CATALOGUE_FINGERPRINT
    )
    assert all(item.parameters == DEFAULT_PARAMS for item in BENCHMARK_SCENARIOS)
    assert all("::p" not in item.scenario_id for item in BENCHMARK_SCENARIOS)
    explicit = tuple(
        sorted(
            (
                build_scenario(family, configuration, DEFAULT_PARAMS)
                for family in SCENARIO_FAMILIES
                for configuration in PROVIDER_CONFIGURATIONS
            ),
            key=lambda item: item.scenario_id,
        )
    )
    assert _catalogue_fingerprint(explicit) == FROZEN_CATALOGUE_FINGERPRINT


def test_default_params_equal_the_historical_constants() -> None:
    assert (
        ScenarioParameters(
            seed=0,
            current_monthly_minor=9_200,
            target_monthly_minor=7_500,
            base_price_minor=7_200,
            trap_fee_minor=30_000,
            promo_credit_minor=5_000,
            required_features=("mobile_hotspot",),
            forbidden_changes=("device_financing_change",),
            expires_in_minutes=60,
            message_variant=0,
        )
        == DEFAULT_PARAMS
    )
    assert parameters_from_seed(0) == DEFAULT_PARAMS
    assert _case_fingerprint(Phase01AEpisode.success().case) == FROZEN_CASE_FINGERPRINT
    assert _case_fingerprint(build_case(DEFAULT_PARAMS)) == FROZEN_CASE_FINGERPRINT


def test_seeded_parameters_match_their_pinned_draws() -> None:
    for seed, expected in PINNED_SEEDED_PARAMETERS.items():
        assert asdict(parameters_from_seed(seed)) == expected, seed


def test_seeded_parameters_are_deterministic_and_distinct() -> None:
    first = parameters_from_seed(17)
    assert first == parameters_from_seed(17)
    assert first != DEFAULT_PARAMS
    assert first.seed == 17
    seen = {parameters_from_seed(seed) for seed in range(1, 200)}
    assert len(seen) == 199
    for params in seen:
        assert params.base_price_minor < params.target_monthly_minor
        assert params.target_monthly_minor < params.current_monthly_minor
        assert params.trap_fee_minor > 0
        assert params.required_features
        assert params.forbidden_changes
        assert params.message_variant in {0, 1, 2}
        assert params.expires_in_minutes >= 5


def test_parameters_validate_their_arithmetic() -> None:
    with pytest.raises(ValueError, match="target"):
        ScenarioParameters(target_monthly_minor=9_200)
    with pytest.raises(ValueError, match="base price"):
        ScenarioParameters(base_price_minor=7_500)
    with pytest.raises(ValueError, match="retention"):
        ScenarioParameters(base_price_minor=7_400)
    with pytest.raises(ValueError, match="required_features"):
        ScenarioParameters(required_features=())
    with pytest.raises(ValueError, match="message_variant"):
        ScenarioParameters(message_variant=3)
    with pytest.raises(ValueError, match="seed"):
        ScenarioParameters(seed=-1)
    with pytest.raises(ValueError, match="must exceed the fixed add-on"):
        ScenarioParameters(
            current_monthly_minor=1_000, target_monthly_minor=900, base_price_minor=700
        )
    for token in (
        "plan_change",
        "revised_plan_change",
        "remove_add_on:premium_data",
        "account_cancellation",
        "predefined_promotion_credit",
    ):
        with pytest.raises(ValueError, match="applied-change tokens"):
            ScenarioParameters(forbidden_changes=(token,))
        with pytest.raises(ValueError, match="applied-change tokens"):
            ScenarioParameters(required_features=(token,))


def test_seeded_scenario_ids_carry_the_seed_and_reflect_parameters() -> None:
    family = next(
        item for item in SCENARIO_FAMILIES if item.hazard == "fee_total_cost_trap"
    )
    configuration = PROVIDER_CONFIGURATIONS[1]
    params = parameters_from_seed(42)
    scenario = build_scenario(family, configuration, params)
    base_id = f"{family.family_id}@1.0::{configuration.configuration_id}@1.0"
    assert scenario.scenario_id == f"{base_id}::p42"
    assert scenario.parameters == params
    offer = scenario.provider_turn.offers[0]
    assert offer.offer_id == f"{scenario.scenario_id}::offer"
    assert offer.monthly_price_minor == (
        params.base_price_minor + configuration.price_delta_minor
    )
    assert offer.fees_minor == params.trap_fee_minor
    assert offer.total_cost_12_months_minor == (
        offer.monthly_price_minor * 12 + params.trap_fee_minor
    )
    assert offer.expires_at == CASE_OBSERVED_AT + timedelta(
        minutes=params.expires_in_minutes
    )
    assert scenario.provider_turn.turn_id == f"{scenario.scenario_id}::turn-1"
    assert scenario.expected_offer_id == offer.offer_id


def test_hand_built_parameters_do_not_collide_with_seeded_ids() -> None:
    family = SCENARIO_FAMILIES[0]
    configuration = PROVIDER_CONFIGURATIONS[0]
    seeded = build_scenario(family, configuration, parameters_from_seed(42))
    assert seeded.scenario_id.endswith("::p42")
    custom = build_scenario(
        family, configuration, replace(parameters_from_seed(42), message_variant=1)
    )
    assert custom.scenario_id != seeded.scenario_id
    assert custom.scenario_id.startswith(f"{seeded.scenario_id}-")
    variant_zero = ScenarioParameters(seed=0, message_variant=1)
    suffix = variant_zero.id_suffix
    assert suffix.startswith("::p0-")
    assert suffix != "::p0"
    assert len(suffix) == len("::p0-") + 8
    assert int(suffix.rsplit("-", 1)[1], 16) >= 0
    assert DEFAULT_PARAMS.id_suffix == ""
    assert all("::p" not in item.scenario_id for item in BENCHMARK_SCENARIOS)


def test_message_variants_change_only_the_public_message() -> None:
    family = SCENARIO_FAMILIES[0]
    configuration = PROVIDER_CONFIGURATIONS[0]
    base = parameters_from_seed(11)
    variants = [
        build_scenario(family, configuration, replace(base, message_variant=variant))
        for variant in (0, 1, 2)
    ]
    messages = {item.provider_turn.message for item in variants}
    assert len(messages) == 3
    # Only the id suffix (hash of the parameters) and the message may differ.
    stable = [_turn_without_message_and_ids(item) for item in variants]
    assert stable[0] == stable[1] == stable[2]
    assert stable[0]["offers"]
    assert all(
        item.expected_action == variants[0].expected_action
        and item.expected_outcome == variants[0].expected_outcome
        and item.private_reason_codes == variants[0].private_reason_codes
        for item in variants
    )
    baseline = build_scenario(family, configuration, ScenarioParameters(seed=9))
    frozen = next(
        item
        for item in BENCHMARK_SCENARIOS
        if item.scenario_id == build_scenario(family, configuration).scenario_id
    )
    assert baseline.provider_turn.message == frozen.provider_turn.message


def test_public_message_names_the_offer_content() -> None:
    forbidden = next(
        item for item in SCENARIO_FAMILIES if item.hazard == "forbidden_term"
    )
    direct = next(item for item in SCENARIO_FAMILIES if item.hazard == "direct_success")
    configuration = PROVIDER_CONFIGURATIONS[0]
    seed_one = build_scenario(forbidden, configuration, parameters_from_seed(1))
    assert seed_one.parameters.forbidden_changes[0] == "contract_term_extension"
    assert "contract-term extension" in seed_one.provider_turn.message
    assert seed_one.provider_turn.offers[0].applied_changes == (
        "contract_term_extension",
    )
    seed_ten = build_scenario(direct, configuration, parameters_from_seed(10))
    feature = seed_ten.parameters.required_features[0]
    assert feature in seed_ten.provider_turn.offers[0].features
    assert feature.replace("_", " ") in seed_ten.provider_turn.message
    assert "mobile hotspot" not in seed_ten.provider_turn.message
    frozen_messages = {
        item.hazard: item.provider_turn.message
        for item in BENCHMARK_SCENARIOS
        if item.configuration_id == configuration.configuration_id
    }
    assert frozen_messages["direct_success"] == (
        "Public quote: A plan with mobile hotspot is available at the quoted price."
    )
    assert frozen_messages["required_feature_loss"] == (
        "Public quote: The offer does not include mobile hotspot."
    )
    assert frozen_messages["forbidden_term"] == (
        "Public quote: The offer includes a device-financing change."
    )
    assert frozen_messages["plan_change"] == (
        "Public quote: A plan with mobile hotspot is available."
    )


def test_environment_verifies_against_the_scenario_parameters() -> None:
    family = next(item for item in SCENARIO_FAMILIES if item.hazard == "direct_success")
    configuration = PROVIDER_CONFIGURATIONS[0]
    params = ScenarioParameters(
        seed=5,
        current_monthly_minor=15_000,
        target_monthly_minor=12_000,
        base_price_minor=11_000,
    )
    scenario = build_scenario(family, configuration, params)
    environment = ProviderEnvironment(scenario)
    turn = environment.observe()
    verification = environment.verify(
        EnvironmentDecision(action="accept_offer", offer_id=turn.offers[0].offer_id)
    )
    # 11_000 would violate the historical 7_500 target; the parameterised
    # context accepts it.
    assert verification.valid_outcome is True
    assert verification.completed is True


def test_parameterised_catalogue_is_sorted_unique_and_keeps_families() -> None:
    scenarios = build_parameterised_scenarios(seeds=range(1, 4))
    assert len(scenarios) == 32 * 3
    ids = [item.scenario_id for item in scenarios]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)
    assert {item.family_id for item in scenarios} == {
        item.family_id for item in SCENARIO_FAMILIES
    }
    with pytest.raises(ValueError, match="seed 0"):
        build_parameterised_scenarios(seeds=(0,))


def test_case_constraints_follow_the_forbidden_changes() -> None:
    frozen = build_case(DEFAULT_PARAMS)
    assert _case_fingerprint(frozen) == FROZEN_CASE_FINGERPRINT
    assert len(frozen.constraints) == 1
    assert frozen.constraints[0].statement == "Do not change device financing."
    params = ScenarioParameters(
        seed=7,
        forbidden_changes=("device_financing_change", "contract_term_extension"),
    )
    case = build_case(params)
    assert case == build_case(params)
    assert [item.statement for item in case.constraints] == [
        "Do not change device financing.",
        "Do not extend the contract term.",
    ]
    assert all(
        item.classification is ConstraintClassification.HARD
        for item in case.constraints
    )
    ids = {item.constraint_id for item in case.constraints}
    assert len(ids) == 2
    assert all(item.version == 4 for item in ids)
