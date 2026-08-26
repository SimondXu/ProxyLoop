from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from google.protobuf.duration_pb2 import Duration
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseCommand,
    CaseCommandType,
    CaseConflictError,
    CaseRuntimeState,
    PostgresCaseRepository,
    ThinAgentRuntime,
)
from proxyloop_connectors import (
    BINDING_REF,
    CHANNEL_KIND,
    FaultInjectingLocalMailboxAdapter,
    LocalMailboxEventKind,
    VerifiedLocalMailboxEvent,
)
from proxyloop_contracts import Money
from proxyloop_workflow_worker import (
    CaseCommandActivityAdapter,
    CaseCommandRequest,
    TemporalCaseClient,
    TemporalSettings,
    activity_for_adapter,
    channel_activity_for_adapter,
)
from proxyloop_workflow_worker.workflow import CaseWorkflow
from temporalio.api.workflowservice.v1 import RegisterNamespaceRequest
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Replayer, Worker

BASE_TIME = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
CREATE_COMMAND_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _database_url() -> str:
    database_url = os.environ.get("PROXYLOOP_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PROXYLOOP_TEST_DATABASE_URL is required")
    with psycopg.connect(database_url) as connection:
        if connection.info.dbname != "proxyloop_test":
            raise AssertionError("Phase 06B1 integration requires proxyloop_test")
    return database_url


def _dependencies() -> tuple[str, str]:
    database_url = _database_url()
    temporal_address = os.environ.get("PROXYLOOP_TEST_TEMPORAL_ADDRESS")
    if not temporal_address:
        pytest.skip(
            "PROXYLOOP_TEST_DATABASE_URL and "
            "PROXYLOOP_TEST_TEMPORAL_ADDRESS are required"
        )
    return database_url, temporal_address


def _truncate(database_url: str) -> None:
    PostgresCaseRepository(database_url)
    with psycopg.connect(database_url) as connection, connection.transaction():
        connection.execute(
            "TRUNCATE TABLE proxyloop_channel_delivery_receipts, "
            "proxyloop_channel_outbox_records, "
            "proxyloop_channel_inbox_receipts, "
            "proxyloop_channel_bindings, "
            "proxyloop_case_runtime_states"
        )


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


def _message_event(event_id: UUID) -> VerifiedLocalMailboxEvent:
    content = "Synthetic Provider message."
    return VerifiedLocalMailboxEvent(
        event_id=event_id,
        binding_ref=BINDING_REF,
        occurred_at=BASE_TIME,
        kind=LocalMailboxEventKind.PROVIDER_MESSAGE,
        raw_payload_hash=hashlib.sha256(f"payload:{event_id}".encode()).hexdigest(),
        content=content,
        fixture_timestamp=BASE_TIME,
    )


class _FailAfterInboxUpdateRepository(PostgresCaseRepository):
    """Inject the failure after the repository has written Case and Outbox."""

    def replace_with_channel_outbox(
        self,
        case_id: UUID,
        *,
        expected_revision: int,
        state: CaseRuntimeState,
        outbox: Any,
        inbox_event_id: UUID,
    ) -> CaseRuntimeState:
        del inbox_event_id
        return super().replace_with_channel_outbox(
            case_id,
            expected_revision=expected_revision,
            state=state,
            outbox=outbox,
            inbox_event_id=uuid4(),
        )


def test_postgres_channel_outbox_commit_rolls_back_atomically() -> None:
    database_url = _database_url()
    _truncate(database_url)
    repository = _FailAfterInboxUpdateRepository(database_url)
    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME)
    created = runtime.apply_command(_create_command())
    event = _message_event(uuid4())
    inbox = repository.reserve_channel_event(event, received_at=BASE_TIME)
    command = CaseCommand(
        schema_version="phase-06b1-v1",
        command_id=inbox.command_id,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.INGEST_CHANNEL_EVENT,
        occurred_at=BASE_TIME,
        expected_revision=created.after_revision,
        channel_kind=CHANNEL_KIND,
        binding_ref=BINDING_REF,
        event_id=event.event_id,
        content_hash=hashlib.sha256(event.content.encode()).hexdigest(),
        payload_hash=event.raw_payload_hash,
    )

    with pytest.raises(CaseConflictError, match="inbox reservation"):
        runtime.apply_command(command)

    persisted = PostgresCaseRepository(database_url).get(SCRIPTED_CASE_ID)
    assert persisted is not None
    assert persisted.snapshot.revision == created.after_revision
    assert len(persisted.transitions) == 1
    inbox_after = repository.get_inbox_receipt(event.event_id)
    assert inbox_after is not None
    assert inbox_after.processing_state == "reserved"
    with psycopg.connect(database_url) as connection:
        outbox_row = connection.execute(
            "SELECT count(*) FROM proxyloop_channel_outbox_records"
        ).fetchone()
    assert outbox_row is not None
    outbox_count = outbox_row[0]
    assert outbox_count == 0


