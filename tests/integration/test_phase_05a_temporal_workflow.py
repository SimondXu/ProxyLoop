from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from google.protobuf.duration_pb2 import Duration
from proxyloop_api import create_app
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseCommand,
    CaseCommandType,
    CaseTransitionRef,
    PostgresCaseRepository,
    ThinAgentRuntime,
)
from proxyloop_contracts import Money
from proxyloop_workflow_worker import (
    CaseCommandActivityAdapter,
    CaseCommandRequest,
    TemporalCaseClient,
    TemporalDispatchError,
    TemporalSettings,
    activity_for_adapter,
)
from proxyloop_workflow_worker.workflow import (
    ACTIVITY_NAME,
    UPDATE_NAME,
    CaseWorkflow,
    update_id_for_command,
)
from temporalio import activity
from temporalio.api.workflowservice.v1 import RegisterNamespaceRequest
from temporalio.client import Client, WorkflowUpdateStage
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

TABLE = "proxyloop_case_runtime_states"


class _FaultingAdapter(CaseCommandActivityAdapter):
    def __init__(
        self,
        runtime: ThinAgentRuntime,
        *,
        after_commit: bool,
    ) -> None:
        super().__init__(runtime)
        self.after_commit = after_commit
        self.attempts = 0

    def apply_command(self, command: CaseCommand) -> CaseTransitionRef:
        self.attempts += 1
        if self.attempts == 1 and not self.after_commit:
            raise ApplicationError("injected transient", type="storage_unavailable")
        transition = super().apply_command(command)
        if self.attempts == 1:
            raise ApplicationError("injected post-commit", type="storage_unavailable")
        return transition


class _ExhaustingAdapter(CaseCommandActivityAdapter):
    def __init__(self, runtime: ThinAgentRuntime, blocked_command_id: UUID) -> None:
        super().__init__(runtime)
        self.blocked_command_id = blocked_command_id
        self.blocked_attempts = 0

    def apply_command(self, command: CaseCommand) -> CaseTransitionRef:
        if command.command_id == self.blocked_command_id:
            self.blocked_attempts += 1
            raise ApplicationError("injected unavailable", type="storage_unavailable")
        return super().apply_command(command)


class _GatedApprovalActivity:
    """Hold one approval activity so the expiry timer must wait on the lock."""

    def __init__(self, runtime: ThinAgentRuntime) -> None:
        self.adapter = CaseCommandActivityAdapter(runtime)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    @activity.defn(name=ACTIVITY_NAME)
    async def apply_command(self, command: CaseCommand) -> CaseTransitionRef:
        if command.command_type == CaseCommandType.DECIDE_APPROVAL:
            self.entered.set()
            await self.release.wait()
        return await asyncio.to_thread(self.adapter.apply_command, command)


def _dependencies() -> tuple[str, str]:
    database_url = _database_url()
    temporal_address = os.environ.get("PROXYLOOP_TEST_TEMPORAL_ADDRESS")
    if not temporal_address:
        pytest.skip(
            "PROXYLOOP_TEST_DATABASE_URL and "
            "PROXYLOOP_TEST_TEMPORAL_ADDRESS are required"
        )
    return database_url, temporal_address


def _database_url() -> str:
    database_url = os.environ.get("PROXYLOOP_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PROXYLOOP_TEST_DATABASE_URL is required")
    with psycopg.connect(database_url) as connection:
        if connection.info.dbname != "proxyloop_test":
            raise AssertionError("Temporal integration requires proxyloop_test")
    return database_url


def _truncate(database_url: str) -> None:
    repository = PostgresCaseRepository(database_url)
    del repository
    with psycopg.connect(database_url) as connection, connection.transaction():
        connection.execute(f"TRUNCATE TABLE {TABLE}")


def _create_request() -> CaseCommandRequest:
    return CaseCommandRequest(
        command_id=uuid4(),
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.CREATE_CASE,
        current_monthly_total=Money(currency="USD", amount_minor=9100),
        target_monthly_total=Money(currency="USD", amount_minor=7200),
        mobile_hotspot_required=True,
        device_financing_change_forbidden=True,
    )


