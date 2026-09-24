"""Typed adapter seams for deterministic and model-backed evaluation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from proxyloop_contracts import (
    CapabilityProposal,
    Evidence,
    FastModelView,
    FastTurnDecision,
    ModelInputPins,
    SlowWorkRequest,
    SlowWorkResult,
)

BOUNDED_FAST_STATUS_TEXT = "I am checking that and will update you."


@dataclass(frozen=True, slots=True)
class FastAdapterResult:
    """Compatibility envelope that makes the Fast input pins explicit."""

    pins: ModelInputPins
    decision: FastTurnDecision


@dataclass(frozen=True, slots=True)
class PreparedSimulatorExecution:
    """Validated-before-commit local simulator transaction."""

    evidence: Evidence
    commit: Callable[[], None]


class FastAdapter(Protocol):
    """Replaceable low-latency decision interface."""

    def decide(self, view: FastModelView) -> FastAdapterResult: ...


class SlowAdapter(Protocol):
    """Replaceable bounded reasoner interface."""

    def reason(self, request: SlowWorkRequest) -> SlowWorkResult: ...


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """The stable identity an adapter reports for its ModelTrace records."""

    provider: str
    model: str
    model_version: str
    adapter_version: str
    prompt_version: str


@dataclass(frozen=True, slots=True)
class ModelCallUsage:
    """What one model call cost, as reported by the adapter that made it.

    ``latency_ms`` is ``None`` when the adapter did not measure the call.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        for name in ("input_tokens", "output_tokens", "latency_ms"):
            value = getattr(self, name)
            if name == "latency_ms" and value is None:
                continue
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative int")


@runtime_checkable
class IdentifiedAdapter(Protocol):
    """Optional: an adapter that names the model behind its calls."""

    @property
    def model_identity(self) -> ModelIdentity: ...


@runtime_checkable
class UsageReportingFastAdapter(Protocol):
    """Optional: a Fast adapter that reports the usage of each call."""

    def decide_with_usage(
        self, view: FastModelView
    ) -> tuple[FastAdapterResult, ModelCallUsage]: ...


@runtime_checkable
class UsageReportingSlowAdapter(Protocol):
    """Optional: a Slow adapter that reports the usage of each call."""

    def reason_with_usage(
        self, request: SlowWorkRequest
    ) -> tuple[SlowWorkResult, ModelCallUsage]: ...


class SimulatorCapabilityAdapter(Protocol):
    """Executor-owned fictional Provider capability boundary."""

    def prepare(
        self, proposal: CapabilityProposal, *, idempotency_key: str
    ) -> PreparedSimulatorExecution:
        """Prepare Evidence and a side-effect commit without mutating state."""


__all__ = [
    "BOUNDED_FAST_STATUS_TEXT",
    "FastAdapter",
    "FastAdapterResult",
    "IdentifiedAdapter",
    "ModelCallUsage",
    "ModelIdentity",
    "PreparedSimulatorExecution",
    "SimulatorCapabilityAdapter",
    "SlowAdapter",
    "UsageReportingFastAdapter",
    "UsageReportingSlowAdapter",
]
