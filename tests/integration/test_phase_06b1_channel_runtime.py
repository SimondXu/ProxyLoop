from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from proxyloop_api import create_app
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseCommand,
    CaseCommandType,
    CaseConflictError,
    CaseRuntimeState,
    CaseTransitionRef,
    ChannelBindingRecord,
    ChannelConflictError,
    ChannelDependencyUnavailableError,
    DeliveryReceiptRecord,
    InboxReceiptRecord,
    InMemoryCaseRepository,
    OutboxRecord,
    PostgresCaseRepository,
    ThinAgentRuntime,
)
from proxyloop_connectors import (
    BINDING_REF,
    CHANNEL_KIND,
    DeliveryAttempt,
    DeliveryObservation,
    LocalMailboxAdapter,
    LocalMailboxEventKind,
    UnknownDelivery,
    VerifiedLocalMailboxEvent,
    build_fixture_headers,
)
from proxyloop_contracts import Money
from proxyloop_workflow_worker import (
    CaseCommandActivityAdapter,
    CaseCommandRequest,
    ChannelDeliveryRequest,
    TemporalCaseClient,
    TemporalDispatchError,
    TemporalSettings,
    activity_for_adapter,
    channel_activity_for_adapter,
)
from proxyloop_workflow_worker.client import _failure_category
from proxyloop_workflow_worker.workflow import CaseWorkflow
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from test_phase_06b1_temporal import _database_url, _truncate

BASE_TIME = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
CREATE_COMMAND_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class _ChannelRepository(InMemoryCaseRepository):
    """Small in-memory channel seam for Runtime contract tests."""

    def __init__(self) -> None:
        super().__init__()
        self.binding: ChannelBindingRecord | None = None
        self.inbox: dict[UUID, InboxReceiptRecord] = {}
        self.outbox: dict[UUID, OutboxRecord] = {}
        self.receipts: list[DeliveryReceiptRecord] = []

    def create(self, state: CaseRuntimeState) -> CaseRuntimeState:
        created = super().create(state)
        self.binding = ChannelBindingRecord(
            channel_kind=CHANNEL_KIND,
            binding_ref=BINDING_REF,
            case_id=state.snapshot.case.case_id,
            local_ref="fictional-provider-local-mailbox",
            remote_ref=f"case/{state.snapshot.case.case_id}",
            allowed_directions=("inbound", "outbound"),
            active=True,
            created_at=state.snapshot.case.created_at,
        )
        return created

    def reserve_channel_event(
        self,
        event: VerifiedLocalMailboxEvent,
        *,
        received_at: datetime,
    ) -> InboxReceiptRecord:
        prior = self.inbox.get(event.event_id)
        if prior is not None:
            if prior.payload_hash != event.raw_payload_hash:
                raise ChannelConflictError("channel_replay_mismatch")
            return replace(prior, deduplicated=True)
        if (
            event.fixture_timestamp is None
            or abs(received_at - event.fixture_timestamp) > timedelta(minutes=5)
            or abs(received_at - event.occurred_at) > timedelta(minutes=5)
        ):
            raise ChannelConflictError("stale_unknown_event")
        assert self.binding is not None
        receipt = InboxReceiptRecord(
            channel_kind=CHANNEL_KIND,
            event_id=event.event_id,
            payload_hash=event.raw_payload_hash,
            binding_ref=BINDING_REF,
            case_id=self.binding.case_id,
            command_id=uuid4(),
            first_seen_at=received_at,
            event_kind=event.kind.value,
            processing_state="reserved",
            content=event.content,
        )
        self.inbox[event.event_id] = receipt
        return receipt

    def get_inbox_receipt(self, event_id: UUID) -> InboxReceiptRecord | None:
        return self.inbox.get(event_id)

    def get_outbox_record(self, delivery_id: UUID) -> OutboxRecord | None:
        return self.outbox.get(delivery_id)

    def record_delivery_observation(
        self,
        delivery_id: UUID,
        *,
        idempotency_key: str,
        state: str,
        provider_message_id: str | None,
        failure_category: str | None = None,
    ) -> OutboxRecord:
        prior = self.outbox[delivery_id]
        assert prior.idempotency_key == idempotency_key
        updated = replace(
            prior,
            state=state,
            provider_message_id=provider_message_id or prior.provider_message_id,
            attempt_count=prior.attempt_count + 1,
            last_failure_category=failure_category,
        )
        self.outbox[delivery_id] = updated
        return updated

    def get_delivery_receipt(self, delivery_id: UUID) -> DeliveryReceiptRecord | None:
        for receipt in reversed(self.receipts):
            if receipt.delivery_id == delivery_id:
                return receipt
        return None

    def replace_with_channel_outbox(
        self,
        case_id: UUID,
        *,
        expected_revision: int,
        state: CaseRuntimeState,
        outbox: OutboxRecord,
        inbox_event_id: UUID,
    ) -> CaseRuntimeState:
        updated = super().replace(
            case_id,
            expected_revision=expected_revision,
            state=state,
        )
        self.outbox[outbox.delivery_id] = outbox
        prior = self.inbox[inbox_event_id]
        self.inbox[inbox_event_id] = InboxReceiptRecord(
            channel_kind=prior.channel_kind,
            event_id=prior.event_id,
            payload_hash=prior.payload_hash,
            binding_ref=prior.binding_ref,
            case_id=prior.case_id,
            command_id=prior.command_id,
            first_seen_at=prior.first_seen_at,
            event_kind=prior.event_kind,
            processing_state="applied",
            content=prior.content,
        )
        return updated

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
        updated = super().replace(
            case_id,
            expected_revision=expected_revision,
            state=state,
        )
        prior = self.outbox[receipt.delivery_id]
        self.outbox[receipt.delivery_id] = replace(
            prior,
            state=outbox_state,
            provider_message_id=receipt.provider_message_id,
        )
        prior_receipt = self.get_delivery_receipt(receipt.delivery_id)
        if prior_receipt is not None and prior_receipt != receipt:
            raise CaseConflictError("delivery observation regressed")
        if prior_receipt is None:
            self.receipts.append(receipt)
        prior_inbox = self.inbox[inbox_event_id]
        self.inbox[inbox_event_id] = InboxReceiptRecord(
            channel_kind=prior_inbox.channel_kind,
            event_id=prior_inbox.event_id,
            payload_hash=prior_inbox.payload_hash,
            binding_ref=prior_inbox.binding_ref,
            case_id=prior_inbox.case_id,
            command_id=prior_inbox.command_id,
            first_seen_at=prior_inbox.first_seen_at,
            event_kind=prior_inbox.event_kind,
            processing_state="applied",
            content=prior_inbox.content,
        )
        return updated


