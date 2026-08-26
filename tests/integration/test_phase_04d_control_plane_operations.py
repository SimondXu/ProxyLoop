from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID, uuid4

import httpx
import pytest
from proxyloop_api import (
    OPERATION_RECORD_FIELDS,
    InMemoryOperationRecorder,
    JsonLoggingOperationRecorder,
    StorageUnavailableError,
    ThinAgentRuntime,
    create_app,
)
from proxyloop_openai_adapter import ModelFailureKind, OpenAICompatibleAdapterError

from scripts.run_phase_04d_control_plane_profile import _run_profile

CREATE_CASE_REQUEST = {
    "current_monthly_total": {"amount_minor": 9200, "currency": "USD"},
    "target_monthly_total": {"amount_minor": 7500, "currency": "USD"},
    "mobile_hotspot_required": True,
    "device_financing_change_forbidden": True,
}


class _FailingSlowAdapter:
    def __init__(self, kind: ModelFailureKind) -> None:
        self.kind = kind

    def reason(self, _request: object) -> object:
        raise OpenAICompatibleAdapterError(self.kind)


class _UnavailableRepository:
    def get(self, _case_id: UUID) -> None:
        raise StorageUnavailableError("storage operation failed")


class _UnhandledRepository:
    def get(self, _case_id: UUID) -> None:
        raise RuntimeError("raw repository secret")


class _ThrowingRecorder:
    def __init__(self) -> None:
        self.calls = 0

    def record(self, _record: object) -> None:
        self.calls += 1
        raise RuntimeError("raw recorder secret")


class _ProbeRepository:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.readiness_calls = 0
        self.case_calls = 0
        self.unavailable = unavailable

    def check_readiness(self) -> None:
        self.readiness_calls += 1
        if self.unavailable:
            raise StorageUnavailableError("password=secret")

    def get(self, _case_id: UUID) -> None:
        self.case_calls += 1
        raise AssertionError("readiness must not read a Case")


class _CountingSlowAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def reason(self, _request: object) -> object:
        self.calls += 1
        raise AssertionError("readiness must not dispatch a model")


def test_case_and_health_requests_emit_one_allowlisted_correlated_record() -> None:
    asyncio.run(_test_case_and_health_requests_emit_one_record())


async def _test_case_and_health_requests_emit_one_record() -> None:
    recorder = InMemoryOperationRecorder()
    app = create_app(ThinAgentRuntime(), recorder=recorder)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        live = await client.get("/health/live")
        ready = await client.get("/health/ready")
        created = await client.post("/cases", json=CREATE_CASE_REQUEST)
        missing = await client.get(f"/cases/{uuid4()}")

    assert live.status_code == 200
    assert ready.status_code == 200
    assert created.status_code == 201
    assert missing.status_code == 404
    assert len(recorder.records) == 4
    assert all(record.correlation_id for record in recorder.records)
    assert len({record.correlation_id for record in recorder.records}) == 4
    assert all(
        set(record.as_json()) == set(recorder.records[0].as_json())
        for record in recorder.records
    )
    assert recorder.records[0].operation == "health_live"
    assert recorder.records[1].operation == "health_ready"
    assert recorder.records[2].error_category == "none"
    assert recorder.records[2].case_id == created.json()["case_id"]
    assert recorder.records[3].error_category == "case_not_found"
    assert recorder.records[2].verifier_outcome == "not_done"
    assert "detail" not in recorder.records[2].as_json()
    assert {
        response.headers["X-ProxyLoop-Correlation-ID"]
        for response in (live, ready, created, missing)
    } == {record.correlation_id for record in recorder.records}


