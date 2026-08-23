from __future__ import annotations

from copy import deepcopy

from proxyloop_data_pipeline import (
    NormalizedTrajectory,
    build_pilot,
    build_quality_report,
    curate_candidates,
    lexical_fingerprint,
)
from proxyloop_data_pipeline.pipeline import fingerprint
from proxyloop_provider_simulator.scenarios import BENCHMARK_SCENARIOS


def test_pilot_meets_frozen_counts_and_safety_gate() -> None:
    bundle = build_pilot()

    assert len(bundle.accepted) == 128
    assert len(bundle.quarantined) == 8
    assert bundle.manifest["split_counts"] == {
        "train": 80,
        "development": 24,
        "test": 24,
    }
    assert bundle.report["provenance_completeness_percent"] == 100.0
    assert bundle.report["training_ready"] is False


def test_four_variants_change_learning_content_not_only_identity() -> None:
    bundle = build_pilot()
    first_scenario = BENCHMARK_SCENARIOS[0].scenario_id
    records = [
        item
        for item in bundle.accepted
        if item.lineage.derivation_parent_id == first_scenario
    ]

    assert len(records) == 4
    assert len({record.content_hash for record in records}) == 4
    assert len({record.semantic_fingerprint for record in records}) == 4
    assert (
        len({record.learning_content.assistant_response_text for record in records})
        == 4
    )


def test_content_hash_does_not_depend_on_identity_metadata() -> None:
    record = build_pilot().accepted[0]
    changed = record.model_dump(mode="python")
    changed["trajectory_id"] = "different-id"
    changed["review_state"] = "pending_human"

    parsed = NormalizedTrajectory.model_validate(changed)
    assert parsed.content_hash == record.content_hash


def test_rejection_probe_categories_are_exact() -> None:
    bundle = build_pilot()

    assert {item["reason_codes"][0] for item in bundle.quarantined} == {
        "missing_provenance",
        "unapproved_license",
        "pii_detected",
        "forbidden_model_field",
        "exact_duplicate",
        "cross_split_semantic_collision",
        "split_mismatch",
        "invalid_verifier_outcome",
    }


def test_generation_is_stable_under_scenario_reordering() -> None:
    ordered = build_pilot(BENCHMARK_SCENARIOS)
    reversed_input = build_pilot(tuple(reversed(BENCHMARK_SCENARIOS)))

    assert ordered.manifest == reversed_input.manifest
    assert ordered.quarantine_manifest == reversed_input.quarantine_manifest
    assert ordered.report == reversed_input.report
    assert ordered.review_sample == reversed_input.review_sample


def test_duplicate_identity_cannot_bypass_content_deduplication() -> None:
    record = build_pilot().accepted[0]
    original = record.model_dump(mode="python")
    duplicate = deepcopy(original)
    duplicate["trajectory_id"] = "zz-duplicate-id-only"

    accepted, rejected = curate_candidates([duplicate, original])
    assert len(accepted) == 1
    assert rejected[0]["reason_codes"] == ["exact_duplicate"]


def test_pii_scan_covers_nested_model_content_and_high_risk_fields() -> None:
    raw = build_pilot().accepted[0].model_dump(mode="python")
    raw["learning_content"]["observation"]["email"] = "synthetic@example.com"  # type: ignore[index]

    accepted, rejected = curate_candidates([raw])

    assert not accepted
    assert rejected[0]["reason_codes"] == ["pii_detected"]


def test_forbidden_scenario_label_is_quarantined() -> None:
    raw = build_pilot().accepted[0].model_dump(mode="python")
    raw["learning_content"]["observation"]["scenario_label"] = "private"  # type: ignore[index]

    accepted, rejected = curate_candidates([raw])

    assert not accepted
    assert rejected[0]["reason_codes"] == ["forbidden_model_field"]