def _create_command() -> CaseCommand:
    return CaseCommand(
        command_id=CREATE_COMMAND_ID,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.CREATE_CASE,
        occurred_at=BASE_TIME,
        current_monthly_total=Money(amount_minor=9200, currency="USD"),
        target_monthly_total=Money(amount_minor=7500, currency="USD"),
        mobile_hotspot_required=True,
        device_financing_change_forbidden=True,
    )


def _message_event(
    event_id: UUID,
    *,
    kind: LocalMailboxEventKind = LocalMailboxEventKind.PROVIDER_MESSAGE,
) -> VerifiedLocalMailboxEvent:
    content = "Synthetic Provider message."
    raw_hash = hashlib.sha256(content.encode()).hexdigest()
    return VerifiedLocalMailboxEvent(
        event_id=event_id,
        binding_ref=BINDING_REF,
        occurred_at=BASE_TIME,
        kind=kind,
        raw_payload_hash=raw_hash,
        content=content,
        fixture_timestamp=BASE_TIME,
    )


def _is_uuid4(value: str) -> bool:
    try:
        parsed = UUID(value)
    except ValueError:
        return False
    return parsed.version == 4 and str(parsed) == value


def test_channel_ingest_is_atomic_and_deduplicated() -> None:
    repository = _ChannelRepository()
    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME)
    runtime.apply_command(_create_command())
    event = _message_event(uuid4())
    inbox = repository.reserve_channel_event(event, received_at=BASE_TIME)
    command = CaseCommand(
        schema_version="phase-06b1-v1",
        command_id=inbox.command_id,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.INGEST_CHANNEL_EVENT,
        occurred_at=event.occurred_at,
        expected_revision=2,
        channel_kind=CHANNEL_KIND,
        binding_ref=BINDING_REF,
        event_id=event.event_id,
        content_hash=hashlib.sha256(event.content.encode()).hexdigest(),
        payload_hash=event.raw_payload_hash,
    )

    applied = runtime.apply_command(command)
    duplicate = runtime.apply_command(command)
    assert applied.after_revision == 3
    assert applied.delivery_id is not None
    assert duplicate.deduplicated is True
    outbox = repository.get_outbox_record(applied.delivery_id)
    assert outbox is not None
    assert outbox.source_event_id == event.event_id
    assert repository.get_inbox_receipt(event.event_id).processing_state == "applied"


def test_unknown_event_requires_fresh_fixture_timestamp_and_event_time() -> None:
    repository = _ChannelRepository()
    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME)
    runtime.apply_command(_create_command())
    stale_header = replace(
        _message_event(uuid4()),
        fixture_timestamp=BASE_TIME - timedelta(minutes=6),
    )
    with pytest.raises(CaseConflictError, match="stale_unknown_event"):
        repository.reserve_channel_event(stale_header, received_at=BASE_TIME)
    assert repository.inbox == {}


def test_local_mailbox_api_fails_closed_without_temporal_mode() -> None:
    event_payload = (
        b'{"schema_version":"local-mailbox-v1",'
        b'"event_id":"11111111-1111-4111-8111-111111111111",'
        b'"binding_ref":"fictional-provider-local-mailbox",'
        b'"occurred_at":"2026-08-26T12:00:00Z",'
        b'"kind":"provider_message",'
        b'"content":"Synthetic Provider message."}'
    )
    headers = build_fixture_headers(event_payload)

    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(ThinAgentRuntime())),
            base_url="http://test",
        ) as client:
            return await client.post(
                "/channels/local_mailbox/events",
                content=event_payload,
                headers=headers,
            )

    response = asyncio.run(request())
    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "channel_dependency_unavailable",
        "message": "channel dependency unavailable",
    }


def test_local_mailbox_api_marks_known_applied_duplicate() -> None:
    repository = _ChannelRepository()
    now = datetime.now(UTC)
    runtime = ThinAgentRuntime(repository, clock=lambda: now)
    runtime.apply_command(_create_command().model_copy(update={"occurred_at": now}))

    class _Temporal:
        async def apply_command(self, request: CaseCommandRequest) -> object:
            return runtime.apply_command(request.to_command(BASE_TIME))

        async def check_readiness(self) -> object:
            return object()

    event_id = uuid4()
    payload = (
        '{"schema_version":"local-mailbox-v1",'
        f'"event_id":"{event_id}",'
        '"binding_ref":"fictional-provider-local-mailbox",'
        f'"occurred_at":"{now.isoformat().replace("+00:00", "Z")}",'
        '"kind":"provider_message",'
        '"content":"Synthetic Provider message."}'
    ).encode()
    headers = build_fixture_headers(payload)

    async def request() -> tuple[httpx.Response, httpx.Response]:
        app = create_app(runtime, temporal_client=_Temporal())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await client.post(
                "/channels/local_mailbox/events",
                content=payload,
                headers=headers,
            )
            duplicate = await client.post(
                "/channels/local_mailbox/events",
                content=payload,
                headers=headers,
            )
        return first, duplicate

    first, duplicate = asyncio.run(request())
    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert first.json()["deduplicated"] is False
    assert duplicate.json()["deduplicated"] is True
    assert duplicate.json()["command_id"] == first.json()["command_id"]


