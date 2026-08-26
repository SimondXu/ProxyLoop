"""Replaceable persistence seam for the shared Case application Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Protocol
from uuid import UUID

from proxyloop_contracts import (
    ActionIntent,
    ApprovalRequest,
    CapabilityProposal,
    CaseContextSnapshot,
    FastTurnDecision,
    ModelInputPins,
    VisibleCaseEvent,
)
from proxyloop_provider_simulator.provider import FictionalMobileProvider

from .commands import CaseTransitionRef


@dataclass(frozen=True, slots=True)
class CaseRuntimeState:
    """One process-local Case record.

    The canonical snapshot and event log are immutable values.  The Provider is
    a process-local simulator adapter; durable stores reconstruct it from the
    validated canonical state rather than serializing its private attributes.
    """

    snapshot: CaseContextSnapshot
    events: tuple[VisibleCaseEvent, ...]
    provider: FictionalMobileProvider
    execution_count: int = 0
    execution_source_pins: ModelInputPins | None = None
    execution_intent: ActionIntent | None = None
    execution_approval: ApprovalRequest | None = None
    execution_proposal: CapabilityProposal | None = None
    transitions: tuple[CaseTransitionRef, ...] = ()
    last_fast_decision: FastTurnDecision | None = None


class CaseNotFoundError(LookupError):
    """The requested Case is not present in the repository."""


class CaseConflictError(RuntimeError):
    """An optimistic update used a stale snapshot revision."""


class StorageUnavailableError(RuntimeError):
    """The configured Case storage dependency could not be reached."""


class CaseRepository(Protocol):
    """Minimal persistence interface used by ``ThinAgentRuntime``."""

    def create(self, state: CaseRuntimeState) -> CaseRuntimeState: ...

    def get(self, case_id: UUID) -> CaseRuntimeState | None: ...

    def replace(
        self,
        case_id: UUID,
        *,
        expected_revision: int,
        state: CaseRuntimeState,
    ) -> CaseRuntimeState: ...


class InMemoryCaseRepository:
    """Thread-safe single-process repository with optimistic replacement."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._states: dict[UUID, CaseRuntimeState] = {}

    def create(self, state: CaseRuntimeState) -> CaseRuntimeState:
        case_id = state.snapshot.case.case_id
        with self._lock:
            if case_id in self._states:
                raise CaseConflictError("case already exists")
            self._states[case_id] = state
            return state

    def get(self, case_id: UUID) -> CaseRuntimeState | None:
        with self._lock:
            return self._states.get(case_id)

    def replace(
        self,
        case_id: UUID,
        *,
        expected_revision: int,
        state: CaseRuntimeState,
    ) -> CaseRuntimeState:
        with self._lock:
            current = self._states.get(case_id)
            if current is None:
                raise CaseNotFoundError("case not found")
            if current.snapshot.revision != expected_revision:
                raise CaseConflictError("case snapshot revision is stale")
            if state.snapshot.case.case_id != case_id:
                raise CaseConflictError("replacement case id does not match")
            self._states[case_id] = state
            return state


__all__ = [
    "CaseConflictError",
    "CaseNotFoundError",
    "CaseRepository",
    "CaseRuntimeState",
    "InMemoryCaseRepository",
    "StorageUnavailableError",
]
