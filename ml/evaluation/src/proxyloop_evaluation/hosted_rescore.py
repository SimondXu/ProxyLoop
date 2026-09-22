"""Integrity, contract-state, and offline rescore for the frozen r4 evidence.

The r4 execution bytes (``hosted_rerun._R4_EXECUTION_PATHS``) stay
byte-identical as the record of what r4 ran with.  This module carries the
checker so the evaluator can evolve without editing them:

- ``check_r4_integrity`` keeps every integrity property of the r4 gate except
  the fresh-fixture replay, calling the frozen ``hosted_rerun`` helpers;
- ``execution_contract_state`` reports whether those bytes still match r4
  (reported, never a failure);
- ``derive_rescored_r4`` re-reads the r4 raw outputs with the *current*
  evaluator into a separately versioned, deterministic artifact;
- ``check_rescored_artifact`` binds the committed rescored artifact to that
  derivation byte for byte.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from proxyloop_provider_simulator.environment import PROVIDER_VERIFIER_VERSION
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .artifacts_v2 import (
    R2_QWEN_OUTPUT_TOKEN_CAP,
    canonical_json,
    report_fingerprint_v2,
)
from .fresh_fixtures import FreshPhase03A1ModelFixture
from .hosted_rerun import (
    _R4_EXECUTION_PATHS,
    R4_PROBE_PER_CALL_MAX_MICROUSD,
    R4_REPORT_PATH,
    HostedRerunReport,
    _fresh_fixtures,
    _provider_error_reconciliation_errors,
    load_report_r4,
    load_source_reports,
    report_fingerprint_r4,
)
from .models import EvaluationReportV2, EvaluationSummaryV2, RunStatus
from .openai_frontier import build_probe_prompt
from .replay_v2 import _preserve_source_evidence, _replay_condition
from .runner_v2 import compose_report_v2

R4_RESCORED_REPORT_PATH = Path("data/evaluation/phase-03a1-r4-rescored-report.json")
R4_RESCORED_SCHEMA_VERSION: Literal["phase-03a1-r4-rescored-v1"] = (
    "phase-03a1-r4-rescored-v1"
)
RESCORE_EVALUATOR_VERSION = f"phase-03a1-rescore::{PROVIDER_VERIFIER_VERSION}"
# Per-file sha256 of the frozen r4 execution bytes.  Their canonical-JSON
# aggregate equals the committed r4 ``execution_contract_fingerprint``; the
# table exists so drift can be attributed to a path, not only detected.
_R4_FILE_HASHES: dict[str, str] = {
    "ml/pyproject.toml": (
        "8217e48f9aec1aa63fbfa26d07bbe42c5077cb4694c103d3eb846fe48a6a7b1c"
    ),
    "ml/uv.lock": ("452ec3243d750b1fd50decfc7744051be9a370fcaa679337d99f17f48e446da2"),
    "ml/evaluation/src/proxyloop_evaluation/artifacts_v2.py": (
        "3f3e2ad72b958bb11e0db1d6a17399a4d0a4e1114753750b5d545c78cbe367f8"
    ),
    "ml/evaluation/src/proxyloop_evaluation/fast_output.py": (
        "b122ac3d00ed3e4e626b7fa85315031913151cd8397f1a51d8b3468dfb9ca132"
    ),
    "ml/evaluation/src/proxyloop_evaluation/fresh_fixtures.py": (
        "b23390ab09b49a6c8ddb3cb5a1b9d94e39dc4d6c4f8bffcedcc9680d27f37ea5"
    ),
    "ml/evaluation/src/proxyloop_evaluation/hosted_rerun.py": (
        "3fd6c441f9e81621f2ae20fe0d53d28eb75fb6b75c6031d3447ce60a02a3e1a5"
    ),
    "ml/evaluation/src/proxyloop_evaluation/openai_frontier.py": (
        "7248c6438c3db453ebbf32ea38c5ae77e0feb2fd0084ce4a3fefcc355eb1d3cb"
    ),
    "ml/evaluation/src/proxyloop_evaluation/qwen_mlx.py": (
        "f482b04f95e3eae94e126ca3d0bf443467b20c2c81fadf065b55df55952c0f78"
    ),
    "ml/evaluation/src/proxyloop_evaluation/replay_v2.py": (
        "2569a774390639a898874796f0284a34b4e5072e012476728a04989d479c318e"
    ),
    "ml/evaluation/src/proxyloop_evaluation/runner_v2.py": (
        "46ad196c4eb1ebab6f09c2302a8f8448e843d875262003f6d029b1f1ef659c4f"
    ),
    "ml/evaluation/src/proxyloop_evaluation/slow_output.py": (
        "825a2d5bf67c7edaa3a2f809b80c32d7dc02733867bae5215df34147d7fe85f5"
    ),
    "scripts/run_phase_03a1_hosted_rerun.py": (
        "537b73a503b3b07ace908a4b36283bca499917a0ee947edf52999cd568d83183"
    ),
}
_R4_PINNED_FINGERPRINT = hashlib.sha256(
    canonical_json(_R4_FILE_HASHES).encode("utf-8")
).hexdigest()
_ROW_DIFF_FIELDS = ("end_to_end_valid", "provider_outcome_valid", "failure_codes")
# The evaluator delta the committed rescored artifact must show against r4.
# Every verifier change (``PROVIDER_VERIFIER_VERSION`` bump) records its
# expected row changes here, so a tampered r4 row cannot be laundered through
# ``make hosted-rescore`` without the delta moving.
_EXPECTED_ROWS_CHANGED_VS_R4: dict[str, tuple[str, ...]] = {
    "scripted_oracle_ceiling_r2": (),
    "untuned_fast_reference_strategy_r2": (),
    "untuned_fast_slow_off_r2": (),
    "untuned_fast_frontier_slow_medium": (),
    "untuned_fast_frontier_slow_high": (),
    "frontier_reference_medium": (),
    "frontier_reference_high": (),
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RescoredReportV2(StrictModel):
    """The current evaluator's reading of the r4 raw outputs plus diagnostics.

    ``EvaluationReportV2`` cannot carry the diagnostics itself: the frozen
    ``report_fingerprint_v2`` dumps every field, so a new field would move the
    committed r2/r3/r4 fingerprints.  This sibling wraps the rescored report.
    """

    schema_version: Literal["phase-03a1-r4-rescored-v1"]
    rescored: EvaluationReportV2
    rows_changed_vs_r4: dict[str, tuple[str, ...]]
    report_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_rescore(self) -> Self:
        if self.rescored.schema_version != self.schema_version:
            raise ValueError("rescored report schema version mismatch")
        if set(self.rows_changed_vs_r4) != {
            item.condition.value for item in self.rescored.conditions
        }:
            raise ValueError("rows_changed_vs_r4 must cover exactly every condition")
        return self


def rescored_report_fingerprint(report: RescoredReportV2) -> str:
    payload = report.model_dump(mode="json", exclude={"report_fingerprint"})
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def check_r4_integrity(root: Path) -> tuple[bool, tuple[str, ...]]:
    """Every integrity property of the r4 gate except the fresh-fixture replay.

    r2/r3 validity itself is ``errata-check``'s job; this binds r4 to them.
    """

    if not (root / R4_REPORT_PATH).is_file():
        return False, (f"missing r4 artifact: {R4_REPORT_PATH}",)
    try:
        source_r2, source_r3 = load_source_reports(root)
        report = load_report_r4(root)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        return False, (f"invalid r4 report: {error}",)

    errors: list[str] = []
    if report.report_fingerprint != report_fingerprint_r4(report):
        errors.append("r4 report fingerprint drift")
    if report.source_r2_report_fingerprint != source_r2.report_fingerprint:
        errors.append("r4 source r2 fingerprint mismatch")
    if report.source_r2_generated_at != source_r2.generated_at:
        errors.append("r4 source r2 timestamp mismatch")
    if report.source_r3_report_fingerprint != source_r3.report_fingerprint:
        errors.append("r4 source r3 fingerprint mismatch")
    if report.source_r3_generated_at != source_r3.generated_at:
        errors.append("r4 source r3 timestamp mismatch")
    if report.matrix_result.report_fingerprint != report_fingerprint_v2(
        report.matrix_result
    ):
        errors.append("r4 nested matrix fingerprint drift")
    if tuple(
        item.model_dump(mode="json") for item in report.matrix_result.conditions[:3]
    ) != tuple(item.model_dump(mode="json") for item in source_r3.conditions[:3]):
        errors.append("r4 deterministic conditions differ from immutable r3")
    for field in (
        "catalog_fingerprint",
        "manifest_fingerprint",
        "episode_fingerprint",
        "ceiling_fingerprint",
    ):
        if getattr(report.matrix_result, field) != getattr(source_r3, field):
            errors.append(f"r4 matrix {field} mismatch")
    errors.extend(_provider_error_reconciliation_errors(report))
    if report.execution_contract_fingerprint != _R4_PINNED_FINGERPRINT:
        errors.append("r4 execution contract pins are stale")
    for probe in report.probe_evidence:
        bundle = build_probe_prompt(probe.label)
        if probe.call.prompt_fingerprint != bundle.prompt_fingerprint:
            errors.append(f"r4 {probe.reasoning_effort} probe prompt drift")
        if probe.call.schema_fingerprint != bundle.schema_fingerprint:
            errors.append(f"r4 {probe.reasoning_effort} probe schema drift")
        if probe.call.estimated_cost_microusd != R4_PROBE_PER_CALL_MAX_MICROUSD:
            errors.append(f"r4 {probe.reasoning_effort} probe maximum drift")
    return not errors, tuple(dict.fromkeys(errors))


def execution_contract_state(root: Path) -> dict[str, object]:
    """Report whether the r4 execution bytes under ``root`` still match r4."""

    r4_fingerprint = load_report_r4(root).execution_contract_fingerprint
    current_hashes: dict[str, str | None] = {}
    for relative in _R4_EXECUTION_PATHS:
        path = root / relative
        current_hashes[relative] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
    current_fingerprint = hashlib.sha256(
        canonical_json(current_hashes).encode("utf-8")
    ).hexdigest()
    drifted_paths = tuple(
        relative
        for relative in _R4_EXECUTION_PATHS
        if current_hashes[relative] != _R4_FILE_HASHES[relative]
    )
    return {
        "r4_fingerprint": r4_fingerprint,
        "current_fingerprint": current_fingerprint,
        "state": (
            "unchanged" if current_fingerprint == r4_fingerprint else "drifted_since_r4"
        ),
        "drifted_paths": drifted_paths,
        "pins_stale": r4_fingerprint != _R4_PINNED_FINGERPRINT,
    }


def derive_rescored_r4(
    r4: HostedRerunReport,
    *,
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
) -> RescoredReportV2:
    """Re-read every r4 condition's raw outputs with the current evaluator.

    No provider or local model is called.  Captured evidence is preserved per
    row (the ``derive_r3_report_from_r2`` pattern); only the evaluator's
    reading may differ, and the difference is recorded per condition.
    """

    rescored: list[EvaluationSummaryV2] = []
    rows_changed: dict[str, tuple[str, ...]] = {}
    replay_count = 0
    for condition in r4.matrix_result.conditions:
        if condition.run_status not in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
            rescored.append(condition)
            rows_changed[condition.condition.value] = ()
            continue
        replayed = _replay_condition(condition, fixtures=fixtures)
        source_rows = {row.episode_id: row for row in condition.episodes}
        rebound_rows = tuple(
            _preserve_source_evidence(row, source_rows[row.episode_id])
            for row in replayed.episodes
        )
        rescored.append(
            replayed.model_copy(
                update={
                    "expected_episode_count": condition.expected_episode_count,
                    "model_call_count": condition.model_call_count,
                    "model_provenance": condition.model_provenance,
                    "prompt_provenance": condition.prompt_provenance,
                    "hosted_max_cost_microusd": condition.hosted_max_cost_microusd,
                    "latency_p50_ms": condition.latency_p50_ms,
                    "latency_p90_ms": condition.latency_p90_ms,
                    "episodes": rebound_rows,
                }
            )
        )
        rows_changed[condition.condition.value] = tuple(
            row.episode_id
            for row in rebound_rows
            if any(
                getattr(row, field) != getattr(source_rows[row.episode_id], field)
                for field in _ROW_DIFF_FIELDS
            )
        )
        replay_count += 1
    source_hosted_calls = sum(
        len(row.hosted_calls)
        for condition in r4.matrix_result.conditions
        for row in condition.episodes
    )
    report = compose_report_v2(
        tuple(rescored),
        host_class=r4.matrix_result.host_class,
        # A pure function of r4 plus the evaluator code carries no wall clock.
        generated_at=datetime.strptime(r4.generated_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        ),
        schema_version=R4_RESCORED_SCHEMA_VERSION,
        source_report_fingerprint=r4.report_fingerprint,
        source_generated_at=r4.generated_at,
        evaluator_version=RESCORE_EVALUATOR_VERSION,
        evaluation_correction_note=(
            "Offline rescore of the immutable r4 raw outputs and call evidence "
            "with the current evaluator; the r4 report keeps the r4-era numbers."
        ),
        source_hosted_call_count=source_hosted_calls,
        new_external_dispatch_count=0,
        offline_replay_condition_count=replay_count,
        source_qwen_output_token_cap=R2_QWEN_OUTPUT_TOKEN_CAP,
    )
    draft = RescoredReportV2(
        schema_version=R4_RESCORED_SCHEMA_VERSION,
        rescored=report,
        rows_changed_vs_r4=rows_changed,
        report_fingerprint="0" * 64,
    )
    return draft.model_copy(
        update={"report_fingerprint": rescored_report_fingerprint(draft)}
    )


def render_rescored_report(report: RescoredReportV2) -> str:
    return (
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )


def write_rescored_report(root: Path, report: RescoredReportV2) -> RescoredReportV2:
    bound = report.model_copy(
        update={"report_fingerprint": rescored_report_fingerprint(report)}
    )
    path = root / R4_RESCORED_REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_rescored_report(bound), encoding="utf-8")
    return bound


def load_rescored_report(root: Path) -> RescoredReportV2:
    return RescoredReportV2.model_validate_json(
        (root / R4_RESCORED_REPORT_PATH).read_text(encoding="utf-8")
    )


def check_rescored_artifact(root: Path) -> tuple[bool, tuple[str, ...]]:
    """The committed rescored artifact is exactly the current derivation."""

    path = root / R4_RESCORED_REPORT_PATH
    if not path.is_file():
        return False, (f"missing rescored artifact: {R4_RESCORED_REPORT_PATH}",)
    try:
        r4 = load_report_r4(root)
        committed = load_rescored_report(root)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        return False, (f"invalid rescored report: {error}",)

    errors: list[str] = []
    if committed.report_fingerprint != rescored_report_fingerprint(committed):
        errors.append("rescored report fingerprint drift")
    if committed.rescored.source_report_fingerprint != r4.report_fingerprint:
        errors.append("rescored source r4 fingerprint mismatch")
    if committed.rows_changed_vs_r4 != _EXPECTED_ROWS_CHANGED_VS_R4:
        errors.append("rows_changed_vs_r4 differs from the recorded evaluator delta")
    derived = derive_rescored_r4(r4, fixtures=_fresh_fixtures())
    if path.read_text(encoding="utf-8") != render_rescored_report(derived):
        errors.append("rescored artifact differs from the in-memory derivation")
    return not errors, tuple(errors)


__all__ = [
    "R4_RESCORED_REPORT_PATH",
    "R4_RESCORED_SCHEMA_VERSION",
    "RESCORE_EVALUATOR_VERSION",
    "RescoredReportV2",
    "check_r4_integrity",
    "check_rescored_artifact",
    "derive_rescored_r4",
    "execution_contract_state",
    "load_rescored_report",
    "render_rescored_report",
    "rescored_report_fingerprint",
    "write_rescored_report",
]