def test_local_mailbox_api_duplicate_racing_first_dispatch_is_deduplicated() -> None:
    """A duplicate whose inbox read predates the first dispatch's commit still
    finds the Case receipt, which is written in the same transaction that
    marks the inbox applied, so the receipt alone proves the event applied."""

    class _StaleInboxRepository(_ChannelRepository):
        def __init__(self) -> None:
            super().__init__()
            self.first_copy: dict[UUID, InboxReceiptRecord] = {}

        def reserve_channel_event(
            self,
            event: VerifiedLocalMailboxEvent,
            *,
            received_at: datetime,
        ) -> InboxReceiptRecord:
            receipt = super().reserve_channel_event(event, received_at=received_at)
            stale = self.first_copy.setdefault(event.event_id, receipt)
            return replace(stale, deduplicated=receipt.deduplicated)

    repository = _StaleInboxRepository()
    now = datetime.now(UTC)
    runtime = ThinAgentRuntime(repository, clock=lambda: now)
    runtime.apply_command(_create_command().model_copy(update={"occurred_at": now}))
    dispatched: list[UUID] = []
    # The real delivery activity, so the first dispatch leaves the outbox
    # accepted as the Workflow would and the duplicate has nothing to re-drive.
    delivery = CaseCommandActivityAdapter(runtime, local_mailbox=LocalMailboxAdapter())

    class _Temporal:
        async def apply_command(self, request: CaseCommandRequest) -> object:
            dispatched.append(request.command_id)
            try:
                transition = runtime.apply_command(request.to_command(BASE_TIME))
            except CaseConflictError as exc:
                raise TemporalDispatchError("channel_conflict") from exc
            assert transition.delivery_id is not None
            delivery.dispatch_channel_delivery(
                ChannelDeliveryRequest(
                    case_id=transition.case_id,
                    delivery_id=transition.delivery_id,
                    idempotency_key=str(transition.delivery_id),
                )
            )
            return transition

        async def check_readiness(self) -> object:
            return object()

    event_id = uuid4()
    payload = (
        '{"schema_version":"local-mailbox-v1",'
        f'"event_id":"{event_id}",'
        '"binding_ref":"fictional-provider-local-mailbox",'
        f'"occurred_at":"{now.isoformat().replace("+00:00", "Z")}",'
        '"kind":"provider_message",'
        '"content":"Synthetic Provider message."}'
    ).encode()
    headers = build_fixture_headers(payload)

    async def request() -> tuple[httpx.Response, httpx.Response]:
        app = create_app(runtime, temporal_client=_Temporal())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await client.post(
                "/channels/local_mailbox/events",
                content=payload,
                headers=headers,
            )
            duplicate = await client.post(
                "/channels/local_mailbox/events",
                content=payload,
                headers=headers,
            )
        return first, duplicate

    first, duplicate = asyncio.run(request())
    inbox = repository.get_inbox_receipt(event_id)
    assert inbox is not None
    assert inbox.processing_state == "applied"
    assert repository.first_copy[event_id].processing_state == "reserved"
    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json()["deduplicated"] is True
    assert duplicate.json()["command_id"] == first.json()["command_id"]
    assert len(dispatched) == 1
    assert [record.state for record in repository.outbox.values()] == ["accepted"]


class _ScriptedTemporal:
    """Fake Temporal client: records every request and lets a test script each
    dispatch by its 1-based call number."""

    def __init__(
        self, handle: Callable[[int, CaseCommandRequest], CaseTransitionRef]
    ) -> None:
        self.requests: list[CaseCommandRequest] = []
        self._handle = handle

    async def apply_command(self, request: CaseCommandRequest) -> CaseTransitionRef:
        self.requests.append(request)
        return self._handle(len(self.requests), request)

    async def check_readiness(self) -> object:
        return object()


def _channel_case() -> tuple[_ChannelRepository, ThinAgentRuntime, datetime]:
    repository = _ChannelRepository()
    now = datetime.now(UTC)
    runtime = ThinAgentRuntime(repository, clock=lambda: now)
    runtime.apply_command(_create_command().model_copy(update={"occurred_at": now}))
    return repository, runtime, now


def _dispatch(
    runtime: ThinAgentRuntime, request: CaseCommandRequest
) -> CaseTransitionRef:
    """Apply as the Case activity would, with its channel conflict category."""

    try:
        return runtime.apply_command(request.to_command(BASE_TIME))
    except CaseConflictError as exc:
        raise TemporalDispatchError("channel_conflict") from exc


def _mailbox_payload(event_id: UUID, now: datetime) -> bytes:
    return (
        '{"schema_version":"local-mailbox-v1",'
        f'"event_id":"{event_id}",'
        '"binding_ref":"fictional-provider-local-mailbox",'
        f'"occurred_at":"{now.isoformat().replace("+00:00", "Z")}",'
        '"kind":"provider_message",'
        '"content":"Synthetic Provider message."}'
    ).encode()


def _post_event(
    runtime: ThinAgentRuntime,
    temporal: _ScriptedTemporal,
    payload: bytes,
    *,
    times: int,
) -> list[httpx.Response]:
    headers = build_fixture_headers(payload)

    async def request() -> list[httpx.Response]:
        app = create_app(runtime, temporal_client=temporal)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return [
                await client.post(
                    "/channels/local_mailbox/events", content=payload, headers=headers
                )
                for _ in range(times)
            ]

    return asyncio.run(request())


def _ingest_receipt(
    repository: _ChannelRepository, command_id: UUID
) -> CaseTransitionRef:
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    (receipt,) = [item for item in state.transitions if item.command_id == command_id]
    return receipt


