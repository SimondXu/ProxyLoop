from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
    CaseRuntimeState,
    CaseTransitionRef,
    PostgresCaseRepository,
    StorageUnavailableError,
    ThinAgentRuntime,
)
from proxyloop_case_runtime.commands import semantic_command_fingerprint
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
    COMMAND_ID_PREFIX,
    UPDATE_NAME,
    CaseWorkflow,
    activity_id_for_command,
    update_id_for_command,
)
from temporalio import activity
from temporalio import workflow as temporal_workflow
from temporalio.api.workflowservice.v1 import RegisterNamespaceRequest
from temporalio.client import (
    Client,
    WorkflowExecutionStatus,
    WorkflowHandle,
    WorkflowHistory,
    WorkflowUpdateFailedError,
    WorkflowUpdateHandle,
    WorkflowUpdateStage,
)
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

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


class _AppendPostCommitFaultingAdapter(CaseCommandActivityAdapter):
    """Fail the first ``APPEND_EVENT`` attempt after its commit only."""

    def __init__(self, runtime: ThinAgentRuntime) -> None:
        super().__init__(runtime)
        self.append_attempts = 0

    def apply_command(self, command: CaseCommand) -> CaseTransitionRef:
        transition = super().apply_command(command)
        if command.command_type is CaseCommandType.APPEND_EVENT:
            self.append_attempts += 1
            if self.append_attempts == 1:
                raise ApplicationError(
                    "injected post-commit", type="storage_unavailable"
                )
        return transition


class _ExhaustingAdapter(CaseCommandActivityAdapter):
    def __init__(self, runtime: ThinAgentRuntime, blocked_command_id: UUID) -> None:
        super().__init__(runtime)
        self.blocked_command_id = blocked_command_id
        self.blocked_attempts = 0
        self.blocking = True

    def apply_command(self, command: CaseCommand) -> CaseTransitionRef:
        if command.command_id == self.blocked_command_id:
            self.blocked_attempts += 1
            if self.blocking:
                raise ApplicationError(
                    "injected unavailable", type="storage_unavailable"
                )
        return super().apply_command(command)


class _ExpiryFaultingAdapter(CaseCommandActivityAdapter):
    """Fail inside the EXPIRE_APPROVAL activity only, until the switch flips."""

    def __init__(
        self,
        runtime: ThinAgentRuntime,
        *,
        error_type: str,
        non_retryable: bool = False,
    ) -> None:
        super().__init__(runtime)
        self.error_type = error_type
        self.non_retryable = non_retryable
        self.faulting = True
        self.expiry_attempts = 0
        self.other_commands: list[UUID] = []

    def apply_command(self, command: CaseCommand) -> CaseTransitionRef:
        if command.command_type is CaseCommandType.EXPIRE_APPROVAL:
            self.expiry_attempts += 1
            if self.faulting:
                raise ApplicationError(
                    "injected expiry fault",
                    type=self.error_type,
                    non_retryable=self.non_retryable,
                )
        else:
            self.other_commands.append(command.command_id)
        return super().apply_command(command)


class _FinalWriteOutageRepository(PostgresCaseRepository):
    """Lose the final approval write ``failures`` times, after the Provider is
    committed."""

    def __init__(self, database_url: str, *, failures: int = 1) -> None:
        self.final_write_failures = failures
        super().__init__(database_url)

    def replace(
        self,
        case_id: UUID,
        *,
        expected_revision: int,
        state: CaseRuntimeState,
    ) -> CaseRuntimeState:
        if (
            state.snapshot.completion_decision is not None
            and self.final_write_failures > 0
        ):
            self.final_write_failures -= 1
            raise StorageUnavailableError("injected final write outage")
        return super().replace(
            case_id,
            expected_revision=expected_revision,
            state=state,
        )


class _RecordingAdapter(CaseCommandActivityAdapter):
    """Record every activity attempt outcome per command id."""

    def __init__(self, runtime: ThinAgentRuntime) -> None:
        super().__init__(runtime)
        self.outcomes: dict[UUID, list[str]] = {}

    def apply_command(self, command: CaseCommand) -> CaseTransitionRef:
        attempts = self.outcomes.setdefault(command.command_id, [])
        try:
            transition = super().apply_command(command)
        except ApplicationError as exc:
            attempts.append(str(exc.type))
            raise
        attempts.append("terminal" if transition.terminal else "applied")
        return transition


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