async def _connect(address: str) -> tuple[Client, str]:
    namespace = f"phase06b1-{uuid4()}"
    bootstrap = await Client.connect(address)
    await bootstrap.service_client.workflow_service.register_namespace(
        RegisterNamespaceRequest(
            namespace=namespace,
            workflow_execution_retention_period=Duration(seconds=86400),
        )
    )
    client = await Client.connect(
        address,
        namespace=namespace,
        data_converter=pydantic_data_converter,
    )
    return client, namespace


def test_live_temporal_local_mailbox_delivery_is_stable() -> None:
    database_url, temporal_address = _dependencies()
    _truncate(database_url)

    async def scenario() -> None:
        task_queue = f"proxyloop-phase06b1-{uuid4()}"
        client, namespace = await _connect(temporal_address)
        settings = TemporalSettings(
            target_host=temporal_address,
            namespace=namespace,
            task_queue=task_queue,
        )
        runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
        adapter = CaseCommandActivityAdapter(
            runtime,
            local_mailbox=FaultInjectingLocalMailboxAdapter(
                lose_response_after_accept=1
            ),
        )
        temporal = TemporalCaseClient(client, settings)
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CaseWorkflow],
            activities=[
                activity_for_adapter(adapter),
                channel_activity_for_adapter(adapter),
            ],
        )
        async with worker:
            created = await temporal.apply_command(
                CaseCommandRequest(
                    command_id=CREATE_COMMAND_ID,
                    case_id=SCRIPTED_CASE_ID,
                    command_type=CaseCommandType.CREATE_CASE,
                    current_monthly_total=Money(amount_minor=9200, currency="USD"),
                    target_monthly_total=Money(amount_minor=7500, currency="USD"),
                    mobile_hotspot_required=True,
                    device_financing_change_forbidden=True,
                )
            )
            event = _message_event(uuid4())
            repository = runtime.repository
            assert isinstance(repository, PostgresCaseRepository)
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
            transition = await temporal.apply_command(request)
            duplicate = await temporal.apply_command(request)
            assert transition.delivery_id is not None
            assert duplicate.command_id == transition.command_id
            assert duplicate.delivery_id == transition.delivery_id
            assert duplicate.after_revision == transition.after_revision

            outbox = repository.get_outbox_record(transition.delivery_id)
            assert outbox is not None
            assert outbox.state == "accepted"
            assert outbox.provider_message_id is not None
            assert outbox.attempt_count >= 1
            assert outbox.provider_message_id.startswith("local-provider-")
            assert outbox.source_event_id == event.event_id
            state = repository.get(SCRIPTED_CASE_ID)
            assert state is not None
            assert len(state.transitions) == 2
            assert len(state.snapshot.visible_events) == 2
            assert (
                sum(
                    item.source_type.value == "provider_message"
                    and item.source_ref == str(event.event_id)
                    for item in state.snapshot.evidence
                )
                == 1
            )
            with psycopg.connect(database_url) as connection:
                outbox_count = connection.execute(
                    "SELECT count(*) FROM proxyloop_channel_outbox_records"
                ).fetchone()
            assert outbox_count is not None
            assert outbox_count[0] == 1

            handle = client.get_workflow_handle(temporal.workflow_id(SCRIPTED_CASE_ID))
            history = await handle.fetch_history()
            replayer = Replayer(
                workflows=[CaseWorkflow],
                data_converter=pydantic_data_converter,
            )
            await replayer.replay_workflow(history)

    asyncio.run(scenario())
