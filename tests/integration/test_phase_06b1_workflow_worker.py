from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from proxyloop_case_runtime import SCRIPTED_CASE_ID, CaseCommandType, OutboxRecord
from proxyloop_connectors import (
    BINDING_REF,
    DeliveryAttempt,
    DeliveryObservation,
    FaultInjectingLocalMailboxAdapter,
    LocalMailboxAdapter,
    UnknownDelivery,
)
from proxyloop_workflow_worker import (
    CaseCommandActivityAdapter,
    CaseCommandRequest,
    ChannelDeliveryRequest,
)
from temporalio.exceptions import ApplicationError

BASE_TIME = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
DELIVERY_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
COMMAND_ID = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
CALLBACK_EVENT_ID = UUID("11111111-1111-4111-8111-111111111111")


class _OutboxRepository:
    def __init__(self, record: OutboxRecord) -> None:
        self.record = record
        self.observations: list[dict[str, object]] = []

    def get_outbox_record(self, delivery_id: UUID) -> OutboxRecord | None:
        return self.record if delivery_id == self.record.delivery_id else None

    def record_delivery_observation(
        self,
        delivery_id: UUID,
        *,
        idempotency_key: str,
        state: str,
        provider_message_id: str | None,
        failure_category: str | None = None,
    ) -> OutboxRecord:
        self.observations.append(
            {
                "delivery_id": delivery_id,
                "idempotency_key": idempotency_key,
                "state": state,
                "provider_message_id": provider_message_id,
                "failure_category": failure_category,
            }
        )
        self.record = replace(
            self.record,
            state=state,
            provider_message_id=provider_message_id,
            attempt_count=self.record.attempt_count + 1,
        )
        return self.record


class _Runtime:
    def __init__(self, repository: _OutboxRepository) -> None:
        self.repository = repository


