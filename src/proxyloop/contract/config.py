"""Session configuration: every condition and ablation is a value here (I1).

There is no manual-clock value: tests inject clocks through constructors.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, field_validator, model_validator

from proxyloop.contract.base import Frozen, canonical_json, sha256_text
from proxyloop.contract.llm import ModelRef


class AblationId(StrEnum):
    """The S3 paired ablations (EVAL §4.2). A3 is a lane swap of ``fast_*``;
    A5 is ``slow_view=raw_transcript``."""

    SUPPRESS_RELAY_USER = "suppress_relay_user"  # A1
    SUPPRESS_RELAY_CP = "suppress_relay_cp"  # A1c
    MUTE_FASTU_EXPLANATIONS = "mute_fastu_explanations"  # A2
    TEACHER_REPAIR_CP = "teacher_repair_cp"  # A4
    TEACHER_REPAIR_USER = "teacher_repair_user"  # A4
    APPROVAL_WITHOUT_FASTU_READBACK = "approval_without_fastu_readback"  # A6


class SlowViewMode(StrEnum):
    RELAY_ONLY = "relay_only"
    RAW_TRANSCRIPT = "raw_transcript"  # ablation A5 only (I5)


class WorldModels(Frozen):
    """The world's models. No default: a required ``SessionConfig`` value."""

    ear: ModelRef
    mouth: ModelRef
    simuser: ModelRef

    @model_validator(mode="after")
    def _pinned(self) -> Self:
        for role, ref in (
            ("ear", self.ear),
            ("mouth", self.mouth),
            ("simuser", self.simuser),
        ):
            if ref.reasoning_effort is None:
                raise ValueError(f"world.{role} must pin its reasoning_effort")
        return self


class Sampling(Frozen):
    temperature: float = Field(ge=0)
    top_p: float = Field(gt=0, le=1)
    max_tokens: int = Field(gt=0)


class SessionConfig(Frozen):
    fast_user: ModelRef
    fast_cp: ModelRef
    slow: ModelRef
    world: WorldModels
    fast_sampling: Sampling
    seed: int  # run seed; per-generation seeds derive from it
    ablations: tuple[AblationId, ...] = ()
    slow_view: SlowViewMode = SlowViewMode.RELAY_ONLY
    live: bool

    @field_validator("ablations")
    @classmethod
    def _sorted(cls, value: tuple[AblationId, ...]) -> tuple[AblationId, ...]:
        return tuple(sorted(set(value)))


def config_hash(cfg: SessionConfig) -> str:
    return sha256_text(canonical_json(cfg.model_dump(mode="json")))
