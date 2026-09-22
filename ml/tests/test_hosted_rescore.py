from __future__ import annotations

import dataclasses
import shutil
import sys
from pathlib import Path

import pytest
from proxyloop_evaluation.artifacts import (
    CEILING_PATH,
    EPISODES_PATH,
    MANIFEST_PATH,
    REPORT_PATH,
    check_baseline_artifacts,
    check_baseline_artifacts_historical,
)
from proxyloop_evaluation.artifacts_v2 import (
    R2_CEILING_PATH,
    R2_EPISODES_PATH,
    R2_MANIFEST_PATH,
    R2_REPORT_PATH,
    R3_REPORT_PATH,
    report_fingerprint_v2,
)
from proxyloop_evaluation.fresh_fixtures import (
    FreshPhase03A1ModelFixture,
    build_fresh_phase03a1_bundle,
)
from proxyloop_evaluation.hosted_rerun import (
    _R4_EXECUTION_PATHS,
    R4_REPORT_PATH,
    HostedRerunReport,
    ProviderErrorEvidence,
    execution_contract_fingerprint_r4,
    load_report_r4,
    report_fingerprint_r4,
    write_report_r4,
)
from proxyloop_evaluation.hosted_rescore import (
    _EXPECTED_ROWS_CHANGED_VS_R4,
    R4_RESCORED_REPORT_PATH,
    R4_RESCORED_SCHEMA_VERSION,
    RescoredReportV2,
    check_r4_integrity,
    check_rescored_artifact,
    derive_rescored_r4,
    execution_contract_state,
    rescored_report_fingerprint,
    write_rescored_report,
)
from proxyloop_provider_simulator.environment import (
    PROVIDER_VERIFIER_VERSION,
    ProviderEnvironment,
)

ROOT = Path(__file__).resolve().parents[2]
_SOURCE_PATHS = (
    R2_MANIFEST_PATH,
    R2_EPISODES_PATH,
    R2_CEILING_PATH,
    R2_REPORT_PATH,
    R3_REPORT_PATH,
    R4_REPORT_PATH,
)


def _copy(tmp_path: Path, relatives: tuple[Path | str, ...]) -> None:
    for relative in relatives:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)


@pytest.fixture(scope="module")
def fixtures() -> tuple[FreshPhase03A1ModelFixture, ...]:
    return build_fresh_phase03a1_bundle().fixtures


@pytest.fixture(scope="module")
def committed_r4() -> HostedRerunReport:
    return load_report_r4(ROOT)


@pytest.fixture(scope="module")
def rescored(
    committed_r4: HostedRerunReport,
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
) -> RescoredReportV2:
    return derive_rescored_r4(committed_r4, fixtures=fixtures)


def _rebind(report: RescoredReportV2) -> RescoredReportV2:
    inner = report.rescored
    inner = inner.model_copy(
        update={"report_fingerprint": report_fingerprint_v2(inner)}
    )
    draft = report.model_copy(update={"rescored": inner})
    return draft.model_copy(
        update={"report_fingerprint": rescored_report_fingerprint(draft)}
    )


def test_current_evaluator_rescores_r4_row_for_row(
    committed_r4: HostedRerunReport,
    rescored: RescoredReportV2,
) -> None:
    assert rescored.schema_version == R4_RESCORED_SCHEMA_VERSION
    assert rescored.rescored.schema_version == R4_RESCORED_SCHEMA_VERSION
    assert rescored.rescored.source_report_fingerprint == (
        committed_r4.report_fingerprint
    )
    assert rescored.rescored.evaluator_version == (
        f"phase-03a1-rescore::{PROVIDER_VERIFIER_VERSION}"
    )
    assert rescored.rescored.new_external_dispatch_count == 0
    assert set(rescored.rows_changed_vs_r4) == {
        condition.condition.value for condition in committed_r4.matrix_result.conditions
    }
    assert rescored.rows_changed_vs_r4 == _EXPECTED_ROWS_CHANGED_VS_R4
    for derived, source in zip(
        rescored.rescored.conditions,
        committed_r4.matrix_result.conditions,
        strict=True,
    ):
        changed = rescored.rows_changed_vs_r4[source.condition.value]
        for derived_row, source_row in zip(
            derived.episodes, source.episodes, strict=True
        ):
            assert derived_row.episode_id == source_row.episode_id
            derived_json = derived_row.model_dump(mode="json")
            source_json = source_row.model_dump(mode="json")
            if source_row.episode_id not in changed:
                assert derived_json == source_json
                continue
            # The state verifier accepts these ``request_replan`` proposals on
            # unacceptable offers; nothing else about the row moves.
            assert source_json["provider_outcome_valid"] is False
            assert derived_json["provider_outcome_valid"] is True
            assert derived_json["reference_match"] is False
            assert derived_json["completed"] is False
            assert derived_json["false_completion"] is False
            assert "invalid_provider_outcome" in source_json["failure_codes"]
            assert "invalid_provider_outcome" not in derived_json["failure_codes"]
            for key in ("end_to_end_valid", "safe_noncompletion", "failure_codes"):
                derived_json.pop(key)
                source_json.pop(key)
            derived_json.pop("provider_outcome_valid")
            source_json.pop("provider_outcome_valid")
            assert derived_json == source_json


