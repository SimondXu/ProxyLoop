"""Offline semantic replay for Phase 03A1-E model evidence."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel

from .artifacts_v2 import (
    R2_FAST_SLOW_CALL_CAP,
    R2_FAST_SLOW_MAX_MICROUSD,
    R2_FRONTIER_INPUT_TOKEN_CAP,
    R2_FRONTIER_OUTPUT_TOKEN_CAP,
    R2_QWEN_OUTPUT_TOKEN_CAP,
    R2_REFERENCE_CALL_CAP,
    R2_REFERENCE_MAX_MICROUSD,
)
from .fresh_fixtures import FreshPhase03A1ModelFixture
from .models import (
    EvaluationConditionV2,
    EvaluationReportV2,
    EvaluationSummaryV2,
    HostedCallEvidence,
    RunStatus,
)
from .openai_frontier import OpenAIFrontierAdapter
from .qwen_mlx import QwenGenerationText, QwenMLXAdapter
from .runner_v2 import (
    compose_report_v2,
    run_frontier_condition_v2,
    run_qwen_reference_strategy_v2,
    run_slow_off_v2,
    scripted_ceiling_condition_v2,
)


@dataclass(frozen=True, slots=True)
class _HostedReplayItem:
    call: HostedCallEvidence
    raw_output: str | None


@dataclass(slots=True)
class _ReplayCompletions:
    items: deque[_HostedReplayItem]
    calls: list[dict[str, object]] = field(default_factory=list)

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if not self.items:
            raise AssertionError("offline replay exhausted hosted call evidence")
        item = self.items.popleft()
        if item.call.status == "failed_provider_call":
            raise TimeoutError("offline-replayed-provider-failure")
        output_model = kwargs.get("response_format")
        parsed: object = item.raw_output
        if isinstance(output_model, type) and issubclass(output_model, BaseModel):
            try:
                parsed = output_model.model_validate_json(item.raw_output or "")
            except ValueError:
                parsed = item.raw_output
        usage: object = None
        if item.call.actual_cost_microusd is not None:
            usage = SimpleNamespace(
                prompt_tokens=item.call.input_tokens,
                completion_tokens=item.call.output_tokens,
                completion_tokens_details=SimpleNamespace(
                    reasoning_tokens=item.call.reasoning_tokens
                ),
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        parsed=parsed,
                        content=item.raw_output,
                    )
                )
            ],
            model=item.call.response_model,
            id=item.call.response_id,
            usage=usage,
        )


@dataclass(slots=True)
class _QwenReplayGenerator:
    items: deque[QwenGenerationText]

    def __call__(self, _: str) -> QwenGenerationText:
        if not self.items:
            raise AssertionError("offline replay exhausted Qwen output evidence")
        return self.items.popleft()


def replay_condition_v2(
    recorded: EvaluationSummaryV2,
    *,
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
) -> tuple[str, ...]:
    """Re-run one condition from frozen fixtures and captured raw outputs."""

    if recorded.run_status not in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
        return ()
    try:
        replayed = _replay_condition(recorded, fixtures=fixtures)
    except (AssertionError, TypeError, ValueError) as error:
        return (f"semantic replay failed: {type(error).__name__}: {error}",)
    if _semantic_projection(recorded) != _semantic_projection(replayed):
        return ("semantic replay mismatch",)
    return ()


def replay_report_v2(
    report: EvaluationReportV2,
    *,
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
) -> tuple[str, ...]:
    errors: list[str] = []
    for condition in report.conditions:
        for error in replay_condition_v2(condition, fixtures=fixtures):
            errors.append(f"{condition.condition.value}: {error}")
    return tuple(errors)


def derive_r3_report_from_r2(
    source: EvaluationReportV2,
    *,
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
) -> EvaluationReportV2:
    """Create a versioned offline re-attribution report from frozen r2 evidence.

    No provider or local model is called. Successful/failed conditions are run
    through the same deterministic runners using only captured raw outputs and
    call evidence; not-run conditions remain exactly as recorded by r2.
    """

    if source.schema_version != "phase-03a1-r2-report-v1":
        raise ValueError("r3 derivation requires the frozen r2 source report")
    corrected: list[EvaluationSummaryV2] = []
    replay_count = 0
    for condition in source.conditions:
        if condition.run_status in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
            replayed = _replay_condition(condition, fixtures=fixtures)
            source_rows = {row.episode_id: row for row in condition.episodes}
            rebound_rows = tuple(
                _preserve_source_evidence(row, source_rows[row.episode_id])
                for row in replayed.episodes
            )
            replayed = replayed.model_copy(
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
            corrected.append(replayed)
            replay_count += 1
        else:
            corrected.append(condition)
    source_hosted_calls = sum(
        len(row.hosted_calls)
        for condition in source.conditions
        for row in condition.episodes
    )
    return compose_report_v2(
        tuple(corrected),
        host_class=source.host_class,
        schema_version="phase-03a1-r3-report-v1",
        source_report_fingerprint=source.report_fingerprint,
        source_generated_at=source.generated_at,
        evaluator_version="phase-03a1-e-r3-offline-attribution-v1",
        evaluation_correction_note=(
            "Offline re-attribution from immutable r2 raw outputs and call evidence; "
            "fixes terminal-provider route attribution and report readiness binding."
        ),
        source_hosted_call_count=source_hosted_calls,
        new_external_dispatch_count=0,
        offline_replay_condition_count=replay_count,
        source_qwen_output_token_cap=R2_QWEN_OUTPUT_TOKEN_CAP,
    )


def _preserve_source_evidence(
    replayed: Any,
    source: Any,
) -> Any:
    """Keep captured evidence byte-equivalent while accepting derived attribution."""

    evidence_fields = (
        "slow_raw_output",
        "fast_raw_output",
        "raw_output_excerpt",
        "validation_error",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "actual_cost_microusd",
        "hosted_calls",
        "input_fingerprint",
        "output_fingerprint",
    )
    return replayed.model_copy(
        update={field: getattr(source, field) for field in evidence_fields}
    )


def _replay_condition(
    recorded: EvaluationSummaryV2,
    *,
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
) -> EvaluationSummaryV2:
    condition = recorded.condition
    selected = _selected_fixtures(recorded, fixtures)
    if condition is EvaluationConditionV2.SCRIPTED_ORACLE_CEILING:
        return scripted_ceiling_condition_v2(selected)
    if condition is EvaluationConditionV2.UNTUNED_FAST_SLOW_OFF:
        return run_slow_off_v2(selected)
    if condition is EvaluationConditionV2.UNTUNED_FAST_REFERENCE_STRATEGY:
        qwen = QwenMLXAdapter(generator=_qwen_generator(recorded, hosted=False))
        return run_qwen_reference_strategy_v2(qwen, selected)

    hosted_items = _hosted_items(recorded)
    completions = _ReplayCompletions(deque(hosted_items))
    effort = (
        "high"
        if condition
        in {
            EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_HIGH,
            EvaluationConditionV2.FRONTIER_REFERENCE_HIGH,
        }
        else "medium"
    )
    reference = condition in {
        EvaluationConditionV2.FRONTIER_REFERENCE_MEDIUM,
        EvaluationConditionV2.FRONTIER_REFERENCE_HIGH,
    }
    adapter = OpenAIFrontierAdapter(
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        reasoning_effort=effort,
        input_token_cap=R2_FRONTIER_INPUT_TOKEN_CAP,
        max_output_tokens=R2_FRONTIER_OUTPUT_TOKEN_CAP,
        call_cap=R2_REFERENCE_CALL_CAP if reference else R2_FAST_SLOW_CALL_CAP,
        usd_ceiling=(
            R2_REFERENCE_MAX_MICROUSD if reference else R2_FAST_SLOW_MAX_MICROUSD
        )
        / 1_000_000,
    )
    frontier_qwen = (
        None
        if reference
        else QwenMLXAdapter(generator=_qwen_generator(recorded, hosted=True))
    )
    replayed = run_frontier_condition_v2(
        adapter,
        condition=condition,
        fixtures=selected,
        qwen=frontier_qwen,
    )
    if completions.items:
        raise AssertionError("offline replay left unused hosted call evidence")
    return replayed


def _selected_fixtures(
    recorded: EvaluationSummaryV2,
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
) -> tuple[FreshPhase03A1ModelFixture, ...]:
    by_id = {fixture.episode_id: fixture for fixture in fixtures}
    selected: list[FreshPhase03A1ModelFixture] = []
    for row in recorded.episodes:
        try:
            selected.append(by_id[row.episode_id])
        except KeyError as error:
            raise ValueError(f"unknown replay episode {row.episode_id}") from error
    return tuple(selected)


def _hosted_items(
    recorded: EvaluationSummaryV2,
) -> tuple[_HostedReplayItem, ...]:
    reference = recorded.condition in {
        EvaluationConditionV2.FRONTIER_REFERENCE_MEDIUM,
        EvaluationConditionV2.FRONTIER_REFERENCE_HIGH,
    }
    items: list[_HostedReplayItem] = []
    for row in recorded.episodes:
        calls = list(row.hosted_calls)
        if not calls:
            raise ValueError(f"{row.episode_id} has no hosted Slow call evidence")
        items.append(_HostedReplayItem(calls.pop(0), row.slow_raw_output))
        if reference and row.fast_json_valid is not None:
            if not calls:
                raise ValueError(f"{row.episode_id} has no hosted Fast call evidence")
            items.append(_HostedReplayItem(calls.pop(0), row.fast_raw_output))
        if calls:
            raise ValueError(f"{row.episode_id} has unexpected hosted call evidence")
    return tuple(items)


def _qwen_generator(
    recorded: EvaluationSummaryV2,
    *,
    hosted: bool,
) -> _QwenReplayGenerator:
    items: list[QwenGenerationText] = []
    for row in recorded.episodes:
        if hosted and row.fast_json_valid is None:
            continue
        if row.fast_raw_output is None:
            raise ValueError(f"{row.episode_id} has no captured Qwen raw output")
        hosted_input = sum(call.input_tokens or 0 for call in row.hosted_calls)
        hosted_output = sum(call.output_tokens or 0 for call in row.hosted_calls)
        input_tokens = (
            (row.input_tokens or 0) - hosted_input if hosted else row.input_tokens
        )
        output_tokens = (
            (row.output_tokens or 0) - hosted_output if hosted else row.output_tokens
        )
        items.append(
            QwenGenerationText(
                text=row.fast_raw_output,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        )
    return _QwenReplayGenerator(deque(items))


def _semantic_projection(summary: EvaluationSummaryV2) -> dict[str, Any]:
    payload = summary.model_dump(mode="json")
    payload.pop("expected_episode_count", None)
    payload.pop("latency_p50_ms", None)
    payload.pop("latency_p90_ms", None)
    payload.pop("hosted_max_cost_microusd", None)
    for row in payload["episodes"]:
        row.pop("latency_ms", None)
        row.pop("validation_error", None)
        for call in row["hosted_calls"]:
            call.pop("latency_ms", None)
            call.pop("estimated_cost_microusd", None)
    return payload


__all__ = [
    "derive_r3_report_from_r2",
    "replay_condition_v2",
    "replay_report_v2",
]