class _GatedCommandActivity:
    """Hold one command's activity until released, so another Update queues."""

    def __init__(self, runtime: ThinAgentRuntime, gated_command_id: UUID) -> None:
        self.adapter = CaseCommandActivityAdapter(runtime)
        self.gated_command_id = gated_command_id
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    @activity.defn(name=ACTIVITY_NAME)
    async def apply_command(self, command: CaseCommand) -> CaseTransitionRef:
        if command.command_id == self.gated_command_id:
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


def test_live_temporal_approval_retry_after_final_write_outage_converges() -> None:
    async def scenario(database_url: str, address: str) -> None:
        task_queue = f"proxyloop-phase05a-claim-retry-{uuid4()}"
        settings = TemporalSettings(target_host=address, task_queue=task_queue)
        client, namespace = await _connected(address)
        settings = replace(settings, namespace=namespace)
        runtime = ThinAgentRuntime(_FinalWriteOutageRepository(database_url))
        adapter = _RecordingAdapter(runtime)
        temporal = TemporalCaseClient(client, settings)
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CaseWorkflow],
            activities=[activity_for_adapter(adapter)],
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
            approve_request = CaseCommandRequest(
                command_id=uuid4(),
                case_id=SCRIPTED_CASE_ID,
                command_type=CaseCommandType.DECIDE_APPROVAL,
                approval_id=waiting.approval_id,
                decision="approved",
                expected_revision=waiting.after_revision,
            )
            completed = await temporal.apply_command(approve_request)

        assert completed.terminal is True
        assert completed.deduplicated is False
        assert completed.before_revision == waiting.after_revision
        assert adapter.outcomes[approve_request.command_id] == [
            "storage_unavailable",
            "terminal",
        ]
        assert not any(
            "case_conflict" in outcomes for outcomes in adapter.outcomes.values()
        )
        state = PostgresCaseRepository(database_url).get(SCRIPTED_CASE_ID)
        assert state is not None
        assert state.snapshot.pending_execution is False
        assert state.execution_claim is None
        assert state.execution_count == 1
        assert [item.source_type.value for item in state.snapshot.evidence].count(
            "confirmation"
        ) == 1
        assert [item.value for item in state.provider.state_history].count(
            "confirmed"
        ) == 1
        assert len(state.transitions) == 3

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
                    id=update_id_for_command(
                        approval_request.command_id,
                        approval_request.semantic_fingerprint(),
                    ),
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


async def _pending_approval(temporal: TemporalCaseClient) -> CaseTransitionRef:
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
    return waiting


async def _wait_for_expiry_attempts(
    adapter: _ExpiryFaultingAdapter, expected: int
) -> None:
    # Activity retry backoff (1+2+4+8 s) runs on the server clock; poll in
    # real time rather than skipping, so a skip cannot time the activity out.
    for _ in range(600):
        if adapter.expiry_attempts >= expected:
            break
        await asyncio.sleep(0.05)
    assert adapter.expiry_attempts == expected


async def _workflow_status(
    environment: WorkflowEnvironment, temporal: TemporalCaseClient
) -> WorkflowExecutionStatus | None:
    handle = environment.client.get_workflow_handle(
        temporal.workflow_id(SCRIPTED_CASE_ID)
    )
    return (await handle.describe()).status


async def _later_distinct_update_reaches_runtime(
    adapter: _ExpiryFaultingAdapter,
    temporal: TemporalCaseClient,
    waiting: CaseTransitionRef,
) -> None:
    # No non-expiry command is valid while the approval is pending, so the
    # liveness proof is that the Update is executed by the Workflow and
    # rejected by the Runtime (``case_conflict``), not lost to a FAILED run.
    seen = len(adapter.other_commands)
    later = CaseCommandRequest(
        command_id=uuid4(),
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.APPEND_EVENT,
        content="A later distinct consumer message.",
        event_type="consumer_message",
        expected_revision=waiting.after_revision,
    )
    with pytest.raises(TemporalDispatchError) as raised:
        await temporal.apply_command(later)
    assert raised.value.category == "case_conflict"
    assert adapter.other_commands[seen:] == [later.command_id]