def test_lexical_fingerprint_collides_on_case_whitespace_and_punctuation() -> None:
    bundle = build_pilot()
    train = next(
        record for record in bundle.accepted if record.lineage.split == "train"
    )
    development = next(
        record for record in bundle.accepted if record.lineage.split == "development"
    )
    noisy_content = train.learning_content.model_dump(mode="python")
    observation = noisy_content["observation"]
    assert isinstance(observation, dict)
    provider_message = observation["provider_message"]
    assert isinstance(provider_message, str)
    observation["provider_message"] = f"  {provider_message.upper()} !!!  "
    response = noisy_content["assistant_response_text"]
    assert isinstance(response, str)
    noisy_content["assistant_response_text"] = f"  {response.upper()} !!!  "

    collision = development.model_dump(mode="python")
    collision["trajectory_id"] = "zz-lexical-collision"
    collision["learning_content"] = noisy_content
    collision["verification"] = train.verification.model_dump(mode="python")
    collision["content_hash"] = fingerprint(
        {
            "learning_content": noisy_content,
            "verification": collision["verification"],
        }
    )
    collision["semantic_fingerprint"] = lexical_fingerprint(noisy_content)

    accepted, rejected = curate_candidates([train.model_dump(mode="python"), collision])

    assert len(accepted) == 1
    assert collision["semantic_fingerprint"] == train.semantic_fingerprint
    assert rejected[0]["reason_codes"] == ["cross_split_semantic_collision"]


def test_frozen_source_and_environment_verification_cannot_be_replaced() -> None:
    base = build_pilot().accepted[0].model_dump(mode="python")
    external_snapshot = deepcopy(base)
    external_snapshot["generation"]["snapshots"][0]["external_model"] = True  # type: ignore[index]

    forged_verification = deepcopy(base)
    forged_verification["trajectory_id"] = "zz-forged-verification"
    forged_verification["verification"]["evidence_ref"] = "forged-evidence"  # type: ignore[index]
    forged_verification["content_hash"] = fingerprint(
        {
            "learning_content": forged_verification["learning_content"],
            "verification": forged_verification["verification"],
        }
    )

    accepted, rejected = curate_candidates([external_snapshot, forged_verification])

    assert not accepted
    assert {item["reason_codes"][0] for item in rejected} == {
        "missing_provenance",
        "invalid_verifier_outcome",
    }


def test_quality_report_derives_failed_audit_from_mutated_evidence() -> None:
    raw = build_pilot().accepted[0].model_dump(mode="python")
    raw["source"]["source_id"] = "unexpected-source"  # type: ignore[index]
    raw["generation"]["snapshots"][0]["external_model"] = True  # type: ignore[index]
    raw["generation"]["snapshots"][0]["external_input_token_count"] = 9  # type: ignore[index]
    raw["generation"]["snapshots"][0]["estimated_external_cost_usd"] = 0.25  # type: ignore[index]
    mutated = NormalizedTrajectory.model_validate(raw)

    report = build_quality_report((mutated,), ())

    assert report["provenance_completeness_percent"] == 0.0
    assert report["external_model_call_count"] == 1
    assert report["external_input_token_count"] == 9
    assert report["estimated_external_cost_usd"] == 0.25
    assert report["automated_audit_status"] == "failed"


def test_missing_provenance_quarantine_retains_external_usage() -> None:
    raw = build_pilot().accepted[0].model_dump(mode="python")
    del raw["source"]
    raw["generation"]["snapshots"][0]["external_model"] = True  # type: ignore[index]
    raw["generation"]["snapshots"][0]["external_input_token_count"] = 9  # type: ignore[index]
    raw["generation"]["snapshots"][0]["estimated_external_cost_usd"] = 0.25  # type: ignore[index]

    accepted, quarantined = curate_candidates([raw])
    report = build_quality_report(accepted, quarantined)
    audit = quarantined[0]["audit"]

    assert not accepted
    assert quarantined[0]["reason_codes"] == ["missing_provenance"]
    assert audit == {
        "external_model_call_count": 1,
        "external_input_token_count": 9,
        "external_output_token_count": 0,
        "estimated_external_cost_usd": 0.25,
    }
    assert report["external_model_call_count"] == 1
    assert report["external_input_token_count"] == 9
    assert report["estimated_external_cost_usd"] == 0.25
    assert report["automated_audit_status"] == "failed"