def test_committed_rescored_artifact_passes_the_check() -> None:
    passed, failures = check_rescored_artifact(ROOT)

    assert passed, failures


def _flip_row(
    report: RescoredReportV2, condition_index: int, field: str
) -> RescoredReportV2:
    condition = report.rescored.conditions[condition_index]
    if field == "failure_codes":
        row_index = 0
        row = condition.episodes[row_index]
        flipped = row.model_copy(
            update={"failure_codes": (*row.failure_codes, "tampered_code")}
        )
        count_update: dict[str, int] = {}
    else:
        row_index = next(
            index
            for index, row in enumerate(condition.episodes)
            if row.end_to_end_valid
        )
        row = condition.episodes[row_index]
        flipped = row.model_copy(update={"end_to_end_valid": False})
        count_update = {"end_to_end_valid_count": condition.end_to_end_valid_count - 1}
    episodes = list(condition.episodes)
    episodes[row_index] = flipped
    tampered_condition = condition.model_copy(
        update={"episodes": tuple(episodes), **count_update}
    )
    conditions = list(report.rescored.conditions)
    conditions[condition_index] = tampered_condition
    tampered_inner = report.rescored.model_copy(
        update={"conditions": tuple(conditions)}
    )
    return _rebind(report.model_copy(update={"rescored": tampered_inner}))


@pytest.mark.parametrize(
    ("condition_index", "field"),
    ((3, "failure_codes"), (5, "end_to_end_valid")),
)
def test_rescore_check_rejects_flipped_row_with_refreshed_fingerprint(
    tmp_path: Path,
    rescored: RescoredReportV2,
    condition_index: int,
    field: str,
) -> None:
    _copy(tmp_path, _SOURCE_PATHS)
    write_rescored_report(tmp_path, _flip_row(rescored, condition_index, field))

    passed, failures = check_rescored_artifact(tmp_path)

    assert not passed
    assert "rescored artifact differs from the in-memory derivation" in failures


def test_rescore_check_rejects_laundered_r4_row_tamper(
    tmp_path: Path,
    committed_r4: HostedRerunReport,
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
) -> None:
    """Flip an r4 row, refresh every fingerprint, regenerate: still rejected."""

    _copy(tmp_path, _SOURCE_PATHS)
    matrix = committed_r4.matrix_result
    condition = matrix.conditions[3]
    row = condition.episodes[0]
    flipped = row.model_copy(
        update={"failure_codes": (*row.failure_codes, "tampered_code")}
    )
    tampered_condition = condition.model_copy(
        update={"episodes": (flipped, *condition.episodes[1:])}
    )
    tampered_matrix = matrix.model_copy(
        update={
            "conditions": (
                *matrix.conditions[:3],
                tampered_condition,
                *matrix.conditions[4:],
            )
        }
    )
    tampered_matrix = tampered_matrix.model_copy(
        update={"report_fingerprint": report_fingerprint_v2(tampered_matrix)}
    )
    tampered_r4 = committed_r4.model_copy(update={"matrix_result": tampered_matrix})
    tampered_r4 = write_report_r4(tmp_path, tampered_r4)
    regenerated = write_rescored_report(
        tmp_path, derive_rescored_r4(tampered_r4, fixtures=fixtures)
    )
    expected = _EXPECTED_ROWS_CHANGED_VS_R4[condition.condition.value]
    assert row.episode_id not in expected
    assert regenerated.rows_changed_vs_r4[condition.condition.value] == tuple(
        sorted((*expected, row.episode_id))
    )

    passed, failures = check_rescored_artifact(tmp_path)

    assert not passed
    assert failures == ("rows_changed_vs_r4 differs from the recorded evaluator delta",)