def test_default_recorder_logs_allowlisted_json_without_retaining_records(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def request() -> tuple[httpx.Response, object]:
        app = create_app(ThinAgentRuntime())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get(
                "/health/live",
                headers={"X-ProxyLoop-Correlation-ID": "forged-by-client"},
            )
        return response, app

    caplog.set_level(logging.INFO, logger="proxyloop_api.operations")
    response, app = asyncio.run(request())
    emitted = [
        item.message
        for item in caplog.records
        if item.name == "proxyloop_api.operations"
    ]
    assert response.status_code == 200
    assert response.headers["X-ProxyLoop-Correlation-ID"] != "forged-by-client"
    assert emitted
    payload = json.loads(emitted[-1])
    assert set(payload) == OPERATION_RECORD_FIELDS
    assert payload["correlation_id"] == response.headers["X-ProxyLoop-Correlation-ID"]
    assert isinstance(app.state.operation_recorder, JsonLoggingOperationRecorder)
    assert logging.getLogger("proxyloop_api.operations").isEnabledFor(logging.INFO)


def test_pending_approval_record_is_not_labeled_policy_approved() -> None:
    async def request(recorder: InMemoryOperationRecorder) -> None:
        app = create_app(ThinAgentRuntime(), recorder=recorder)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            created = await client.post("/cases", json=CREATE_CASE_REQUEST)
            await client.post(
                f"/cases/{created.json()['case_id']}/events",
                json={"content": "Review the offer."},
            )

    recorder = InMemoryOperationRecorder()
    asyncio.run(request(recorder))
    assert recorder.records[-1].policy_outcome == "approval_required"
    assert recorder.records[-1].approval_outcome == "pending"
    assert recorder.records[-1].verifier_outcome == "not_done"


def test_unmatched_route_never_logs_raw_path() -> None:
    async def request(recorder: InMemoryOperationRecorder) -> httpx.Response:
        app = create_app(ThinAgentRuntime(), recorder=recorder)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get("/raw-secret-path/credential=secret")

    recorder = InMemoryOperationRecorder()
    response = asyncio.run(request(recorder))
    record = recorder.records[0]
    assert response.status_code == 404
    assert record.route == "<unmatched>"
    assert record.operation == "<unmatched>"
    assert "raw-secret-path" not in json.dumps(record.as_json())
    assert "credential=secret" not in json.dumps(record.as_json())


def test_invalid_case_uuid_is_redacted_and_classified_as_request_invalid() -> None:
    async def request(recorder: InMemoryOperationRecorder) -> httpx.Response:
        app = create_app(ThinAgentRuntime(), recorder=recorder)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get("/cases/credential-secret-not-a-uuid")

    recorder = InMemoryOperationRecorder()
    response = asyncio.run(request(recorder))
    record = recorder.records[0]
    assert response.status_code == 422
    assert record.case_id is None
    assert record.error_category == "request_invalid"
    assert "credential-secret-not-a-uuid" not in json.dumps(record.as_json())


def test_unhandled_error_is_redacted_inside_middleware_with_correlation_header() -> (
    None
):
    async def request(recorder: InMemoryOperationRecorder) -> httpx.Response:
        app = create_app(
            ThinAgentRuntime(repository=_UnhandledRepository()), recorder=recorder
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get(f"/cases/{uuid4()}")

    recorder = InMemoryOperationRecorder()
    response = asyncio.run(request(recorder))
    assert response.status_code == 500
    assert response.json() == {
        "detail": {
            "code": "internal_error",
            "message": "internal operation failed safely",
        }
    }
    assert response.headers["X-ProxyLoop-Correlation-ID"]
    assert "raw repository secret" not in response.text
    assert recorder.records[0].error_category == "internal_error"


def test_throwing_recorder_falls_back_to_one_redacted_json_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def request(recorder: _ThrowingRecorder) -> httpx.Response:
        app = create_app(ThinAgentRuntime(), recorder=recorder)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get("/health/live")

    caplog.set_level(logging.INFO, logger="proxyloop_api.operations")
    recorder = _ThrowingRecorder()
    response = asyncio.run(request(recorder))
    emitted = [
        item.message
        for item in caplog.records
        if item.name == "proxyloop_api.operations"
    ]
    assert response.status_code == 200
    assert response.headers["X-ProxyLoop-Correlation-ID"]
    assert recorder.calls == 1
    assert len(emitted) == 1
    payload = json.loads(emitted[0])
    assert set(payload) == OPERATION_RECORD_FIELDS
    assert "raw recorder secret" not in caplog.text


def test_model_timeout_and_storage_failure_are_redacted_and_classified() -> None:
    asyncio.run(_test_model_timeout_and_storage_failure())


async def _test_model_timeout_and_storage_failure() -> None:
    timeout_recorder = InMemoryOperationRecorder()
    timeout_runtime = ThinAgentRuntime(
        fast=_FailingSlowAdapter(ModelFailureKind.TIMEOUT),
        slow=_FailingSlowAdapter(ModelFailureKind.TIMEOUT),
    )
    storage_recorder = InMemoryOperationRecorder()
    storage_runtime = ThinAgentRuntime(repository=_UnavailableRepository())
    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(timeout_runtime, recorder=timeout_recorder)
            ),
            base_url="http://testserver",
        ) as timeout_client,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(storage_runtime, recorder=storage_recorder)
            ),
            base_url="http://testserver",
        ) as storage_client,
    ):
        timeout_response = await timeout_client.post("/cases", json=CREATE_CASE_REQUEST)
        storage_response = await storage_client.get(f"/cases/{uuid4()}")

    assert timeout_response.status_code == 503
    assert timeout_response.json() == {
        "detail": {
            "code": "model_timeout",
            "message": "model operation failed safely",
        }
    }
    assert storage_response.status_code == 503
    assert storage_response.json() == {
        "detail": {
            "code": "storage_unavailable",
            "message": "storage dependency unavailable",
        }
    }
    assert timeout_recorder.records[0].error_category == "model_timeout"
    assert timeout_recorder.records[0].adapter_mode == "model"
    assert storage_recorder.records[0].error_category == "storage_unavailable"
    assert "secret" not in storage_response.text