def test_time_skipping_expiry_retry_exhaustion_keeps_workflow_alive() -> None:
    database_url = _database_url()
    _truncate(database_url)

    async def scenario() -> None:
        environment = await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter
        )
        async with environment:
            task_queue = f"proxyloop-phase05a-expiry-fault-{uuid4()}"
            settings = TemporalSettings(task_queue=task_queue)
            runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
            temporal = TemporalCaseClient(environment.client, settings)
            adapter = _ExpiryFaultingAdapter(runtime, error_type="storage_unavailable")
            worker = Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[CaseWorkflow],
                activities=[activity_for_adapter(adapter)],
            )
            async with worker:
                waiting = await _pending_approval(temporal)
                assert waiting.approval_expires_at is not None
                # Skip to just past the expiry only: a longer skip would also
                # fire the Workflow-level retry timers and repeat the round.
                await environment.sleep(
                    waiting.approval_expires_at
                    - await environment.get_current_time()
                    + timedelta(seconds=1)
                )
                await _wait_for_expiry_attempts(adapter, 5)
                assert (
                    await _workflow_status(environment, temporal)
                    is WorkflowExecutionStatus.RUNNING
                )
                state = runtime.repository.get(SCRIPTED_CASE_ID)
                assert state is not None
                assert state.snapshot.approval_requests[0].decision.value == "pending"
                await _later_distinct_update_reaches_runtime(adapter, temporal, waiting)
                assert adapter.expiry_attempts == 5

                adapter.faulting = False
                # One exhausted round backs off for 15 s before the next. The
                # time-skipping server advances on the wall clock while no skip
                # is in progress, so the switch must flip within that 15 s
                # window (measured gap: well under 1 s) or a further round runs.
                await environment.sleep(timedelta(minutes=6))
                await _wait_for_expiry_attempts(adapter, 6)
                for _ in range(100):
                    state = runtime.repository.get(SCRIPTED_CASE_ID)
                    if (
                        state is not None
                        and state.snapshot.approval_requests[0].decision.value
                        == "expired"
                    ):
                        break
                    await asyncio.sleep(0.01)
                await environment.sleep(timedelta(hours=1))
                assert adapter.expiry_attempts == 6
                assert (
                    await _workflow_status(environment, temporal)
                    is WorkflowExecutionStatus.RUNNING
                )

            state = runtime.repository.get(SCRIPTED_CASE_ID)
            assert state is not None
            approval = state.snapshot.approval_requests[0]
            assert approval.decision.value == "expired"
            assert approval.decided_at == approval.expires_at
            assert (
                len(
                    [
                        event
                        for event in state.snapshot.visible_events
                        if event.event_type == "approval_expired"
                    ]
                )
                == 1
            )
            assert len(state.transitions) == 3

    asyncio.run(scenario())


def test_time_skipping_non_retryable_expiry_failure_does_not_spin() -> None:
    database_url = _database_url()
    _truncate(database_url)

    async def scenario() -> None:
        environment = await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter
        )
        async with environment:
            task_queue = f"proxyloop-phase05a-expiry-conflict-{uuid4()}"
            settings = TemporalSettings(task_queue=task_queue)
            runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
            temporal = TemporalCaseClient(environment.client, settings)
            adapter = _ExpiryFaultingAdapter(
                runtime, error_type="case_conflict", non_retryable=True
            )
            worker = Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[CaseWorkflow],
                activities=[activity_for_adapter(adapter)],
            )
            async with worker:
                waiting = await _pending_approval(temporal)
                await environment.sleep(timedelta(hours=2))
                await _wait_for_expiry_attempts(adapter, 1)
                assert (
                    await _workflow_status(environment, temporal)
                    is WorkflowExecutionStatus.RUNNING
                )
                await _later_distinct_update_reaches_runtime(adapter, temporal, waiting)
                await environment.sleep(timedelta(hours=1))
                await asyncio.sleep(0.5)
                assert adapter.expiry_attempts == 1
                assert (
                    await _workflow_status(environment, temporal)
                    is WorkflowExecutionStatus.RUNNING
                )

            state = runtime.repository.get(SCRIPTED_CASE_ID)
            assert state is not None
            assert state.snapshot.approval_requests[0].decision.value == "pending"
            assert len(state.transitions) == 2

    asyncio.run(scenario())


async def _pending_approval_in_second_run(
    environment: WorkflowEnvironment, temporal: TemporalCaseClient
) -> tuple[CaseCommandRequest, CaseCommandRequest, CaseTransitionRef]:
    # Temporal deduplicates an Update ID inside one run before the handler
    # runs, so a replayed command only reaches ``apply_case_command`` (and
    # the Runtime's stored receipt) once the Workflow has continued as new.
    create_request = _create_request()
    created = await temporal.apply_command(create_request)
    handle = environment.client.get_workflow_handle(
        temporal.workflow_id(SCRIPTED_CASE_ID)
    )
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
    assert waiting.approval_expires_at is not None
    for _ in range(100):
        current_run_id = (
            await handle.describe()
        ).raw_description.workflow_execution_info.execution.run_id
        if current_run_id != first_run_id:
            break
        await asyncio.sleep(0.01)
    assert current_run_id != first_run_id
    return create_request, append_request, waiting


