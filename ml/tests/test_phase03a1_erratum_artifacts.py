from __future__ import annotations

import json
from pathlib import Path

import pytest
from proxyloop_evaluation.artifacts_v2 import (
    R2_CEILING_PATH,
    R2_EPISODES_PATH,
    R2_HOSTED_BUDGET_CEILING_MICROUSD,
    R2_MANIFEST_PATH,
    R2_REPORT_PATH,
    R3_REPORT_PATH,
    build_r2_fixture_payloads,
    check_r2_artifacts,
    report_fingerprint_v2,
    write_fixtures_v2,
    write_report_v3,
)
from proxyloop_evaluation.fresh_fixtures import build_fresh_phase03a1_bundle
from proxyloop_evaluation.models import (
    EvaluationReportV2,
)
from proxyloop_evaluation.replay_v2 import derive_r3_report_from_r2
from proxyloop_evaluation.runner_v2 import initial_report_v2

ROOT = Path(__file__).resolve().parents[2]


def test_write_fixtures_is_deterministic_and_does_not_write_report(
    tmp_path: Path,
) -> None:
    write_fixtures_v2(tmp_path)
    first = {
        relative: (tmp_path / relative).read_text(encoding="utf-8")
        for relative in (R2_MANIFEST_PATH, R2_EPISODES_PATH, R2_CEILING_PATH)
    }

    write_fixtures_v2(tmp_path)
    second = {
        relative: (tmp_path / relative).read_text(encoding="utf-8")
        for relative in (R2_MANIFEST_PATH, R2_EPISODES_PATH, R2_CEILING_PATH)
    }

    assert first == second
    assert not (tmp_path / R2_REPORT_PATH).exists()


def test_fixture_payloads_bind_bundle_manifest_and_episode_fingerprints() -> None:
    payloads = build_r2_fixture_payloads()
    manifest = payloads[R2_MANIFEST_PATH]
    episodes = payloads[R2_EPISODES_PATH]
    ceiling = payloads[R2_CEILING_PATH]

    assert manifest["scenario_count"] == 32
    assert manifest["bundle_fingerprint"] == manifest["catalog"]["bundle_fingerprint"]
    assert manifest["manifest_fingerprint"] == manifest["manifest"]["content_hash"]
    assert episodes["episode_count"] == 32
    assert episodes["episode_fingerprint"] == ceiling["episode_fingerprint"]
    assert ceiling["gate_passed"] is True
    assert ceiling["valid_outcome_count"] == 32
    assert ceiling["false_completion_count"] == 0
    assert ceiling["leakage_violation_count"] == 0
    hosted = ceiling["hosted_configuration"]
    assert hosted["hosted_budget_ceiling_microusd"] == (
        R2_HOSTED_BUDGET_CEILING_MICROUSD
    )
    assert [row["reasoning_effort"] for row in hosted["conditions"]] == [
        "medium",
        "high",
        "medium",
        "high",
    ]
    assert sum(row["maximum_cost_microusd"] for row in hosted["conditions"]) == (
        R2_HOSTED_BUDGET_CEILING_MICROUSD
    )


def test_fixture_check_rejects_tampered_and_reordered_artifacts(tmp_path: Path) -> None:
    write_fixtures_v2(tmp_path)
    ok, errors = check_r2_artifacts(tmp_path)
    assert ok, errors

    episodes_path = tmp_path / R2_EPISODES_PATH
    payload = json.loads(episodes_path.read_text(encoding="utf-8"))
    payload["episodes"] = list(reversed(payload["episodes"]))
    episodes_path.write_text(json.dumps(payload), encoding="utf-8")
    ok, errors = check_r2_artifacts(tmp_path)
    assert not ok
    assert any("episode fingerprint" in error for error in errors)

    write_fixtures_v2(tmp_path)
    manifest_path = tmp_path / R2_MANIFEST_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["scenario_assignments"][0]["split"] = "heldout-tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    ok, errors = check_r2_artifacts(tmp_path)
    assert not ok
    assert any("manifest" in error for error in errors)


def test_fresh_ids_are_disjoint_from_legacy_catalog() -> None:
    payloads = build_r2_fixture_payloads()
    manifest = payloads[R2_MANIFEST_PATH]
    assert manifest["old_new_id_intersection"] == []
    assert set(manifest["scenario_ids"]) == {
        row["scenario_id"] for row in manifest["manifest"]["scenario_assignments"]
    }


