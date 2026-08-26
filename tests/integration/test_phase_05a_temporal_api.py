from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from proxyloop_api import create_app
from proxyloop_api.config import services_from_environment
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseTransitionRef,
    ThinAgentRuntime,
)
from proxyloop_workflow_worker import (
    CaseCommandRequest,
    TemporalDispatchError,
    TemporalReadinessResult,
)

CREATE_CASE_REQUEST = {
    "current_monthly_total": {"currency": "USD", "amount_minor": 9100},
    "target_monthly_total": {"currency": "USD", "amount_minor": 7200},
    "mobile_hotspot_required": True,
    "device_financing_change_forbidden": True,
}


class FakeTemporalCaseClient:
    def __init__(
        self,
        runtime: ThinAgentRuntime,
        *,
        ready: bool = True,
    ) -> None:
        self.runtime = runtime
        self.ready = ready
        self.commands: list[CaseCommandRequest] = []
        self.now = datetime(2035, 1, 1, tzinfo=UTC)

    async def apply_command(
        self,
        command: CaseCommandRequest,
    ) -> CaseTransitionRef:
        self.commands.append(command)
        result = self.runtime.apply_command(command.to_command(self.now))
        self.now += timedelta(seconds=1)
        return result

    async def check_readiness(self) -> TemporalReadinessResult:
        return TemporalReadinessResult(
            ready=self.ready,
            error_category="none" if self.ready else "dependency_not_ready",
        )


class FailingTemporalCaseClient(FakeTemporalCaseClient):
    def __init__(self, runtime: ThinAgentRuntime, category: str) -> None:
        super().__init__(runtime)
        self.category = category

    async def apply_command(
        self,
        command: CaseCommandRequest,
    ) -> CaseTransitionRef:
        del command
        raise TemporalDispatchError(self.category)


def _client_for(
    runtime: ThinAgentRuntime,
    temporal: FakeTemporalCaseClient,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=create_app(runtime, temporal_client=temporal)
        ),
        base_url="http://test",
    )


def test_temporal_api_dispatch_preserves_payload_and_command_deduplication() -> None:
    runtime = ThinAgentRuntime()
    temporal = FakeTemporalCaseClient(runtime)
    command_id = str(uuid4())

    async def request() -> tuple[httpx.Response, httpx.Response]:
        async with _client_for(runtime, temporal) as client:
            first = await client.post(
                "/cases",
                headers={"Idempotency-Key": command_id},
                json=CREATE_CASE_REQUEST,
            )
            duplicate = await client.post(
                "/cases",
                headers={"Idempotency-Key": command_id},
                json=CREATE_CASE_REQUEST,
            )
        return first, duplicate

    first, duplicate = asyncio.run(request())

    assert first.status_code == 201
    assert duplicate.status_code == 201
    assert first.json() == duplicate.json()
    assert first.json()["case_id"] == str(SCRIPTED_CASE_ID)
    assert len(temporal.commands) == 2
    assert temporal.commands[0].command_id == UUID(command_id)
    state = runtime.repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    assert len(state.transitions) == 1
    assert state.snapshot.visible_events[0].occurred_at == datetime(
        2035, 1, 1, tzinfo=UTC
    )


def test_temporal_api_rejects_noncanonical_idempotency_key() -> None:
    runtime = ThinAgentRuntime()
    temporal = FakeTemporalCaseClient(runtime)

    async def request() -> httpx.Response:
        async with _client_for(runtime, temporal) as client:
            return await client.post(
                "/cases",
                headers={"Idempotency-Key": str(uuid4()).upper()},
                json=CREATE_CASE_REQUEST,
            )

    response = asyncio.run(request())

    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "invalid_command", "message": "command rejected"}
    }
    assert temporal.commands == []


def test_temporal_readiness_is_explicit_and_redacted() -> None:
    runtime = ThinAgentRuntime()
    temporal = FakeTemporalCaseClient(runtime, ready=False)

    async def request() -> tuple[httpx.Response, httpx.Response]:
        async with _client_for(runtime, temporal) as client:
            live = await client.get("/health/live")
            ready = await client.get("/health/ready")
        return live, ready

    live, ready = asyncio.run(request())

    assert live.json()["orchestration_mode"] == "temporal"
    assert ready.status_code == 503
    assert ready.json() == {
        "status": "unavailable",
        "ready": False,
        "dependency": "temporal",
        "adapter_mode": "scripted",
        "storage_mode": "memory",
        "orchestration_mode": "temporal",
        "detail": {
            "code": "dependency_not_ready",
            "message": "configured dependency is not ready",
        },
    }


@pytest.mark.parametrize(
    "category, status, message",
    [
        ("state_invalid", 503, "stored Case state failed validation"),
        (
            "model_path",
            409,
            "model execution is unavailable in Temporal mode",
        ),
    ],
)
def test_temporal_domain_failures_keep_redacted_stable_categories(
    category: str,
    status: int,
    message: str,
) -> None:
    runtime = ThinAgentRuntime()
    temporal = FailingTemporalCaseClient(runtime, category)

    async def request() -> httpx.Response:
        async with _client_for(runtime, temporal) as client:
            return await client.post("/cases", json=CREATE_CASE_REQUEST)

    response = asyncio.run(request())
    assert response.status_code == status
    assert response.json() == {"detail": {"code": category, "message": message}}


@pytest.mark.parametrize(
    "values, message",
    [
        (
            {"PROXYLOOP_ORCHESTRATION_MODE": "unknown"},
            "PROXYLOOP_ORCHESTRATION_MODE must be direct or temporal",
        ),
        (
            {"PROXYLOOP_ORCHESTRATION_MODE": "temporal"},
            "Temporal orchestration requires PostgreSQL storage",
        ),
        (
            {
                "PROXYLOOP_ORCHESTRATION_MODE": "temporal",
                "PROXYLOOP_STORAGE_MODE": "postgres",
                "PROXYLOOP_DATABASE_URL": "postgresql://unused",
                "PROXYLOOP_RUNTIME_MODE": "model",
            },
            "Temporal orchestration requires scripted Runtime mode",
        ),
    ],
)
def test_temporal_mode_rejects_incompatible_configuration(
    values: dict[str, str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        asyncio.run(services_from_environment(environ=values))