# "append" is guard-only: its dedup receipt equals the pending transition,
# so it also passes pre-fix; "create" is the regression that failed on main.
@pytest.mark.parametrize("replayed", ["create", "append"])
def test_time_skipping_deduplicated_replay_keeps_pending_expiry(
    replayed: str,
) -> None:
    database_url = _database_url()
    _truncate(database_url)

    async def scenario() -> None:
        environment = await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter
        )
        async with environment:
            task_queue = f"proxyloop-phase05a-dedup-{uuid4()}"
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
                (
                    create_request,
                    append_request,
                    waiting,
                ) = await _pending_approval_in_second_run(environment, temporal)
                older = create_request if replayed == "create" else append_request
                replay = await temporal.apply_command(older)
                assert replay.deduplicated is True
                assert replay.command_id == older.command_id
                assert replay.after_revision <= waiting.after_revision

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
                assert (
                    await _workflow_status(environment, temporal)
                    is WorkflowExecutionStatus.RUNNING
                )

            state = runtime.repository.get(SCRIPTED_CASE_ID)
            assert state is not None
            approval = state.snapshot.approval_requests[0]
            assert approval.decision.value == "expired"
            assert approval.decided_at == approval.expires_at
            assert (
                len(
                    [
                        event
                        for event in state.snapshot.visible_events
                        if event.event_type == "approval_expired"
                    ]
                )
                == 1
            )
            assert len(state.transitions) == 3

    asyncio.run(scenario())


def test_time_skipping_post_commit_retry_receipt_keeps_pending_expiry() -> None:
    database_url = _database_url()
    _truncate(database_url)

    async def scenario() -> None:
        environment = await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter
        )
        async with environment:
            task_queue = f"proxyloop-phase05a-retry-receipt-{uuid4()}"
            settings = TemporalSettings(task_queue=task_queue)
            runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
            temporal = TemporalCaseClient(environment.client, settings)
            adapter = _AppendPostCommitFaultingAdapter(runtime)
            worker = Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[CaseWorkflow],
                activities=[activity_for_adapter(adapter)],
            )
            async with worker:
                created = await temporal.apply_command(_create_request())
                # The first attempt commits then fails to report; the activity
                # retry returns the stored receipt, which is newer than the
                # create receipt and must become the Workflow's last transition.
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
                assert adapter.append_attempts == 2
                assert waiting.deduplicated is True
                assert waiting.approval_id is not None
                assert waiting.approval_expires_at is not None
                assert waiting.after_revision > created.after_revision

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
                assert (
                    await _workflow_status(environment, temporal)
                    is WorkflowExecutionStatus.RUNNING
                )

            state = runtime.repository.get(SCRIPTED_CASE_ID)
            assert state is not None
            approval = state.snapshot.approval_requests[0]
            assert approval.decision.value == "expired"
            assert approval.decided_at == approval.expires_at
            assert (
                len(
                    [
                        event
                        for event in state.snapshot.visible_events
                        if event.event_type == "approval_expired"
                    ]
                )
                == 1
            )
            assert len(state.transitions) == 3

    asyncio.run(scenario())


def _append_request(command_id: UUID, expected_revision: int) -> CaseCommandRequest:
    return CaseCommandRequest(
        command_id=command_id,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.APPEND_EVENT,
        content="Review the fictional offer.",
        event_type="consumer_message",
        expected_revision=expected_revision,
    )


def test_update_id_binds_command_id_and_semantic_request() -> None:
    command_id = UUID("A1B2C3D4-E5F6-4A7B-8C9D-0E1F2A3B4C5D")
    stale = _append_request(command_id, 7)
    current = _append_request(command_id, 2)

    stale_id = update_id_for_command(command_id, stale.semantic_fingerprint())
    assert stale_id == update_id_for_command(
        command_id, _append_request(command_id, 7).semantic_fingerprint()
    )
    assert stale_id == stale_id.lower()
    assert stale_id.startswith(f"{COMMAND_ID_PREFIX}{str(command_id).lower()}:")
    assert stale_id != update_id_for_command(command_id, current.semantic_fingerprint())
    # Recorded histories carry the Activity ID; its format must not change.
    assert activity_id_for_command(command_id) == (
        f"{COMMAND_ID_PREFIX}{str(command_id).lower()}"
    )


