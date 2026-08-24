from __future__ import annotations

import json

from scripts.run_phase_03a1_harness import (
    build_phase03a1_harness_report,
    check_harness,
)


def test_phase03a1_scripted_oracle_ceiling_has_two_visible_positions() -> None:
    report = build_phase03a1_harness_report()
    ceiling = report["ceiling_report"]
    assert isinstance(ceiling, dict)
    assert ceiling["scenario_count"] == 32
    assert ceiling["gate_passed"] is True
    assert ceiling["multi_position_episode_count"] == 32
    assert ceiling["false_completion_count"] == 0
    assert ceiling["valid_noncompletion_count"] > 0
    assert ceiling["provider_holdout_episode_count"] > 0
    assert ceiling["reference_strategy_input_count"] > 0
    assert ceiling["ineligible_reference_strategy_input_count"] == 0


def test_phase03a1_report_is_deterministic_and_json_serializable() -> None:
    first = build_phase03a1_harness_report()
    second = build_phase03a1_harness_report()
    assert first == second
    assert json.loads(json.dumps(first, ensure_ascii=False)) == first
    assert check_harness() == (True, ())


def test_phase03a1_public_episode_export_has_no_private_metadata() -> None:
    report = build_phase03a1_harness_report()
    episodes = report["episodes"]
    assert isinstance(episodes, list)
    serialized = json.dumps(episodes)
    for forbidden in (
        "family_id",
        "entity_cluster",
        "configuration_id",
        "expected_action",
        "expected_outcome",
        "private_reason_codes",
        "evaluator_criteria",
        "gold_label",
        "oracle_action",
        "oracle_offer_id",
        "oracle_reason_codes",
    ):
        assert forbidden not in serialized


def test_phase03a1_episode_export_binds_routes_traces_capability_and_evidence() -> None:
    report = build_phase03a1_harness_report()
    episodes = report["episodes"]
    assert isinstance(episodes, list)
    for episode in episodes:
        expected_routes = (
            ["slow_refresh", "fast_now"]
            if episode["reference_strategy_fixture_eligible"]
            else ["fast_now"]
        )
        assert [
            decision["outcome"] for decision in episode["routing_decisions"]
        ] == expected_routes
        assert all(
            trace["contract_type"] == "model_trace" and trace["result"] == "succeeded"
            for trace in episode["adapter_traces"]
        )
        if not episode["reference_strategy_fixture_eligible"]:
            assert all(
                trace["model"] != "scripted_slow" for trace in episode["adapter_traces"]
            )
        assert episode["capability_attempt"]["capability_id"].startswith("simulator.")
        assert episode["execution"] == {
            "first_status": "executed",
            "duplicate_status": "reused",
            "commit_count": 1,
            "evidence_id": episode["execution"]["evidence_id"],
        }
        assert episode["execution"]["evidence_id"] is not None
        assert episode["public_episode"]["provider_mutation_count"] in {0, 1}
        evidence_ref = episode["transition"]["evidence_ref"]
        evidence_refs = episode["public_episode"]["outcome"]["evidence_refs"]
        if evidence_ref is None:
            assert evidence_refs == []
        else:
            assert evidence_refs == [evidence_ref]
        assert len(episode["episode_fingerprint"]) == 64
