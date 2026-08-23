from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "data" / "manifests" / "phase-02-pilot-manifest.json"
QUARANTINE_PATH = ROOT / "data" / "manifests" / "phase-02-quarantine.json"
REPORT_PATH = ROOT / "data" / "manifests" / "phase-02-quality-report.json"
SAMPLE_PATH = ROOT / "data" / "samples" / "phase-02-review-sample.json"
SCHEMA_PATH = ROOT / "data" / "schemas" / "normalized-trajectory-v1.schema.json"

EXPECTED_REJECTION_CATEGORIES = {
    "cross_split_semantic_collision",
    "exact_duplicate",
    "forbidden_model_field",
    "invalid_verifier_outcome",
    "missing_provenance",
    "pii_detected",
    "split_mismatch",
    "unapproved_license",
}


def read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_committed_pilot_artifacts_prove_the_frozen_gate() -> None:
    schema = read_json(SCHEMA_PATH)
    manifest = read_json(MANIFEST_PATH)
    quarantine = read_json(QUARANTINE_PATH)
    report = read_json(REPORT_PATH)

    assert schema["title"] == "NormalizedTrajectory"
    assert manifest["trajectory_count"] == 128
    assert manifest["scenario_count"] == 32
    assert manifest["family_count"] == 16
    assert manifest["provider_configuration_count"] == 2
    assert manifest["split_counts"] == {
        "development": 24,
        "test": 24,
        "train": 80,
    }
    assert quarantine["candidate_count"] == 8
    assert set(quarantine["reason_counts"]) == EXPECTED_REJECTION_CATEGORIES

    assert report["candidate_count"] == 136
    assert report["accepted_count"] == 128
    assert report["quarantined_count"] == 8
    assert report["provenance_completeness_percent"] == 100.0
    assert report["accepted_pii_violation_count"] == 0
    assert report["accepted_exact_duplicate_count"] == 0
    assert report["accepted_cross_split_leakage_count"] == 0
    assert report["external_model_call_count"] == 0
    assert report["external_input_token_count"] == 0
    assert report["external_output_token_count"] == 0
    assert report["estimated_external_cost_usd"] == 0
    assert report["human_review_status"] == "pending_human"
    assert report["training_ready"] is False
    assert report["expansion_decision"] == "conditional_data_factory_expansion"


def test_review_sample_is_redacted_pending_and_family_complete() -> None:
    sample = read_json(SAMPLE_PATH)
    records = sample["records"]

    assert isinstance(records, list)
    assert len(records) == 16
    assert {record["family_id"] for record in records} == {
        record["family_id"] for record in read_json(MANIFEST_PATH)["records"]
    }
    assert all(record["review_state"] == "pending_human" for record in records)
    serialized = json.dumps(records, sort_keys=True)
    assert "consumer_id" not in serialized
    assert "account_pin" not in serialized
    assert "@example" not in serialized