def test_request_fingerprint_matches_runtime_receipt_fingerprint() -> None:
    requests = [
        _create_request(),
        _append_request(uuid4(), 2),
        CaseCommandRequest(
            command_id=uuid4(),
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.DECIDE_APPROVAL,
            approval_id=uuid4(),
            decision="approved",
            expected_revision=3,
        ),
        CaseCommandRequest(
            command_id=uuid4(),
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.EXPIRE_APPROVAL,
            approval_id=uuid4(),
            expected_revision=3,
            approval_expires_at=datetime(2026, 8, 26, 14, tzinfo=UTC),
        ),
        _ingest_request(datetime(2026, 8, 26, 12, tzinfo=UTC)),
        CaseCommandRequest(
            schema_version="phase-06b1-v1",
            command_id=uuid4(),
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.RECORD_CHANNEL_DELIVERY,
            expected_revision=4,
            channel_occurred_at=datetime(2026, 8, 26, 12, 5, tzinfo=UTC),
            channel_kind="local_mailbox",
            binding_ref="fictional-provider-local-mailbox",
            event_id=uuid4(),
            delivery_id=uuid4(),
            provider_message_id="local-provider-1",
            delivery_status="delivered",
            artifact_hash="b" * 64,
            payload_hash="b" * 64,
        ),
    ]
    for request in requests:
        for occurred_at in (
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2027, 6, 1, 12, tzinfo=UTC),
        ):
            command = request.to_command(occurred_at)
            assert request.semantic_fingerprint() == semantic_command_fingerprint(
                command
            )
            round_trip = CaseCommandRequest.from_command(command)
            assert round_trip == request
            assert round_trip.semantic_fingerprint() == request.semantic_fingerprint()

    # ``channel_occurred_at`` becomes ``occurred_at``, which the Runtime
    # fingerprint excludes, so it is not part of the request fingerprint.
    assert (
        _ingest_request(datetime(2026, 8, 26, 12, tzinfo=UTC)).semantic_fingerprint()
        == _ingest_request(datetime(2026, 8, 27, 9, tzinfo=UTC)).semantic_fingerprint()
    )


_INGEST_COMMAND_ID = UUID("b1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")
_INGEST_EVENT_ID = UUID("c1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")


def _ingest_request(channel_occurred_at: datetime) -> CaseCommandRequest:
    return CaseCommandRequest(
        schema_version="phase-06b1-v1",
        command_id=_INGEST_COMMAND_ID,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.INGEST_CHANNEL_EVENT,
        expected_revision=2,
        channel_occurred_at=channel_occurred_at,
        channel_kind="local_mailbox",
        binding_ref="fictional-provider-local-mailbox",
        event_id=_INGEST_EVENT_ID,
        content_hash="a" * 64,
        payload_hash="c" * 64,
    )


def test_live_temporal_corrected_retry_of_conflicted_command_executes() -> None:
    """T1 (audit C-4): a corrected body under the same command id is not
    answered with the cached ``case_conflict`` of the stale body."""

    async def scenario(database_url: str, address: str) -> None:
        task_queue = f"proxyloop-phase05a-corrected-{uuid4()}"
        settings = TemporalSettings(target_host=address, task_queue=task_queue)
        client, namespace = await _connected(address)
        settings = replace(settings, namespace=namespace)
        runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
        adapter = _RecordingAdapter(runtime)
        temporal = TemporalCaseClient(client, settings)
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CaseWorkflow],
            activities=[activity_for_adapter(adapter)],
        )
        command_id = uuid4()
        async with worker:
            created = await temporal.apply_command(_create_request())
            with pytest.raises(TemporalDispatchError) as raised:
                await temporal.apply_command(
                    _append_request(command_id, created.after_revision + 5)
                )
            corrected = await temporal.apply_command(
                _append_request(command_id, created.after_revision)
            )

        assert raised.value.category == "case_conflict"
        assert corrected.command_id == command_id
        assert corrected.deduplicated is False
        assert corrected.before_revision == created.after_revision
        assert corrected.after_revision > created.after_revision
        assert adapter.outcomes[command_id] == ["case_conflict", "applied"]
        state = runtime.repository.get(SCRIPTED_CASE_ID)
        assert state is not None
        assert len(state.transitions) == 2

    _run_live(scenario)


