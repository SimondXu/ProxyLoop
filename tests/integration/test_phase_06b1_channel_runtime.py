from __future__ import annotations

import asyncio
import hashlib
import json
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
    ChannelBindingRecord,
    ChannelConflictError,
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
    LocalMailboxEventKind,
    VerifiedLocalMailboxEvent,
    build_fixture_headers,
)
from proxyloop_contracts import Money
from proxyloop_workflow_worker import (
    CaseCommandActivityAdapter,
    CaseCommandRequest,
    TemporalDispatchError,
)
from proxyloop_workflow_worker.client import _failure_category
from temporalio.exceptions import ApplicationError
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

    class _Temporal:
        async def apply_command(self, request: CaseCommandRequest) -> object:
            dispatched.append(request.command_id)
            try:
                return runtime.apply_command(request.to_command(BASE_TIME))
            except CaseConflictError as exc:
                raise TemporalDispatchError("channel_conflict") from exc

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


class _InboxWriteFailureRepository(PostgresCaseRepository):
    """Point the final Inbox write of one delivery callback at a missing row."""

    def __init__(self, database_url: str) -> None:
        self.fail_inbox_write = False
        super().__init__(database_url)

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
        if self.fail_inbox_write:
            self.fail_inbox_write = False
            inbox_event_id = uuid4()
        return super().replace_with_delivery_receipt(
            case_id,
            expected_revision=expected_revision,
            state=state,
            inbox_event_id=inbox_event_id,
            receipt=receipt,
            outbox_state=outbox_state,
        )


def _postgres_accepted_delivery(
    repository: PostgresCaseRepository,
) -> tuple[ThinAgentRuntime, UUID, int]:
    """An in-progress Case whose one outbound reply the adapter accepted."""

    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME)
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
    return runtime, applied.delivery_id, applied.after_revision


def _postgres_delivery_callback(
    repository: PostgresCaseRepository,
    *,
    delivery_id: UUID,
    expected_revision: int,
    delivery_status: str = "delivered",
) -> CaseCommand:
    event = _message_event(uuid4(), kind=LocalMailboxEventKind.DELIVERY)
    inbox = repository.reserve_channel_event(event, received_at=BASE_TIME)
    return CaseCommand(
        schema_version="phase-06b1-v1",
        command_id=inbox.command_id,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.RECORD_CHANNEL_DELIVERY,
        occurred_at=BASE_TIME,
        expected_revision=expected_revision,
        channel_kind=CHANNEL_KIND,
        binding_ref=BINDING_REF,
        event_id=event.event_id,
        delivery_id=delivery_id,
        provider_message_id="local-provider-test",
        delivery_status=delivery_status,
        artifact_hash=hashlib.sha256(b"artifact").hexdigest(),
        payload_hash=event.raw_payload_hash,
    )


def _delivery_receipt_rows(database_url: str) -> int:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            "SELECT count(*) FROM proxyloop_channel_delivery_receipts"
        ).fetchone()
    assert row is not None
    return int(row[0])


def test_postgres_delivery_callback_write_is_atomic_and_retryable() -> None:
    """C-8: a failed callback write leaves no partial Case, Outbox or receipt."""

    database_url = _database_url()
    _truncate(database_url)
    repository = _InboxWriteFailureRepository(database_url)
    runtime, delivery_id, revision = _postgres_accepted_delivery(repository)
    before = PostgresCaseRepository(database_url).get(SCRIPTED_CASE_ID)
    assert before is not None
    assert before.snapshot.completion_decision is None
    callback = _postgres_delivery_callback(
        repository, delivery_id=delivery_id, expected_revision=revision
    )

    # The Case UPDATE, Outbox UPDATE and receipt INSERT run before the Inbox
    # write fails, so only a single transaction keeps them from persisting.
    repository.fail_inbox_write = True
    with pytest.raises(CaseConflictError, match="inbox reservation is not pending"):
        runtime.apply_command(callback)

    fresh = PostgresCaseRepository(database_url)
    unchanged = fresh.get(SCRIPTED_CASE_ID)
    assert unchanged is not None
    assert unchanged.snapshot == before.snapshot
    assert unchanged.transitions == before.transitions
    outbox = fresh.get_outbox_record(delivery_id)
    assert outbox is not None
    assert outbox.state == "accepted"
    inbox = fresh.get_inbox_receipt(callback.event_id)
    assert inbox is not None
    assert inbox.processing_state == "reserved"
    assert fresh.get_delivery_receipt(delivery_id) is None
    assert _delivery_receipt_rows(database_url) == 0

    delivered = runtime.apply_command(callback)

    assert delivered.after_revision == revision + 1
    after = PostgresCaseRepository(database_url).get(SCRIPTED_CASE_ID)
    assert after is not None
    assert after.snapshot.revision == revision + 1
    added = after.snapshot.evidence[len(before.snapshot.evidence) :]
    assert [item.source_type.value for item in added] == ["provider_event"]
    receipt = fresh.get_delivery_receipt(delivery_id)
    assert receipt is not None
    assert receipt.evidence_id == added[0].evidence_id
    assert receipt.observation_state == "delivered"
    outbox_after = fresh.get_outbox_record(delivery_id)
    assert outbox_after is not None
    assert outbox_after.state == "delivered"
    inbox_after = fresh.get_inbox_receipt(callback.event_id)
    assert inbox_after is not None
    assert inbox_after.processing_state == "applied"
    assert _delivery_receipt_rows(database_url) == 1