async def _connected(address: str) -> tuple[Client, str]:
    namespace = f"phase05a-{uuid4()}"
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


def _run_live(
    scenario: Callable[[str, str], object],
) -> object:
    database_url, temporal_address = _dependencies()
    _truncate(database_url)
    return asyncio.run(scenario(database_url, temporal_address))


def test_live_temporal_postgres_duplicate_callback_continue_as_new_and_replay() -> None:
    async def scenario(database_url: str, address: str) -> None:
        task_queue = f"proxyloop-phase05a-{uuid4()}"
        settings = TemporalSettings(
            target_host=address,
            task_queue=task_queue,
            continue_as_new_after=2,
        )
        client, namespace = await _connected(address)
        settings = replace(settings, namespace=namespace)
        runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
        adapter = CaseCommandActivityAdapter(runtime)
        temporal = TemporalCaseClient(client, settings)
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CaseWorkflow],
            activities=[activity_for_adapter(adapter)],
        )
        async with worker:
            create_request = _create_request()
            created = await temporal.apply_command(create_request)
            handle = client.get_workflow_handle(temporal.workflow_id(SCRIPTED_CASE_ID))
            first_run_id = (
                await handle.describe()
            ).raw_description.workflow_execution_info.execution.run_id
            append_request = CaseCommandRequest(
                command_id=uuid4(),
                case_id=SCRIPTED_CASE_ID,
                command_type=CaseCommandType.APPEND_EVENT,
                content="Review the fictional offer.",
                event_type="consumer_message",
                expected_revision=created.after_revision,
            )
            waiting = await temporal.apply_command(append_request)
            assert waiting.approval_id is not None
            for _ in range(100):
                current_run_id = (
                    await handle.describe()
                ).raw_description.workflow_execution_info.execution.run_id
                if current_run_id != first_run_id:
                    break
                await asyncio.sleep(0.01)
            assert current_run_id != first_run_id
            cross_run_duplicate = await temporal.apply_command(create_request)
            assert cross_run_duplicate.deduplicated is True
            approve_request = CaseCommandRequest(
                command_id=uuid4(),
                case_id=SCRIPTED_CASE_ID,
                command_type=CaseCommandType.DECIDE_APPROVAL,
                approval_id=waiting.approval_id,
                decision="approved",
                expected_revision=waiting.after_revision,
            )
            completed = await temporal.apply_command(approve_request)
            duplicate = await temporal.apply_command(approve_request)

        state = runtime.repository.get(SCRIPTED_CASE_ID)
        assert state is not None
        assert completed.terminal is True
        assert duplicate.command_id == completed.command_id
        assert state.execution_count == 1
        assert len(state.transitions) == 3
        assert len(state.snapshot.evidence) == 3

        description = await handle.describe()
        assert (
            description.raw_description.execution_config.task_queue.name == task_queue
        )
        history = await handle.fetch_history()
        first_history = await client.get_workflow_handle(
            temporal.workflow_id(SCRIPTED_CASE_ID),
            run_id=first_run_id,
        ).fetch_history()
        replayer = Replayer(
            workflows=[CaseWorkflow],
            data_converter=pydantic_data_converter,
        )
        await replayer.replay_workflow(first_history)
        await replayer.replay_workflow(history)

    _run_live(scenario)


@pytest.mark.parametrize("after_commit", [False, True])
def test_live_temporal_activity_retry_is_idempotent(after_commit: bool) -> None:
    async def scenario(database_url: str, address: str) -> None:
        task_queue = f"proxyloop-phase05a-fault-{uuid4()}"
        settings = TemporalSettings(target_host=address, task_queue=task_queue)
        client, namespace = await _connected(address)
        settings = replace(settings, namespace=namespace)
        runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
        adapter = _FaultingAdapter(runtime, after_commit=after_commit)
        temporal = TemporalCaseClient(client, settings)
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CaseWorkflow],
            activities=[activity_for_adapter(adapter)],
        )
        async with worker:
            transition = await temporal.apply_command(_create_request())

        state = runtime.repository.get(SCRIPTED_CASE_ID)
        assert transition.after_revision == 2
        assert adapter.attempts == 2
        assert state is not None
        assert len(state.transitions) == 1
        assert state.execution_count == 0

    _run_live(scenario)