def test_report_fingerprint_v2_excludes_only_fingerprint_field() -> None:
    payloads = build_r2_fixture_payloads()
    payload = {
        "schema_version": "phase-03a1-r2-report-v1",
        "generated_at": "2026-08-24T00:00:00Z",
        "catalog_fingerprint": payloads[R2_MANIFEST_PATH]["catalog_fingerprint"],
        "manifest_fingerprint": payloads[R2_MANIFEST_PATH]["manifest_fingerprint"],
        "episode_fingerprint": payloads[R2_EPISODES_PATH]["episode_fingerprint"],
        "ceiling_fingerprint": payloads[R2_CEILING_PATH]["ceiling_fingerprint"],
        "host_class": "test",
        "conditions": [],
        "hosted_budget_ceiling_microusd": 0,
        "cost_accounting_note": "test",
        "provider_identity_note": "test",
        "phase_completion_ready": False,
        "phase_completion_blockers": ["not_run"],
        "report_fingerprint": "0" * 64,
    }

    class Report:
        def model_dump(self, **_: object) -> dict[str, object]:
            return payload

    assert len(report_fingerprint_v2(Report())) == 64
    assert report_fingerprint_v2(Report()) != payload["report_fingerprint"]


@pytest.mark.parametrize(
    "relative", [R2_MANIFEST_PATH, R2_EPISODES_PATH, R2_CEILING_PATH]
)
def test_fixture_files_are_present_after_write(tmp_path: Path, relative: Path) -> None:
    write_fixtures_v2(tmp_path)
    assert (tmp_path / relative).is_file()


def test_root_bundle_is_stable_for_artifact_generation() -> None:
    bundle = build_fresh_phase03a1_bundle()
    payloads = build_r2_fixture_payloads()
    assert payloads[R2_MANIFEST_PATH]["bundle_fingerprint"] == (
        bundle.metadata.bundle_fingerprint
    )


def test_check_accepts_a_truthful_not_run_report_and_rejects_fingerprint_drift(
    tmp_path: Path,
) -> None:
    write_fixtures_v2(tmp_path)
    from proxyloop_evaluation.artifacts_v2 import write_report_v2

    fixtures = build_fresh_phase03a1_bundle().fixtures
    write_report_v2(tmp_path, initial_report_v2(fixtures, host_class="test"))
    ok, errors = check_r2_artifacts(tmp_path)
    assert ok, errors

    report_path = tmp_path / R2_REPORT_PATH
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    report_payload["generated_at"] = "2026-08-24T00:00:01Z"
    report_path.write_text(json.dumps(report_payload), encoding="utf-8")
    ok, errors = check_r2_artifacts(tmp_path)
    assert not ok
    assert "r2 report fingerprint drift" in errors


def test_check_rejects_refingerprinted_false_phase_readiness(tmp_path: Path) -> None:
    write_fixtures_v2(tmp_path)
    from proxyloop_evaluation.artifacts_v2 import write_report_v2

    fixtures = build_fresh_phase03a1_bundle().fixtures
    report = write_report_v2(
        tmp_path,
        initial_report_v2(fixtures, host_class="test"),
    )
    report_path = tmp_path / R2_REPORT_PATH
    tampered = report.model_copy(
        update={
            "phase_completion_ready": True,
            "phase_completion_blockers": (),
            "report_fingerprint": "0" * 64,
        }
    )
    tampered = tampered.model_copy(
        update={"report_fingerprint": report_fingerprint_v2(tampered)}
    )
    report_path.write_text(
        json.dumps(tampered.model_dump(mode="json")),
        encoding="utf-8",
    )

    ok, errors = check_r2_artifacts(tmp_path)

    assert not ok
    assert any("phase completion" in error for error in errors)


def _write_initial_r2_and_r3(
    tmp_path: Path,
) -> tuple[EvaluationReportV2, EvaluationReportV2]:
    from proxyloop_evaluation.artifacts_v2 import write_report_v2

    fixtures = build_fresh_phase03a1_bundle().fixtures
    source_draft = initial_report_v2(fixtures, host_class="test").model_copy(
        update={
            "generated_at": "2026-08-24T00:00:00Z",
            "report_fingerprint": "0" * 64,
        }
    )
    source = write_report_v2(
        tmp_path,
        source_draft,
    )
    corrected = write_report_v3(
        tmp_path,
        derive_r3_report_from_r2(source, fixtures=fixtures),
    )
    return source, corrected


