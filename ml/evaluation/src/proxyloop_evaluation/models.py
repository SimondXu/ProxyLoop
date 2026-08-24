"""Strict result contracts for Phase 03A1 untuned baselines."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BaselineCondition(StrEnum):
    SCRIPTED_ORACLE_CEILING = "scripted_oracle_ceiling"
    UNTUNED_FAST_REFERENCE_STRATEGY = "untuned_fast_reference_strategy"
    UNTUNED_FAST_SLOW_OFF = "untuned_fast_slow_off"
    UNTUNED_FAST_FRONTIER_SLOW = "untuned_fast_frontier_slow"
    FRONTIER_REFERENCE = "frontier_reference"


class RunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NOT_RUN_MISSING_CREDENTIALS = "not_run_missing_credentials"
    NOT_RUN_MODEL_UNAVAILABLE = "not_run_model_unavailable"
    NOT_RUN_BUDGET_REJECTED = "not_run_budget_rejected"


class ModelProvenance(StrictModel):
    provider: str
    model_id: str
    model_revision: str | None = None
    source_model_id: str | None = None
    source_model_revision: str | None = None
    weight_format: str
    quantization: str | None = None
    untuned_label: str
    license: str | None = None
    runtime: str
    checkpoint_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    tokenizer_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    chat_template_fingerprint: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )


class PromptProvenance(StrictModel):
    prompt_version: str
    prompt_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_schema_version: str
    output_schema_version: str


class HostedCallEvidence(StrictModel):
    status: str
    requested_model: str
    response_model: str | None
    response_model_version: str | None
    response_id: str | None
    requested_reasoning_effort: str | None = None
    reasoning_tokens: int | None = Field(default=None, ge=0)
    prompt_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    estimated_cost_microusd: int = Field(ge=0)
    actual_cost_microusd: int | None = Field(default=None, ge=0)


class EpisodeBaselineResult(StrictModel):
    episode_id: str
    split: str
    provider_split: str
    safety: bool
    route_outcomes: tuple[str, ...]
    adapter_status: str
    schema_valid: bool
    pins_valid: bool
    fast_action_intent_null: bool
    route_agreement: bool
    policy_violation_count: int = Field(ge=0)
    leakage_violation_count: int = Field(ge=0)
    completed: bool
    valid_outcome: bool
    false_completion: bool
    failure_codes: tuple[str, ...]
    input_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    output_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    raw_output_excerpt: str | None = Field(default=None, max_length=16384)
    validation_error: str | None = Field(default=None, max_length=512)
    latency_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    actual_cost_microusd: int = Field(ge=0)
    hosted_calls: tuple[HostedCallEvidence, ...] = ()


class ConditionSummary(StrictModel):
    condition: BaselineCondition
    run_status: RunStatus
    not_run_reason: str | None = None
    expected_episode_count: int = Field(ge=0)
    evaluated_episode_count: int = Field(ge=0)
    model_call_count: int = Field(ge=0)
    schema_valid_count: int = Field(ge=0)
    valid_outcome_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    valid_noncompletion_count: int = Field(ge=0)
    false_completion_count: int = Field(ge=0)
    policy_violation_count: int = Field(ge=0)
    leakage_violation_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    actual_cost_microusd: int = Field(ge=0)
    hosted_max_cost_microusd: int = Field(ge=0)
    cost_accounting_complete: bool
    latency_p50_ms: int | None = Field(default=None, ge=0)
    latency_p90_ms: int | None = Field(default=None, ge=0)
    failure_slices: dict[str, int]
    model_provenance: tuple[ModelProvenance, ...]
    prompt_provenance: tuple[PromptProvenance, ...]
    episodes: tuple[EpisodeBaselineResult, ...]

    @model_validator(mode="after")
    def validate_status_and_totals(self) -> ConditionSummary:
        if self.run_status is RunStatus.SUCCEEDED:
            if self.not_run_reason is not None:
                raise ValueError("successful condition cannot have a not-run reason")
            if self.evaluated_episode_count != self.expected_episode_count:
                raise ValueError("successful condition must evaluate every episode")
        else:
            if not self.not_run_reason:
                raise ValueError("non-success condition requires a reason")
        if self.evaluated_episode_count != len(self.episodes):
            raise ValueError("evaluated count must equal episode record count")
        if self.schema_valid_count != sum(row.schema_valid for row in self.episodes):
            raise ValueError("schema-valid count does not match episode records")
        if self.valid_outcome_count != sum(row.valid_outcome for row in self.episodes):
            raise ValueError("valid-outcome count does not match episode records")
        if self.completed_count != sum(row.completed for row in self.episodes):
            raise ValueError("completed count does not match episode records")
        if self.valid_noncompletion_count != sum(
            row.valid_outcome and not row.completed for row in self.episodes
        ):
            raise ValueError("valid non-completion count does not match episodes")
        if self.false_completion_count != sum(
            row.false_completion for row in self.episodes
        ):
            raise ValueError("false-completion count does not match episode records")
        if self.policy_violation_count != sum(
            row.policy_violation_count for row in self.episodes
        ):
            raise ValueError("policy violation count does not match episode records")
        if self.leakage_violation_count != sum(
            row.leakage_violation_count for row in self.episodes
        ):
            raise ValueError("leakage count does not match episode records")
        if self.input_tokens != sum(row.input_tokens or 0 for row in self.episodes):
            raise ValueError("input token count does not match episode records")
        if self.output_tokens != sum(row.output_tokens or 0 for row in self.episodes):
            raise ValueError("output token count does not match episode records")
        if self.actual_cost_microusd != sum(
            row.actual_cost_microusd for row in self.episodes
        ):
            raise ValueError("actual cost does not match episode records")
        observed_hosted_cost = sum(
            call.actual_cost_microusd or 0
            for row in self.episodes
            for call in row.hosted_calls
        )
        if observed_hosted_cost != self.actual_cost_microusd:
            raise ValueError("hosted call cost does not match condition cost")
        evidence_complete = all(
            call.actual_cost_microusd is not None
            for row in self.episodes
            for call in row.hosted_calls
        )
        if self.cost_accounting_complete != evidence_complete:
            raise ValueError(
                "cost accounting completeness does not match call evidence"
            )
        return self


class BaselineReport(StrictModel):
    schema_version: str
    generated_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    manifest_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    episode_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    harness_ceiling_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    harness_ceiling_gate_passed: bool
    host_class: str
    conditions: tuple[ConditionSummary, ...]
    hosted_budget_ceiling_microusd: int = Field(ge=0)
    phase_completion_ready: bool
    phase_completion_blockers: tuple[str, ...]
    report_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_conditions(self) -> BaselineReport:
        observed = tuple(condition.condition for condition in self.conditions)
        expected = tuple(BaselineCondition)
        if observed != expected:
            raise ValueError("baseline conditions must be complete and ordered")
        actual_hosted_cost = sum(
            condition.actual_cost_microusd
            for condition in self.conditions
            if any(
                provenance.weight_format == "hosted"
                for provenance in condition.model_provenance
            )
        )
        if actual_hosted_cost > self.hosted_budget_ceiling_microusd:
            raise ValueError("actual hosted cost exceeds the approved ceiling")
        return self


class EvaluationConditionV2(StrEnum):
    SCRIPTED_ORACLE_CEILING = "scripted_oracle_ceiling_r2"
    UNTUNED_FAST_REFERENCE_STRATEGY = "untuned_fast_reference_strategy_r2"
    UNTUNED_FAST_SLOW_OFF = "untuned_fast_slow_off_r2"
    UNTUNED_FAST_FRONTIER_SLOW_MEDIUM = "untuned_fast_frontier_slow_medium"
    UNTUNED_FAST_FRONTIER_SLOW_HIGH = "untuned_fast_frontier_slow_high"
    FRONTIER_REFERENCE_MEDIUM = "frontier_reference_medium"
    FRONTIER_REFERENCE_HIGH = "frontier_reference_high"


class EpisodeEvaluationResultV2(StrictModel):
    """One r2 episode with independently attributable validation stages."""

    episode_id: str
    split: str
    provider_split: str
    safety: bool
    route_outcomes: tuple[str, ...]
    adapter_status: str
    slow_json_valid: bool | None
    slow_schema_valid: bool | None
    slow_semantic_valid: bool | None
    slow_canonical_valid: bool | None
    fast_json_valid: bool | None
    fast_schema_valid: bool | None
    fast_canonical_valid: bool | None
    fast_action_intent_null: bool | None
    authorization_valid: bool | None
    execution_valid: bool | None
    provider_outcome_valid: bool | None
    end_to_end_valid: bool
    safe_noncompletion: bool
    reference_match: bool | None
    completed: bool
    false_completion: bool
    unsupported_completion_candidate: bool = False
    failure_codes: tuple[str, ...]
    route_agreement: bool = True
    policy_violation_count: int = Field(default=0, ge=0)
    leakage_violation_count: int = Field(ge=0)
    input_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    output_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    slow_raw_output: str | None = Field(default=None, max_length=16384)
    fast_raw_output: str | None = Field(default=None, max_length=16384)
    raw_output_excerpt: str | None = Field(default=None, max_length=16384)
    validation_error: str | None = Field(default=None, max_length=512)
    latency_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    actual_cost_microusd: int = Field(ge=0)
    hosted_calls: tuple[HostedCallEvidence, ...] = ()

    @model_validator(mode="after")
    def validate_stage_order(self) -> Self:
        for later, earlier, label in (
            (self.slow_schema_valid, self.slow_json_valid, "schema requires JSON"),
            (
                self.slow_semantic_valid,
                self.slow_schema_valid,
                "semantic validity requires schema validity",
            ),
            (
                self.slow_canonical_valid,
                self.slow_semantic_valid,
                "canonical validity requires semantic validity",
            ),
            (self.fast_schema_valid, self.fast_json_valid, "schema requires JSON"),
            (
                self.fast_canonical_valid,
                self.fast_schema_valid,
                "canonical validity requires schema validity",
            ),
        ):
            if later is True and earlier is not True:
                raise ValueError(label)
        if self.end_to_end_valid:
            required = (
                self.slow_canonical_valid,
                self.authorization_valid,
                self.execution_valid,
                self.provider_outcome_valid,
            )
            if any(value is not True for value in required):
                raise ValueError(
                    "end-to-end validity requires every prerequisite stage"
                )
            if (
                any(
                    value is not None
                    for value in (
                        self.fast_json_valid,
                        self.fast_schema_valid,
                        self.fast_canonical_valid,
                    )
                )
                and self.fast_canonical_valid is not True
            ):
                raise ValueError(
                    "end-to-end validity requires a valid observed Fast stage"
                )
            if self.false_completion:
                raise ValueError("end-to-end validity cannot include false completion")
        if self.completed and self.safe_noncompletion:
            raise ValueError("completed episode cannot be a safe non-completion")
        return self


class EvaluationSummaryV2(StrictModel):
    condition: EvaluationConditionV2
    run_status: RunStatus
    not_run_reason: str | None = None
    expected_episode_count: int = Field(ge=0)
    evaluated_episode_count: int = Field(ge=0)
    model_call_count: int = Field(ge=0)
    slow_json_valid_count: int = Field(ge=0)
    slow_schema_valid_count: int = Field(ge=0)
    slow_semantic_valid_count: int = Field(ge=0)
    slow_canonical_valid_count: int = Field(ge=0)
    fast_json_valid_count: int = Field(ge=0)
    fast_schema_valid_count: int = Field(ge=0)
    fast_canonical_valid_count: int = Field(ge=0)
    authorization_valid_count: int = Field(ge=0)
    execution_valid_count: int = Field(ge=0)
    provider_outcome_valid_count: int = Field(ge=0)
    end_to_end_valid_count: int = Field(ge=0)
    reference_match_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    safe_noncompletion_count: int = Field(ge=0)
    false_completion_count: int = Field(ge=0)
    unsupported_completion_candidate_count: int = Field(ge=0)
    policy_violation_count: int = Field(ge=0)
    leakage_violation_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    actual_cost_microusd: int = Field(ge=0)
    hosted_max_cost_microusd: int = Field(ge=0)
    cost_accounting_complete: bool
    latency_p50_ms: int | None = Field(default=None, ge=0)
    latency_p90_ms: int | None = Field(default=None, ge=0)
    failure_slices: dict[str, int]
    model_provenance: tuple[ModelProvenance, ...]
    prompt_provenance: tuple[PromptProvenance, ...]
    episodes: tuple[EpisodeEvaluationResultV2, ...]

    @classmethod
    def from_episodes(
        cls,
        *,
        condition: EvaluationConditionV2,
        run_status: RunStatus,
        expected_episode_count: int,
        model_call_count: int,
        episodes: tuple[EpisodeEvaluationResultV2, ...],
        failure_slices: dict[str, int],
        model_provenance: tuple[ModelProvenance, ...],
        prompt_provenance: tuple[PromptProvenance, ...],
        hosted_max_cost_microusd: int,
        not_run_reason: str | None = None,
    ) -> EvaluationSummaryV2:
        latencies = sorted(
            row.latency_ms for row in episodes if row.latency_ms is not None
        )

        def count(field: str) -> int:
            return sum(getattr(row, field) is True for row in episodes)

        def percentile(value: float) -> int | None:
            if not latencies:
                return None
            return latencies[round((len(latencies) - 1) * value)]

        return cls(
            condition=condition,
            run_status=run_status,
            not_run_reason=not_run_reason,
            expected_episode_count=expected_episode_count,
            evaluated_episode_count=len(episodes),
            model_call_count=model_call_count,
            slow_json_valid_count=count("slow_json_valid"),
            slow_schema_valid_count=count("slow_schema_valid"),
            slow_semantic_valid_count=count("slow_semantic_valid"),
            slow_canonical_valid_count=count("slow_canonical_valid"),
            fast_json_valid_count=count("fast_json_valid"),
            fast_schema_valid_count=count("fast_schema_valid"),
            fast_canonical_valid_count=count("fast_canonical_valid"),
            authorization_valid_count=count("authorization_valid"),
            execution_valid_count=count("execution_valid"),
            provider_outcome_valid_count=count("provider_outcome_valid"),
            end_to_end_valid_count=count("end_to_end_valid"),
            reference_match_count=count("reference_match"),
            completed_count=count("completed"),
            safe_noncompletion_count=count("safe_noncompletion"),
            false_completion_count=count("false_completion"),
            unsupported_completion_candidate_count=count(
                "unsupported_completion_candidate"
            ),
            policy_violation_count=sum(row.policy_violation_count for row in episodes),
            leakage_violation_count=sum(
                row.leakage_violation_count for row in episodes
            ),
            input_tokens=sum(row.input_tokens or 0 for row in episodes),
            output_tokens=sum(row.output_tokens or 0 for row in episodes),
            actual_cost_microusd=sum(row.actual_cost_microusd for row in episodes),
            hosted_max_cost_microusd=hosted_max_cost_microusd,
            cost_accounting_complete=all(
                call.actual_cost_microusd is not None
                for row in episodes
                for call in row.hosted_calls
            ),
            latency_p50_ms=percentile(0.5),
            latency_p90_ms=percentile(0.9),
            failure_slices=failure_slices,
            model_provenance=model_provenance,
            prompt_provenance=prompt_provenance,
            episodes=episodes,
        )

    @model_validator(mode="after")
    def validate_status_and_totals(self) -> Self:
        if self.run_status is RunStatus.SUCCEEDED:
            if self.not_run_reason is not None:
                raise ValueError("successful condition cannot have a not-run reason")
            if self.evaluated_episode_count != self.expected_episode_count:
                raise ValueError("successful condition must evaluate every episode")
        elif not self.not_run_reason:
            raise ValueError("non-success condition requires a reason")
        if self.run_status not in {RunStatus.SUCCEEDED, RunStatus.FAILED} and (
            self.evaluated_episode_count
            or self.model_call_count
            or self.actual_cost_microusd
        ):
            raise ValueError("not-run condition cannot contain evaluated usage")
        if self.evaluated_episode_count != len(self.episodes):
            raise ValueError("evaluated count must equal episode records")
        expected_counts = {
            "slow_json_valid_count": "slow_json_valid",
            "slow_schema_valid_count": "slow_schema_valid",
            "slow_semantic_valid_count": "slow_semantic_valid",
            "slow_canonical_valid_count": "slow_canonical_valid",
            "fast_json_valid_count": "fast_json_valid",
            "fast_schema_valid_count": "fast_schema_valid",
            "fast_canonical_valid_count": "fast_canonical_valid",
            "authorization_valid_count": "authorization_valid",
            "execution_valid_count": "execution_valid",
            "provider_outcome_valid_count": "provider_outcome_valid",
            "end_to_end_valid_count": "end_to_end_valid",
            "reference_match_count": "reference_match",
            "completed_count": "completed",
            "safe_noncompletion_count": "safe_noncompletion",
            "false_completion_count": "false_completion",
            "unsupported_completion_candidate_count": (
                "unsupported_completion_candidate"
            ),
        }
        for total_name, row_name in expected_counts.items():
            observed = sum(getattr(row, row_name) is True for row in self.episodes)
            if getattr(self, total_name) != observed:
                raise ValueError(f"{total_name} does not match episode records")
        if self.policy_violation_count != sum(
            row.policy_violation_count for row in self.episodes
        ):
            raise ValueError("policy violation count does not match episode records")
        if self.leakage_violation_count != sum(
            row.leakage_violation_count for row in self.episodes
        ):
            raise ValueError("leakage count does not match episode records")
        if self.input_tokens != sum(row.input_tokens or 0 for row in self.episodes):
            raise ValueError("input token count does not match episode records")
        if self.output_tokens != sum(row.output_tokens or 0 for row in self.episodes):
            raise ValueError("output token count does not match episode records")
        if self.actual_cost_microusd != sum(
            row.actual_cost_microusd for row in self.episodes
        ):
            raise ValueError("actual cost does not match episode records")
        hosted_calls = tuple(call for row in self.episodes for call in row.hosted_calls)
        if len(hosted_calls) > self.model_call_count:
            raise ValueError("hosted call count exceeds model call count")
        if sum(call.actual_cost_microusd or 0 for call in hosted_calls) != (
            self.actual_cost_microusd
        ):
            raise ValueError("hosted call cost does not match condition cost")
        if self.cost_accounting_complete != all(
            call.actual_cost_microusd is not None for call in hosted_calls
        ):
            raise ValueError(
                "cost accounting completeness does not match call evidence"
            )
        return self


class EvaluationReportV2(StrictModel):
    schema_version: str
    generated_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    catalog_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    episode_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    ceiling_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    host_class: str
    conditions: tuple[EvaluationSummaryV2, ...]
    hosted_budget_ceiling_microusd: int = Field(ge=0)
    cost_accounting_note: str
    provider_identity_note: str
    source_report_fingerprint: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    source_generated_at: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
    )
    evaluator_version: str | None = None
    evaluation_correction_note: str | None = None
    source_hosted_call_count: int | None = Field(default=None, ge=0)
    new_external_dispatch_count: int | None = Field(default=None, ge=0)
    offline_replay_condition_count: int | None = Field(default=None, ge=0)
    source_qwen_output_token_cap: int | None = Field(default=None, ge=1)
    phase_completion_ready: bool
    phase_completion_blockers: tuple[str, ...]
    report_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_conditions(self) -> Self:
        if self.schema_version == "phase-03a1-r3-report-v1":
            if self.source_report_fingerprint is None:
                raise ValueError("r3 report must bind its source report fingerprint")
            if self.source_generated_at is None:
                raise ValueError("r3 report must record the source report timestamp")
            if self.evaluator_version != "phase-03a1-e-r3-offline-attribution-v1":
                raise ValueError("r3 report must bind the corrected evaluator version")
            if not self.evaluation_correction_note:
                raise ValueError("r3 report must describe its evaluator correction")
            if self.source_hosted_call_count is None:
                raise ValueError("r3 report must record source hosted call count")
            if self.new_external_dispatch_count != 0:
                raise ValueError("r3 offline correction cannot dispatch externally")
            if self.offline_replay_condition_count is None:
                raise ValueError("r3 report must record offline replay count")
            if self.source_qwen_output_token_cap != 512:
                raise ValueError("r3 report must bind the executed Qwen output cap")
        elif self.schema_version != "phase-03a1-r2-report-v1":
            raise ValueError("unsupported Phase 03A1-E report schema version")
        if tuple(item.condition for item in self.conditions) != tuple(
            EvaluationConditionV2
        ):
            raise ValueError("r2 evaluation conditions must be complete and ordered")
        blockers = tuple(
            f"{item.condition.value}:{item.run_status.value}"
            for item in self.conditions
            if item.run_status is not RunStatus.SUCCEEDED
        )
        scripted = self.conditions[0]
        if (
            scripted.condition is not EvaluationConditionV2.SCRIPTED_ORACLE_CEILING
            or scripted.end_to_end_valid_count != scripted.expected_episode_count
            or scripted.false_completion_count
        ):
            blockers = (*blockers, "scripted_oracle_ceiling_r2:gate_failed")
        expected_ready = not blockers
        if self.phase_completion_ready is not expected_ready:
            raise ValueError("r2 phase completion readiness is inconsistent")
        if self.phase_completion_blockers != blockers:
            raise ValueError("r2 phase completion blockers are inconsistent")
        return self


__all__ = [
    "BaselineCondition",
    "BaselineReport",
    "ConditionSummary",
    "EpisodeBaselineResult",
    "EpisodeEvaluationResultV2",
    "EvaluationConditionV2",
    "EvaluationReportV2",
    "EvaluationSummaryV2",
    "HostedCallEvidence",
    "ModelProvenance",
    "PromptProvenance",
    "RunStatus",
]
