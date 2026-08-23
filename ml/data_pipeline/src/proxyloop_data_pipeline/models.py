from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class LicenseRecord(FrozenModel):
    license_id: str = Field(min_length=1)
    status: Literal["approved", "unapproved"]
    allowed_use: str = Field(min_length=1)


class SourceProvenance(FrozenModel):
    source_id: str = Field(min_length=1)
    source_type: Literal["project_owned_simulator"]
    license: LicenseRecord


class TrajectoryLineage(FrozenModel):
    derivation_parent_id: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    family_version: str = Field(min_length=1)
    entity_cluster: str = Field(min_length=1)
    provider_configuration_id: str = Field(min_length=1)
    provider_configuration_version: str = Field(min_length=1)
    split: Literal["train", "development", "test"]
    response_variant: int = Field(ge=0, lt=4)


class GeneratorSnapshot(FrozenModel):
    role: Literal["teacher", "provider", "judge"]
    adapter_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    external_model: bool = False
    external_input_token_count: int = Field(default=0, ge=0)
    external_output_token_count: int = Field(default=0, ge=0)
    estimated_external_cost_usd: float = Field(default=0.0, ge=0)


class GenerationRecord(FrozenModel):
    simulator_version: str = Field(min_length=1)
    split_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_template_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    generation_config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshots: tuple[GeneratorSnapshot, ...] = Field(min_length=3, max_length=3)


class TrajectoryDecision(FrozenModel):
    action: str = Field(min_length=1)
    offer_id: str | None = None
    completion_candidate: bool


class LearningContent(FrozenModel):
    observation: dict[str, object]
    decision: TrajectoryDecision
    assistant_response_text: str = Field(min_length=1)


class TrajectoryVerification(FrozenModel):
    valid_outcome: bool
    completed: bool
    false_completion: bool
    reason_codes: tuple[str, ...]
    evidence_ref: str | None = None


class NormalizedTrajectory(FrozenModel):
    schema_version: Literal["1.0"]
    trajectory_id: str = Field(min_length=1)
    source: SourceProvenance
    lineage: TrajectoryLineage
    generation: GenerationRecord
    learning_content: LearningContent
    verification: TrajectoryVerification
    review_state: Literal["pending_human"]
    rejection_reasons: tuple[str, ...] = ()
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


__all__ = [
    "GenerationRecord",
    "GeneratorSnapshot",
    "LearningContent",
    "LicenseRecord",
    "NormalizedTrajectory",
    "SourceProvenance",
    "TrajectoryDecision",
    "TrajectoryLineage",
    "TrajectoryVerification",
]
