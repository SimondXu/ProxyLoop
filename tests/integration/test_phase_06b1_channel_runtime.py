from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
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
    assert snapshot["pins"]
    assert [event["event_type"] for event in snapshot["visible_events"]] == [
        "provider_offer"
    ]
    assert [item["source_type"] for item in snapshot["evidence"]] == [
        "provider_message"
    ]
    assert all(
        item["source_ref"] == "pine-mobile:offer:pine-value-5g:v1"
        for item in snapshot["evidence"]
    )
    assert "Synthetic Provider message." not in str(payload)
    assert artifact_hash not in str(payload)
    assert "local-provider-test" not in str(payload)
