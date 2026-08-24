"""Typed adapter seams for deterministic and model-backed evaluation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

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
    "PreparedSimulatorExecution",
    "SimulatorCapabilityAdapter",
    "SlowAdapter",
]
