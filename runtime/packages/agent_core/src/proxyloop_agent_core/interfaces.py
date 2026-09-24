"""Typed adapter seams for deterministic and model-backed evaluation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from proxyloop_contracts import (
    CapabilityProposal,
    Evidence,
    FastModelView,
    FastTurnDecision,
    ModelInputPins,
    SlowWorkRequest,
    SlowWorkResult,
)

from .fast_observation import FAST_OBSERVATION_REFUSAL_CODES
from .local_fast_wire import (
    CLIENT_DETAIL_CODES,
    INVALID_OUTPUT_DETAIL_CODES,
    UNRENDERABLE_DETAIL_CODES,
    WIRE_ERROR_CODES,
)
from .observation import SafeObservation

BOUNDED_FAST_STATUS_TEXT = "I am checking that and will update you."
# A Fast call that did not yield a decision, by cause (design §2.6).
FAST_ADAPTER_FAILURE_CODES: Final = frozenset(
    {
        "fast_adapter_timeout",
        "fast_adapter_unavailable",
        "fast_adapter_busy",
        "fast_adapter_protocol_error",
        "fast_adapter_invalid_output",
        "fast_adapter_identity_mismatch",
        "fast_input_unrenderable",
    }
)
FAST_ADAPTER_FAILURE_DETAIL_CODES: Final = frozenset(
    {
        *INVALID_OUTPUT_DETAIL_CODES,
        *UNRENDERABLE_DETAIL_CODES,
        *WIRE_ERROR_CODES,
        *CLIENT_DETAIL_CODES,
        *FAST_OBSERVATION_REFUSAL_CODES,
    }
)


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


class FastAdapterFailure(RuntimeError):
    """A Fast call that yielded no decision, for an allow-listed cause.

    With ``capture_fast_failures`` the coordinator records it as a ``FAILED``
    trace and the Runtime delivers the fallback line; any other exception
    propagates. Codes outside the allow-lists are refused, so the trace can
    never carry content.
    """

    def __init__(
        self,
        reason_code: str,
        *,
        detail_code: str | None = None,
        usage: ModelCallUsage | None = None,
    ) -> None:
        if reason_code not in FAST_ADAPTER_FAILURE_CODES:
            raise ValueError("Fast failure reason code is not allow-listed")
        if detail_code is not None and (
            detail_code not in FAST_ADAPTER_FAILURE_DETAIL_CODES
        ):
            raise ValueError("Fast failure detail code is not allow-listed")
        if usage is not None and not isinstance(usage, ModelCallUsage):
            raise ValueError("Fast failure usage must be a ModelCallUsage")
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.detail_code = detail_code
        self.usage = usage

    @property
    def reason_codes(self) -> tuple[str, ...]:
        if self.detail_code is None:
            return (self.reason_code,)
        return (self.reason_code, self.detail_code)


@runtime_checkable
class ObservingFastAdapter(Protocol):
    """Optional: a Fast adapter whose model input needs the public observation.

    The coordinator derives the observation from the snapshot it projected the
    view from; the adapter never sees the snapshot.
    """

    def decide_observed(
        self, view: FastModelView, observation: SafeObservation
    ) -> tuple[FastAdapterResult, ModelCallUsage]: ...


@runtime_checkable
class LabelledFastBackend(Protocol):
    """Optional: a Fast adapter that names its opt-in backend for ``adapter_mode``."""

    @property
    def fast_backend_label(self) -> str: ...


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
    "FAST_ADAPTER_FAILURE_CODES",
    "FAST_ADAPTER_FAILURE_DETAIL_CODES",
    "FastAdapter",
    "FastAdapterFailure",
    "FastAdapterResult",
    "IdentifiedAdapter",
    "LabelledFastBackend",
    "ModelCallUsage",
    "ModelIdentity",
    "ObservingFastAdapter",
    "PreparedSimulatorExecution",
    "SimulatorCapabilityAdapter",
    "SlowAdapter",
    "UsageReportingFastAdapter",
    "UsageReportingSlowAdapter",
]
