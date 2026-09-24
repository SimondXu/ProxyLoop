"""Model-backed Fast under Temporal (PR-11, spec pr11-fast-under-temporal-preflight).

The worker builds its Fast adapter from ``PROXYLOOP_FAST_BACKEND`` with the
API's refusal matrix (D1); the API lifts its Temporal refusal and labels
(D2); a typed Fast failure never fails the activity (D4); channel commands
keep the scripted Fast and the constant outbound body (D5-A). CI uses the
in-test fake gateway only. The two time-skipping tests follow PR-3: an
in-memory repository, the process-local test server, gated on
``PROXYLOOP_TEST_TEMPORAL_ADDRESS`` alone, run in ``phase05a-check``.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from local_fast_fake_gateway import FakeGateway
from proxyloop_agent_core import BOUNDED_FAST_STATUS_TEXT
from proxyloop_api import config as api_config
from proxyloop_case_runtime import (
    FAST_FALLBACK_TEXT,
    SCRIPTED_CASE_ID,
    CaseCommand,
    CaseCommandType,
    CaseTransitionRef,
    InMemoryCaseRepository,
    ThinAgentRuntime,
)
from proxyloop_connectors import (
    BINDING_REF,
    CHANNEL_KIND,
    LocalMailboxEventKind,
    VerifiedLocalMailboxEvent,
)
from proxyloop_contracts import ModelResult, Money
from proxyloop_local_fast import (
    MAX_TIMEOUT_S,
    LocalFastHttpAdapter,
    LocalFastStartupError,
)
from proxyloop_workflow_worker import (
    ACTIVITY_RETRY_POLICY,
    ACTIVITY_START_TO_CLOSE,
    CaseCommandActivityAdapter,
    CaseCommandRequest,
    TemporalCaseClient,
    TemporalReadinessResult,
    TemporalSettings,
    activity_for_adapter,
    channel_activity_for_adapter,
)
from proxyloop_workflow_worker import activities as worker_activities
from proxyloop_workflow_worker.workflow import CaseWorkflow
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from test_phase_06b1_channel_runtime import _ChannelRepository

WORKER_BASE = {
    "PROXYLOOP_STORAGE_MODE": "postgres",
    "PROXYLOOP_DATABASE_URL": "postgresql://unused.invalid/none",
}
_GATED = pytest.mark.skipif(
    not os.environ.get("PROXYLOOP_TEST_TEMPORAL_ADDRESS"),
    reason="PROXYLOOP_TEST_TEMPORAL_ADDRESS is required (runs in phase05a-check)",
)


@pytest.fixture
def gateway() -> Iterator[FakeGateway]:
    with FakeGateway(backend="distilled") as running:
        yield running


def _no_database(url: str) -> object:
    raise AssertionError("the worker opened the database before refusing")


def _local_worker_adapter(
    monkeypatch: pytest.MonkeyPatch,
    repository: InMemoryCaseRepository,
    environ: Mapping[str, str],
) -> CaseCommandActivityAdapter:
    monkeypatch.setattr(
        worker_activities, "PostgresCaseRepository", lambda _url: repository
    )
    return worker_activities.activity_adapter_from_environment(
        {**WORKER_BASE, **environ}
    )


def _create(occurred_at: datetime) -> CaseCommand:
    return CaseCommand(
        command_id=uuid4(),
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.CREATE_CASE,
        occurred_at=occurred_at,
        current_monthly_total=Money(amount_minor=9200, currency="USD"),
        target_monthly_total=Money(amount_minor=7500, currency="USD"),
        mobile_hotspot_required=True,
        device_financing_change_forbidden=True,
    )


def _consumer_turn(expected_revision: int, occurred_at: datetime) -> CaseCommand:
    return CaseCommand(
        command_id=uuid4(),
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.APPEND_EVENT,
        occurred_at=occurred_at,
        content="Please review the current offer.",
        event_type="consumer_message",
        expected_revision=expected_revision,
    )


def _ingest_request(
    repository: _ChannelRepository, expected_revision: int, now: datetime
) -> CaseCommandRequest:
    content = "Synthetic Provider message."
    event = VerifiedLocalMailboxEvent(
        event_id=uuid4(),
        binding_ref=BINDING_REF,
        occurred_at=now,
        kind=LocalMailboxEventKind.PROVIDER_MESSAGE,
        raw_payload_hash=hashlib.sha256(content.encode()).hexdigest(),
        content=content,
        fixture_timestamp=now,
    )
    inbox = repository.reserve_channel_event(event, received_at=now)
    return CaseCommandRequest(
        schema_version="phase-06b1-v1",
        command_id=inbox.command_id,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.INGEST_CHANNEL_EVENT,
        expected_revision=expected_revision,
        channel_occurred_at=now,
        channel_kind=CHANNEL_KIND,
        binding_ref=BINDING_REF,
        event_id=event.event_id,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        payload_hash=event.raw_payload_hash,
    )


def _fast_results(repository: InMemoryCaseRepository) -> list[tuple[Any, ...]]:
    return [
        (trace.result, trace.reason_codes)
        for trace in repository.list_model_traces(SCRIPTED_CASE_ID)
        if trace.role == "fast"
    ]


# --- D1: the worker selects Fast with the API's refusal matrix -------------


@pytest.mark.parametrize(
    ("environ", "error", "message"),
    [
        ({"PROXYLOOP_FAST_BACKEND": "bogus"}, ValueError, "PROXYLOOP_FAST_BACKEND"),
        (
            {
                "PROXYLOOP_FAST_BACKEND": "distilled",
                "PROXYLOOP_FAST_GATEWAY_URL": "http://10.0.0.5:8765",
            },
            ValueError,
            "loopback",
        ),
        (
            {"PROXYLOOP_FAST_BACKEND": "untuned", "PROXYLOOP_FAST_TIMEOUT_S": "0"},
            ValueError,
            "PROXYLOOP_FAST_TIMEOUT_S",
        ),
        (
            {"PROXYLOOP_FAST_BACKEND": "untuned", "PROXYLOOP_FAST_TIMEOUT_S": "25.5"},
            ValueError,
            "PROXYLOOP_FAST_TIMEOUT_S",
        ),
        (
            {"PROXYLOOP_FAST_BACKEND": "distilled", "PROXYLOOP_RUNTIME_MODE": "model"},
            ValueError,
            "scripted Runtime mode",
        ),
    ],
)
def test_worker_refuses_a_bad_fast_selection_before_the_database(
    monkeypatch: pytest.MonkeyPatch,
    environ: dict[str, str],
    error: type[Exception],
    message: str,
) -> None:
    # T1: on main the worker ignored the variable and opened the database.
    monkeypatch.setattr(worker_activities, "PostgresCaseRepository", _no_database)
    with pytest.raises(error, match=message):
        worker_activities.runtime_from_environment({**WORKER_BASE, **environ})


def test_worker_refuses_an_absent_or_mismatched_gateway(
    monkeypatch: pytest.MonkeyPatch, gateway: FakeGateway
) -> None:
    # T1 / L5: the same start-time identity probe as the API.
    monkeypatch.setattr(worker_activities, "PostgresCaseRepository", _no_database)
    with pytest.raises(LocalFastStartupError, match="backend"):
        worker_activities.runtime_from_environment(
            {
                **WORKER_BASE,
                "PROXYLOOP_FAST_BACKEND": "untuned",
                "PROXYLOOP_FAST_GATEWAY_URL": gateway.url,
            }
        )
    with FakeGateway(backend="distilled") as stopped:
        url = stopped.url
    with pytest.raises(LocalFastStartupError, match="unavailable"):
        worker_activities.runtime_from_environment(
            {
                **WORKER_BASE,
                "PROXYLOOP_FAST_BACKEND": "distilled",
                "PROXYLOOP_FAST_GATEWAY_URL": url,
            }
        )


def test_worker_selects_the_labelled_local_backend(
    monkeypatch: pytest.MonkeyPatch, gateway: FakeGateway
) -> None:
    # T2: Case commands get the local adapter; channel commands keep scripted
    # Fast over the same repository (D5-A).
    repository = _ChannelRepository()
    adapter = _local_worker_adapter(
        monkeypatch,
        repository,
        {
            "PROXYLOOP_FAST_BACKEND": "distilled",
            "PROXYLOOP_FAST_GATEWAY_URL": gateway.url,
        },
    )

    assert adapter.runtime.adapter_mode == "local_distilled_candidate"
    assert adapter.runtime.repository is repository
    assert adapter.channel_runtime is not adapter.runtime
    assert adapter.channel_runtime.adapter_mode == "scripted"
    assert adapter.channel_runtime.repository is repository


def test_worker_scripted_default_builds_one_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _ChannelRepository()
    adapter = _local_worker_adapter(monkeypatch, repository, {})

    assert adapter.runtime.adapter_mode == "scripted"
    assert adapter.channel_runtime is adapter.runtime


# --- D4: a typed Fast failure never fails the activity ---------------------


@pytest.mark.parametrize(
    ("behaviour", "code"),
    [
        ("busy", "fast_adapter_busy"),
        ("slow", "fast_adapter_timeout"),
        ("drop", "fast_adapter_unavailable"),
    ],
)
def test_a_fast_failure_applies_the_command_without_an_activity_error(
    gateway: FakeGateway, behaviour: str, code: str
) -> None:
    # T3: the activity returns a transition, so Temporal has nothing to retry.
    repository = InMemoryCaseRepository()
    fast = LocalFastHttpAdapter.connect(
        base_url=gateway.url, backend="distilled", timeout_s=0.5
    )
    adapter = CaseCommandActivityAdapter(ThinAgentRuntime(repository, fast=fast))
    now = datetime.now(UTC)
    created = adapter.apply_command(_create(now))
    gateway.behaviour = behaviour

    transition = adapter.apply_command(_consumer_turn(created.after_revision, now))

    assert isinstance(transition, CaseTransitionRef)
    assert transition.after_revision > created.after_revision
    assert len(gateway.raw_requests) == 1
    assert _fast_results(repository)[-1] == (ModelResult.FAILED, (code,))
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    line = state.snapshot.visible_events[-1]
    assert (line.event_type, line.content) == ("assistant_message", FAST_FALLBACK_TEXT)


# --- D5-A: channel commands keep the constant body -------------------------


def test_channel_ingest_under_a_local_backend_keeps_the_constant_body(
    monkeypatch: pytest.MonkeyPatch, gateway: FakeGateway
) -> None:
    # T4: I7 holds byte for byte and the model is never called.
    repository = _ChannelRepository()
    adapter = _local_worker_adapter(
        monkeypatch,
        repository,
        {
            "PROXYLOOP_FAST_BACKEND": "distilled",
            "PROXYLOOP_FAST_GATEWAY_URL": gateway.url,
        },
    )
    now = datetime.now(UTC)
    created = adapter.apply_command(_create(now))
    request = _ingest_request(repository, created.after_revision, now)

    transition = adapter.apply_command(request.to_command(now))

    assert transition.delivery_id is not None
    outbox = repository.outbox[transition.delivery_id]
    assert outbox.body == BOUNDED_FAST_STATUS_TEXT
    assert outbox.body_hash == hashlib.sha256(outbox.body.encode()).hexdigest()
    assert gateway.raw_requests == []
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    assert state.snapshot.visible_events[-1].event_type == "provider_message"


def test_one_local_runtime_for_every_command_would_fail_channel_ingest(
    gateway: FakeGateway,
) -> None:
    # T4, the hazard D5-A removes: the channel path's equality check fails
    # closed on a model line (or on a captured failure's missing decision).
    repository = _ChannelRepository()
    fast = LocalFastHttpAdapter.connect(base_url=gateway.url, backend="distilled")
    adapter = CaseCommandActivityAdapter(ThinAgentRuntime(repository, fast=fast))
    now = datetime.now(UTC)
    created = adapter.apply_command(_create(now))
    request = _ingest_request(repository, created.after_revision, now)

    with pytest.raises(ApplicationError) as raised:
        adapter.apply_command(request.to_command(now))

    assert raised.value.type == "model_path"
    assert raised.value.non_retryable


# --- D2: the API lifts its Temporal refusal --------------------------------


class _ReadyTemporal:
    @classmethod
    async def connect(cls, settings: TemporalSettings) -> _ReadyTemporal:
        del settings
        return cls()

    async def check_readiness(self) -> TemporalReadinessResult:
        return TemporalReadinessResult(ready=True)


def _temporal_api_environment(url: str, backend: str) -> dict[str, str]:
    return {
        "PROXYLOOP_ORCHESTRATION_MODE": "temporal",
        "PROXYLOOP_STORAGE_MODE": "postgres",
        "PROXYLOOP_DATABASE_URL": "postgresql://unused.invalid/none",
        "PROXYLOOP_FAST_BACKEND": backend,
        "PROXYLOOP_FAST_GATEWAY_URL": url,
    }


def test_temporal_api_starts_with_a_matching_gateway_and_labels_it(
    monkeypatch: pytest.MonkeyPatch, gateway: FakeGateway
) -> None:
    # T5: on main Temporal refused every non-scripted Fast backend.
    monkeypatch.setattr(
        api_config, "PostgresCaseRepository", lambda _url: InMemoryCaseRepository()
    )
    monkeypatch.setattr(api_config, "TemporalCaseClient", _ReadyTemporal)

    services = asyncio.run(
        api_config.services_from_environment(
            environ=_temporal_api_environment(gateway.url, "distilled")
        )
    )

    assert isinstance(services.temporal_client, _ReadyTemporal)
    assert services.runtime.adapter_mode == "local_distilled_candidate"


def test_temporal_api_refuses_an_absent_or_mismatched_gateway(
    monkeypatch: pytest.MonkeyPatch, gateway: FakeGateway
) -> None:
    monkeypatch.setattr(
        api_config, "PostgresCaseRepository", lambda _url: InMemoryCaseRepository()
    )
    monkeypatch.setattr(api_config, "TemporalCaseClient", _ReadyTemporal)
    with pytest.raises(LocalFastStartupError, match="backend"):
        asyncio.run(
            api_config.services_from_environment(
                environ=_temporal_api_environment(gateway.url, "untuned")
            )
        )
    with FakeGateway(backend="distilled") as stopped:
        url = stopped.url
    with pytest.raises(LocalFastStartupError, match="unavailable"):
        asyncio.run(
            api_config.services_from_environment(
                environ=_temporal_api_environment(url, "distilled")
            )
        )


# --- D3: the budget ---------------------------------------------------------


def test_the_fast_cap_fits_inside_the_activity_start_to_close() -> None:
    # T6: Fast ≤ 25 s leaves ≥ 5 s of the 30 s activity for everything else;
    # PR-11 changes neither limit nor the retry policy.
    assert ACTIVITY_START_TO_CLOSE.total_seconds() >= MAX_TIMEOUT_S + 5
    assert ACTIVITY_START_TO_CLOSE.total_seconds() == 30
    assert ACTIVITY_RETRY_POLICY.maximum_attempts == 5
    assert "model_path" in (ACTIVITY_RETRY_POLICY.non_retryable_error_types or ())


# --- Gated: the Workflow runs the activity once -----------------------------


class _CountingAdapter(CaseCommandActivityAdapter):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.applied: list[UUID] = []

    def apply_command(self, command: CaseCommand) -> Any:
        self.applied.append(command.command_id)
        return super().apply_command(command)


def _create_request() -> CaseCommandRequest:
    return CaseCommandRequest(
        command_id=uuid4(),
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.CREATE_CASE,
        current_monthly_total=Money(currency="USD", amount_minor=9200),
        target_monthly_total=Money(currency="USD", amount_minor=7500),
        mobile_hotspot_required=True,
        device_financing_change_forbidden=True,
    )


@_GATED
@pytest.mark.parametrize(
    ("behaviour", "code"),
    [("busy", "fast_adapter_busy"), ("slow", "fast_adapter_timeout")],
)
def test_time_skipping_fast_failure_runs_the_activity_once(
    behaviour: str, code: str
) -> None:
    """G1: the Update succeeds with the fallback; the activity ran once."""

    repository = InMemoryCaseRepository()

    async def scenario(gateway: FakeGateway) -> _CountingAdapter:
        fast = LocalFastHttpAdapter.connect(
            base_url=gateway.url, backend="distilled", timeout_s=0.5
        )
        adapter = _CountingAdapter(ThinAgentRuntime(repository, fast=fast))
        environment = await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter
        )
        async with environment:
            task_queue = f"proxyloop-pr11-fast-{uuid4()}"
            temporal = TemporalCaseClient(
                environment.client, TemporalSettings(task_queue=task_queue)
            )
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[CaseWorkflow],
                activities=[activity_for_adapter(adapter)],
            ):
                created = await temporal.apply_command(_create_request())
                gateway.behaviour = behaviour
                turn = CaseCommandRequest(
                    command_id=uuid4(),
                    case_id=SCRIPTED_CASE_ID,
                    command_type=CaseCommandType.APPEND_EVENT,
                    content="Please review the current offer.",
                    event_type="consumer_message",
                    expected_revision=created.after_revision,
                )
                transition = await temporal.apply_command(turn)
                assert transition.command_id == turn.command_id
        return adapter

    with FakeGateway(backend="distilled") as gateway:
        adapter = asyncio.run(scenario(gateway))
        assert len(gateway.raw_requests) == 1

    assert len(adapter.applied) == 2
    assert len(set(adapter.applied)) == 2
    assert _fast_results(repository)[-1] == (ModelResult.FAILED, (code,))
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    assert state.snapshot.visible_events[-1].content == FAST_FALLBACK_TEXT


@_GATED
def test_time_skipping_channel_ingest_under_a_local_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G2: the worker composition delivers the constant body, no model call."""

    repository = _ChannelRepository()

    async def scenario(gateway: FakeGateway) -> CaseTransitionRef:
        adapter = _local_worker_adapter(
            monkeypatch,
            repository,
            {
                "PROXYLOOP_FAST_BACKEND": "distilled",
                "PROXYLOOP_FAST_GATEWAY_URL": gateway.url,
            },
        )
        environment = await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter
        )
        async with environment:
            task_queue = f"proxyloop-pr11-channel-{uuid4()}"
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
                created = await temporal.apply_command(_create_request())
                request = _ingest_request(
                    repository, created.after_revision, datetime.now(UTC)
                )
                return await temporal.apply_command(request)

    with FakeGateway(backend="distilled") as gateway:
        transition = asyncio.run(scenario(gateway))
        assert gateway.raw_requests == []

    assert transition.delivery_id is not None
    outbox = repository.outbox[transition.delivery_id]
    assert outbox.body == BOUNDED_FAST_STATUS_TEXT
    assert outbox.state == "accepted"