def test_recorded_evaluator_delta_is_the_state_verifier_flip() -> None:
    assert PROVIDER_VERIFIER_VERSION == "phase-01b-verifier-v2-state"
    assert {name: len(ids) for name, ids in _EXPECTED_ROWS_CHANGED_VS_R4.items()} == {
        "scripted_oracle_ceiling_r2": 0,
        "untuned_fast_reference_strategy_r2": 0,
        "untuned_fast_slow_off_r2": 0,
        "untuned_fast_frontier_slow_medium": 2,
        "untuned_fast_frontier_slow_high": 1,
        "frontier_reference_medium": 0,
        "frontier_reference_high": 1,
    }
    for ids in _EXPECTED_ROWS_CHANGED_VS_R4.values():
        assert ids == tuple(sorted(ids))
        for episode_id in ids:
            assert (
                "forbidden-term" in episode_id or "required-feature-loss" in episode_id
            )


def test_derivation_runs_the_current_verifier(
    monkeypatch: pytest.MonkeyPatch,
    committed_r4: HostedRerunReport,
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
) -> None:
    """A verifier change must surface as row changes, not be copied over."""

    original = ProviderEnvironment._verify_decision

    def invalidate_everything(
        self: ProviderEnvironment, *args: object, **kwargs: object
    ) -> object:
        return dataclasses.replace(original(self, *args, **kwargs), valid_outcome=False)

    monkeypatch.setattr(ProviderEnvironment, "_verify_decision", invalidate_everything)

    rescored = derive_rescored_r4(committed_r4, fixtures=fixtures)

    hosted = tuple(
        condition.condition.value
        for condition in committed_r4.matrix_result.conditions[3:]
    )
    assert any(rescored.rows_changed_vs_r4[name] for name in hosted), (
        rescored.rows_changed_vs_r4
    )


def test_rescore_check_rejects_wrong_source_fingerprint(
    tmp_path: Path,
    rescored: RescoredReportV2,
) -> None:
    _copy(tmp_path, _SOURCE_PATHS)
    tampered_inner = rescored.rescored.model_copy(
        update={"source_report_fingerprint": "f" * 64}
    )
    write_rescored_report(
        tmp_path, _rebind(rescored.model_copy(update={"rescored": tampered_inner}))
    )

    passed, failures = check_rescored_artifact(tmp_path)

    assert not passed
    assert "rescored source r4 fingerprint mismatch" in failures


def test_rescore_check_requires_the_separate_artifact(tmp_path: Path) -> None:
    _copy(tmp_path, _SOURCE_PATHS)

    passed, failures = check_rescored_artifact(tmp_path)

    assert not passed
    assert failures == (f"missing rescored artifact: {R4_RESCORED_REPORT_PATH}",)


def test_integrity_passes_on_the_committed_tree() -> None:
    passed, failures = check_r4_integrity(ROOT)

    assert passed, failures


def test_integrity_requires_the_r4_artifact(tmp_path: Path) -> None:
    _copy(tmp_path, _SOURCE_PATHS[:-1])

    passed, failures = check_r4_integrity(tmp_path)

    assert not passed
    assert failures == (f"missing r4 artifact: {R4_REPORT_PATH}",)


def test_integrity_rejects_refingerprinted_source_binding_tamper(
    tmp_path: Path,
    committed_r4: HostedRerunReport,
) -> None:
    _copy(tmp_path, _SOURCE_PATHS)
    tampered = committed_r4.model_copy(
        update={"source_r3_report_fingerprint": "f" * 64}
    )
    tampered = tampered.model_copy(
        update={"report_fingerprint": report_fingerprint_r4(tampered)}
    )
    write_report_r4(tmp_path, tampered)

    passed, failures = check_r4_integrity(tmp_path)

    assert not passed
    assert "r4 source r3 fingerprint mismatch" in failures


def test_integrity_rejects_unrefreshed_fingerprint_tamper(
    tmp_path: Path,
    committed_r4: HostedRerunReport,
) -> None:
    _copy(tmp_path, _SOURCE_PATHS)
    tampered = committed_r4.model_copy(
        update={"source_r2_generated_at": "2000-01-01T00:00:00Z"}
    )
    write_report_r4(tmp_path, tampered)

    passed, failures = check_r4_integrity(tmp_path)

    assert not passed
    assert "r4 source r2 timestamp mismatch" in failures


@pytest.mark.parametrize("mutation", ("delete", "index", "duplicate"))
def test_integrity_rejects_refingerprinted_provider_error_tamper(
    tmp_path: Path,
    committed_r4: HostedRerunReport,
    mutation: str,
) -> None:
    _copy(tmp_path, _SOURCE_PATHS)
    first, *rest = committed_r4.provider_errors
    assert first.call_index is not None
    if mutation == "delete":
        provider_errors: tuple[ProviderErrorEvidence, ...] = tuple(rest)
    elif mutation == "index":
        provider_errors = (first.model_copy(update={"call_index": 999}), *rest)
    else:
        provider_errors = (first, first, *rest)
    tampered = committed_r4.model_copy(update={"provider_errors": provider_errors})
    tampered = tampered.model_copy(
        update={"report_fingerprint": report_fingerprint_r4(tampered)}
    )
    write_report_r4(tmp_path, tampered)

    passed, failures = check_r4_integrity(tmp_path)

    assert not passed
    assert any("Provider error evidence" in failure for failure in failures)