@pytest.mark.parametrize(
    ("kind", "category"),
    [
        (ModelFailureKind.TRANSPORT, "model_transport"),
        (ModelFailureKind.INVALID_OUTPUT, "model_invalid_output"),
    ],
)
def test_model_failure_categories_are_stable(
    kind: ModelFailureKind, category: str
) -> None:
    async def request(recorder: InMemoryOperationRecorder) -> httpx.Response:
        adapter = _FailingSlowAdapter(kind)
        app = create_app(
            ThinAgentRuntime(fast=adapter, slow=adapter),
            recorder=recorder,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post("/cases", json=CREATE_CASE_REQUEST)

    recorder = InMemoryOperationRecorder()
    response = asyncio.run(request(recorder))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == category
    assert recorder.records[0].error_category == category


def test_readiness_does_not_dispatch_or_read_case() -> None:
    async def request(app: object) -> tuple[httpx.Response, httpx.Response]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get("/health/live"), await client.get("/health/ready")

    probe = _ProbeRepository()
    adapter = _CountingSlowAdapter()
    runtime = ThinAgentRuntime(
        repository=probe,
        fast=adapter,
        slow=adapter,
    )
    live, ready = asyncio.run(request(create_app(runtime)))
    assert live.status_code == 200
    assert ready.status_code == 200
    assert probe.readiness_calls == 1
    assert probe.case_calls == 0
    assert adapter.calls == 0
    assert runtime.adapter_mode == "model"
    assert runtime.storage_mode == "postgres"

    unavailable_probe = _ProbeRepository(unavailable=True)
    unavailable_runtime = ThinAgentRuntime(repository=unavailable_probe)
    _live, unavailable_ready = asyncio.run(request(create_app(unavailable_runtime)))
    assert unavailable_ready.status_code == 503
    assert unavailable_ready.json()["dependency"] == "postgres"
    assert unavailable_probe.readiness_calls == 1
    assert unavailable_probe.case_calls == 0


def test_readiness_unavailable_is_redacted_and_classified() -> None:
    async def request(recorder: InMemoryOperationRecorder) -> httpx.Response:
        runtime = ThinAgentRuntime(repository=_ProbeRepository(unavailable=True))
        app = create_app(runtime, recorder=recorder)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get("/health/ready")

    recorder = InMemoryOperationRecorder()
    response = asyncio.run(request(recorder))
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "ready": False,
        "dependency": "postgres",
        "adapter_mode": "scripted",
        "storage_mode": "postgres",
        "detail": {
            "code": "dependency_not_ready",
            "message": "configured dependency is not ready",
        },
    }
    assert "secret" not in response.text
    assert recorder.records[0].error_category == "dependency_not_ready"


@pytest.mark.parametrize(
    "override", [{"adapter_mode": "scripted"}, {"storage_mode": "memory"}]
)
def test_runtime_profile_overrides_are_not_accepted(override: dict[str, str]) -> None:
    with pytest.raises(TypeError):
        ThinAgentRuntime(**override)  # type: ignore[arg-type]


def test_stale_case_revision_is_classified() -> None:
    async def request(recorder: InMemoryOperationRecorder) -> httpx.Response:
        runtime = ThinAgentRuntime()
        app = create_app(runtime, recorder=recorder)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            created = await client.post("/cases", json=CREATE_CASE_REQUEST)
            return await client.post(
                f"/cases/{created.json()['case_id']}/events",
                json={"content": "stale", "expected_revision": 999},
            )

    recorder = InMemoryOperationRecorder()
    response = asyncio.run(request(recorder))
    assert response.status_code == 409
    assert response.json() == {"detail": "case snapshot revision is stale"}
    assert recorder.records[-1].error_category == "stale_cas"


def test_local_profile_report_is_bounded_diagnostic_evidence() -> None:
    report = asyncio.run(_run_profile(1))
    assert report["schema_version"] == "phase-04d-control-plane-profile-v1"
    assert report["result_role"] == "local_diagnostic"
    assert report["profile"]["credentials_used"] is False
    assert report["requests"]["p50_ms"] >= 0
    assert report["requests"]["p95_ms"] >= report["requests"]["p50_ms"]
    assert report["requests"]["timeout_rate"] > 0
    assert report["outcomes"]["error_categories"] == ["model_timeout", "none"]