def test_live_temporal_identical_retry_keeps_cached_outcome() -> None:
    """T2: identical retries do not re-execute a failed or successful command."""

    async def scenario(database_url: str, address: str) -> None:
        task_queue = f"proxyloop-phase05a-identical-{uuid4()}"
        settings = TemporalSettings(target_host=address, task_queue=task_queue)
        client, namespace = await _connected(address)
        settings = replace(settings, namespace=namespace)
        runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
        adapter = _RecordingAdapter(runtime)
        temporal = TemporalCaseClient(client, settings)
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CaseWorkflow],
            activities=[activity_for_adapter(adapter)],
        )
        failed_id = uuid4()
        succeeded_id = uuid4()
        async with worker:
            created = await temporal.apply_command(_create_request())
            stale = _append_request(failed_id, created.after_revision + 5)
            categories = []
            for _ in range(2):
                with pytest.raises(TemporalDispatchError) as raised:
                    await temporal.apply_command(stale)
                categories.append(raised.value.category)
            success = _append_request(succeeded_id, created.after_revision)
            first = await temporal.apply_command(success)
            repeated = await temporal.apply_command(success)

        assert categories == ["case_conflict", "case_conflict"]
        assert adapter.outcomes[failed_id] == ["case_conflict"]
        assert adapter.outcomes[succeeded_id] == ["applied"]
        assert repeated == first
        state = runtime.repository.get(SCRIPTED_CASE_ID)
        assert state is not None
        assert len(state.transitions) == 2

    _run_live(scenario)


def test_live_temporal_changed_body_after_success_is_runtime_conflict() -> None:
    """T3: a reused command id with a different body after success reaches the
    Runtime's receipt fingerprint check instead of the cached success."""

    async def scenario(database_url: str, address: str) -> None:
        task_queue = f"proxyloop-phase05a-reused-{uuid4()}"
        settings = TemporalSettings(target_host=address, task_queue=task_queue)
        client, namespace = await _connected(address)
        settings = replace(settings, namespace=namespace)
        runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
        adapter = _RecordingAdapter(runtime)
        temporal = TemporalCaseClient(client, settings)
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CaseWorkflow],
            activities=[activity_for_adapter(adapter)],
        )
        command_id = uuid4()
        async with worker:
            created = await temporal.apply_command(_create_request())
            applied = await temporal.apply_command(
                _append_request(command_id, created.after_revision)
            )
            changed = CaseCommandRequest(
                command_id=command_id,
                case_id=SCRIPTED_CASE_ID,
                command_type=CaseCommandType.APPEND_EVENT,
                content="A different fictional message.",
                event_type="consumer_message",
                expected_revision=created.after_revision,
            )
            with pytest.raises(TemporalDispatchError) as raised:
                await temporal.apply_command(changed)

        assert applied.deduplicated is False
        assert raised.value.category == "case_conflict"
        assert adapter.outcomes[command_id] == ["applied", "case_conflict"]
        state = runtime.repository.get(SCRIPTED_CASE_ID)
        assert state is not None
        assert len(state.transitions) == 2
        assert state.transitions[-1].after_revision == applied.after_revision

    _run_live(scenario)


async def _run_id(handle: WorkflowHandle) -> str:
    description = await handle.describe()
    return description.raw_description.workflow_execution_info.execution.run_id


async def _start_queued(
    handle: WorkflowHandle, request: CaseCommandRequest
) -> WorkflowUpdateHandle[CaseTransitionRef]:
    # ACCEPTED means the handler has started and is waiting on the lock.
    return await handle.start_update(
        UPDATE_NAME,
        request,
        wait_for_stage=WorkflowUpdateStage.ACCEPTED,
        id=update_id_for_command(request.command_id, request.semantic_fingerprint()),
        result_type=CaseTransitionRef,
    )


def _failure_type(error: BaseException) -> str | None:
    # The first ApplicationError is the activity's category; deeper ones are
    # the converted Python causes.
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, ApplicationError) and current.type:
            return current.type
        current = current.__cause__
    return None


