"""Synchronous PostgreSQL persistence for the shared Case Runtime."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg
from proxyloop_connectors import (
    BINDING_REF,
    CHANNEL_KIND,
    FRESHNESS_WINDOW,
    VerifiedLocalMailboxEvent,
)
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
    FastTurnDecision,
    ModelInputPins,
    ProviderOffer,
    VisibleCaseEvent,
)
from proxyloop_provider_simulator.provider import FictionalMobileProvider
from proxyloop_telecom_domain import CompletionVerification, verify_completion
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .commands import CaseTransitionRef
from .repository import (
    CaseConflictError,
    CaseNotFoundError,
    CaseRuntimeState,
    ChannelBindingRecord,
    ChannelConflictError,
    DeliveryReceiptRecord,
    InboxReceiptRecord,
    OutboxRecord,
    StorageUnavailableError,
)

_STORAGE_VERSION: Literal[1] = 1
_TABLE_NAME = "proxyloop_case_runtime_states"
_PROVIDER_CONFIG_REF = "pine-mobile:runtime-v1"
_BINDINGS_TABLE = "proxyloop_channel_bindings"
_INBOX_TABLE = "proxyloop_channel_inbox_receipts"
_OUTBOX_TABLE = "proxyloop_channel_outbox_records"
_DELIVERY_TABLE = "proxyloop_channel_delivery_receipts"


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
    transitions: tuple[CaseTransitionRef, ...] = ()
    last_fast_decision: FastTurnDecision | None = None

    @model_validator(mode="after")
    def state_history_matches_snapshot(self) -> _CaseStorageEnvelope:
        if self.events != self.snapshot.visible_events:
            raise ValueError("stored event history does not match snapshot")
        command_ids: set[UUID] = set()
        prior_revision = 0
        for transition in self.transitions:
            if transition.case_id != self.snapshot.case.case_id:
                raise ValueError("stored transition references another Case")
            if transition.command_id in command_ids:
                raise ValueError("stored transitions contain a duplicate command")
            if transition.after_revision < prior_revision:
                raise ValueError("stored transitions are not revision ordered")
            if transition.after_revision > self.snapshot.revision:
                raise ValueError("stored transition exceeds the current revision")
            command_ids.add(transition.command_id)
            prior_revision = transition.after_revision
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
                cursor.execute(
                    f"""
                    INSERT INTO {_BINDINGS_TABLE}
                        (binding_ref, channel_kind, case_id, local_ref, remote_ref,
                         allowed_directions, active, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (binding_ref) DO NOTHING
                    """,
                    (
                        BINDING_REF,
                        CHANNEL_KIND,
                        case_id,
                        "fictional-provider-local-mailbox",
                        f"case/{case_id}",
                        Jsonb(["inbound", "outbound"]),
                        True,
                        state.snapshot.case.created_at,
                    ),
                )
        except CaseConflictError:
            raise
        except psycopg.Error:
            raise StorageUnavailableError(
                "PostgreSQL Case storage operation failed"
            ) from None
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
            raise StorageUnavailableError(
                "PostgreSQL Case storage operation failed"
            ) from None
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
            raise StorageUnavailableError(
                "PostgreSQL Case storage operation failed"
            ) from None

    def check_readiness(self) -> None:
        """Run the read-only dependency probe used by the control plane."""

        try:
            with (
                self._connect() as connection,
                connection.transaction(),
                connection.cursor() as cursor,
            ):
                cursor.execute("SELECT 1")
                if cursor.fetchone() != (1,):
                    raise StorageUnavailableError("PostgreSQL readiness probe failed")
        except StorageUnavailableError:
            raise
        except psycopg.Error:
            raise StorageUnavailableError("PostgreSQL readiness probe failed") from None

    def get_channel_binding(
        self, binding_ref: str = BINDING_REF
    ) -> ChannelBindingRecord | None:
        try:
            with (
                self._connect() as connection,
                connection.transaction(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    f"""
                    SELECT channel_kind, binding_ref, case_id, local_ref, remote_ref,
                           allowed_directions, active, created_at
                    FROM {_BINDINGS_TABLE}
                    WHERE binding_ref = %s
                    """,
                    (binding_ref,),
                )
                row = cursor.fetchone()
        except psycopg.Error:
            raise StorageUnavailableError(
                "PostgreSQL channel operation failed"
            ) from None
        return _binding_from_row(row) if row is not None else None

    def reserve_channel_event(
        self,
        event: VerifiedLocalMailboxEvent,
        *,
        received_at: datetime,
    ) -> InboxReceiptRecord:
        """Reserve one event identity before dispatching its Case command."""

        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")
        try:
            with (
                self._connect() as connection,
                connection.transaction(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    f"""
                    SELECT channel_kind, event_id, payload_hash, binding_ref, case_id,
                           command_id, first_seen_at, event_kind, processing_state,
                           content
                    FROM {_INBOX_TABLE}
                    WHERE channel_kind = %s AND event_id = %s
                    FOR UPDATE
                    """,
                    (CHANNEL_KIND, event.event_id),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    prior = _inbox_from_row(existing, deduplicated=True)
                    if prior.payload_hash != event.raw_payload_hash:
                        raise ChannelConflictError("channel_replay_mismatch")
                    return prior
                if (
                    event.fixture_timestamp is None
                    or abs(received_at - event.fixture_timestamp) > FRESHNESS_WINDOW
                    or abs(received_at - event.occurred_at) > FRESHNESS_WINDOW
                ):
                    raise ChannelConflictError("stale_unknown_event")
                cursor.execute(
                    f"""
                    SELECT channel_kind, binding_ref, case_id, local_ref, remote_ref,
                           allowed_directions, active, created_at
                    FROM {_BINDINGS_TABLE}
                    WHERE binding_ref = %s
                    FOR SHARE
                    """,
                    (event.binding_ref,),
                )
                binding_row = cursor.fetchone()
                if binding_row is None:
                    raise ChannelConflictError("unknown_binding")
                binding = _binding_from_row(binding_row)
                if not binding.active:
                    raise ChannelConflictError("channel_conflict")
                command_id = uuid4()
                cursor.execute(
                    f"""
                    INSERT INTO {_INBOX_TABLE}
                        (channel_kind, event_id, payload_hash, binding_ref, case_id,
                         command_id, first_seen_at, event_kind, processing_state,
                         content)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (channel_kind, event_id) DO NOTHING
                    """,
                    (
                        CHANNEL_KIND,
                        event.event_id,
                        event.raw_payload_hash,
                        event.binding_ref,
                        binding.case_id,
                        command_id,
                        received_at,
                        event.kind.value,
                        "reserved",
                        event.content,
                    ),
                )
                if cursor.rowcount != 1:
                    cursor.execute(
                        f"""
                        SELECT channel_kind, event_id, payload_hash, binding_ref,
                               case_id,
                               command_id, first_seen_at, event_kind, processing_state,
                               content
                        FROM {_INBOX_TABLE}
                        WHERE channel_kind = %s AND event_id = %s
                        FOR UPDATE
                        """,
                        (CHANNEL_KIND, event.event_id),
                    )
                    raced = cursor.fetchone()
                    if raced is None:
                        raise StorageUnavailableError(
                            "channel inbox reservation was lost"
                        )
                    prior = _inbox_from_row(raced, deduplicated=True)
                    if prior.payload_hash != event.raw_payload_hash:
                        raise ChannelConflictError("channel_replay_mismatch")
                    return prior
                return InboxReceiptRecord(
                    channel_kind=CHANNEL_KIND,
                    event_id=event.event_id,
                    payload_hash=event.raw_payload_hash,
                    binding_ref=event.binding_ref,
                    case_id=binding.case_id,
                    command_id=command_id,
                    first_seen_at=received_at,
                    event_kind=event.kind.value,
                    processing_state="reserved",
                    content=event.content,
                )
        except (CaseConflictError, CaseNotFoundError):
            raise
        except psycopg.Error:
            raise StorageUnavailableError(
                "PostgreSQL channel operation failed"
            ) from None

    def get_inbox_receipt(self, event_id: UUID) -> InboxReceiptRecord | None:
        try:
            with (
                self._connect() as connection,
                connection.transaction(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    f"""
                    SELECT channel_kind, event_id, payload_hash, binding_ref, case_id,
                           command_id, first_seen_at, event_kind, processing_state,
                           content
                    FROM {_INBOX_TABLE}
                    WHERE channel_kind = %s AND event_id = %s
                    """,
                    (CHANNEL_KIND, event_id),
                )
                row = cursor.fetchone()
        except psycopg.Error:
            raise StorageUnavailableError(
                "PostgreSQL channel operation failed"
            ) from None
        return _inbox_from_row(row) if row is not None else None

    def get_outbox_record(self, delivery_id: UUID) -> OutboxRecord | None:
        try:
            with (
                self._connect() as connection,
                connection.transaction(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    f"""
                    SELECT delivery_id, idempotency_key, case_id, binding_ref,
                           source_event_id, source_command_id, source_case_revision,
                           source_strategy_id, source_strategy_revision,
                           source_event_cursor, body, body_hash, state,
                           provider_message_id, attempt_count, last_failure_category
                    FROM {_OUTBOX_TABLE}
                    WHERE delivery_id = %s
                    """,
                    (delivery_id,),
                )
                row = cursor.fetchone()
        except psycopg.Error:
            raise StorageUnavailableError(
                "PostgreSQL channel operation failed"
            ) from None
        return _outbox_from_row(row) if row is not None else None

    def get_delivery_receipt(self, delivery_id: UUID) -> DeliveryReceiptRecord | None:
        try:
            with (
                self._connect() as connection,
                connection.transaction(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    f"""
                    SELECT delivery_id, provider_message_id, observation_state,
                           artifact_hash, observed_at, captured_at, evidence_id
                    FROM {_DELIVERY_TABLE}
                    WHERE delivery_id = %s
                    ORDER BY observed_at DESC
                    LIMIT 1
                    """,
                    (delivery_id,),
                )
                row = cursor.fetchone()
        except psycopg.Error:
            raise StorageUnavailableError(
                "PostgreSQL channel operation failed"
            ) from None
        return _delivery_from_row(row) if row is not None else None

    def record_delivery_observation(
        self,
        delivery_id: UUID,
        *,
        idempotency_key: str,
        state: str,
        provider_message_id: str | None,
        failure_category: str | None = None,
    ) -> OutboxRecord:
        """Persist an adapter observation without changing Case revision."""

        if state not in {
            "accepted",
            "failed_retryable",
            "failed_terminal",
            "unknown",
        }:
            raise ValueError("unsupported delivery observation state")
        try:
            with (
                self._connect() as connection,
                connection.transaction(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    f"""
                    SELECT delivery_id, idempotency_key, case_id, binding_ref,
                           source_event_id, source_command_id, source_case_revision,
                           source_strategy_id, source_strategy_revision,
                           source_event_cursor, body, body_hash, state,
                           provider_message_id, attempt_count, last_failure_category
                    FROM {_OUTBOX_TABLE}
                    WHERE delivery_id = %s AND idempotency_key = %s
                    FOR UPDATE
                    """,
                    (delivery_id, idempotency_key),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise CaseNotFoundError("outbox delivery not found")
                prior = _outbox_from_row(existing)
                if (
                    prior.provider_message_id is not None
                    and provider_message_id is not None
                    and prior.provider_message_id != provider_message_id
                ):
                    raise CaseConflictError("delivery provider message changed")
                if not _delivery_observation_is_monotonic(prior.state, state):
                    raise CaseConflictError("delivery observation regressed")
                if prior.state in {"delivered", "bounced"}:
                    return prior
                cursor.execute(
                    f"""
                    UPDATE {_OUTBOX_TABLE}
                    SET state = %s,
                        provider_message_id = COALESCE(%s, provider_message_id),
                        attempt_count = attempt_count + 1,
                        last_failure_category = %s,
                        updated_at = now()
                    WHERE delivery_id = %s AND idempotency_key = %s
                    """,
                    (
                        state,
                        provider_message_id,
                        failure_category,
                        delivery_id,
                        idempotency_key,
                    ),
                )
                if cursor.rowcount != 1:
                    raise CaseNotFoundError("outbox delivery not found")
                cursor.execute(
                    f"""
                    SELECT delivery_id, idempotency_key, case_id, binding_ref,
                           source_event_id, source_command_id, source_case_revision,
                           source_strategy_id, source_strategy_revision,
                           source_event_cursor, body, body_hash, state,
                           provider_message_id, attempt_count, last_failure_category
                    FROM {_OUTBOX_TABLE}
                    WHERE delivery_id = %s
                    """,
                    (delivery_id,),
                )
                row = cursor.fetchone()
        except (CaseNotFoundError, CaseConflictError):
            raise
        except psycopg.Error:
            raise StorageUnavailableError(
                "PostgreSQL channel operation failed"
            ) from None
        if row is None:
            raise CaseNotFoundError("outbox delivery not found")
        return _outbox_from_row(row)

    def replace_with_channel_outbox(
        self,
        case_id: UUID,
        *,
        expected_revision: int,
        state: CaseRuntimeState,
        outbox: OutboxRecord,
        inbox_event_id: UUID,
    ) -> CaseRuntimeState:
        """CAS the Case, insert its first outbox row, and apply inbox together."""

        if outbox.case_id != case_id or state.snapshot.case.case_id != case_id:
            raise CaseConflictError("channel Case binding does not match")
        payload = self._encode_state(state)
        try:
            with (
                self._connect() as connection,
                connection.transaction(),
                connection.cursor() as cursor,
            ):
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
                if cursor.rowcount != 1:
                    raise CaseConflictError("case snapshot revision is stale")
                cursor.execute(
                    f"""
                    INSERT INTO {_OUTBOX_TABLE}
                        (delivery_id, idempotency_key, case_id, binding_ref,
                         source_event_id, source_command_id, source_case_revision,
                         source_strategy_id, source_strategy_revision,
                         source_event_cursor, body, body_hash, state,
                         provider_message_id, attempt_count, last_failure_category)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s)
                    """,
                    (
                        outbox.delivery_id,
                        outbox.idempotency_key,
                        outbox.case_id,
                        outbox.binding_ref,
                        outbox.source_event_id,
                        outbox.source_command_id,
                        outbox.source_case_revision,
                        outbox.source_strategy_id,
                        outbox.source_strategy_revision,
                        outbox.source_event_cursor,
                        outbox.body,
                        outbox.body_hash,
                        outbox.state,
                        outbox.provider_message_id,
                        outbox.attempt_count,
                        outbox.last_failure_category,
                    ),
                )
                cursor.execute(
                    f"""
                    UPDATE {_INBOX_TABLE}
                    SET processing_state = 'applied'
                    WHERE channel_kind = %s AND event_id = %s
                      AND case_id = %s AND processing_state = 'reserved'
                    """,
                    (CHANNEL_KIND, inbox_event_id, case_id),
                )
                if cursor.rowcount != 1:
                    raise CaseConflictError("channel inbox reservation is not pending")
        except (CaseConflictError, CaseNotFoundError):
            raise
        except psycopg.errors.UniqueViolation:
            raise CaseConflictError("channel outbox already exists") from None
        except psycopg.Error:
            raise StorageUnavailableError(
                "PostgreSQL channel operation failed"
            ) from None
        return state

    def replace_with_delivery_receipt(
        self,
        case_id: UUID,
        *,
        expected_revision: int,
        state: CaseRuntimeState,
        inbox_event_id: UUID,
        receipt: DeliveryReceiptRecord,
        outbox_state: str,
    ) -> CaseRuntimeState:
        """CAS Case, append receipt, update Outbox, and mark Inbox atomically."""

        if state.snapshot.case.case_id != case_id:
            raise CaseConflictError("delivery Case binding does not match")
        payload = self._encode_state(state)
        try:
            with (
                self._connect() as connection,
                connection.transaction(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    f"""
                    SELECT delivery_id, idempotency_key, case_id, binding_ref,
                           source_event_id, source_command_id, source_case_revision,
                           source_strategy_id, source_strategy_revision,
                           source_event_cursor, body, body_hash, state,
                           provider_message_id, attempt_count, last_failure_category
                    FROM {_OUTBOX_TABLE}
                    WHERE delivery_id = %s AND case_id = %s
                    FOR UPDATE
                    """,
                    (receipt.delivery_id, case_id),
                )
                outbox_row = cursor.fetchone()
                if outbox_row is None:
                    raise CaseNotFoundError("outbox delivery not found")
                prior_outbox = _outbox_from_row(outbox_row)
                if prior_outbox.provider_message_id != receipt.provider_message_id:
                    raise CaseConflictError("delivery provider message changed")
                if not _delivery_observation_is_monotonic(
                    prior_outbox.state, outbox_state
                ):
                    raise CaseConflictError("delivery observation regressed")
                cursor.execute(
                    f"""
                    SELECT delivery_id, provider_message_id, observation_state,
                           artifact_hash, observed_at, captured_at, evidence_id
                    FROM {_DELIVERY_TABLE}
                    WHERE delivery_id = %s
                    FOR UPDATE
                    """,
                    (receipt.delivery_id,),
                )
                prior_receipt_row = cursor.fetchone()
                prior_receipt = (
                    _delivery_from_row(prior_receipt_row)
                    if prior_receipt_row is not None
                    else None
                )
                if prior_receipt is not None and prior_receipt != receipt:
                    raise CaseConflictError("delivery observation regressed")
                if prior_receipt is None and prior_outbox.state in {
                    "delivered",
                    "bounced",
                }:
                    raise CaseConflictError("delivery observation regressed")
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
                if cursor.rowcount != 1:
                    raise CaseConflictError("case snapshot revision is stale")
                cursor.execute(
                    f"""
                    UPDATE {_OUTBOX_TABLE}
                    SET state = %s, provider_message_id = %s,
                        updated_at = now()
                    WHERE delivery_id = %s AND case_id = %s
                    """,
                    (
                        outbox_state,
                        receipt.provider_message_id,
                        receipt.delivery_id,
                        case_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise CaseNotFoundError("outbox delivery not found")
                if prior_receipt is None:
                    cursor.execute(
                        f"""
                        INSERT INTO {_DELIVERY_TABLE}
                            (delivery_id, provider_message_id, observation_state,
                             artifact_hash, observed_at, captured_at, evidence_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            receipt.delivery_id,
                            receipt.provider_message_id,
                            receipt.observation_state,
                            receipt.artifact_hash,
                            receipt.observed_at,
                            receipt.captured_at,
                            receipt.evidence_id,
                        ),
                    )
                cursor.execute(
                    f"""
                    UPDATE {_INBOX_TABLE}
                    SET processing_state = 'applied'
                    WHERE channel_kind = %s AND event_id = %s
                      AND case_id = %s AND processing_state = 'reserved'
                    """,
                    (CHANNEL_KIND, inbox_event_id, case_id),
                )
                if cursor.rowcount != 1:
                    raise CaseConflictError("channel inbox reservation is not pending")
        except (CaseConflictError, CaseNotFoundError):
            raise
        except psycopg.errors.UniqueViolation:
            raise CaseConflictError(
                "channel delivery observation already exists"
            ) from None
        except psycopg.Error:
            raise StorageUnavailableError(
                "PostgreSQL channel operation failed"
            ) from None
        return state

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
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_BINDINGS_TABLE} (
                        binding_ref text PRIMARY KEY,
                        channel_kind text NOT NULL,
                        case_id uuid NOT NULL UNIQUE,
                        local_ref text NOT NULL,
                        remote_ref text NOT NULL,
                        allowed_directions jsonb NOT NULL,
                        active boolean NOT NULL,
                        created_at timestamptz NOT NULL
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_INBOX_TABLE} (
                        channel_kind text NOT NULL,
                        event_id uuid NOT NULL,
                        payload_hash text NOT NULL,
                        binding_ref text NOT NULL
                            REFERENCES {_BINDINGS_TABLE}(binding_ref),
                        case_id uuid NOT NULL,
                        command_id uuid NOT NULL UNIQUE,
                        first_seen_at timestamptz NOT NULL,
                        event_kind text NOT NULL,
                        processing_state text NOT NULL,
                        result jsonb,
                        PRIMARY KEY (channel_kind, event_id)
                    )
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE {_INBOX_TABLE}
                    ADD COLUMN IF NOT EXISTS content text
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_OUTBOX_TABLE} (
                        delivery_id uuid PRIMARY KEY,
                        idempotency_key text NOT NULL UNIQUE,
                        case_id uuid NOT NULL,
                        binding_ref text NOT NULL
                            REFERENCES {_BINDINGS_TABLE}(binding_ref),
                        source_event_id uuid NOT NULL,
                        source_command_id uuid NOT NULL,
                        source_case_revision bigint NOT NULL,
                        source_strategy_id uuid,
                        source_strategy_revision bigint NOT NULL,
                        source_event_cursor bigint NOT NULL,
                        body text NOT NULL,
                        body_hash text NOT NULL,
                        state text NOT NULL,
                        provider_message_id text,
                        attempt_count bigint NOT NULL DEFAULT 0,
                        last_failure_category text,
                        created_at timestamptz NOT NULL DEFAULT now(),
                        updated_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_DELIVERY_TABLE} (
                        delivery_id uuid NOT NULL
                            REFERENCES {_OUTBOX_TABLE}(delivery_id),
                        provider_message_id text NOT NULL,
                        observation_state text NOT NULL,
                        artifact_hash text NOT NULL,
                        observed_at timestamptz NOT NULL,
                        captured_at timestamptz NOT NULL,
                        evidence_id uuid NOT NULL,
                        PRIMARY KEY (
                            delivery_id, provider_message_id, observation_state
                        )
                        )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE UNIQUE INDEX IF NOT EXISTS
                        {_DELIVERY_TABLE}_delivery_id_idx
                    ON {_DELIVERY_TABLE} (delivery_id)
                    """
                )
        except psycopg.Error:
            raise StorageUnavailableError(
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
                transitions=state.transitions,
                last_fast_decision=state.last_fast_decision,
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
            transitions=envelope.transitions,
            last_fast_decision=envelope.last_fast_decision,
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


def _binding_from_row(row: tuple[Any, ...]) -> ChannelBindingRecord:
    directions = row[5]
    if not isinstance(directions, list) or not all(
        isinstance(item, str) for item in directions
    ):
        raise RuntimeError("stored channel binding directions are invalid")
    return ChannelBindingRecord(
        channel_kind=str(row[0]),
        binding_ref=str(row[1]),
        case_id=row[2],
        local_ref=str(row[3]),
        remote_ref=str(row[4]),
        allowed_directions=tuple(directions),
        active=bool(row[6]),
        created_at=row[7],
    )


def _inbox_from_row(
    row: tuple[Any, ...], *, deduplicated: bool = False
) -> InboxReceiptRecord:
    return InboxReceiptRecord(
        channel_kind=str(row[0]),
        event_id=row[1],
        payload_hash=str(row[2]),
        binding_ref=str(row[3]),
        case_id=row[4],
        command_id=row[5],
        first_seen_at=row[6],
        event_kind=str(row[7]),
        processing_state=str(row[8]),
        content=row[9],
        deduplicated=deduplicated,
    )


def _outbox_from_row(row: tuple[Any, ...]) -> OutboxRecord:
    return OutboxRecord(
        delivery_id=row[0],
        idempotency_key=str(row[1]),
        case_id=row[2],
        binding_ref=str(row[3]),
        source_event_id=row[4],
        source_command_id=row[5],
        source_case_revision=int(row[6]),
        source_strategy_id=row[7],
        source_strategy_revision=int(row[8]),
        source_event_cursor=int(row[9]),
        body=str(row[10]),
        body_hash=str(row[11]),
        state=str(row[12]),
        provider_message_id=row[13],
        attempt_count=int(row[14]),
        last_failure_category=row[15],
    )


def _delivery_from_row(row: tuple[Any, ...]) -> DeliveryReceiptRecord:
    return DeliveryReceiptRecord(
        delivery_id=row[0],
        provider_message_id=str(row[1]),
        observation_state=str(row[2]),
        artifact_hash=str(row[3]),
        observed_at=row[4],
        captured_at=row[5],
        evidence_id=row[6],
    )


def _delivery_observation_is_monotonic(current: str, incoming: str) -> bool:
    if current == incoming:
        return True
    if incoming in {"delivered", "bounced"}:
        return current not in {"delivered", "bounced"}
    if current in {"delivered", "bounced", "accepted"}:
        return False
    if current == "unknown":
        return incoming == "accepted"
    if current == "failed_terminal":
        return False
    if current == "failed_retryable":
        return incoming in {"accepted", "failed_terminal"}
    return current == "pending" and incoming in {
        "accepted",
        "failed_retryable",
        "failed_terminal",
        "unknown",
    }


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
