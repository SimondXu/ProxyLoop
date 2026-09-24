"""P2 API hygiene: content-free error detail (R-2), a replay route that
agrees with its snapshot (B2-7), no dead clock read (B2-9)."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from proxyloop_api import (
    CaseConflictError,
    CaseRuntimeState,
    InMemoryCaseRepository,
    ThinAgentRuntime,
    create_app,
)
from proxyloop_api.operations import CORRELATION_ID_HEADER
from test_phase_05a_temporal_api import FailingTemporalCaseClient, _client_for

BASE_TIME = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
CREATE_CASE_REQUEST = {
    "current_monthly_total": {"amount_minor": 9200, "currency": "USD"},
    "target_monthly_total": {"amount_minor": 7500, "currency": "USD"},
    "mobile_hotspot_required": True,
    "device_financing_change_forbidden": True,
}
INTERNAL_TEXT = "internal detail /srv/proxyloop row 42"


class _InternalConflictRepository(InMemoryCaseRepository):
    """Raise a conflict whose text must stay server-side."""

    def create(self, state: CaseRuntimeState) -> CaseRuntimeState:
        del state
        raise CaseConflictError(INTERNAL_TEXT)


class _CountingClock:
    def __init__(self) -> None:
        self.reads = 0

    def __call__(self) -> datetime:
        self.reads += 1
        return BASE_TIME + timedelta(seconds=self.reads)


def _client(runtime: ThinAgentRuntime) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://testserver",
    )


def test_conflict_and_not_found_details_are_category_only() -> None:
    asyncio.run(_test_conflict_and_not_found_details_are_category_only())


async def _test_conflict_and_not_found_details_are_category_only() -> None:
    async with _client(ThinAgentRuntime()) as client:
        created = await client.post("/cases", json=CREATE_CASE_REQUEST)
        assert created.status_code == 201
        case_id = created.json()["case_id"]

        again = await client.post("/cases", json=CREATE_CASE_REQUEST)
        assert again.status_code == 409
        assert again.json() == {"detail": "case_conflict"}

        stale = await client.post(
            f"/cases/{case_id}/events",
            json={"content": "stale", "expected_revision": 999},
        )
        assert stale.status_code == 409
        assert stale.json() == {"detail": "stale_cas"}

        missing_approval = await client.post(
            f"/cases/{case_id}/approvals/{uuid4()}",
            json={"decision": "approved"},
        )
        assert missing_approval.status_code == 404
        assert missing_approval.json() == {"detail": "not_found"}


def test_internal_conflict_text_is_logged_not_returned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="proxyloop_api.app")
    response = asyncio.run(
        _post_create(ThinAgentRuntime(_InternalConflictRepository()))
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "case_conflict"}
    assert INTERNAL_TEXT not in response.text
    correlation_id = response.headers[CORRELATION_ID_HEADER]
    logged = [
        record.getMessage()
        for record in caplog.records
        if record.name == "proxyloop_api.app"
    ]
    assert any(
        INTERNAL_TEXT in message and correlation_id in message for message in logged
    ), logged


async def _post_create(runtime: ThinAgentRuntime) -> httpx.Response:
    async with _client(runtime) as client:
        return await client.post("/cases", json=CREATE_CASE_REQUEST)


def test_event_replay_after_completion_reports_the_snapshot_route() -> None:
    asyncio.run(_test_event_replay_after_completion_reports_the_snapshot_route())


async def _test_event_replay_after_completion_reports_the_snapshot_route() -> None:
    async with _client(ThinAgentRuntime()) as client:
        created = await client.post("/cases", json=CREATE_CASE_REQUEST)
        case_id = created.json()["case_id"]
        event_key = {"Idempotency-Key": str(uuid4())}
        event_body = {"content": "Please review the current offer."}
        turn = await client.post(
            f"/cases/{case_id}/events", json=event_body, headers=event_key
        )
        assert turn.status_code == 200
        waiting = turn.json()
        assert waiting["route"] == "wait_for_approval"
        # A replay before anything else changed keeps the receipt's route.
        early = await client.post(
            f"/cases/{case_id}/events", json=event_body, headers=event_key
        )
        assert early.status_code == 200
        assert early.json()["route"] == "wait_for_approval"
        assert early.json()["revision"] == waiting["revision"]
        approval = waiting["approval"]
        approved = await client.post(
            f"/cases/{case_id}/approvals/{approval['approval_id']}",
            json={"decision": "approved", "expected_revision": waiting["revision"]},
        )
        assert approved.status_code == 200
        assert approved.json()["completion"]["decision"] == "complete"

        replay = await client.post(
            f"/cases/{case_id}/events", json=event_body, headers=event_key
        )
        assert replay.status_code == 200
        replayed = replay.json()
        assert replayed["revision"] == approved.json()["revision"]
        assert replayed["completion"]["decision"] == "complete"
        assert replayed["route"] == "terminal"


def test_repeat_decision_on_rejected_approval_reads_no_clock() -> None:
    clock = _CountingClock()
    runtime = ThinAgentRuntime(clock=clock)
    case_id = runtime.create_case().snapshot.case.case_id
    waiting = runtime.append_event(case_id, content="Review the offer.")
    assert waiting.approval is not None
    runtime.approve(case_id, waiting.approval.approval_id, decision="rejected")

    reads_before = clock.reads
    with pytest.raises(CaseConflictError, match="approval is already terminal"):
        runtime.approve(case_id, waiting.approval.approval_id, decision="rejected")
    assert clock.reads == reads_before


def test_temporal_not_found_detail_is_the_category_code() -> None:
    runtime = ThinAgentRuntime()
    temporal = FailingTemporalCaseClient(runtime, "case_not_found")

    async def request() -> httpx.Response:
        async with _client_for(runtime, temporal) as client:
            return await client.post("/cases", json=CREATE_CASE_REQUEST)

    response = asyncio.run(request())
    assert response.status_code == 404
    assert response.json() == {"detail": "not_found"}