def test_live_temporal_retry_exhaustion_allows_later_distinct_command() -> None:
    async def scenario(database_url: str, address: str) -> None:
        task_queue = f"proxyloop-phase05a-exhaust-{uuid4()}"
        settings = TemporalSettings(target_host=address, task_queue=task_queue)
        client, namespace = await _connected(address)
        settings = replace(settings, namespace=namespace)
        runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
        blocked = _create_request()
        adapter = _ExhaustingAdapter(runtime, blocked.command_id)
        temporal = TemporalCaseClient(client, settings)
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CaseWorkflow],
            activities=[activity_for_adapter(adapter)],
        )
        async with worker:
            with pytest.raises(TemporalDispatchError) as raised:
                await temporal.apply_command(blocked)
            recovered = await temporal.apply_command(_create_request())

        assert raised.value.category == "temporal_unavailable"
        assert adapter.blocked_attempts == 5
        assert recovered.after_revision == 2
        state = runtime.repository.get(SCRIPTED_CASE_ID)
        assert state is not None
        assert len(state.transitions) == 1

    _run_live(scenario)


def test_live_temporal_queued_command_runs_on_replacement_worker() -> None:
    async def scenario(database_url: str, address: str) -> None:
        task_queue = f"proxyloop-phase05a-queued-{uuid4()}"
        settings = TemporalSettings(target_host=address, task_queue=task_queue)
        client, namespace = await _connected(address)
        settings = replace(settings, namespace=namespace)
        runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
        temporal = TemporalCaseClient(client, settings)
        pending = asyncio.create_task(temporal.apply_command(_create_request()))
        await asyncio.sleep(0.1)
        assert pending.done() is False
        assert runtime.repository.get(SCRIPTED_CASE_ID) is None

        replacement = Worker(
            client,
            task_queue=task_queue,
            workflows=[CaseWorkflow],
            activities=[activity_for_adapter(CaseCommandActivityAdapter(runtime))],
        )
        async with replacement:
            transition = await asyncio.wait_for(pending, timeout=10)

        assert transition.after_revision == 2
        assert runtime.repository.get(SCRIPTED_CASE_ID) is not None

    _run_live(scenario)


def test_live_temporal_worker_recovery_while_waiting_for_approval() -> None:
    async def scenario(database_url: str, address: str) -> None:
        task_queue = f"proxyloop-phase05a-recovery-{uuid4()}"
        settings = TemporalSettings(target_host=address, task_queue=task_queue)
        client, namespace = await _connected(address)
        settings = replace(settings, namespace=namespace)
        runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
        temporal = TemporalCaseClient(client, settings)

        first_worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CaseWorkflow],
            activities=[activity_for_adapter(CaseCommandActivityAdapter(runtime))],
        )
        async with first_worker:
            created = await temporal.apply_command(_create_request())
            waiting = await temporal.apply_command(
                CaseCommandRequest(
                    command_id=uuid4(),
                    case_id=SCRIPTED_CASE_ID,
                    command_type=CaseCommandType.APPEND_EVENT,
                    content="Review the fictional offer.",
                    event_type="consumer_message",
                    expected_revision=created.after_revision,
                )
            )

        assert waiting.approval_id is not None
        replacement_runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
        replacement_worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CaseWorkflow],
            activities=[
                activity_for_adapter(CaseCommandActivityAdapter(replacement_runtime))
            ],
        )
        async with replacement_worker:
            completed = await temporal.apply_command(
                CaseCommandRequest(
                    command_id=uuid4(),
                    case_id=SCRIPTED_CASE_ID,
                    command_type=CaseCommandType.DECIDE_APPROVAL,
                    approval_id=waiting.approval_id,
                    decision="approved",
                    expected_revision=waiting.after_revision,
                )
            )

        assert completed.terminal is True
        state = replacement_runtime.repository.get(SCRIPTED_CASE_ID)
        assert state is not None
        assert state.execution_count == 1

    _run_live(scenario)


