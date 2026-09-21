from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from proxyloop_contracts import Case
from proxyloop_evaluation.fresh_fixtures import build_fresh_safe_observation
from proxyloop_evaluation.phase03c_scenarios import (
    DEFAULT_INVARIANT_SEEDS,
    INVARIANT_MANIFEST_PATH,
    INVARIANT_MANIFEST_SCHEMA_VERSION,
    MESSAGE_OFFER_CONSISTENCY,
    ORACLE_AGREEMENT,
    SUCCESS_COMPLIANCE,
    TWELVE_MONTH_ARITHMETIC,
    VERIFIER_AGREEMENT,
    build_parameterised_observation,
    check_instance_invariants,
    check_invariant_manifest,
    harvest_positions,
    parameters_fingerprint,
    run_invariant_suite,
    write_invariant_manifest,
)
from proxyloop_provider_simulator.episode import Phase01AEpisode, build_case
from proxyloop_provider_simulator.scenarios import (
    BENCHMARK_SCENARIOS,
    DEFAULT_PARAMS,
    PROVIDER_CONFIGURATIONS,
    SCENARIO_FAMILIES,
    ProviderConfiguration,
    ProviderTurn,
    ScenarioFamily,
    ScenarioParameters,
    build_parameterised_scenarios,
    build_scenario,
    parameters_from_seed,
)

ROOT = Path(__file__).resolve().parents[2]
PROMOTION_FAMILY = next(
    family for family in SCENARIO_FAMILIES if family.hazard == "promotion_credit"
)
# SHA-256 of ``Phase01AEpisode.success().case.model_dump_json()``; the
# parameterised observation builder must read exactly this Case by default.
FROZEN_CASE_FINGERPRINT = (
    "37d8e149f01daa19007ed93231312559c89f6cb774711013d35ca97eaea7bb5b"
)


def _family(hazard: str) -> ScenarioFamily:
    return next(family for family in SCENARIO_FAMILIES if family.hazard == hazard)


def _case_sha256(case: Case) -> str:
    return hashlib.sha256(case.model_dump_json().encode("utf-8")).hexdigest()


def test_default_params_observation_matches_fresh_builder() -> None:
    assert len(BENCHMARK_SCENARIOS) == 32
    for scenario in BENCHMARK_SCENARIOS:
        expected = build_fresh_safe_observation(scenario, scenario.provider_turn)
        actual = build_parameterised_observation(scenario, scenario.provider_turn)
        assert actual == expected, scenario.scenario_id


def test_default_case_is_the_pinned_phase_01a_case() -> None:
    assert _case_sha256(Phase01AEpisode.success().case) == FROZEN_CASE_FINGERPRINT
    assert _case_sha256(build_case(DEFAULT_PARAMS)) == FROZEN_CASE_FINGERPRINT


def test_invariants_accept_frozen_catalogue() -> None:
    for scenario in BENCHMARK_SCENARIOS:
        assert check_instance_invariants(scenario) == (), scenario.scenario_id


def test_invariants_accept_seeds_one_to_three() -> None:
    scenarios = build_parameterised_scenarios(seeds=(1, 2, 3))
    assert len(scenarios) == 96
    for scenario in scenarios:
        assert check_instance_invariants(scenario) == (), scenario.scenario_id
    report = run_invariant_suite((1, 2, 3))
    assert report.total_instances == 96
    assert report.accepted_count == 96
    assert report.quarantined == ()
    assert dict(report.family_counts) == {
        family.family_id: 6 for family in SCENARIO_FAMILIES
    }


@pytest.mark.parametrize("configuration", PROVIDER_CONFIGURATIONS)
def test_uncatalogued_promo_credit_is_quarantined(
    configuration: ProviderConfiguration,
) -> None:
    scenario = build_scenario(
        PROMOTION_FAMILY,
        configuration,
        ScenarioParameters(seed=7, promo_credit_minor=4_000),
    )
    reasons = check_instance_invariants(scenario)
    assert TWELVE_MONTH_ARITHMETIC in reasons
    assert SUCCESS_COMPLIANCE in reasons
    # The oracle declines (fee_total_mismatch) while the family expects
    # acceptance, and the verifier rejects the declined decision.
    assert ORACLE_AGREEMENT in reasons
    assert VERIFIER_AGREEMENT in reasons


def test_message_offer_consistency_names_offer_content() -> None:
    configuration = PROVIDER_CONFIGURATIONS[0]
    forbidden = build_scenario(
        _family("forbidden_term"), configuration, parameters_from_seed(1)
    )
    assert forbidden.provider_turn.offers[0].applied_changes == (
        "contract_term_extension",
    )
    assert "contract-term extension" in forbidden.provider_turn.message
    assert check_instance_invariants(forbidden) == ()
    direct = build_scenario(
        _family("direct_success"), configuration, parameters_from_seed(10)
    )
    feature = direct.parameters.required_features[0]
    assert feature in direct.provider_turn.offers[0].features
    assert feature.replace("_", " ") in direct.provider_turn.message
    assert check_instance_invariants(direct) == ()
    frozen_direct = next(
        item
        for item in BENCHMARK_SCENARIOS
        if item.hazard == "direct_success"
        and item.configuration_id == configuration.configuration_id
    )
    assert frozen_direct.provider_turn.message == (
        "Public quote: A plan with mobile hotspot is available at the quoted price."
    )