class _CountingMailboxAdapter(LocalMailboxAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.send_calls = 0
        self.lookup_calls = 0

    def send(self, attempt: DeliveryAttempt) -> DeliveryObservation:
        self.send_calls += 1
        return super().send(attempt)

    def lookup(self, attempt: DeliveryAttempt) -> DeliveryObservation | UnknownDelivery:
        self.lookup_calls += 1
        return super().lookup(attempt)


def test_channel_request_is_compact_and_fault_retry_recovers() -> None:
    body = "I am checking that and will update you."
    record = OutboxRecord(
        delivery_id=DELIVERY_ID,
        idempotency_key=str(DELIVERY_ID),
        case_id=SCRIPTED_CASE_ID,
        binding_ref=BINDING_REF,
        source_event_id=CALLBACK_EVENT_ID,
        source_command_id=COMMAND_ID,
        source_case_revision=3,
        source_strategy_id=None,
        source_strategy_revision=1,
        source_event_cursor=4,
        body=body,
        body_hash=hashlib.sha256(body.encode()).hexdigest(),
    )
    repository = _OutboxRepository(record)
    adapter = CaseCommandActivityAdapter(
        _Runtime(repository),
        local_mailbox=FaultInjectingLocalMailboxAdapter(lose_response_after_accept=1),
    )
    result = adapter.dispatch_channel_delivery(
        ChannelDeliveryRequest(
            case_id=SCRIPTED_CASE_ID,
            delivery_id=DELIVERY_ID,
            idempotency_key=str(DELIVERY_ID),
        )
    )
    assert result.state == "accepted"
    assert len(repository.observations) == 1
    assert repository.observations[0]["provider_message_id"]


def test_replacement_activity_attempt_looks_up_before_sending() -> None:
    body = "I am checking that and will update you."
    record = OutboxRecord(
        delivery_id=DELIVERY_ID,
        idempotency_key=str(DELIVERY_ID),
        case_id=SCRIPTED_CASE_ID,
        binding_ref=BINDING_REF,
        source_event_id=CALLBACK_EVENT_ID,
        source_command_id=COMMAND_ID,
        source_case_revision=3,
        source_strategy_id=None,
        source_strategy_revision=1,
        source_event_cursor=4,
        body=body,
        body_hash=hashlib.sha256(body.encode()).hexdigest(),
    )
    repository = _OutboxRepository(record)
    first_adapter = FaultInjectingLocalMailboxAdapter(lose_response_after_accept=1)
    first = CaseCommandActivityAdapter(_Runtime(repository), first_adapter)
    request = ChannelDeliveryRequest(
        case_id=SCRIPTED_CASE_ID,
        delivery_id=DELIVERY_ID,
        idempotency_key=str(DELIVERY_ID),
    )
    first_result = first.dispatch_channel_delivery(request)

    replacement_adapter = _CountingMailboxAdapter()
    replacement = CaseCommandActivityAdapter(_Runtime(repository), replacement_adapter)
    replacement_result = replacement.dispatch_channel_delivery(
        request, activity_attempt=2
    )
    assert replacement_adapter.lookup_calls == 0
    assert replacement_adapter.send_calls == 0
    assert replacement_result.provider_message_id == first_result.provider_message_id


def test_replacement_activity_resends_when_adapter_accepted_but_db_is_pending() -> None:
    body = "I am checking that and will update you."
    record = OutboxRecord(
        delivery_id=DELIVERY_ID,
        idempotency_key=str(DELIVERY_ID),
        case_id=SCRIPTED_CASE_ID,
        binding_ref=BINDING_REF,
        source_event_id=CALLBACK_EVENT_ID,
        source_command_id=COMMAND_ID,
        source_case_revision=3,
        source_strategy_id=None,
        source_strategy_revision=1,
        source_event_cursor=4,
        body=body,
        body_hash=hashlib.sha256(body.encode()).hexdigest(),
    )
    repository = _OutboxRepository(record)
    request = ChannelDeliveryRequest(
        case_id=SCRIPTED_CASE_ID,
        delivery_id=DELIVERY_ID,
        idempotency_key=str(DELIVERY_ID),
    )
    attempt = DeliveryAttempt(
        delivery_id=record.delivery_id,
        idempotency_key=record.idempotency_key,
        binding_ref=record.binding_ref,
        body=record.body,
        body_hash=record.body_hash,
    )
    first_mailbox = FaultInjectingLocalMailboxAdapter(lose_response_after_accept=1)
    with pytest.raises(TimeoutError):
        first_mailbox.send(attempt)
    first_observation = first_mailbox.lookup(attempt)
    assert isinstance(first_observation, DeliveryObservation)

    replacement_mailbox = _CountingMailboxAdapter()
    replacement = CaseCommandActivityAdapter(_Runtime(repository), replacement_mailbox)
    result = replacement.dispatch_channel_delivery(request, activity_attempt=2)
    assert replacement_mailbox.lookup_calls == 1
    assert replacement_mailbox.send_calls == 1
    assert result.provider_message_id == first_observation.provider_message_id


def test_terminal_outbox_without_provider_id_fails_closed() -> None:
    body = "I am checking that and will update you."
    record = OutboxRecord(
        delivery_id=DELIVERY_ID,
        idempotency_key=str(DELIVERY_ID),
        case_id=SCRIPTED_CASE_ID,
        binding_ref=BINDING_REF,
        source_event_id=CALLBACK_EVENT_ID,
        source_command_id=COMMAND_ID,
        source_case_revision=3,
        source_strategy_id=None,
        source_strategy_revision=1,
        source_event_cursor=4,
        body=body,
        body_hash=hashlib.sha256(body.encode()).hexdigest(),
        state="delivered",
    )
    repository = _OutboxRepository(record)
    adapter = CaseCommandActivityAdapter(_Runtime(repository))
    request = ChannelDeliveryRequest(
        case_id=SCRIPTED_CASE_ID,
        delivery_id=DELIVERY_ID,
        idempotency_key=str(DELIVERY_ID),
    )
    with pytest.raises(ApplicationError) as raised:
        adapter.dispatch_channel_delivery(request)
    assert raised.value.type == "channel_conflict"


def test_unknown_stored_outbox_state_fails_closed_without_adapter_call() -> None:
    body = "I am checking that and will update you."
    record = OutboxRecord(
        delivery_id=DELIVERY_ID,
        idempotency_key=str(DELIVERY_ID),
        case_id=SCRIPTED_CASE_ID,
        binding_ref=BINDING_REF,
        source_event_id=CALLBACK_EVENT_ID,
        source_command_id=COMMAND_ID,
        source_case_revision=3,
        source_strategy_id=None,
        source_strategy_revision=1,
        source_event_cursor=4,
        body=body,
        body_hash=hashlib.sha256(body.encode()).hexdigest(),
        state="corrupt",
    )
    repository = _OutboxRepository(record)
    mailbox = _CountingMailboxAdapter()
    adapter = CaseCommandActivityAdapter(_Runtime(repository), mailbox)
    request = ChannelDeliveryRequest(
        case_id=SCRIPTED_CASE_ID,
        delivery_id=DELIVERY_ID,
        idempotency_key=str(DELIVERY_ID),
    )

    with pytest.raises(ApplicationError) as raised:
        adapter.dispatch_channel_delivery(request)

    assert raised.value.type == "channel_conflict"
    assert mailbox.lookup_calls == 0
    assert mailbox.send_calls == 0
    assert repository.observations == []


def test_known_adapter_retry_looks_up_without_sending() -> None:
    body = "I am checking that and will update you."
    record = OutboxRecord(
        delivery_id=DELIVERY_ID,
        idempotency_key=str(DELIVERY_ID),
        case_id=SCRIPTED_CASE_ID,
        binding_ref=BINDING_REF,
        source_event_id=CALLBACK_EVENT_ID,
        source_command_id=COMMAND_ID,
        source_case_revision=3,
        source_strategy_id=None,
        source_strategy_revision=1,
        source_event_cursor=4,
        body=body,
        body_hash=hashlib.sha256(body.encode()).hexdigest(),
    )
    repository = _OutboxRepository(record)
    mailbox = _CountingMailboxAdapter()
    adapter = CaseCommandActivityAdapter(_Runtime(repository), mailbox)
    request = ChannelDeliveryRequest(
        case_id=SCRIPTED_CASE_ID,
        delivery_id=DELIVERY_ID,
        idempotency_key=str(DELIVERY_ID),
    )
    attempt = DeliveryAttempt(
        delivery_id=record.delivery_id,
        idempotency_key=record.idempotency_key,
        binding_ref=record.binding_ref,
        body=record.body,
        body_hash=record.body_hash,
    )
    first = mailbox.send(attempt)
    retry = adapter.dispatch_channel_delivery(request, activity_attempt=2)
    assert mailbox.send_calls == 1
    assert mailbox.lookup_calls == 1
    assert retry.provider_message_id == first.provider_message_id


def test_fail_before_accept_then_replacement_retry_sends_once() -> None:
    body = "I am checking that and will update you."
    record = OutboxRecord(
        delivery_id=DELIVERY_ID,
        idempotency_key=str(DELIVERY_ID),
        case_id=SCRIPTED_CASE_ID,
        binding_ref=BINDING_REF,
        source_event_id=CALLBACK_EVENT_ID,
        source_command_id=COMMAND_ID,
        source_case_revision=3,
        source_strategy_id=None,
        source_strategy_revision=1,
        source_event_cursor=4,
        body=body,
        body_hash=hashlib.sha256(body.encode()).hexdigest(),
    )
    repository = _OutboxRepository(record)
    request = ChannelDeliveryRequest(
        case_id=SCRIPTED_CASE_ID,
        delivery_id=DELIVERY_ID,
        idempotency_key=str(DELIVERY_ID),
    )
    first = CaseCommandActivityAdapter(
        _Runtime(repository),
        FaultInjectingLocalMailboxAdapter(fail_before_accept=1),
    )
    with pytest.raises(ApplicationError) as raised:
        first.dispatch_channel_delivery(request)
    assert raised.value.type == "channel_dependency_unavailable"

    replacement_mailbox = _CountingMailboxAdapter()
    replacement = CaseCommandActivityAdapter(_Runtime(repository), replacement_mailbox)
    result = replacement.dispatch_channel_delivery(request, activity_attempt=2)
    assert isinstance(result, OutboxRecord)
    assert replacement_mailbox.lookup_calls == 1
    assert replacement_mailbox.send_calls == 1
    assert result.state == "accepted"
    assert result.provider_message_id


def test_channel_command_request_round_trips_to_strict_case_command() -> None:
    request = CaseCommandRequest(
        schema_version="phase-06b1-v1",
        command_id=COMMAND_ID,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.INGEST_CHANNEL_EVENT,
        expected_revision=2,
        channel_occurred_at=BASE_TIME,
        channel_kind="local_mailbox",
        binding_ref=BINDING_REF,
        event_id=CALLBACK_EVENT_ID,
        content_hash="a" * 64,
        payload_hash="b" * 64,
    )
    command = request.to_command(BASE_TIME)
    assert command.schema_version == "phase-06b1-v1"
    assert command.command_type is CaseCommandType.INGEST_CHANNEL_EVENT
    assert command.occurred_at == BASE_TIME