def test_local_mailbox_redelivery_redrives_an_exhausted_delivery() -> None:
    """R17-T1: the ingest committed but its delivery activity exhausted (503);
    the redelivery sends the identical request again so the Workflow re-drives
    the delivery."""

    repository, runtime, now = _channel_case()

    def handle(call: int, request: CaseCommandRequest) -> CaseTransitionRef:
        transition = _dispatch(runtime, request)
        if call == 1:
            raise TemporalDispatchError("channel_dependency_unavailable")
        return transition

    temporal = _ScriptedTemporal(handle)
    first, redelivery = _post_event(
        runtime, temporal, _mailbox_payload(uuid4(), now), times=2
    )

    assert first.status_code == 503
    assert redelivery.status_code == 200
    assert redelivery.json()["deduplicated"] is True
    assert len(temporal.requests) == 2
    original, redriven = temporal.requests
    assert redriven == original
    receipt = _ingest_receipt(repository, original.command_id)
    assert redriven.semantic_fingerprint() == receipt.command_fingerprint
    assert redelivery.json()["delivery_id"] == str(receipt.delivery_id)


def test_local_mailbox_redrive_response_is_always_deduplicated() -> None:
    repository, runtime, now = _channel_case()

    def handle(call: int, request: CaseCommandRequest) -> CaseTransitionRef:
        transition = _dispatch(runtime, request)
        if call == 1:
            raise TemporalDispatchError("channel_dependency_unavailable")
        return transition.model_copy(update={"deduplicated": False})

    temporal = _ScriptedTemporal(handle)
    _, redelivery = _post_event(
        runtime, temporal, _mailbox_payload(uuid4(), now), times=2
    )

    assert redelivery.status_code == 200
    assert redelivery.json()["deduplicated"] is True
    assert len(temporal.requests) == 2
    del repository


def test_local_mailbox_redrive_failure_is_not_retried_in_route() -> None:
    _, runtime, now = _channel_case()

    def handle(call: int, request: CaseCommandRequest) -> CaseTransitionRef:
        _dispatch(runtime, request)
        raise TemporalDispatchError("channel_dependency_unavailable")

    temporal = _ScriptedTemporal(handle)
    first, redelivery = _post_event(
        runtime, temporal, _mailbox_payload(uuid4(), now), times=2
    )

    assert first.status_code == 503
    assert redelivery.status_code == 503
    assert len(temporal.requests) == 2


@pytest.mark.parametrize(
    "outbox_state", ["accepted", "delivered", "bounced", "failed_terminal"]
)
def test_local_mailbox_duplicate_of_settled_delivery_is_not_redriven(
    outbox_state: str,
) -> None:
    """R17-T2: only a delivery the activity would still send is re-driven."""

    repository, runtime, now = _channel_case()

    def handle(call: int, request: CaseCommandRequest) -> CaseTransitionRef:
        del call
        return _dispatch(runtime, request)

    temporal = _ScriptedTemporal(handle)
    payload = _mailbox_payload(uuid4(), now)
    (first,) = _post_event(runtime, temporal, payload, times=1)
    (delivery_id,) = repository.outbox
    repository.outbox[delivery_id] = replace(
        repository.outbox[delivery_id],
        state=outbox_state,
        provider_message_id=(
            None if outbox_state == "failed_terminal" else "local-provider-fixture"
        ),
    )
    (duplicate,) = _post_event(runtime, temporal, payload, times=1)

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json()["deduplicated"] is True
    assert len(temporal.requests) == 1


def test_local_mailbox_redrive_falls_back_when_no_fingerprint_matches() -> None:
    """A receipt whose fingerprint neither candidate request reproduces is
    answered from the receipt, as before, and never re-sent."""

    repository, runtime, now = _channel_case()

    def handle(call: int, request: CaseCommandRequest) -> CaseTransitionRef:
        _dispatch(runtime, request)
        raise TemporalDispatchError("channel_dependency_unavailable")

    temporal = _ScriptedTemporal(handle)
    payload = _mailbox_payload(uuid4(), now)
    (first,) = _post_event(runtime, temporal, payload, times=1)
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    *earlier, receipt = state.transitions
    repository.replace(
        SCRIPTED_CASE_ID,
        expected_revision=state.snapshot.revision,
        state=replace(
            state,
            transitions=(
                *earlier,
                receipt.model_copy(update={"command_fingerprint": "0" * 64}),
            ),
        ),
    )
    (duplicate,) = _post_event(runtime, temporal, payload, times=1)

    assert first.status_code == 503
    assert duplicate.status_code == 200
    assert duplicate.json()["deduplicated"] is True
    assert len(temporal.requests) == 1


def _commit_other_event(
    repository: _ChannelRepository, runtime: ThinAgentRuntime
) -> None:
    """A concurrent command: another mailbox event ingested directly."""

    event = _message_event(uuid4())
    inbox = repository.reserve_channel_event(event, received_at=BASE_TIME)
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    assert event.content is not None
    runtime.apply_command(
        CaseCommand(
            schema_version="phase-06b1-v1",
            command_id=inbox.command_id,
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.INGEST_CHANNEL_EVENT,
            occurred_at=event.occurred_at,
            expected_revision=state.snapshot.revision,
            channel_kind=CHANNEL_KIND,
            binding_ref=BINDING_REF,
            event_id=event.event_id,
            content_hash=hashlib.sha256(event.content.encode()).hexdigest(),
            payload_hash=event.raw_payload_hash,
        )
    )


def test_local_mailbox_stale_revision_is_retried_with_the_fresh_revision() -> None:
    """R5-T1: the route's revision read loses to a concurrent commit; the
    route re-reads and dispatches once more with the advanced revision."""

    repository, runtime, now = _channel_case()

    def handle(call: int, request: CaseCommandRequest) -> CaseTransitionRef:
        if call == 1:
            _commit_other_event(repository, runtime)
        return _dispatch(runtime, request)

    temporal = _ScriptedTemporal(handle)
    (response,) = _post_event(
        runtime, temporal, _mailbox_payload(uuid4(), now), times=1
    )

    assert response.status_code == 200
    assert response.json()["deduplicated"] is False
    assert len(temporal.requests) == 2
    stale, fresh = temporal.requests
    assert fresh.command_id == stale.command_id
    assert stale.expected_revision is not None
    assert fresh.expected_revision is not None
    assert fresh.expected_revision > stale.expected_revision
    receipt = _ingest_receipt(repository, fresh.command_id)
    assert fresh.semantic_fingerprint() == receipt.command_fingerprint