def _write_refingerprinted(path: Path, report: EvaluationReportV2) -> None:
    bound = report.model_copy(
        update={"report_fingerprint": report_fingerprint_v2(report)}
    )
    path.write_text(json.dumps(bound.model_dump(mode="json")), encoding="utf-8")


def test_r3_checker_binds_source_and_rejects_refingerprinted_readiness(
    tmp_path: Path,
) -> None:
    write_fixtures_v2(tmp_path)
    _, corrected = _write_initial_r2_and_r3(tmp_path)
    assert corrected.source_generated_at == "2026-08-24T00:00:00Z"
    assert corrected.generated_at != corrected.source_generated_at
    assert corrected.source_qwen_output_token_cap == 512
    ok, errors = check_r2_artifacts(tmp_path)
    assert ok, errors

    tampered = corrected.model_copy(
        update={"phase_completion_ready": True, "phase_completion_blockers": ()}
    )
    _write_refingerprinted(tmp_path / R3_REPORT_PATH, tampered)

    ok, errors = check_r2_artifacts(tmp_path)
    assert not ok
    assert any("phase completion" in error for error in errors)


def test_r3_checker_rejects_refingerprinted_source_fingerprint_tamper(
    tmp_path: Path,
) -> None:
    write_fixtures_v2(tmp_path)
    _, corrected = _write_initial_r2_and_r3(tmp_path)
    tampered = corrected.model_copy(update={"source_report_fingerprint": "f" * 64})
    _write_refingerprinted(tmp_path / R3_REPORT_PATH, tampered)

    ok, errors = check_r2_artifacts(tmp_path)
    assert not ok
    assert "r3 source report fingerprint mismatch" in errors


@pytest.mark.parametrize("tamper", ["raw_evidence", "not_run_reason"])
def test_r3_checker_rejects_refingerprinted_r2_source_tamper(
    tmp_path: Path,
    tamper: str,
) -> None:
    write_fixtures_v2(tmp_path)
    source, _ = _write_initial_r2_and_r3(tmp_path)
    conditions = list(source.conditions)
    if tamper == "raw_evidence":
        rows = list(conditions[0].episodes)
        rows[0] = rows[0].model_copy(update={"slow_raw_output": "{}"})
        conditions[0] = conditions[0].model_copy(update={"episodes": tuple(rows)})
    else:
        conditions[3] = conditions[3].model_copy(
            update={"not_run_reason": "tampered not-run reason"}
        )
    tampered = source.model_copy(update={"conditions": tuple(conditions)})
    _write_refingerprinted(tmp_path / R2_REPORT_PATH, tampered)

    ok, errors = check_r2_artifacts(tmp_path)
    assert not ok
    assert "r3 source report fingerprint mismatch" in errors


def test_check_replays_scripted_rows_after_a_valid_refingerprint(
    tmp_path: Path,
) -> None:
    write_fixtures_v2(tmp_path)
    from proxyloop_evaluation.artifacts_v2 import write_report_v2

    fixtures = build_fresh_phase03a1_bundle().fixtures
    write_report_v2(tmp_path, initial_report_v2(fixtures, host_class="test"))
    report_path = tmp_path / R2_REPORT_PATH
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    scripted = payload["conditions"][0]
    scripted["episodes"][0]["end_to_end_valid"] = False
    scripted["end_to_end_valid_count"] -= 1
    payload["phase_completion_ready"] = False
    payload["phase_completion_blockers"] = [
        f"{condition['condition']}:{condition['run_status']}"
        for condition in payload["conditions"]
        if condition["run_status"] != "succeeded"
    ] + ["scripted_oracle_ceiling_r2:gate_failed"]
    unbound = EvaluationReportV2.model_validate_json(
        json.dumps({**payload, "report_fingerprint": "0" * 64})
    )
    payload["report_fingerprint"] = report_fingerprint_v2(unbound)
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    ok, errors = check_r2_artifacts(tmp_path)

    assert not ok
    assert any("scripted" in error and "replay" in error for error in errors)
