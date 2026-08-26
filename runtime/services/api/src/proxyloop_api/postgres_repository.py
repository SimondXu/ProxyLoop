"""Synchronous PostgreSQL persistence for the fictional Case Runtime."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import psycopg
from proxyloop_contracts import (
    ActionIntent,
    ApprovalDecision,
    ApprovalRequest,
    CapabilityArgument,
    CapabilityProposal,
    CapabilityReference,
    CaseContextSnapshot,
    CompletionOutcome,
    Evidence,
    EvidenceType,
    ModelInputPins,
    ProviderOffer,
    VisibleCaseEvent,
)
from proxyloop_provider_simulator.provider import FictionalMobileProvider
from proxyloop_telecom_domain import CompletionVerification, verify_completion
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .repository import (
    CaseConflictError,
    CaseNotFoundError,
    CaseRuntimeState,
)

_STORAGE_VERSION: Literal[1] = 1
_TABLE_NAME = "proxyloop_case_runtime_states"
_PROVIDER_CONFIG_REF = "pine-mobile:runtime-v1"


class _CaseStorageEnvelope(BaseModel):
    """Private, strict representation of one persisted runtime aggregate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    storage_version: Literal[1]
    snapshot: CaseContextSnapshot
    events: tuple[VisibleCaseEvent, ...]
    execution_count: int = Field(ge=0)
    execution_source_pins: ModelInputPins | None = None
    execution_intent: ActionIntent | None = None
    execution_approval: ApprovalRequest | None = None
    execution_proposal: CapabilityProposal | None = None

    @model_validator(mode="after")
    def state_history_matches_snapshot(self) -> _CaseStorageEnvelope:
        if self.events != self.snapshot.visible_events:
            raise ValueError("stored event history does not match snapshot")
        return self