def test_local_mailbox_stale_revision_retry_is_bounded() -> None:
    repository, runtime, now = _channel_case()

    def handle(call: int, request: CaseCommandRequest) -> CaseTransitionRef:
        del call
        _commit_other_event(repository, runtime)
        return _dispatch(runtime, request)

    temporal = _ScriptedTemporal(handle)
    (response,) = _post_event(
        runtime, temporal, _mailbox_payload(uuid4(), now), times=1
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "channel_conflict"
    assert len(temporal.requests) == 2


def test_local_mailbox_conflict_without_revision_change_is_not_retried() -> None:
    """R5-T2: a genuine conflict (the Case did not move) is a 409 after one
    dispatch."""

    _, runtime, now = _channel_case()

    def handle(call: int, request: CaseCommandRequest) -> CaseTransitionRef:
        del call, request
        raise TemporalDispatchError("channel_conflict")

    temporal = _ScriptedTemporal(handle)
    (response,) = _post_event(
        runtime, temporal, _mailbox_payload(uuid4(), now), times=1
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "channel_conflict"
    assert len(temporal.requests) == 1


def test_local_mailbox_delivery_conflict_after_ingest_commit_is_not_retried() -> None:
    """R5-T3: the ingest committed (the revision advanced) and the delivery
    activity then failed with ``channel_conflict``; the receipt exists, so the
    route must not re-dispatch."""

    _, runtime, now = _channel_case()

    def handle(call: int, request: CaseCommandRequest) -> CaseTransitionRef:
        del call
        _dispatch(runtime, request)
        raise TemporalDispatchError("channel_conflict")

    temporal = _ScriptedTemporal(handle)
    (response,) = _post_event(
        runtime, temporal, _mailbox_payload(uuid4(), now), times=1
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "channel_conflict"
    assert len(temporal.requests) == 1


def test_local_mailbox_unavailable_dispatch_is_not_retried_after_case_moved() -> None:
    """Only ``channel_conflict`` is retried: an unavailable dispatch that
    committed nothing is a 503 after one dispatch even though another event
    advanced the Case meanwhile."""

    repository, runtime, now = _channel_case()

    def handle(call: int, request: CaseCommandRequest) -> CaseTransitionRef:
        del call, request
        _commit_other_event(repository, runtime)
        raise TemporalDispatchError("channel_dependency_unavailable")

    temporal = _ScriptedTemporal(handle)
    (response,) = _post_event(
        runtime, temporal, _mailbox_payload(uuid4(), now), times=1
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "channel_dependency_unavailable"
    assert len(temporal.requests) == 1


class _UnavailableObservationRepository(_ChannelRepository):
    """Delivery observations fail (retryably) until ``healthy`` is set."""

    def __init__(self) -> None:
        super().__init__()
        self.healthy = False

    def record_delivery_observation(
        self,
        delivery_id: UUID,
        *,
        idempotency_key: str,
        state: str,
        provider_message_id: str | None,
        failure_category: str | None = None,
    ) -> OutboxRecord:
        if not self.healthy:
            raise ChannelDependencyUnavailableError("channel storage unavailable")
        return super().record_delivery_observation(
            delivery_id,
            idempotency_key=idempotency_key,
            state=state,
            provider_message_id=provider_message_id,
            failure_category=failure_category,
        )


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


@pytest.mark.skipif(
    not os.environ.get("PROXYLOOP_TEST_TEMPORAL_ADDRESS"),
    reason="PROXYLOOP_TEST_TEMPORAL_ADDRESS is required (runs in phase06b1-check)",
)
def test_time_skipping_identical_ingest_redrives_exhausted_delivery() -> None:
    """The Workflow half of R-17, no DB: after the delivery activity exhausts,
    the identical ingest Update (the route's re-drive) reaches the Workflow
    once R-1 has rolled the run, re-runs the delivery activity, and the outbox
    is accepted after exactly one adapter send, although the observation write
    failed after that send on every earlier attempt. Takes about 15 s: the
    activity retry backoff is real time. It uses the process-local
    time-skipping server, but is gated to ``phase06b1-check`` so ``make test``
    never starts or downloads that server."""

    repository = _UnavailableObservationRepository()
    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME)
    created = runtime.apply_command(_create_command())
    event = _message_event(uuid4())
    assert event.content is not None
    inbox = repository.reserve_channel_event(event, received_at=BASE_TIME)
    request = CaseCommandRequest(
        schema_version="phase-06b1-v1",
        command_id=inbox.command_id,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.INGEST_CHANNEL_EVENT,
        expected_revision=created.after_revision,
        channel_occurred_at=event.occurred_at,
        channel_kind=CHANNEL_KIND,
        binding_ref=BINDING_REF,
        event_id=event.event_id,
        content_hash=hashlib.sha256(event.content.encode()).hexdigest(),
        payload_hash=event.raw_payload_hash,
    )
    mailbox = _CountingMailboxAdapter()

    async def scenario() -> tuple[str, CaseTransitionRef]:
        environment = await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter
        )
        async with environment:
            task_queue = f"proxyloop-phase06b1-redrive-{uuid4()}"
            adapter = CaseCommandActivityAdapter(runtime, local_mailbox=mailbox)
            temporal = TemporalCaseClient(
                environment.client, TemporalSettings(task_queue=task_queue)
            )
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[CaseWorkflow],
                activities=[
                    activity_for_adapter(adapter),
                    channel_activity_for_adapter(adapter),
                ],
            ):
                # Starts the Workflow; the Runtime deduplicates the create.
                await temporal.apply_command(_create_command())
                with pytest.raises(TemporalDispatchError) as raised:
                    await temporal.apply_command(request)
                (pending,) = repository.outbox.values()
                assert pending.state == "pending"
                repository.healthy = True
                return raised.value.category, await temporal.apply_command(request)

    category, redriven = asyncio.run(scenario())

    assert category == "channel_dependency_unavailable"
    assert redriven.command_id == inbox.command_id
    (outbox,) = repository.outbox.values()
    assert outbox.state == "accepted"
    assert outbox.provider_message_id is not None
    assert mailbox.send_calls == 1
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    assert len(state.transitions) == 2


@pytest.mark.parametrize(
    "category, status, message",
    [
        ("channel_replay_mismatch", 409, "channel event replay rejected"),
        ("channel_conflict", 409, "channel conflict"),
        ("stale_unknown_event", 422, "channel event rejected"),
        ("unknown_binding", 422, "channel event rejected"),
        ("channel_dependency_unavailable", 503, "channel dependency unavailable"),
    ],
)
def test_temporal_channel_failures_are_redacted_and_classified(
    category: str, status: int, message: str
) -> None:
    runtime = ThinAgentRuntime()

    class _Temporal:
        async def apply_command(self, request: CaseCommandRequest) -> object:
            del request
            raise TemporalDispatchError(category)

        async def check_readiness(self) -> object:
            return object()

    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(runtime, temporal_client=_Temporal())
            ),
            base_url="http://test",
        ) as client:
            return await client.post(
                "/cases",
                json={
                    "current_monthly_total": {
                        "currency": "USD",
                        "amount_minor": 9200,
                    },
                    "target_monthly_total": {
                        "currency": "USD",
                        "amount_minor": 7500,
                    },
                    "mobile_hotspot_required": True,
                    "device_financing_change_forbidden": True,
                },
            )

    response = asyncio.run(request())
    assert response.status_code == status
    assert response.json() == {"detail": {"code": category, "message": message}}


