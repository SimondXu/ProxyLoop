from __future__ import annotations

import json
from dataclasses import replace

from proxyloop_agent_core import ScriptedOracleConsumer
from proxyloop_contracts import CaseContextSnapshot
from proxyloop_evaluation.fresh_fixtures import (
    FRESH_PHASE03A1_CATALOG_VERSION,
    FRESH_PHASE03A1_FIXTURE_DERIVATION_VERSION,
    FRESH_PHASE03A1_SEED_VERSION,
    build_fresh_phase03a1_bundle,
    build_fresh_phase03a1_manifest,
    build_fresh_phase03a1_scenarios,
    build_fresh_safe_observation,
)
from proxyloop_provider_simulator.multi_turn import MultiTurnProviderEnvironment
from proxyloop_provider_simulator.scenarios import BENCHMARK_SCENARIOS


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def test_fresh_catalog_has_disjoint_r2_ids_and_preserves_known_breadth() -> None:
    old_ids = {scenario.scenario_id for scenario in BENCHMARK_SCENARIOS}
    fresh = build_fresh_phase03a1_scenarios()

    assert len(fresh) == 32
    assert len({scenario.scenario_id for scenario in fresh}) == 32
    assert not old_ids.intersection(scenario.scenario_id for scenario in fresh)
    assert {scenario.family_id for scenario in fresh} == {
        scenario.family_id for scenario in BENCHMARK_SCENARIOS
    }
    assert {scenario.configuration_id for scenario in fresh} == {
        scenario.configuration_id for scenario in BENCHMARK_SCENARIOS
    }
    assert all(scenario.family_version.startswith("2.") for scenario in fresh)
    assert all(scenario.configuration_version.startswith("2.") for scenario in fresh)
    assert all(scenario.scenario_id.startswith("phase-03a1-r2::") for scenario in fresh)
    assert all(
        scenario.provider_turn.turn_id.startswith("phase-03a1-r2::")
        for scenario in fresh
    )
    assert all(
        scenario.provider_turn.message.startswith("Fresh Provider update:")
        for scenario in fresh
    )


def test_fresh_bundle_fingerprint_is_order_invariant_and_version_bound() -> None:
    bundle = build_fresh_phase03a1_bundle()
    reversed_bundle = build_fresh_phase03a1_bundle(
        scenarios=tuple(reversed(bundle.scenarios))
    )

    assert bundle.metadata.catalog_version == FRESH_PHASE03A1_CATALOG_VERSION
    assert bundle.metadata.seed_version == FRESH_PHASE03A1_SEED_VERSION
    assert (
        bundle.metadata.fixture_derivation_version
        == FRESH_PHASE03A1_FIXTURE_DERIVATION_VERSION
    )
    assert (
        bundle.metadata.bundle_fingerprint
        == reversed_bundle.metadata.bundle_fingerprint
    )

    drifted = replace(bundle.scenarios[0], family_version="2.1")
    drifted_bundle = build_fresh_phase03a1_bundle(
        scenarios=(drifted, *bundle.scenarios[1:])
    )
    assert (
        drifted_bundle.metadata.bundle_fingerprint != bundle.metadata.bundle_fingerprint
    )


def test_fresh_manifest_exposes_all_split_ids_without_crossing_boundaries() -> None:
    scenarios = build_fresh_phase03a1_scenarios()
    manifest = build_fresh_phase03a1_manifest(scenarios)

    assert manifest.scenario_count == 32
    assert manifest.split_counts == {
        "development": 16,
        "family_entity_heldout": 6,
        "safety": 10,
    }
    assert manifest.provider_split_counts == {
        "development": 16,
        "provider_heldout": 16,
    }
    assert set(manifest.ids_for_split("development"))
    assert set(manifest.ids_for_split("family_entity_heldout"))
    assert set(manifest.ids_for_split("safety"))
    assert set(manifest.ids_for_provider_split("provider_heldout"))
    assert set(manifest.ids_for_split("safety")).issubset(
        set(manifest.ids_for_split("safety"))
    )
    assert all(
        assignment.family_split == assignment.entity_split
        for assignment in manifest.scenario_assignments
    )


def test_model_fixtures_strip_oracle_actions_and_recompute_snapshot_pins() -> None:
    bundle = build_fresh_phase03a1_bundle()

    assert len(bundle.fixtures) == 32
    for fixture in bundle.fixtures:
        snapshot = CaseContextSnapshot.model_validate(
            fixture.snapshot.model_dump(mode="python")
        )
        assert snapshot.action_intents == ()
        assert snapshot.approval_requests == ()
        assert snapshot.planning_basis.approval_state_fingerprint
        assert snapshot.pins.planning_basis_fingerprint == (
            snapshot.planning_basis.planning_basis_fingerprint
        )
        assert fixture.reference_capability_id.startswith("simulator.")
        snapshot_dump = _json(snapshot.model_dump(mode="json")).lower()
        assert "reference_capability_id" not in snapshot_dump
        assert "reference_offer_id" not in snapshot_dump
        assert "expected_action" not in snapshot_dump
        assert "expected_outcome" not in snapshot_dump


def test_r2_scripted_oracle_environment_is_safe_and_prompt_dump_is_public_only() -> (
    None
):
    bundle = build_fresh_phase03a1_bundle()
    valid = 0
    false_completion = 0
    forbidden = {
        "family_id",
        "entity_cluster",
        "configuration_id",
        "expected_action",
        "expected_outcome",
        "reference_capability_id",
        "reference_offer_id",
        "private_reason_codes",
        "oracle_action",
    }

    for scenario in bundle.scenarios:
        environment = MultiTurnProviderEnvironment(scenario)
        opening = environment.start()
        decision = ScriptedOracleConsumer().decide(
            build_fresh_safe_observation(scenario, opening.turn)
        )
        attempt = {
            "capability_id": f"simulator.{decision.action.value}",
            "idempotency_key": f"r2-oracle:{scenario.scenario_id}",
            "offer_id": decision.offer_id,
        }
        transition = environment.submit_capability_attempt(attempt)
        valid += int(transition.verification.valid_outcome)
        false_completion += int(transition.verification.false_completion)
        dump = _json(environment.export_public_episode())
        assert not any(key in dump for key in forbidden)

    assert valid == 32
    assert false_completion == 0
