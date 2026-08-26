"""Replaceable persistence seam for the shared Case application Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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


class ChannelConflictError(CaseConflictError):
    """A channel event or delivery does not match authoritative state."""


class ChannelDependencyUnavailableError(StorageUnavailableError):
    """The channel persistence/dispatch dependency is unavailable."""


@dataclass(frozen=True, slots=True)
class ChannelBindingRecord:
    channel_kind: str
    binding_ref: str
    case_id: UUID
    local_ref: str
    remote_ref: str
    allowed_directions: tuple[str, ...]
    active: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class InboxReceiptRecord:
    channel_kind: str
    event_id: UUID
    payload_hash: str
    binding_ref: str
    case_id: UUID
    command_id: UUID
    first_seen_at: datetime
    event_kind: str
    processing_state: str
    content: str | None = None
    deduplicated: bool = False


@dataclass(frozen=True, slots=True)
class OutboxRecord:
    delivery_id: UUID
    idempotency_key: str
    case_id: UUID
    binding_ref: str
    source_event_id: UUID
    source_command_id: UUID
    source_case_revision: int
    source_strategy_id: UUID | None
    source_strategy_revision: int
    source_event_cursor: int
    body: str
    body_hash: str
    state: str = "pending"
    provider_message_id: str | None = None
    attempt_count: int = 0
    last_failure_category: str | None = None


@dataclass(frozen=True, slots=True)
class DeliveryReceiptRecord:
    delivery_id: UUID
    provider_message_id: str
    observation_state: str
    artifact_hash: str
    observed_at: datetime
    captured_at: datetime
    evidence_id: UUID


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
    "ChannelBindingRecord",
    "ChannelConflictError",
    "ChannelDependencyUnavailableError",
    "DeliveryReceiptRecord",
    "InMemoryCaseRepository",
    "InboxReceiptRecord",
    "OutboxRecord",
    "StorageUnavailableError",
]