def test_temporal_activity_preserves_channel_conflict_category() -> None:
    class _Runtime:
        def apply_command(self, command: CaseCommand) -> object:
            del command
            raise ChannelConflictError("unknown_binding")

    adapter = CaseCommandActivityAdapter(_Runtime())
    command = _create_command().model_copy(
        update={
            "command_type": CaseCommandType.INGEST_CHANNEL_EVENT,
            "command_id": uuid4(),
            "expected_revision": 2,
            "schema_version": "phase-06b1-v1",
            "channel_kind": CHANNEL_KIND,
            "binding_ref": BINDING_REF,
            "event_id": uuid4(),
            "content_hash": hashlib.sha256(b"Synthetic Provider message.").hexdigest(),
            "payload_hash": hashlib.sha256(b"payload").hexdigest(),
        }
    )

    with pytest.raises(ApplicationError) as raised:
        adapter.apply_command(command)
    assert raised.value.type == "unknown_binding"
    assert raised.value.non_retryable is True


@pytest.mark.parametrize(
    "category",
    [
        "channel_replay_mismatch",
        "stale_unknown_event",
        "unknown_binding",
        "channel_conflict",
        "channel_dependency_unavailable",
    ],
)
def test_temporal_client_allowlists_channel_failure_categories(category: str) -> None:
    error = ApplicationError("redacted", type=category)
    assert _failure_category(error) == category


class _FailFinalWriteOnceChannelRepository(_ChannelRepository):
    def __init__(self) -> None:
        super().__init__()
        self.fail_final_write = True

    def replace(
        self,
        case_id: UUID,
        *,
        expected_revision: int,
        state: CaseRuntimeState,
    ) -> CaseRuntimeState:
        if state.snapshot.completion_decision is not None and self.fail_final_write:
            self.fail_final_write = False
            raise CaseConflictError("injected final CAS conflict")
        return super().replace(
            case_id,
            expected_revision=expected_revision,
            state=state,
        )


def test_delivery_callback_is_refused_while_execution_claim_is_pending() -> None:
    repository = _FailFinalWriteOnceChannelRepository()
    now = [BASE_TIME]
    runtime = ThinAgentRuntime(repository, clock=lambda: now[0])
    runtime.apply_command(_create_command())
    event = _message_event(uuid4())
    inbox = repository.reserve_channel_event(event, received_at=BASE_TIME)
    ingest = CaseCommand(
        schema_version="phase-06b1-v1",
        command_id=inbox.command_id,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.INGEST_CHANNEL_EVENT,
        occurred_at=event.occurred_at,
        expected_revision=2,
        channel_kind=CHANNEL_KIND,
        binding_ref=BINDING_REF,
        event_id=event.event_id,
        content_hash=hashlib.sha256(event.content.encode()).hexdigest(),
        payload_hash=event.raw_payload_hash,
    )
    applied = runtime.apply_command(ingest)
    assert applied.delivery_id is not None
    accepted = repository.get_outbox_record(applied.delivery_id)
    assert accepted is not None
    repository.outbox[applied.delivery_id] = replace(
        accepted,
        state="accepted",
        provider_message_id="local-provider-test",
    )

    now[0] = BASE_TIME + timedelta(minutes=1)
    waiting = runtime.append_event(SCRIPTED_CASE_ID, content="Review the offer.")
    assert waiting.approval is not None
    approval_command = CaseCommand(
        command_id=uuid4(),
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.DECIDE_APPROVAL,
        occurred_at=BASE_TIME + timedelta(minutes=2),
        expected_revision=waiting.snapshot.revision,
        approval_id=waiting.approval.approval_id,
        decision="approved",
    )
    with pytest.raises(CaseConflictError, match="final CAS"):
        runtime.apply_command(approval_command)
    claimed = repository.get(SCRIPTED_CASE_ID)
    assert claimed is not None
    assert claimed.snapshot.pending_execution is True
    claim_revision = claimed.snapshot.revision

    delivery_event = _message_event(uuid4(), kind=LocalMailboxEventKind.DELIVERY)
    delivery_inbox = repository.reserve_channel_event(
        delivery_event, received_at=BASE_TIME
    )
    callback = CaseCommand(
        schema_version="phase-06b1-v1",
        command_id=delivery_inbox.command_id,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.RECORD_CHANNEL_DELIVERY,
        occurred_at=BASE_TIME,
        expected_revision=claim_revision,
        channel_kind=CHANNEL_KIND,
        binding_ref=BINDING_REF,
        event_id=delivery_event.event_id,
        delivery_id=applied.delivery_id,
        provider_message_id="local-provider-test",
        delivery_status="delivered",
        artifact_hash=hashlib.sha256(b"artifact").hexdigest(),
        payload_hash=delivery_event.raw_payload_hash,
    )
    with pytest.raises(ChannelConflictError, match="not available for channel"):
        runtime.apply_command(callback)
    still_pending = repository.get(SCRIPTED_CASE_ID)
    assert still_pending is not None
    assert still_pending.snapshot.revision == claim_revision
    assert still_pending.snapshot.pending_execution is True
    assert still_pending.execution_claim is not None
    assert repository.receipts == []

    now[0] = BASE_TIME + timedelta(minutes=3)
    completed = runtime.apply_command(approval_command)
    assert completed.terminal is True
    assert completed.deduplicated is False

    replayed_event = _message_event(uuid4(), kind=LocalMailboxEventKind.DELIVERY)
    replayed_inbox = repository.reserve_channel_event(
        replayed_event, received_at=BASE_TIME
    )
    replayed = callback.model_copy(
        update={
            "command_id": replayed_inbox.command_id,
            "event_id": replayed_event.event_id,
            "expected_revision": completed.after_revision,
            "payload_hash": replayed_event.raw_payload_hash,
        }
    )
    delivered = runtime.apply_command(replayed)
    assert delivered.after_revision == completed.after_revision + 1
    assert delivered.delivery_status == "delivered"
    final = repository.get(SCRIPTED_CASE_ID)
    assert final is not None
    assert final.snapshot.pending_execution is False
    assert final.execution_claim is None
    assert final.execution_count == 1
    assert final.snapshot.completion_decision is not None
    assert len(repository.receipts) == 1