@pytest.mark.parametrize(
    ("hazard", "message"),
    [
        ("direct_success", "Public quote: A plan is available at the quoted price."),
        (
            "plan_change",
            "Public quote: A plan with international roaming is available.",
        ),
        (
            "required_feature_loss",
            "Public quote: The offer does not include a feature.",
        ),
        ("forbidden_term", "Public quote: The offer includes a change."),
    ],
)
def test_message_offer_consistency_quarantines_mismatched_text(
    hazard: str, message: str
) -> None:
    scenario = build_scenario(
        _family(hazard), PROVIDER_CONFIGURATIONS[0], parameters_from_seed(10)
    )
    assert check_instance_invariants(scenario) == ()
    turn: ProviderTurn = replace(scenario.provider_turn, message=message)
    tampered = replace(scenario, provider_turn=turn)
    assert check_instance_invariants(tampered) == (MESSAGE_OFFER_CONSISTENCY,)


def test_harvest_positions_returns_two_positions() -> None:
    scenario = build_parameterised_scenarios(seeds=(5,))[0]
    positions = harvest_positions(scenario)
    assert [position.position_index for position in positions] == [1, 2]
    assert [position.event_cursor for position in positions] == [1, 3]
    first, second = positions
    assert first.observation.provider_message != second.observation.provider_message
    assert first.provider_turn.message == scenario.provider_turn.message
    assert first.oracle_action in {
        "accept_offer",
        "decline",
        "request_clarification",
        "request_replan",
        "escalate",
        "refuse_disclosure",
    }
    assert second.oracle_action
    assert (first.oracle_offer_id is not None) == (
        first.oracle_action == "accept_offer"
    )


def test_harvest_positions_records_oracle_action_per_family() -> None:
    for scenario in BENCHMARK_SCENARIOS:
        first, _second = harvest_positions(scenario)
        expected = scenario.expected_action.value
        actual = (
            "decline_offer" if first.oracle_action == "decline" else first.oracle_action
        )
        assert actual == expected, scenario.scenario_id


def test_committed_manifest_is_reproducible() -> None:
    path = ROOT / INVARIANT_MANIFEST_PATH
    committed = json.loads(path.read_text(encoding="utf-8"))
    assert committed["schema_version"] == INVARIANT_MANIFEST_SCHEMA_VERSION
    assert committed["seed_range"] == {"first": 1, "last": 1000, "count": 1000}
    assert committed["total_instances"] == 32_000
    assert committed["quarantined"] == []
    assert committed["quarantined_count"] == 0
    assert committed["accepted_count"] == 32_000
    assert committed["parameters_fingerprint"] == parameters_fingerprint(
        DEFAULT_INVARIANT_SEEDS
    )
    assert check_invariant_manifest(path, DEFAULT_INVARIANT_SEEDS) == ()


def test_manifest_check_reports_drift(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    report = write_invariant_manifest(path, (1, 2))
    assert check_invariant_manifest(path, (1, 2)) == ()
    tampered = report.to_dict()
    tampered["content_fingerprint"] = "0" * 64
    path.write_text(json.dumps(tampered), encoding="utf-8")
    assert check_invariant_manifest(path, (1, 2)) == (
        "manifest_drift:content_fingerprint",
    )
    tampered = report.to_dict()
    tampered["parameters_fingerprint"] = "0" * 64
    path.write_text(json.dumps(tampered), encoding="utf-8")
    assert check_invariant_manifest(path, (1, 2)) == (
        "manifest_drift:parameters_fingerprint",
    )
    assert check_invariant_manifest(tmp_path / "missing.json", (1,)) == (
        f"missing_manifest:{tmp_path / 'missing.json'}",
    )


def test_manifest_check_reports_committed_quarantine_rows(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    report = write_invariant_manifest(path, (1,))
    tampered = report.to_dict()
    scenario_id = build_parameterised_scenarios(seeds=(1,))[0].scenario_id
    tampered["quarantined"] = [
        {"scenario_id": scenario_id, "reason_codes": [ORACLE_AGREEMENT]}
    ]
    tampered["quarantined_count"] = 1
    tampered["accepted_count"] = 31
    path.write_text(json.dumps(tampered), encoding="utf-8")
    problems = check_invariant_manifest(path, (1,))
    assert f"quarantined:{scenario_id}:{ORACLE_AGREEMENT}" in problems
    assert "manifest_drift:quarantined" in problems