def test_postgres_repeated_delivery_callback_keeps_one_receipt() -> None:
    """C-8: a repeated callback keeps one receipt; a regression writes nothing.

    The repeat is not a no-op: it keeps the snapshot and the receipt but
    records its transition, marks its Inbox applied, and rewrites the Outbox
    with the same state.
    """

    database_url = _database_url()
    _truncate(database_url)
    repository = PostgresCaseRepository(database_url)
    runtime, delivery_id, revision = _postgres_accepted_delivery(repository)
    first = runtime.apply_command(
        _postgres_delivery_callback(
            repository, delivery_id=delivery_id, expected_revision=revision
        )
    )
    after_first = PostgresCaseRepository(database_url).get(SCRIPTED_CASE_ID)
    assert after_first is not None
    receipt = repository.get_delivery_receipt(delivery_id)
    assert receipt is not None

    repeated = _postgres_delivery_callback(
        repository, delivery_id=delivery_id, expected_revision=first.after_revision
    )
    duplicate = runtime.apply_command(repeated)

    assert duplicate.after_revision == first.after_revision
    after_duplicate = PostgresCaseRepository(database_url).get(SCRIPTED_CASE_ID)
    assert after_duplicate is not None
    assert after_duplicate.snapshot == after_first.snapshot
    assert len(after_duplicate.transitions) == len(after_first.transitions) + 1
    assert repository.get_delivery_receipt(delivery_id) == receipt
    repeated_inbox = repository.get_inbox_receipt(repeated.event_id)
    assert repeated_inbox is not None
    assert repeated_inbox.processing_state == "applied"
    assert _delivery_receipt_rows(database_url) == 1

    bounced = _postgres_delivery_callback(
        repository,
        delivery_id=delivery_id,
        expected_revision=first.after_revision,
        delivery_status="bounced",
    )
    # The Runtime refuses the regression before it reaches storage ...
    with pytest.raises(ChannelConflictError, match="regressed"):
        runtime.apply_command(bounced)
    # ... so drive the storage checks directly: an Outbox regression
    # (delivered -> bounced) and a receipt that differs from the stored one.
    for outbox_state, regressing in (
        ("bounced", replace(receipt, observation_state="bounced")),
        ("delivered", replace(receipt, artifact_hash="0" * 64)),
    ):
        with pytest.raises(CaseConflictError, match="delivery observation regressed"):
            repository.replace_with_delivery_receipt(
                SCRIPTED_CASE_ID,
                expected_revision=after_duplicate.snapshot.revision,
                state=after_duplicate,
                inbox_event_id=bounced.event_id,
                receipt=regressing,
                outbox_state=outbox_state,
            )

    final = PostgresCaseRepository(database_url).get(SCRIPTED_CASE_ID)
    assert final is not None
    assert final.snapshot == after_first.snapshot
    assert final.transitions == after_duplicate.transitions
    outbox = repository.get_outbox_record(delivery_id)
    assert outbox is not None
    assert outbox.state == "delivered"
    bounced_inbox = repository.get_inbox_receipt(bounced.event_id)
    assert bounced_inbox is not None
    assert bounced_inbox.processing_state == "reserved"
    assert repository.get_delivery_receipt(delivery_id) == receipt
    assert _delivery_receipt_rows(database_url) == 1