def test_channel_delivery_rejects_replayed_callback_payload() -> None:
    repository = _ChannelRepository()
    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME)
    runtime.apply_command(_create_command())
    event = _message_event(uuid4())
    inbox = repository.reserve_channel_event(event, received_at=BASE_TIME)
    ingest = CaseCommand(
        schema_version="phase-06b1-v1",
        command_id=inbox.command_id,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.INGEST_CHANNEL_EVENT,
        occurred_at=event.occurred_at,
        expected_revision=2,
        channel_kind=CHANNEL_KIND,
        binding_ref=BINDING_REF,
        event_id=event.event_id,
        content_hash=hashlib.sha256(event.content.encode()).hexdigest(),
        payload_hash=event.raw_payload_hash,
    )
    applied = runtime.apply_command(ingest)
    assert applied.delivery_id is not None
    accepted = repository.get_outbox_record(applied.delivery_id)
    assert accepted is not None
    repository.outbox[applied.delivery_id] = replace(
        accepted,
        state="accepted",
        provider_message_id="local-provider-test",
    )
    delivery_event = _message_event(uuid4(), kind=LocalMailboxEventKind.DELIVERY)
    delivery_inbox = repository.reserve_channel_event(
        delivery_event, received_at=BASE_TIME
    )
    artifact_hash = hashlib.sha256(b"artifact").hexdigest()
    callback = CaseCommand(
        schema_version="phase-06b1-v1",
        command_id=delivery_inbox.command_id,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.RECORD_CHANNEL_DELIVERY,
        occurred_at=BASE_TIME,
        expected_revision=applied.after_revision,
        channel_kind=CHANNEL_KIND,
        binding_ref=BINDING_REF,
        event_id=delivery_event.event_id,
        delivery_id=applied.delivery_id,
        provider_message_id="local-provider-test",
        delivery_status="delivered",
        artifact_hash=artifact_hash,
        payload_hash=delivery_event.raw_payload_hash,
    )
    first = runtime.apply_command(callback)
    state_after_first = repository.get(SCRIPTED_CASE_ID)
    assert state_after_first is not None
    event_count = len(state_after_first.snapshot.visible_events)
    evidence_count = len(state_after_first.snapshot.evidence)

    duplicate_event = _message_event(uuid4(), kind=LocalMailboxEventKind.DELIVERY)
    duplicate_inbox = repository.reserve_channel_event(
        duplicate_event, received_at=BASE_TIME
    )
    duplicate = callback.model_copy(
        update={
            "command_id": duplicate_inbox.command_id,
            "event_id": duplicate_event.event_id,
            "expected_revision": first.after_revision,
            "payload_hash": duplicate_event.raw_payload_hash,
        }
    )
    duplicate_result = runtime.apply_command(duplicate)
    assert duplicate_result.after_revision == first.after_revision
    state_after_duplicate = repository.get(SCRIPTED_CASE_ID)
    assert state_after_duplicate is not None
    assert len(state_after_duplicate.snapshot.visible_events) == event_count
    assert len(state_after_duplicate.snapshot.evidence) == evidence_count

    mismatched_event = _message_event(uuid4(), kind=LocalMailboxEventKind.DELIVERY)
    mismatched_inbox = repository.reserve_channel_event(
        mismatched_event, received_at=BASE_TIME
    )
    mismatched = duplicate.model_copy(
        update={
            "command_id": mismatched_inbox.command_id,
            "event_id": mismatched_event.event_id,
            "payload_hash": hashlib.sha256(b"replayed").hexdigest(),
        }
    )
    with pytest.raises(CaseConflictError, match="replay mismatch"):
        runtime.apply_command(mismatched)

    reordered_event = _message_event(uuid4(), kind=LocalMailboxEventKind.DELIVERY)
    reordered_inbox = repository.reserve_channel_event(
        reordered_event, received_at=BASE_TIME
    )
    reordered = duplicate.model_copy(
        update={
            "command_id": reordered_inbox.command_id,
            "event_id": reordered_event.event_id,
            "payload_hash": reordered_event.raw_payload_hash,
            "delivery_status": "bounced",
        }
    )
    with pytest.raises(CaseConflictError, match="regressed"):
        runtime.apply_command(reordered)
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    assert state.snapshot.revision == first.after_revision

    async def get_case() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime)),
            base_url="http://test",
        ) as client:
            return await client.get(f"/cases/{SCRIPTED_CASE_ID}")

    response = asyncio.run(get_case())
    assert response.status_code == 200
    payload = response.json()
    snapshot = payload["snapshot"]
    assert snapshot["revision"] == state.snapshot.revision
    assert snapshot["event_cursor"] == state.snapshot.event_cursor
    assert "pins" not in snapshot
    assert [event["event_type"] for event in snapshot["visible_events"]] == [
        "provider_offer"
    ]
    assert "evidence" not in snapshot
    non_channel_evidence = [
        item
        for item in state.snapshot.evidence
        if item.source_type.value != "provider_event"
        and not (
            item.source_type.value == "provider_message" and _is_uuid4(item.source_ref)
        )
    ]
    assert [item.source_type.value for item in non_channel_evidence] == [
        "provider_message"
    ]
    assert all(
        item.source_ref == "pine-mobile:offer:pine-value-5g:v1"
        for item in non_channel_evidence
    )
    assert {item["source_type"] for item in payload["evidence"]} <= {
        "simulator_transition",
        "confirmation",
    }
    channel_evidence = [
        item for item in state.snapshot.evidence if item not in non_channel_evidence
    ]
    assert {item.source_type.value for item in channel_evidence} == {
        "provider_message",
        "provider_event",
    }
    encoded = json.dumps(payload)
    for item in channel_evidence:
        assert str(item.evidence_id) not in encoded
        assert item.content_hash not in encoded
    assert "Synthetic Provider message." not in str(payload)
    assert artifact_hash not in str(payload)
    assert "local-provider-test" not in str(payload)