def test_live_temporal_api_projects_authoritative_postgres_state() -> None:
    async def scenario(database_url: str, address: str) -> None:
        task_queue = f"proxyloop-phase05a-api-{uuid4()}"
        settings = TemporalSettings(target_host=address, task_queue=task_queue)
        client, namespace = await _connected(address)
        settings = replace(settings, namespace=namespace)
        runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
        temporal = TemporalCaseClient(client, settings)
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CaseWorkflow],
            activities=[activity_for_adapter(CaseCommandActivityAdapter(runtime))],
        )
        async with (
            worker,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(
                    app=create_app(runtime, temporal_client=temporal)
                ),
                base_url="http://test",
            ) as api,
        ):
            created = await api.post(
                "/cases",
                headers={"Idempotency-Key": str(uuid4())},
                json={
                    "current_monthly_total": {
                        "currency": "USD",
                        "amount_minor": 9100,
                    },
                    "target_monthly_total": {
                        "currency": "USD",
                        "amount_minor": 7200,
                    },
                    "mobile_hotspot_required": True,
                    "device_financing_change_forbidden": True,
                },
            )
            waiting = await api.post(
                f"/cases/{SCRIPTED_CASE_ID}/events",
                headers={"Idempotency-Key": str(uuid4())},
                json={
                    "content": "Review the fictional offer.",
                    "expected_revision": created.json()["revision"],
                },
            )
            approval = waiting.json()["approval"]
            completed = await api.post(
                f"/cases/{SCRIPTED_CASE_ID}/approvals/{approval['approval_id']}",
                headers={"Idempotency-Key": str(uuid4())},
                json={
                    "decision": "approved",
                    "expected_revision": waiting.json()["revision"],
                    "expected_case_revision": approval["case_revision"],
                    "expected_action_intent_revision": approval[
                        "action_intent_revision"
                    ],
                },
            )
            fetched = await api.get(f"/cases/{SCRIPTED_CASE_ID}")

        assert created.status_code == 201
        assert waiting.status_code == 200
        assert completed.status_code == 200
        assert completed.json()["completion"]["decision"] == "complete"
        assert fetched.json()["revision"] == completed.json()["revision"]
        state = runtime.repository.get(SCRIPTED_CASE_ID)
        assert state is not None
        assert state.execution_count == 1

    _run_live(scenario)


def test_time_skipping_persists_canonical_approval_expiry() -> None:
    database_url = _database_url()
    _truncate(database_url)

    async def scenario() -> None:
        environment = await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter
        )
        async with environment:
            task_queue = f"proxyloop-phase05a-time-{uuid4()}"
            settings = TemporalSettings(
                task_queue=task_queue,
                continue_as_new_after=2,
            )
            runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
            temporal = TemporalCaseClient(environment.client, settings)
            worker = Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[CaseWorkflow],
                activities=[activity_for_adapter(CaseCommandActivityAdapter(runtime))],
            )
            async with worker:
                created = await temporal.apply_command(_create_request())
                handle = environment.client.get_workflow_handle(
                    temporal.workflow_id(SCRIPTED_CASE_ID)
                )
                first_run_id = (
                    await handle.describe()
                ).raw_description.workflow_execution_info.execution.run_id
                waiting = await temporal.apply_command(
                    CaseCommandRequest(
                        command_id=uuid4(),
                        case_id=SCRIPTED_CASE_ID,
                        command_type=CaseCommandType.APPEND_EVENT,
                        content="Review the fictional offer.",
                        event_type="consumer_message",
                        expected_revision=created.after_revision,
                    )
                )
                assert waiting.approval_expires_at is not None
                for _ in range(100):
                    current_run_id = (
                        await handle.describe()
                    ).raw_description.workflow_execution_info.execution.run_id
                    if current_run_id != first_run_id:
                        break
                    await asyncio.sleep(0.01)
                assert current_run_id != first_run_id
                await environment.sleep(timedelta(hours=2))
                for _ in range(100):
                    state = runtime.repository.get(SCRIPTED_CASE_ID)
                    if (
                        state is not None
                        and state.snapshot.approval_requests[0].decision.value
                        == "expired"
                    ):
                        break
                    await asyncio.sleep(0.01)

            state = runtime.repository.get(SCRIPTED_CASE_ID)
            assert state is not None
            approval = state.snapshot.approval_requests[0]
            assert approval.decision.value == "expired"
            assert approval.decided_at == approval.expires_at
            assert state.snapshot.visible_events[-1].actor.value == "system"
            assert state.snapshot.visible_events[-1].event_type == "approval_expired"
            assert state.execution_count == 0
            assert len(state.snapshot.evidence) == 1

    asyncio.run(scenario())