class PostgresCaseRepository:
    """A small transaction-per-operation PostgreSQL Case repository.

    The adapter deliberately opens a fresh connection for each operation.  It
    keeps the repository synchronous, avoids introducing a pool in this phase,
    and lets PostgreSQL own cross-process revision compare-and-swap ordering.
    """

    def __init__(self, database_url: str) -> None:
        if not database_url or not database_url.strip():
            raise ValueError("PostgreSQL storage requires a database URL")
        self._database_url = database_url
        self._bootstrap()

    def create(self, state: CaseRuntimeState) -> CaseRuntimeState:
        case_id = state.snapshot.case.case_id
        payload = self._encode_state(state)
        try:
            with (
                self._connect() as connection,
                connection.transaction(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    f"""
                            INSERT INTO {_TABLE_NAME}
                                (case_id, revision, payload)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (case_id) DO NOTHING
                            """,
                    (case_id, state.snapshot.revision, Jsonb(payload)),
                )
                if cursor.rowcount != 1:
                    raise CaseConflictError("case already exists")
        except CaseConflictError:
            raise
        except psycopg.Error:
            raise RuntimeError("PostgreSQL Case storage operation failed") from None
        return state

    def get(self, case_id: UUID) -> CaseRuntimeState | None:
        try:
            with (
                self._connect() as connection,
                connection.transaction(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    f"SELECT revision, payload FROM {_TABLE_NAME} WHERE case_id = %s",
                    (case_id,),
                )
                row = cursor.fetchone()
        except psycopg.Error:
            raise RuntimeError("PostgreSQL Case storage operation failed") from None
        if row is None:
            return None
        return self._decode_state(case_id, row[0], row[1])

    def replace(
        self,
        case_id: UUID,
        *,
        expected_revision: int,
        state: CaseRuntimeState,
    ) -> CaseRuntimeState:
        try:
            with (
                self._connect() as connection,
                connection.transaction(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    f"SELECT 1 FROM {_TABLE_NAME} WHERE case_id = %s",
                    (case_id,),
                )
                if cursor.fetchone() is None:
                    raise CaseNotFoundError("case not found")
                if state.snapshot.case.case_id != case_id:
                    raise CaseConflictError("replacement case id does not match")
                payload = self._encode_state(state)
                cursor.execute(
                    f"""
                            UPDATE {_TABLE_NAME}
                            SET revision = %s, payload = %s, updated_at = now()
                            WHERE case_id = %s AND revision = %s
                            """,
                    (
                        state.snapshot.revision,
                        Jsonb(payload),
                        case_id,
                        expected_revision,
                    ),
                )
                if cursor.rowcount == 1:
                    return state
                raise CaseConflictError("case snapshot revision is stale")
        except (CaseConflictError, CaseNotFoundError):
            raise
        except psycopg.Error:
            raise RuntimeError("PostgreSQL Case storage operation failed") from None

    def _connect(self) -> Any:
        return psycopg.connect(self._database_url, row_factory=tuple_row)

    def _bootstrap(self) -> None:
        try:
            with (
                self._connect() as connection,
                connection.transaction(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    f"""
                            CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
                                case_id uuid PRIMARY KEY,
                                revision bigint NOT NULL CHECK (revision >= 1),
                                payload jsonb NOT NULL,
                                updated_at timestamptz NOT NULL DEFAULT now()
                            )
                            """
                )
        except psycopg.Error:
            raise RuntimeError(
                "PostgreSQL Case storage schema initialization failed"
            ) from None

    @staticmethod
    def _encode_state(state: CaseRuntimeState) -> dict[str, object]:
        try:
            envelope = _CaseStorageEnvelope(
                storage_version=_STORAGE_VERSION,
                snapshot=state.snapshot,
                events=state.events,
                execution_count=state.execution_count,
                execution_source_pins=state.execution_source_pins,
                execution_intent=state.execution_intent,
                execution_approval=state.execution_approval,
                execution_proposal=state.execution_proposal,
            )
            _verify_provider_state(state, envelope)
        except (ValidationError, ValueError, RuntimeError):
            raise RuntimeError("Case state failed storage validation") from None
        return envelope.model_dump(mode="json")

    @staticmethod
    def _decode_state(
        case_id: UUID,
        row_revision: object,
        payload: object,
    ) -> CaseRuntimeState:
        if not isinstance(payload, dict):
            raise RuntimeError("stored Case payload is invalid")
        if payload.get("storage_version") != _STORAGE_VERSION:
            raise RuntimeError("unsupported Case storage version")
        try:
            envelope = _CaseStorageEnvelope.model_validate_json(json.dumps(payload))
            if envelope.snapshot.case.case_id != case_id:
                raise ValueError("stored Case id does not match row")
            if row_revision != envelope.snapshot.revision:
                raise ValueError("stored relational revision does not match payload")
            provider = _reconstruct_provider(envelope)
        except (ValidationError, ValueError, RuntimeError):
            raise RuntimeError("stored Case payload is invalid") from None
        return CaseRuntimeState(
            snapshot=envelope.snapshot,
            events=envelope.events,
            provider=provider,
            execution_count=envelope.execution_count,
            execution_source_pins=envelope.execution_source_pins,
            execution_intent=envelope.execution_intent,
            execution_approval=envelope.execution_approval,
            execution_proposal=envelope.execution_proposal,
        )


def _verify_provider_state(
    state: CaseRuntimeState,
    envelope: _CaseStorageEnvelope,
) -> None:
    """Reject state that could not have come from the deterministic simulator."""

    reconstructed = _reconstruct_provider(envelope)
    provider_transition_is_in_flight = (
        reconstructed.state.value == "awaiting_approval"
        and state.provider.state.value == "offered"
        and envelope.snapshot.approval_requests
        and envelope.snapshot.approval_requests[0].decision is ApprovalDecision.PENDING
    )
    if (
        state.provider.state is not reconstructed.state
        and not provider_transition_is_in_flight
    ):
        raise ValueError("Provider state does not match the Case snapshot")
    if state.provider.confirmation != reconstructed.confirmation:
        raise ValueError("Provider confirmation does not match the Case snapshot")
    if state.provider.confirmation_evidence != reconstructed.confirmation_evidence:
        raise ValueError("Provider Evidence does not match the Case snapshot")


def _reconstruct_provider(envelope: _CaseStorageEnvelope) -> FictionalMobileProvider:
    snapshot = envelope.snapshot
    if snapshot.provider_config_ref != _PROVIDER_CONFIG_REF:
        raise ValueError("unsupported Provider configuration")
    if len(snapshot.offers) != 1:
        raise ValueError("stored Case must contain one deterministic offer")
    offer = snapshot.offers[0]
    provider = FictionalMobileProvider()
    generated_offer, generated_offer_evidence = provider.issue_offer(
        snapshot.case,
        issued_at=offer.created_at,
    )
    if generated_offer != offer:
        raise ValueError("stored offer does not match the deterministic Provider")
    matching_offer_evidence = _evidence_by_id(snapshot.evidence, offer.evidence_ids)
    if matching_offer_evidence != generated_offer_evidence:
        raise ValueError("stored offer Evidence does not match the Provider")

    intents = snapshot.action_intents
    approvals = snapshot.approval_requests
    if len(intents) > 1 or len(approvals) > 1:
        raise ValueError("stored Case contains duplicate action state")
    intent = intents[0] if intents else None
    approval = approvals[0] if approvals else None
    if (intent is None) != (approval is None):
        raise ValueError("stored approval must have an action intent")
    if intent is not None and approval is not None:
        if approval.action_intent_id != intent.intent_id:
            raise ValueError("stored approval does not reference its intent")
        provider.await_approval(intent)

    if snapshot.completion_decision is None:
        if snapshot.pending_execution:
            _verify_pending_fields(envelope, snapshot, intent, approval, offer)
        elif approval is not None and approval.decision is ApprovalDecision.APPROVED:
            raise ValueError("approved Case without completion must be pending")
        else:
            _verify_no_execution_fields(envelope)
        return provider

    if snapshot.completion_decision.decision is not CompletionOutcome.COMPLETE:
        raise ValueError("only verified terminal Cases can be reconstructed")
    if approval is None or intent is None:
        raise ValueError("terminal Case is missing approval state")
    if approval.decision is not ApprovalDecision.APPROVED:
        raise ValueError("terminal Case approval is not approved")
    if envelope.execution_count != 1:
        raise ValueError("terminal Case must have one execution")
    if envelope.execution_approval != approval or envelope.execution_intent != intent:
        raise ValueError("terminal execution pins do not match approval state")
    if envelope.execution_source_pins is None:
        raise ValueError("terminal Case is missing source pins")
    if envelope.execution_source_pins != snapshot.pins:
        raise ValueError("terminal execution pins do not match snapshot identity")
    if envelope.execution_proposal != _capability_proposal(offer, approval.decided_at):
        raise ValueError("terminal execution proposal is not deterministic")
    confirmation_evidence = _confirmation_evidence(snapshot.evidence)
    provider.execute_approved_offer(
        approval,
        executed_at=confirmation_evidence.observed_at,
    )
    if provider.confirmation_evidence != confirmation_evidence:
        raise ValueError("stored confirmation Evidence does not match the Provider")
    _verify_simulator_transition_evidence(
        snapshot.evidence,
        intent=intent,
        approval=approval,
        executed_at=confirmation_evidence.observed_at,
    )
    if (
        confirmation_evidence.evidence_id
        not in snapshot.completion_decision.evidence_ids
    ):
        raise ValueError("terminal completion is not bound to confirmation Evidence")
    confirmation = provider.confirmation
    if confirmation is None:
        raise ValueError("deterministic Provider returned no confirmation")
    verified_completion = verify_completion(
        CompletionVerification(
            completion_id=snapshot.completion_decision.completion_id,
            case=snapshot.case,
            offer=offer,
            action_intent=intent,
            approval_request=approval,
            confirmation=confirmation,
            evidence=confirmation_evidence,
            confirmation_authority=provider,
            executed_at=confirmation.confirmed_at,
            evaluated_at=snapshot.completion_decision.evaluated_at,
        )
    )
    if verified_completion != snapshot.completion_decision:
        raise ValueError("stored completion does not match the authoritative verifier")
    return provider


def _verify_no_execution_fields(envelope: _CaseStorageEnvelope) -> None:
    if envelope.execution_count != 0:
        raise ValueError("non-terminal Case cannot have executions")
    if any(
        field is not None
        for field in (
            envelope.execution_source_pins,
            envelope.execution_intent,
            envelope.execution_approval,
            envelope.execution_proposal,
        )
    ):
        raise ValueError("non-executing Case contains execution metadata")


def _verify_pending_fields(
    envelope: _CaseStorageEnvelope,
    snapshot: CaseContextSnapshot,
    intent: ActionIntent | None,
    approval: ApprovalRequest | None,
    offer: ProviderOffer,
) -> None:
    if intent is None or approval is None:
        raise ValueError("pending execution is missing approval state")
    if envelope.execution_count != 0:
        raise ValueError("pending execution cannot have a completed execution")
    if approval.decision is not ApprovalDecision.APPROVED:
        raise ValueError("pending execution approval is not approved")
    if envelope.execution_source_pins is None:
        raise ValueError("pending execution is missing source pins")
    if envelope.execution_source_pins != snapshot.pins:
        raise ValueError("pending execution pins do not match snapshot pins")
    if envelope.execution_source_pins.case_id != snapshot.case.case_id:
        raise ValueError("pending execution pins reference another Case")
    if envelope.execution_intent != intent or envelope.execution_approval != approval:
        raise ValueError("pending execution pins do not match approval state")
    expected_proposal = _capability_proposal(offer, approval.decided_at)
    if envelope.execution_proposal != expected_proposal:
        raise ValueError("pending execution proposal is not deterministic")


def _evidence_by_id(
    evidence: tuple[Evidence, ...], evidence_ids: tuple[UUID, ...]
) -> Evidence:
    if len(evidence_ids) != 1:
        raise ValueError("deterministic offer requires one Evidence id")
    matching = [item for item in evidence if item.evidence_id == evidence_ids[0]]
    if len(matching) != 1:
        raise ValueError("referenced offer Evidence is missing")
    return matching[0]


def _confirmation_evidence(evidence: tuple[Evidence, ...]) -> Evidence:
    matching = [
        item for item in evidence if item.source_type is EvidenceType.CONFIRMATION
    ]
    if len(matching) != 1:
        raise ValueError("terminal Case requires one confirmation Evidence")
    return matching[0]


def _verify_simulator_transition_evidence(
    evidence: tuple[Evidence, ...],
    *,
    intent: ActionIntent,
    approval: ApprovalRequest,
    executed_at: datetime,
) -> Evidence:
    if (
        approval.case_id != intent.case_id
        or approval.action_intent_id != intent.intent_id
        or approval.action_intent_revision != intent.revision
    ):
        raise ValueError("simulator transition Evidence approval binding is invalid")
    matching = [
        item
        for item in evidence
        if item.source_type is EvidenceType.SIMULATOR_TRANSITION
    ]
    if len(matching) != 1:
        raise ValueError("terminal Case requires one simulator transition Evidence")
    idempotency_key = intent.idempotency_key
    expected = Evidence(
        contract_type="evidence",
        schema_version="1.0",
        evidence_id=_stable_uuid(f"executor-evidence:{idempotency_key}"),
        case_id=intent.case_id,
        source_type=EvidenceType.SIMULATOR_TRANSITION,
        source_ref=idempotency_key,
        content_hash=hashlib.sha256(idempotency_key.encode()).hexdigest(),
        observed_at=executed_at,
        captured_at=executed_at,
        media_type="application/json",
    )
    if matching[0] != expected:
        raise ValueError("stored simulator transition Evidence is not deterministic")
    return matching[0]


def _capability_proposal(
    offer: ProviderOffer,
    created_at: datetime | None,
) -> CapabilityProposal:
    if created_at is None:
        raise ValueError("execution proposal requires a creation timestamp")
    return CapabilityProposal(
        proposal_id=_stable_uuid(f"proposal:{offer.offer_id}"),
        capability=CapabilityReference(
            namespace="simulator",
            capability_id="simulator.accept_fictional_offer",
            version="1.0",
        ),
        arguments=(CapabilityArgument(name="offer_id", value=str(offer.offer_id)),),
        created_at=created_at,
        expires_at=offer.expires_at,
    )


def _stable_uuid(value: str) -> UUID:
    raw = bytearray(hashlib.sha256(value.encode()).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


__all__ = ["PostgresCaseRepository"]