def test_contract_state_is_unchanged_on_the_committed_tree(
    committed_r4: HostedRerunReport,
) -> None:
    state = execution_contract_state(ROOT)

    assert state == {
        "r4_fingerprint": committed_r4.execution_contract_fingerprint,
        "current_fingerprint": execution_contract_fingerprint_r4(),
        "state": "unchanged",
        "drifted_paths": (),
        "pins_stale": False,
    }


@pytest.mark.parametrize("drifted", _R4_EXECUTION_PATHS)
def test_contract_state_reports_each_drifted_frozen_path(
    tmp_path: Path,
    committed_r4: HostedRerunReport,
    drifted: str,
) -> None:
    _copy(tmp_path, (R4_REPORT_PATH, *_R4_EXECUTION_PATHS))
    assert execution_contract_state(tmp_path)["state"] == "unchanged"
    target = tmp_path / drifted
    target.write_bytes(target.read_bytes() + b"\n# drift\n")

    state = execution_contract_state(tmp_path)

    assert state["state"] == "drifted_since_r4"
    assert state["drifted_paths"] == (drifted,)
    assert state["r4_fingerprint"] == committed_r4.execution_contract_fingerprint
    assert state["current_fingerprint"] != state["r4_fingerprint"]


def test_contract_state_reports_a_missing_frozen_path(tmp_path: Path) -> None:
    _copy(tmp_path, (R4_REPORT_PATH, *_R4_EXECUTION_PATHS))
    missing = _R4_EXECUTION_PATHS[2]
    (tmp_path / missing).unlink()

    state = execution_contract_state(tmp_path)

    assert state["state"] == "drifted_since_r4"
    assert state["drifted_paths"] == (missing,)
    assert state["pins_stale"] is False


def test_stale_pins_are_reported_not_silent(
    tmp_path: Path,
    committed_r4: HostedRerunReport,
) -> None:
    _copy(tmp_path, (*_SOURCE_PATHS, *_R4_EXECUTION_PATHS))
    tampered = committed_r4.model_copy(
        update={"execution_contract_fingerprint": "e" * 64}
    )
    tampered = tampered.model_copy(
        update={"report_fingerprint": report_fingerprint_r4(tampered)}
    )
    write_report_r4(tmp_path, tampered)

    state = execution_contract_state(tmp_path)
    passed, failures = check_r4_integrity(tmp_path)

    assert state["state"] == "drifted_since_r4"
    assert state["drifted_paths"] == ()
    assert state["pins_stale"] is True
    assert not passed
    assert "r4 execution contract pins are stale" in failures


def test_contract_state_never_fails_integrity_or_rescore(
    tmp_path: Path,
    rescored: RescoredReportV2,
) -> None:
    _copy(tmp_path, (*_SOURCE_PATHS, *_R4_EXECUTION_PATHS))
    write_rescored_report(tmp_path, rescored)
    target = tmp_path / _R4_EXECUTION_PATHS[0]
    target.write_bytes(target.read_bytes() + b"\n# drift\n")

    assert execution_contract_state(tmp_path)["state"] == "drifted_since_r4"
    integrity_passed, integrity_failures = check_r4_integrity(tmp_path)
    rescore_passed, rescore_failures = check_rescored_artifact(tmp_path)

    assert integrity_passed, integrity_failures
    assert rescore_passed, rescore_failures


def test_historical_baseline_check_passes_without_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "proxyloop_evaluation.replay", None)

    passed, failures = check_baseline_artifacts_historical(ROOT)

    assert passed, failures
    with pytest.raises(ImportError):
        check_baseline_artifacts(ROOT)


def test_historical_baseline_check_keeps_integrity_checks(tmp_path: Path) -> None:
    _copy(tmp_path, (REPORT_PATH, MANIFEST_PATH, EPISODES_PATH, CEILING_PATH))
    target = tmp_path / REPORT_PATH
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            '"harness_ceiling_gate_passed": true',
            '"harness_ceiling_gate_passed": false',
        ),
        encoding="utf-8",
    )

    passed, failures = check_baseline_artifacts_historical(tmp_path)

    assert not passed
    assert "scripted Harness ceiling must pass" in failures
    assert "baseline report fingerprint drift" in failures
