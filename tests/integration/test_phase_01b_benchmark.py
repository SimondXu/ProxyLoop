from __future__ import annotations

from copy import deepcopy

from scripts.run_phase_01b_benchmark import (
    FORBIDDEN_OBSERVATION_KEYS,
    _fingerprint,
    _gate_passes,
    _leaked_keys,
    build_benchmark_report,
)


def test_scripted_environment_ceiling_passes_all_32_scenarios() -> None:
    report = build_benchmark_report()

    assert report["scenario_count"] == 32
    assert report["family_count"] == 16
    assert report["provider_configuration_count"] == 2
    assert report["valid_outcome_count"] == 32
    assert report["false_completion_count"] == 0
    assert report["leakage_violation_count"] == 0
    assert report["gate_passed"] is True


def test_benchmark_report_is_deterministic() -> None:
    assert build_benchmark_report() == build_benchmark_report()


def test_every_run_has_no_observation_leakage_and_a_valid_outcome() -> None:
    report = build_benchmark_report()
    runs = report["runs"]
    assert isinstance(runs, list)

    assert all(run["leaked_observation_keys"] == [] for run in runs)
    assert all(run["verification"]["valid_outcome"] is True for run in runs)
    assert all(run["verification"]["false_completion"] is False for run in runs)
    assert all(
        run["verification"]["evidence_ref"] is not None
        for run in runs
        if run["verification"]["completed"] is True
    )


def test_leakage_scanner_rejects_nested_gold_and_private_keys() -> None:
    payload = {
        "safe": {"expected_action": "accept_offer"},
        "offers": [{"database_state": "hidden"}],
    }

    assert set(_leaked_keys(payload)) == {"database_state", "expected_action"}
    assert {"expected_action", "database_state"} <= FORBIDDEN_OBSERVATION_KEYS


def test_report_fingerprint_changes_if_a_result_is_tampered() -> None:
    report = build_benchmark_report()
    tampered = deepcopy(report)
    tampered["valid_outcome_count"] = 31

    report_payload = {
        key: value for key, value in report.items() if key != "report_fingerprint"
    }
    tampered_payload = {
        key: value for key, value in tampered.items() if key != "report_fingerprint"
    }

    assert _fingerprint(tampered_payload) != _fingerprint(report_payload)


def test_gate_rejects_missing_configuration_family_or_split() -> None:
    valid = {
        "scenario_count": 32,
        "family_count": 16,
        "provider_configuration_count": 2,
        "valid_outcome_count": 32,
        "false_completion_count": 0,
        "leakage_violation_count": 0,
        "family_split_counts": {"train": 10, "development": 3, "test": 3},
        "scenario_split_counts": {"train": 20, "development": 6, "test": 6},
    }

    assert _gate_passes(**valid) is True
    for key, invalid_value in (
        ("family_count", 15),
        ("provider_configuration_count", 1),
        ("family_split_counts", {"train": 16, "development": 0, "test": 0}),
    ):
        invalid = {**valid, key: invalid_value}
        assert _gate_passes(**invalid) is False


def test_report_fingerprint_binds_family_and_configuration_versions() -> None:
    report = build_benchmark_report()
    tampered = deepcopy(report)
    runs = tampered["runs"]
    runs[0]["family_version"] = "2.0"
    runs[0]["provider_configuration_version"] = "2.0"
    original_payload = {
        key: value for key, value in report.items() if key != "report_fingerprint"
    }
    tampered_payload = {
        key: value for key, value in tampered.items() if key != "report_fingerprint"
    }

    assert _fingerprint(tampered_payload) != _fingerprint(original_payload)