def test_postgres_delivery_callback_after_complete_is_stored() -> None:
    """R-10: a delivery callback on a COMPLETE Case passes the PostgreSQL codec."""

    database_url = _database_url()
    _truncate(database_url)
    repository = PostgresCaseRepository(database_url)
    now = [BASE_TIME]
    runtime = ThinAgentRuntime(repository, clock=lambda: now[0])
    created = runtime.apply_command(_create_command())
    event = _message_event(uuid4())
    inbox = repository.reserve_channel_event(event, received_at=BASE_TIME)
    applied = runtime.apply_command(
        CaseCommand(
            schema_version="phase-06b1-v1",
            command_id=inbox.command_id,
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.INGEST_CHANNEL_EVENT,
            occurred_at=event.occurred_at,
            expected_revision=created.after_revision,
            channel_kind=CHANNEL_KIND,
            binding_ref=BINDING_REF,
            event_id=event.event_id,
            content_hash=hashlib.sha256(event.content.encode()).hexdigest(),
            payload_hash=event.raw_payload_hash,
        )
    )
    assert applied.delivery_id is not None
    outbox = repository.get_outbox_record(applied.delivery_id)
    assert outbox is not None
    repository.record_delivery_observation(
        applied.delivery_id,
        idempotency_key=outbox.idempotency_key,
        state="accepted",
        provider_message_id="local-provider-test",
    )
    now[0] = BASE_TIME + timedelta(minutes=1)
    waiting = runtime.append_event(SCRIPTED_CASE_ID, content="Review the offer.")
    assert waiting.approval is not None
    completed = runtime.apply_command(
        CaseCommand(
            command_id=uuid4(),
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.DECIDE_APPROVAL,
            occurred_at=BASE_TIME + timedelta(minutes=2),
            expected_revision=waiting.snapshot.revision,
            approval_id=waiting.approval.approval_id,
            decision="approved",
        )
    )
    assert completed.terminal is True
    before = PostgresCaseRepository(database_url).get(SCRIPTED_CASE_ID)
    assert before is not None
    assert before.snapshot.completion_receipt is not None

    delivery_event = _message_event(uuid4(), kind=LocalMailboxEventKind.DELIVERY)
    delivery_inbox = repository.reserve_channel_event(
        delivery_event, received_at=BASE_TIME
    )
    delivered = runtime.apply_command(
        CaseCommand(
            schema_version="phase-06b1-v1",
            command_id=delivery_inbox.command_id,
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.RECORD_CHANNEL_DELIVERY,
            occurred_at=BASE_TIME,
            expected_revision=before.snapshot.revision,
            channel_kind=CHANNEL_KIND,
            binding_ref=BINDING_REF,
            event_id=delivery_event.event_id,
            delivery_id=applied.delivery_id,
            provider_message_id="local-provider-test",
            delivery_status="delivered",
            artifact_hash=hashlib.sha256(b"artifact").hexdigest(),
            payload_hash=delivery_event.raw_payload_hash,
        )
    )

    assert delivered.after_revision == before.snapshot.revision + 1
    fresh = PostgresCaseRepository(database_url)
    after = fresh.get(SCRIPTED_CASE_ID)
    assert after is not None
    assert after.snapshot.revision == before.snapshot.revision + 1
    assert after.snapshot.case.phase is before.snapshot.case.phase
    assert after.snapshot.completion_decision == before.snapshot.completion_decision
    assert after.snapshot.completion_receipt == before.snapshot.completion_receipt
    assert after.execution_source_pins == before.execution_source_pins
    delivery_inbox_after = fresh.get_inbox_receipt(delivery_event.event_id)
    assert delivery_inbox_after is not None
    assert delivery_inbox_after.processing_state == "applied"
    outbox_after = fresh.get_outbox_record(applied.delivery_id)
    assert outbox_after is not None
    assert outbox_after.state == "delivered"
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            "SELECT count(*) FROM proxyloop_channel_delivery_receipts"
        ).fetchone()
    assert row is not None
    assert row[0] == 1