def test_live_temporal_identical_retry_after_exhaustion_reaches_runtime() -> None:
    """R-1 T1: retryable exhaustion rolls the run, so the identical retry is
    executed instead of answered with the cached ``temporal_unavailable``."""

    async def scenario(database_url: str, address: str) -> None:
        task_queue = f"proxyloop-phase05a-exhausted-retry-{uuid4()}"
        settings = TemporalSettings(target_host=address, task_queue=task_queue)
        client, namespace = await _connected(address)
        settings = replace(settings, namespace=namespace)
        runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
        blocked_id = uuid4()
        adapter = _ExhaustingAdapter(runtime, blocked_id)
        temporal = TemporalCaseClient(client, settings)
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CaseWorkflow],
            activities=[activity_for_adapter(adapter)],
        )
        async with worker:
            created = await temporal.apply_command(_create_request())
            handle = client.get_workflow_handle(temporal.workflow_id(SCRIPTED_CASE_ID))
            first_run_id = await _run_id(handle)
            blocked = _append_request(blocked_id, created.after_revision)
            with pytest.raises(TemporalDispatchError) as raised:
                await temporal.apply_command(blocked)
            adapter.blocking = False
            retried = await temporal.apply_command(blocked)
            final_run_id = await _run_id(handle)

        assert raised.value.category == "temporal_unavailable"
        assert adapter.blocked_attempts == 6
        assert retried.command_id == blocked_id
        assert retried.deduplicated is False
        assert retried.approval_id is not None
        assert final_run_id != first_run_id
        state = runtime.repository.get(SCRIPTED_CASE_ID)
        assert state is not None
        assert len(state.transitions) == 2

    _run_live(scenario)


def test_live_temporal_identical_approval_retry_finishes_exhausted_claim() -> None:
    """R-1 T2: an approval whose final write exhausted the activity retries is
    finished by its own identical retry, without a second Provider execution."""

    async def scenario(database_url: str, address: str) -> None:
        task_queue = f"proxyloop-phase05a-exhausted-claim-{uuid4()}"
        settings = TemporalSettings(target_host=address, task_queue=task_queue)
        client, namespace = await _connected(address)
        settings = replace(settings, namespace=namespace)
        runtime = ThinAgentRuntime(
            _FinalWriteOutageRepository(database_url, failures=5)
        )
        adapter = _RecordingAdapter(runtime)
        temporal = TemporalCaseClient(client, settings)
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CaseWorkflow],
            activities=[activity_for_adapter(adapter)],
        )
        async with worker:
            waiting = await _pending_approval(temporal)
            approve_request = CaseCommandRequest(
                command_id=uuid4(),
                case_id=SCRIPTED_CASE_ID,
                command_type=CaseCommandType.DECIDE_APPROVAL,
                approval_id=waiting.approval_id,
                decision="approved",
                expected_revision=waiting.after_revision,
            )
            with pytest.raises(TemporalDispatchError) as raised:
                await temporal.apply_command(approve_request)
            stuck = PostgresCaseRepository(database_url).get(SCRIPTED_CASE_ID)
            completed = await temporal.apply_command(approve_request)

        assert raised.value.category == "temporal_unavailable"
        assert stuck is not None
        assert stuck.snapshot.pending_execution is True
        assert stuck.execution_claim is not None
        assert completed.terminal is True
        assert adapter.outcomes[approve_request.command_id] == [
            *["storage_unavailable"] * 5,
            "terminal",
        ]
        state = PostgresCaseRepository(database_url).get(SCRIPTED_CASE_ID)
        assert state is not None
        assert state.snapshot.pending_execution is False
        assert state.execution_claim is None
        assert state.execution_count == 1
        assert [item.source_type.value for item in state.snapshot.evidence].count(
            "confirmation"
        ) == 1
        assert [item.value for item in state.provider.state_history].count(
            "confirmed"
        ) == 1

    _run_live(scenario)


def test_live_temporal_exhaustion_with_queued_command_rolls_after_it() -> None:
    """R-1 T3: a command queued behind the exhausted one still runs, and the
    exhausted command's identical retry then reaches the Runtime."""

    async def scenario(database_url: str, address: str) -> None:
        task_queue = f"proxyloop-phase05a-exhausted-queued-{uuid4()}"
        settings = TemporalSettings(target_host=address, task_queue=task_queue)
        client, namespace = await _connected(address)
        settings = replace(settings, namespace=namespace)
        runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
        blocked_id = uuid4()
        adapter = _ExhaustingAdapter(runtime, blocked_id)
        temporal = TemporalCaseClient(client, settings)
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CaseWorkflow],
            activities=[activity_for_adapter(adapter)],
        )
        async with worker:
            created = await temporal.apply_command(_create_request())
            handle = client.get_workflow_handle(temporal.workflow_id(SCRIPTED_CASE_ID))
            first_run_id = await _run_id(handle)
            blocked = _append_request(blocked_id, created.after_revision)
            blocked_task = asyncio.create_task(temporal.apply_command(blocked))
            for _ in range(200):
                if adapter.blocked_attempts >= 1:
                    break
                await asyncio.sleep(0.05)
            assert adapter.blocked_attempts >= 1
            queued_request = _append_request(uuid4(), created.after_revision)
            queued = await _start_queued(handle, queued_request)
            with pytest.raises(TemporalDispatchError) as raised:
                await blocked_task
            queued_result = await asyncio.wait_for(queued.result(), timeout=30)
            adapter.blocking = False
            with pytest.raises(TemporalDispatchError) as retried:
                await temporal.apply_command(blocked)
            final_run_id = await _run_id(handle)

        assert raised.value.category == "temporal_unavailable"
        assert queued_result.command_id == queued_request.command_id
        assert queued_result.deduplicated is False
        assert retried.value.category == "case_conflict"
        assert adapter.blocked_attempts == 6
        assert final_run_id != first_run_id
        state = runtime.repository.get(SCRIPTED_CASE_ID)
        assert state is not None
        assert len(state.transitions) == 2
        assert state.transitions[-1].after_revision == queued_result.after_revision

    _run_live(scenario)


