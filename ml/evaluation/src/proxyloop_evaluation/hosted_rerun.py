"""Source-bound Phase 03A1-R Provider probe and hosted r4 evidence.

The module owns the complete rerun interface: probe orchestration, immutable
source binding, r4 serialization, and offline replay. Callers never write r2 or
r3 and cannot bypass the probe-ready gate through this interface.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .artifacts_v2 import (
    R2_FAST_SLOW_MAX_MICROUSD,
    R2_REFERENCE_MAX_MICROUSD,
    R2_REPORT_PATH,
    R3_REPORT_PATH,
    canonical_json,
    check_r2_artifacts,
    report_fingerprint_v2,
)
from .fresh_fixtures import FreshPhase03A1ModelFixture
from .models import (
    EvaluationConditionV2,
    EvaluationReportV2,
    HostedCallEvidence,
    RunStatus,
)
from .openai_frontier import (
    FrontierAdapterError,
    FrontierCallRecord,
    FrontierCallStatus,
    FrontierErrorEvidence,
    OpenAIFrontierAdapter,
    build_probe_prompt,
)
from .replay_v2 import replay_report_v2
from .runner_v2 import (
    compose_report_v2,
    hosted_report_v2,
    not_run_condition_v2,
)

R4_REPORT_PATH = Path("data/evaluation/phase-03a1-r4-hosted-rerun-report.json")
R4_SCHEMA_VERSION = "phase-03a1-r4-hosted-rerun-v1"
R4_PROBE_INPUT_TOKEN_CAP = 256
R4_PROBE_OUTPUT_TOKEN_CAP = 512
R4_PROBE_PER_CALL_MAX_MICROUSD = 11_264
R4_PROBE_BUDGET_CEILING_MICROUSD = 22_528
R4_MATRIX_BUDGET_CEILING_MICROUSD = 22_020_096
R4_TOTAL_BUDGET_CEILING_MICROUSD = 22_042_624
R4_PROBE_LABEL_BY_EFFORT = {
    "medium": "phase-03a1-r4-medium-probe",
    "high": "phase-03a1-r4-high-probe",
}
ProbeEffort = Literal["medium", "high"]
_R4_EXECUTION_PATHS = (
    "ml/pyproject.toml",
    "ml/uv.lock",
    "ml/evaluation/src/proxyloop_evaluation/artifacts_v2.py",
    "ml/evaluation/src/proxyloop_evaluation/fast_output.py",
    "ml/evaluation/src/proxyloop_evaluation/fresh_fixtures.py",
    "ml/evaluation/src/proxyloop_evaluation/hosted_rerun.py",
    "ml/evaluation/src/proxyloop_evaluation/openai_frontier.py",
    "ml/evaluation/src/proxyloop_evaluation/qwen_mlx.py",
    "ml/evaluation/src/proxyloop_evaluation/replay_v2.py",
    "ml/evaluation/src/proxyloop_evaluation/runner_v2.py",
    "ml/evaluation/src/proxyloop_evaluation/slow_output.py",
    "scripts/run_phase_03a1_hosted_rerun.py",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ProviderErrorEvidence(StrictModel):
    scope: str
    call_index: int | None = Field(default=None, ge=1)
    error_class: str
    status_code: int | None = None
    request_id: str | None = Field(default=None, max_length=512)
    provider_code: str | None = Field(default=None, max_length=512)
    provider_type: str | None = Field(default=None, max_length=512)
    provider_param: str | None = Field(default=None, max_length=512)


class ProviderProbeEvidence(StrictModel):
    reasoning_effort: Literal["medium", "high"]
    label: str
    dispatched: bool
    output_ok: bool
    output_label: str | None = None
    not_run_reason: str | None = None
    call: HostedCallEvidence
    error: ProviderErrorEvidence | None = None

    @model_validator(mode="after")
    def validate_probe(self) -> Self:
        expected_label = R4_PROBE_LABEL_BY_EFFORT[self.reasoning_effort]
        if self.label != expected_label:
            raise ValueError("probe label does not match frozen effort label")
        if self.call.requested_reasoning_effort != self.reasoning_effort:
            raise ValueError("probe call reasoning effort mismatch")
        if self.output_ok:
            if not self.dispatched or self.call.status != FrontierCallStatus.SUCCEEDED:
                raise ValueError(
                    "successful probe must be a dispatched successful call"
                )
            if self.output_label != self.label:
                raise ValueError("successful probe must echo the frozen label")
            if not self.call.response_id or not self.call.response_model:
                raise ValueError("successful probe requires response identity metadata")
            if not self.call.input_tokens or not self.call.output_tokens:
                raise ValueError("successful probe requires positive token usage")
            if self.call.actual_cost_microusd is None:
                raise ValueError("successful probe requires complete cost accounting")
            if self.error is not None or self.not_run_reason is not None:
                raise ValueError("successful probe cannot carry failure evidence")
        elif not self.error and not self.not_run_reason:
            raise ValueError("failed or skipped probe requires a blocker")
        if not self.dispatched and self.call.actual_cost_microusd is not None:
            raise ValueError("undispatched probe cannot record actual cost")
        return self


class HostedRerunReport(StrictModel):
    schema_version: Literal["phase-03a1-r4-hosted-rerun-v1"]
    generated_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    source_r2_report_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_r2_generated_at: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
    )
    source_r3_report_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_r3_generated_at: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
    )
    execution_contract_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_evidence: tuple[ProviderProbeEvidence, ProviderProbeEvidence]
    probe_ready: bool
    matrix_result: EvaluationReportV2
    provider_errors: tuple[ProviderErrorEvidence, ...]
    probe_budget_ceiling_microusd: int = Field(ge=0)
    matrix_budget_ceiling_microusd: int = Field(ge=0)
    total_budget_ceiling_microusd: int = Field(ge=0)
    probe_external_dispatch_count: int = Field(ge=0)
    matrix_external_dispatch_count: int = Field(ge=0)
    new_external_dispatch_count: int = Field(ge=0)
    actual_cost_microusd: int = Field(ge=0)
    cost_accounting_complete: bool
    cost_accounting_note: str
    provider_identity_note: str
    phase_completion_ready: bool
    phase_completion_blockers: tuple[str, ...]
    report_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_rerun(self) -> Self:
        if tuple(item.reasoning_effort for item in self.probe_evidence) != (
            "medium",
            "high",
        ):
            raise ValueError("probe evidence must be ordered medium then high")
        expected_probe_ready = all(item.output_ok for item in self.probe_evidence)
        if self.probe_ready is not expected_probe_ready:
            raise ValueError("probe readiness is inconsistent")
        expected_probe_dispatches = sum(item.dispatched for item in self.probe_evidence)
        if self.probe_external_dispatch_count != expected_probe_dispatches:
            raise ValueError("probe dispatch count is inconsistent")
        matrix_dispatches = sum(
            len(row.hosted_calls)
            for condition in self.matrix_result.conditions[3:]
            for row in condition.episodes
        )
        if self.matrix_external_dispatch_count != matrix_dispatches:
            raise ValueError("matrix dispatch count is inconsistent")
        if self.new_external_dispatch_count != (
            expected_probe_dispatches + matrix_dispatches
        ):
            raise ValueError("total external dispatch count is inconsistent")
        probe_cost = sum(
            item.call.actual_cost_microusd or 0 for item in self.probe_evidence
        )
        matrix_cost = sum(
            condition.actual_cost_microusd
            for condition in self.matrix_result.conditions[3:]
        )
        if self.actual_cost_microusd != probe_cost + matrix_cost:
            raise ValueError("r4 actual cost is inconsistent")
        expected_accounting = all(
            (not item.dispatched) or item.call.actual_cost_microusd is not None
            for item in self.probe_evidence
        ) and all(
            condition.cost_accounting_complete
            for condition in self.matrix_result.conditions[3:]
        )
        if self.cost_accounting_complete is not expected_accounting:
            raise ValueError("r4 cost accounting completeness is inconsistent")
        if self.probe_budget_ceiling_microusd != R4_PROBE_BUDGET_CEILING_MICROUSD:
            raise ValueError("r4 probe budget ceiling drift")
        if self.matrix_budget_ceiling_microusd != R4_MATRIX_BUDGET_CEILING_MICROUSD:
            raise ValueError("r4 matrix budget ceiling drift")
        if self.total_budget_ceiling_microusd != R4_TOTAL_BUDGET_CEILING_MICROUSD:
            raise ValueError("r4 total budget ceiling drift")
        blockers = _phase_blockers(self.probe_evidence, self.matrix_result)
        ready = self.probe_ready and self.matrix_result.phase_completion_ready
        if self.phase_completion_ready is not ready:
            raise ValueError("r4 phase completion readiness is inconsistent")
        if self.phase_completion_blockers != blockers:
            raise ValueError("r4 phase completion blockers are inconsistent")
        return self


def report_fingerprint_r4(report: HostedRerunReport) -> str:
    payload = report.model_dump(mode="json", exclude={"report_fingerprint"})
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def execution_contract_fingerprint_r4() -> str:
    """Bind every local file that can change probe or matrix execution."""

    root = Path(__file__).resolve().parents[4]
    hashes = {
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in _R4_EXECUTION_PATHS
    }
    return hashlib.sha256(canonical_json(hashes).encode("utf-8")).hexdigest()


def run_provider_probes(
    adapters: tuple[OpenAIFrontierAdapter, OpenAIFrontierAdapter],
) -> tuple[ProviderProbeEvidence, ProviderProbeEvidence]:
    evidence: list[ProviderProbeEvidence] = []
    abort_reason: str | None = None
    efforts: tuple[ProbeEffort, ProbeEffort] = ("medium", "high")
    for effort, adapter in zip(efforts, adapters, strict=True):
        label = R4_PROBE_LABEL_BY_EFFORT[effort]
        if abort_reason is not None:
            evidence.append(_skipped_probe(adapter, effort, label, abort_reason))
            continue
        output = None
        caught: FrontierAdapterError | None = None
        try:
            output = adapter.probe(label=label)
        except FrontierAdapterError as error:
            caught = error
        item = _probe_evidence(adapter, effort, label, output, caught)
        evidence.append(item)
        if not item.output_ok:
            abort_reason = (
                "not attempted after the preceding probe failed its audit gate"
            )
    if len(evidence) != 2:
        raise AssertionError("r4 probe runner must produce exactly two evidence rows")
    return evidence[0], evidence[1]


def initial_matrix_from_source(
    source_r3: EvaluationReportV2,
    *,
    host_class: str,
) -> EvaluationReportV2:
    local = source_r3.conditions[:3]
    if any(item.run_status is not RunStatus.SUCCEEDED for item in local):
        raise ValueError("r4 requires three successful deterministic r3 conditions")
    hosted = tuple(
        not_run_condition_v2(
            condition,
            "r4 hosted condition blocked until the Provider probe passes",
            hosted_max_cost_microusd=_matrix_maximum(condition),
        )
        for condition in tuple(EvaluationConditionV2)[3:]
    )
    return compose_report_v2((*local, *hosted), host_class=host_class)


def compose_r4_report(
    *,
    source_r2: EvaluationReportV2,
    source_r3: EvaluationReportV2,
    probes: tuple[ProviderProbeEvidence, ProviderProbeEvidence],
    matrix_result: EvaluationReportV2,
    provider_errors: tuple[ProviderErrorEvidence, ...] = (),
    generated_at: datetime | None = None,
) -> HostedRerunReport:
    probe_dispatches = sum(item.dispatched for item in probes)
    matrix_dispatches = sum(
        len(row.hosted_calls)
        for condition in matrix_result.conditions[3:]
        for row in condition.episodes
    )
    actual_cost = sum(item.call.actual_cost_microusd or 0 for item in probes) + sum(
        item.actual_cost_microusd for item in matrix_result.conditions[3:]
    )
    cost_complete = all(
        (not item.dispatched) or item.call.actual_cost_microusd is not None
        for item in probes
    ) and all(item.cost_accounting_complete for item in matrix_result.conditions[3:])
    timestamp = (generated_at or datetime.now(UTC)).replace(microsecond=0)
    blockers = _phase_blockers(probes, matrix_result)
    draft = HostedRerunReport(
        schema_version="phase-03a1-r4-hosted-rerun-v1",
        generated_at=timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_r2_report_fingerprint=source_r2.report_fingerprint,
        source_r2_generated_at=source_r2.generated_at,
        source_r3_report_fingerprint=source_r3.report_fingerprint,
        source_r3_generated_at=source_r3.generated_at,
        execution_contract_fingerprint=execution_contract_fingerprint_r4(),
        probe_evidence=probes,
        probe_ready=all(item.output_ok for item in probes),
        matrix_result=matrix_result,
        provider_errors=provider_errors,
        probe_budget_ceiling_microusd=R4_PROBE_BUDGET_CEILING_MICROUSD,
        matrix_budget_ceiling_microusd=R4_MATRIX_BUDGET_CEILING_MICROUSD,
        total_budget_ceiling_microusd=R4_TOTAL_BUDGET_CEILING_MICROUSD,
        probe_external_dispatch_count=probe_dispatches,
        matrix_external_dispatch_count=matrix_dispatches,
        new_external_dispatch_count=probe_dispatches + matrix_dispatches,
        actual_cost_microusd=actual_cost,
        cost_accounting_complete=cost_complete,
        cost_accounting_note=(
            "29qg exposes token usage but no billed-cost field; reported cost is "
            "a conservative usage-accounted estimate, not an invoice."
        ),
        provider_identity_note=(
            "The requested/returned Terra model identifiers are recorded, but the "
            "proxy's hidden physical backend is not independently verified."
        ),
        phase_completion_ready=(
            all(item.output_ok for item in probes)
            and matrix_result.phase_completion_ready
        ),
        phase_completion_blockers=blockers,
        report_fingerprint="0" * 64,
    )
    return draft.model_copy(update={"report_fingerprint": report_fingerprint_r4(draft)})


def run_hosted_matrix(
    source_r3: EvaluationReportV2,
    *,
    frontier_adapters: tuple[object, object, object, object],
    qwen: object,
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
    host_class: str,
) -> EvaluationReportV2:
    return hosted_report_v2(
        source_r3.conditions[:3],
        frontier_adapters=frontier_adapters,
        qwen=qwen,
        fixtures=fixtures,
        host_class=host_class,
    )


def provider_errors_from_adapters(
    scopes: tuple[str, ...], adapters: tuple[object, ...]
) -> tuple[ProviderErrorEvidence, ...]:
    errors: list[ProviderErrorEvidence] = []
    for scope, adapter in zip(scopes, adapters, strict=True):
        history = getattr(adapter, "error_history", None)
        if isinstance(history, tuple) and history:
            errors.extend(
                _error_evidence(scope, detail)
                for detail in history
                if isinstance(detail, FrontierErrorEvidence)
            )
            continue
        detail = getattr(adapter, "last_error", None)
        if isinstance(detail, FrontierErrorEvidence):
            errors.append(_error_evidence(scope, detail))
    return tuple(errors)


def write_report_r4(root: Path, report: HostedRerunReport) -> HostedRerunReport:
    bound = report.model_copy(
        update={"report_fingerprint": report_fingerprint_r4(report)}
    )
    path = root / R4_REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            bound.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return bound


def load_source_reports(root: Path) -> tuple[EvaluationReportV2, EvaluationReportV2]:
    source_r2 = EvaluationReportV2.model_validate_json(
        (root / R2_REPORT_PATH).read_text(encoding="utf-8")
    )
    source_r3 = EvaluationReportV2.model_validate_json(
        (root / R3_REPORT_PATH).read_text(encoding="utf-8")
    )
    return source_r2, source_r3


def load_report_r4(root: Path) -> HostedRerunReport:
    return HostedRerunReport.model_validate_json(
        (root / R4_REPORT_PATH).read_text(encoding="utf-8")
    )


def check_hosted_rerun_sources(root: Path) -> tuple[bool, tuple[str, ...]]:
    """Validate every deterministic pre-dispatch input without requiring r4."""

    passed, source_failures = check_r2_artifacts(root)
    if not passed:
        return False, source_failures
    try:
        source_r2, source_r3 = load_source_reports(root)
        execution_contract_fingerprint_r4()
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        return False, (f"invalid hosted-rerun source: {error}",)

    errors: list[str] = []
    if source_r2.schema_version != "phase-03a1-r2-report-v1":
        errors.append("hosted rerun requires the immutable r2 report")
    if source_r3.schema_version != "phase-03a1-r3-report-v1":
        errors.append("hosted rerun requires the authoritative r3 report")
    if any(
        condition.run_status is not RunStatus.SUCCEEDED
        for condition in source_r3.conditions[:3]
    ):
        errors.append("hosted rerun requires three successful r3 local conditions")
    if (
        len(R4_PROBE_LABEL_BY_EFFORT) * R4_PROBE_PER_CALL_MAX_MICROUSD
    ) != R4_PROBE_BUDGET_CEILING_MICROUSD:
        errors.append("hosted rerun probe budget arithmetic drift")
    if R4_TOTAL_BUDGET_CEILING_MICROUSD != (
        R4_PROBE_BUDGET_CEILING_MICROUSD + R4_MATRIX_BUDGET_CEILING_MICROUSD
    ):
        errors.append("hosted rerun total budget arithmetic drift")
    for effort in ("medium", "high"):
        label = R4_PROBE_LABEL_BY_EFFORT[effort]
        bundle = build_probe_prompt(label)
        if not bundle.prompt_fingerprint or not bundle.schema_fingerprint:
            errors.append(f"hosted rerun {effort} probe fingerprint is missing")
    return not errors, tuple(dict.fromkeys(errors))


def check_hosted_rerun_artifacts(root: Path) -> tuple[bool, tuple[str, ...]]:
    passed, source_failures = check_hosted_rerun_sources(root)
    if not passed:
        return False, source_failures
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
    if report.execution_contract_fingerprint != execution_contract_fingerprint_r4():
        errors.append("r4 execution contract drift after Provider probe")
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
    errors.extend(
        replay_report_v2(
            report.matrix_result,
            fixtures=_fresh_fixtures(),
        )
    )
    errors.extend(_provider_error_reconciliation_errors(report))
    for probe in report.probe_evidence:
        bundle = build_probe_prompt(probe.label)
        if probe.call.prompt_fingerprint != bundle.prompt_fingerprint:
            errors.append(f"r4 {probe.reasoning_effort} probe prompt drift")
        if probe.call.schema_fingerprint != bundle.schema_fingerprint:
            errors.append(f"r4 {probe.reasoning_effort} probe schema drift")
        if probe.call.estimated_cost_microusd != R4_PROBE_PER_CALL_MAX_MICROUSD:
            errors.append(f"r4 {probe.reasoning_effort} probe maximum drift")
    return not errors, tuple(dict.fromkeys(errors))


def _provider_error_reconciliation_errors(
    report: HostedRerunReport,
) -> tuple[str, ...]:
    """Bind each dispatched failure to one non-orphaned error-history row."""

    errors: list[str] = []
    expected_failed_calls: set[tuple[str, int]] = set()
    allowed_none_scopes: set[str] = set()
    known_scopes: set[str] = set()
    expected_probe_errors: list[ProviderErrorEvidence] = []

    for probe in report.probe_evidence:
        scope = f"provider_probe_{probe.reasoning_effort}"
        known_scopes.add(scope)
        if probe.dispatched and probe.call.status.startswith("failed_"):
            expected_failed_calls.add((scope, 1))
        if probe.error is not None:
            expected_probe_errors.append(probe.error)
            if probe.error.call_index is None:
                allowed_none_scopes.add(scope)

    for condition in report.matrix_result.conditions[3:]:
        scope = condition.condition.value
        known_scopes.add(scope)
        calls = tuple(
            call for episode in condition.episodes for call in episode.hosted_calls
        )
        for call_index, call in enumerate(calls, start=1):
            if call.status.startswith("failed_"):
                expected_failed_calls.add((scope, call_index))
        if not calls and condition.run_status is not RunStatus.SUCCEEDED:
            allowed_none_scopes.add(scope)

    actual_by_key: dict[tuple[str, int | None], list[ProviderErrorEvidence]] = {}
    for detail in report.provider_errors:
        key = (detail.scope, detail.call_index)
        actual_by_key.setdefault(key, []).append(detail)
        if detail.scope not in known_scopes:
            errors.append(f"orphan Provider error scope: {detail.scope}")
        if detail.call_index is None:
            if detail.scope not in allowed_none_scopes:
                errors.append(
                    f"orphan undispatched Provider error evidence: {detail.scope}"
                )
        elif (detail.scope, detail.call_index) not in expected_failed_calls:
            errors.append(
                "orphan dispatched Provider error evidence: "
                f"{detail.scope} call {detail.call_index}"
            )

    for key, rows in actual_by_key.items():
        if len(rows) > 1:
            errors.append(f"duplicate Provider error evidence: {key[0]} call {key[1]}")
    for scope, call_index in sorted(expected_failed_calls):
        if (scope, call_index) not in actual_by_key:
            errors.append(f"missing Provider error evidence: {scope} call {call_index}")
    actual_payloads = [item.model_dump(mode="json") for item in report.provider_errors]
    for expected in expected_probe_errors:
        if expected.model_dump(mode="json") not in actual_payloads:
            errors.append(
                f"probe error detail is absent from Provider history: {expected.scope}"
            )
    return tuple(errors)


def _fresh_fixtures() -> tuple[FreshPhase03A1ModelFixture, ...]:
    from .fresh_fixtures import build_fresh_phase03a1_bundle

    return build_fresh_phase03a1_bundle().fixtures


def _phase_blockers(
    probes: tuple[ProviderProbeEvidence, ProviderProbeEvidence],
    matrix_result: EvaluationReportV2,
) -> tuple[str, ...]:
    probe_blockers = tuple(
        f"provider_probe_{item.reasoning_effort}:{item.call.status}"
        for item in probes
        if not item.output_ok
    )
    return (*probe_blockers, *matrix_result.phase_completion_blockers)


def _probe_evidence(
    adapter: OpenAIFrontierAdapter,
    effort: ProbeEffort,
    label: str,
    output: object | None,
    error: FrontierAdapterError | None,
) -> ProviderProbeEvidence:
    record = adapter.last_call
    if record is None:
        raise AssertionError("probe adapter did not expose call evidence")
    output_label = getattr(output, "label", None)
    output_ok = (
        output is not None
        and getattr(output, "ok", False) is True
        and output_label == label
        and record.status is FrontierCallStatus.SUCCEEDED
    )
    detail = adapter.last_error
    return ProviderProbeEvidence(
        reasoning_effort=effort,
        label=label,
        dispatched=adapter.calls_started > 0,
        output_ok=output_ok,
        output_label=output_label if isinstance(output_label, str) else None,
        not_run_reason=None if output_ok or detail is not None else str(error),
        call=_call_evidence(record),
        error=_error_evidence(f"provider_probe_{effort}", detail) if detail else None,
    )


def _skipped_probe(
    adapter: OpenAIFrontierAdapter,
    effort: ProbeEffort,
    label: str,
    reason: str,
) -> ProviderProbeEvidence:
    bundle = build_probe_prompt(label)
    return ProviderProbeEvidence(
        reasoning_effort=effort,
        label=label,
        dispatched=False,
        output_ok=False,
        not_run_reason=reason,
        call=HostedCallEvidence(
            status="not_run_probe_rejected",
            requested_model=adapter.model,
            response_model=None,
            response_model_version=None,
            response_id=None,
            requested_reasoning_effort=effort,
            reasoning_tokens=None,
            prompt_fingerprint=bundle.prompt_fingerprint,
            schema_fingerprint=bundle.schema_fingerprint,
            input_tokens=None,
            output_tokens=None,
            latency_ms=None,
            estimated_cost_microusd=R4_PROBE_PER_CALL_MAX_MICROUSD,
            actual_cost_microusd=None,
        ),
    )


def _call_evidence(record: FrontierCallRecord) -> HostedCallEvidence:
    return HostedCallEvidence(
        status=record.status.value,
        requested_model=record.requested_model,
        response_model=record.response_model,
        response_model_version=record.response_model_version,
        response_id=record.response_id,
        requested_reasoning_effort=record.requested_reasoning_effort,
        reasoning_tokens=record.reasoning_tokens,
        prompt_fingerprint=record.prompt_fingerprint,
        schema_fingerprint=record.schema_fingerprint,
        input_tokens=record.input_tokens if record.input_tokens else None,
        output_tokens=record.output_tokens if record.output_tokens else None,
        latency_ms=record.latency_ms,
        estimated_cost_microusd=round(record.estimated_cost_usd * 1_000_000),
        actual_cost_microusd=(
            round(record.actual_cost_usd * 1_000_000)
            if record.actual_cost_usd is not None
            else None
        ),
    )


def _error_evidence(scope: str, detail: FrontierErrorEvidence) -> ProviderErrorEvidence:
    return ProviderErrorEvidence(
        scope=scope,
        call_index=detail.call_index,
        error_class=detail.error_class,
        status_code=detail.status_code,
        request_id=detail.request_id,
        provider_code=detail.provider_code,
        provider_type=detail.provider_type,
        provider_param=detail.provider_param,
    )


def _matrix_maximum(condition: EvaluationConditionV2) -> int:
    if condition in {
        EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_MEDIUM,
        EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_HIGH,
    }:
        return R2_FAST_SLOW_MAX_MICROUSD
    if condition in {
        EvaluationConditionV2.FRONTIER_REFERENCE_MEDIUM,
        EvaluationConditionV2.FRONTIER_REFERENCE_HIGH,
    }:
        return R2_REFERENCE_MAX_MICROUSD
    return 0


__all__ = [
    "R4_PROBE_BUDGET_CEILING_MICROUSD",
    "R4_PROBE_INPUT_TOKEN_CAP",
    "R4_PROBE_LABEL_BY_EFFORT",
    "R4_PROBE_OUTPUT_TOKEN_CAP",
    "R4_REPORT_PATH",
    "R4_TOTAL_BUDGET_CEILING_MICROUSD",
    "HostedRerunReport",
    "ProviderErrorEvidence",
    "ProviderProbeEvidence",
    "check_hosted_rerun_artifacts",
    "check_hosted_rerun_sources",
    "compose_r4_report",
    "execution_contract_fingerprint_r4",
    "initial_matrix_from_source",
    "load_report_r4",
    "load_source_reports",
    "provider_errors_from_adapters",
    "report_fingerprint_r4",
    "run_hosted_matrix",
    "run_provider_probes",
    "write_report_r4",
]