def test_time_skipping_approval_update_races_expiry_without_stale_execution() -> None:
    database_url = _database_url()
    _truncate(database_url)

    async def scenario() -> None:
        environment = await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter
        )
        async with environment:
            task_queue = f"proxyloop-phase05a-race-{uuid4()}"
            settings = TemporalSettings(task_queue=task_queue)
            runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
            temporal = TemporalCaseClient(environment.client, settings)
            gated_activity = _GatedApprovalActivity(runtime)
            worker = Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[CaseWorkflow],
                activities=[gated_activity.apply_command],
            )
            async with worker:
                created = await temporal.apply_command(_create_request())
                waiting = await temporal.apply_command(
                    CaseCommandRequest(
                        command_id=uuid4(),
                        case_id=SCRIPTED_CASE_ID,
                        command_type=CaseCommandType.APPEND_EVENT,
                        content="Review the fictional offer.",
                        event_type="consumer_message",
                        expected_revision=created.after_revision,
                    )
                )
                assert waiting.approval_id is not None
                assert waiting.approval_expires_at is not None
                remaining = (
                    waiting.approval_expires_at - await environment.get_current_time()
                )
                race_window = timedelta(seconds=1)
                assert remaining > race_window
                await environment.sleep(remaining - race_window)
                approval_request = CaseCommandRequest(
                    command_id=uuid4(),
                    case_id=SCRIPTED_CASE_ID,
                    command_type=CaseCommandType.DECIDE_APPROVAL,
                    approval_id=waiting.approval_id,
                    decision="approved",
                    expected_revision=waiting.after_revision,
                )
                handle = environment.client.get_workflow_handle(
                    temporal.workflow_id(SCRIPTED_CASE_ID)
                )
                accepted = await handle.start_update(
                    UPDATE_NAME,
                    approval_request,
                    wait_for_stage=WorkflowUpdateStage.ACCEPTED,
                    id=update_id_for_command(approval_request.command_id),
                    result_type=CaseTransitionRef,
                )
                result_task = asyncio.create_task(accepted.result())
                await asyncio.wait_for(gated_activity.entered.wait(), timeout=10)
                assert not result_task.done()
                await environment.sleep(race_window)
                assert (
                    await environment.get_current_time() >= waiting.approval_expires_at
                )
                assert not result_task.done()
                gated_activity.release.set()
                transition = await result_task
                assert transition.terminal is True
                for _ in range(100):
                    state = runtime.repository.get(SCRIPTED_CASE_ID)
                    if state is not None and (
                        state.snapshot.completion_decision is not None
                        or state.snapshot.approval_requests[0].decision.value
                        == "expired"
                    ):
                        break
                    await asyncio.sleep(0.01)

            state = runtime.repository.get(SCRIPTED_CASE_ID)
            assert state is not None
            decision = state.snapshot.approval_requests[0].decision.value
            assert decision == "approved"
            assert state.execution_count == 1
            assert state.snapshot.completion_decision is not None
            assert (
                len(
                    [
                        item
                        for item in state.snapshot.evidence
                        if item.source_type.value
                        in {"simulator_transition", "confirmation"}
                    ]
                )
                == 2
            )
            assert all(
                event.event_type != "approval_expired"
                for event in state.snapshot.visible_events
            )
            assert len(state.transitions) == 3

    asyncio.run(scenario())