def test_live_temporal_continue_as_new_waits_for_queued_command() -> None:
    """R-1b T4: reaching the Continue-As-New threshold while another Update is
    queued on the lock must not spin the Workflow task; both complete."""

    async def scenario(database_url: str, address: str) -> None:
        task_queue = f"proxyloop-phase05a-threshold-queued-{uuid4()}"
        settings = TemporalSettings(
            target_host=address,
            task_queue=task_queue,
            continue_as_new_after=2,
        )
        client, namespace = await _connected(address)
        settings = replace(settings, namespace=namespace)
        runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
        stuck_id = uuid4()
        gated = _GatedCommandActivity(runtime, stuck_id)
        temporal = TemporalCaseClient(client, settings)
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CaseWorkflow],
            activities=[gated.apply_command],
        )
        async with worker:
            created = await temporal.apply_command(_create_request())
            handle = client.get_workflow_handle(temporal.workflow_id(SCRIPTED_CASE_ID))
            first_run_id = await _run_id(handle)
            stuck_request = _append_request(stuck_id, created.after_revision)
            stuck_task = asyncio.create_task(temporal.apply_command(stuck_request))
            await asyncio.wait_for(gated.entered.wait(), timeout=10)
            queued_request = _append_request(uuid4(), created.after_revision)
            queued = await _start_queued(handle, queued_request)
            gated.release.set()
            try:
                stuck_result = await asyncio.wait_for(stuck_task, timeout=30)
                with pytest.raises(WorkflowUpdateFailedError) as queued_failed:
                    await asyncio.wait_for(queued.result(), timeout=30)
            finally:
                stuck_task.cancel()
            for _ in range(100):
                final_run_id = await _run_id(handle)
                if final_run_id != first_run_id:
                    break
                await asyncio.sleep(0.05)

        assert stuck_result.command_id == stuck_id
        assert stuck_result.approval_id is not None
        # The queued append reached the Runtime, which refuses it because the
        # stuck append moved the Case to a pending approval.
        assert _failure_type(queued_failed.value) == "case_conflict"
        assert final_run_id != first_run_id
        state = runtime.repository.get(SCRIPTED_CASE_ID)
        assert state is not None
        assert len(state.transitions) == 2

    _run_live(scenario)


# Recorded on main @ 14d3fcf (before R-1) against the Compose Temporal: create,
# an append that exhausts five ``storage_unavailable`` attempts, then a
# distinct append that succeeds in the same run. Stack traces and client
# identities were blanked.
_PRE_R1_HISTORY = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "temporal_history.case-workflow-exhaustion-then-success.pre-r1.json"
)


def test_replay_pre_r1_history_keeps_the_patch_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R-1 T5: a history recorded before the fix replays on the patched code,
    and would not replay if the roll were not behind ``workflow.patched``."""

    history = WorkflowHistory.from_json(
        f"proxyloop-case/{SCRIPTED_CASE_ID}",
        _PRE_R1_HISTORY.read_text(encoding="utf-8"),
    )

    async def replay(runner: UnsandboxedWorkflowRunner | None = None) -> None:
        replayer = (
            Replayer(
                workflows=[CaseWorkflow],
                data_converter=pydantic_data_converter,
            )
            if runner is None
            else Replayer(
                workflows=[CaseWorkflow],
                data_converter=pydantic_data_converter,
                workflow_runner=runner,
            )
        )
        await replayer.replay_workflow(history)

    asyncio.run(replay())

    # Forcing the patch on during replay stands in for an ungated change.
    monkeypatch.setattr(temporal_workflow, "patched", lambda patch_id: True)
    with pytest.raises(temporal_workflow.NondeterminismError, match="Continue as new"):
        asyncio.run(replay(UnsandboxedWorkflowRunner()))
