"""Strict result contracts for Phase 03A1 untuned baselines."""

from __future__ import annotations

from enum import StrEnum

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


__all__ = [
    "BaselineCondition",
    "BaselineReport",
    "ConditionSummary",
    "EpisodeBaselineResult",
    "HostedCallEvidence",
    "ModelProvenance",
    "PromptProvenance",
    "RunStatus",
]
