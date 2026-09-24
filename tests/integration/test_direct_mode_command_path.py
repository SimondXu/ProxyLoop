"""Direct mode shares the Temporal command path (P1 B2-4, B2-6, E-11).

The key/body matrix runs against the default direct mode and against the
fake Temporal client of the existing Temporal API tests. The modes match on
status codes and deduplication behaviour. The fake calls the Runtime directly,
so its error ``detail`` equals direct mode's: a content-free category
(P2 R-2). Direct mode and a real Temporal server agree on ``case_conflict``,
``approval_expired`` and ``not_found``; for a stale revision direct mode and
the fake return ``stale_cas`` while the real workflow activity classifies it
``case_conflict`` (known limit; the fix belongs in ``activities.py``). Direct
mode also expires a pending approval in process.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid1, uuid4

import httpx
import pytest
from fastapi import FastAPI
from proxyloop_api import create_app
from proxyloop_api.direct_expiry import EXPIRY_MAX_ATTEMPTS, expiry_retry_backoff
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseCommandType,
    ThinAgentRuntime,
)
from proxyloop_workflow_worker import expiry_command_id
from test_phase_05a_temporal_api import FakeTemporalCaseClient

BASE_TIME = datetime(2035, 1, 1, tzinfo=UTC)
CREATE_CASE_REQUEST = {
    "current_monthly_total": {"currency": "USD", "amount_minor": 9100},
    "target_monthly_total": {"currency": "USD", "amount_minor": 7200},
    "mobile_hotspot_required": True,
    "device_financing_change_forbidden": True,
}
REUSED = {"detail": "case_conflict"}
MALFORMED = {"detail": {"code": "invalid_command", "message": "command rejected"}}
MODES = ("direct", "temporal")


class SteppingClock:
    """A UTC clock that advances one second per read and can jump."""

    def __init__(self, start: datetime = BASE_TIME) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


class GatedSleep:
    """Record each requested delay and wait until the test releases it."""

    def __init__(self) -> None:
        self.delays: list[float] = []
        self.cancelled = 0
        self._gate = asyncio.Event()

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        try:
            await self._gate.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        self._gate = asyncio.Event()

    def release(self) -> None:
        self._gate.set()


def _app(mode: str, runtime: ThinAgentRuntime) -> FastAPI:
    if mode == "direct":
        return create_app(runtime)
    return create_app(runtime, temporal_client=FakeTemporalCaseClient(runtime))


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


def _run(test: Callable[[], Coroutine[Any, Any, None]]) -> None:
    asyncio.run(test())


def _key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid4())}


async def _settle(done: Callable[[], bool]) -> None:
    for _ in range(200):
        if done():
            return
        await asyncio.sleep(0)
    raise AssertionError("background expiry did not settle")


def _expiry_receipts(runtime: ThinAgentRuntime) -> list[Any]:
    state = runtime.repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    return [
        item
        for item in state.transitions
        if item.command_type is CaseCommandType.EXPIRE_APPROVAL
    ]


@pytest.mark.parametrize("mode", MODES)
def test_create_key_body_matrix_is_mode_independent(mode: str) -> None:
    runtime = ThinAgentRuntime()

    async def scenario() -> None:
        async with _client(_app(mode, runtime)) as client:
            for malformed in ("not-a-uuid", str(uuid4()).upper()):
                rejected = await client.post(
                    "/cases",
                    headers={"Idempotency-Key": malformed},
                    json=CREATE_CASE_REQUEST,
                )
                assert rejected.status_code == 422
                assert rejected.json() == MALFORMED
            assert runtime.repository.get(SCRIPTED_CASE_ID) is None

            key = _key()
            first = await client.post("/cases", headers=key, json=CREATE_CASE_REQUEST)
            replay = await client.post("/cases", headers=key, json=CREATE_CASE_REQUEST)
            assert first.status_code == 201
            assert replay.status_code == 201
            assert replay.json() == first.json()

            changed = await client.post(
                "/cases",
                headers=key,
                json={
                    **CREATE_CASE_REQUEST,
                    "target_monthly_total": {"currency": "USD", "amount_minor": 7300},
                },
            )
            assert changed.status_code == 409
            assert changed.json() == REUSED

            fresh = await client.post("/cases", json=CREATE_CASE_REQUEST)
            assert fresh.status_code == 409
            assert fresh.json() == {"detail": "case_conflict"}

        state = runtime.repository.get(SCRIPTED_CASE_ID)
        assert state is not None
        assert [item.command_type for item in state.transitions] == [
            CaseCommandType.CREATE_CASE
        ]

    _run(scenario)


@pytest.mark.parametrize("mode", MODES)
def test_event_key_body_matrix_is_mode_independent(mode: str) -> None:
    runtime = ThinAgentRuntime()

    async def scenario() -> None:
        async with _client(_app(mode, runtime)) as client:
            created = (await client.post("/cases", json=CREATE_CASE_REQUEST)).json()
            url = f"/cases/{created['case_id']}/events"
            body = {
                "content": "Please review the current offer.",
                "expected_revision": created["revision"],
            }

            malformed = await client.post(
                url, headers={"Idempotency-Key": "not-a-uuid"}, json=body
            )
            assert malformed.status_code == 422
            assert malformed.json() == MALFORMED

            non_v4_case = await client.post(f"/cases/{uuid1()}/events", json=body)
            assert non_v4_case.status_code == 422
            assert non_v4_case.json() == MALFORMED

            key = _key()
            first = await client.post(url, headers=key, json=body)
            replay = await client.post(url, headers=key, json=body)
            assert first.status_code == 200
            assert first.json()["route"] == "wait_for_approval"
            assert replay.status_code == 200
            assert replay.json() == first.json()

            changed = await client.post(
                url, headers=key, json={**body, "content": "Something else."}
            )
            assert changed.status_code == 409
            assert changed.json() == REUSED

            fresh = await client.post(url, json=body)
            assert fresh.status_code == 409
            assert fresh.json() == {"detail": "stale_cas"}

        state = runtime.repository.get(SCRIPTED_CASE_ID)
        assert state is not None
        assert [item.command_type for item in state.transitions][-1] is (
            CaseCommandType.APPEND_EVENT
        )
        assert state.snapshot.event_cursor == 3

    _run(scenario)


@pytest.mark.parametrize("mode", MODES)
def test_approval_key_body_matrix_is_mode_independent(mode: str) -> None:
    runtime = ThinAgentRuntime()

    async def scenario() -> None:
        async with _client(_app(mode, runtime)) as client:
            created = (await client.post("/cases", json=CREATE_CASE_REQUEST)).json()
            waiting = (
                await client.post(
                    f"/cases/{created['case_id']}/events",
                    json={"content": "Please review the current offer."},
                )
            ).json()
            approval = waiting["approval"]
            url = f"/cases/{created['case_id']}/approvals/{approval['approval_id']}"
            body = {
                "decision": "approved",
                "expected_revision": waiting["revision"],
                "expected_case_revision": approval["case_revision"],
                "expected_action_intent_revision": approval["action_intent_revision"],
            }

            malformed = await client.post(
                url, headers={"Idempotency-Key": "not-a-uuid"}, json=body
            )
            assert malformed.status_code == 422
            assert malformed.json() == MALFORMED

            for non_v4_url in (
                f"/cases/{uuid1()}/approvals/{approval['approval_id']}",
                f"/cases/{created['case_id']}/approvals/{uuid1()}",
            ):
                non_v4 = await client.post(non_v4_url, json=body)
                assert non_v4.status_code == 422
                assert non_v4.json() == MALFORMED

            key = _key()
            first = await client.post(url, headers=key, json=body)
            replay = await client.post(url, headers=key, json=body)
            assert first.status_code == 200
            assert first.json()["completion"]["decision"] == "complete"
            assert replay.status_code == 200
            assert replay.json() == first.json()

            changed = await client.post(
                url, headers=key, json={**body, "decision": "rejected"}
            )
            assert changed.status_code == 409
            assert changed.json() == REUSED

            fresh = await client.post(url, json=body)
            assert fresh.status_code == 409
            assert fresh.json() == {"detail": "stale_cas"}

            pin_less = await client.post(url, json={"decision": "approved"})
            assert pin_less.status_code == 409
            assert pin_less.json() == {"detail": "case_conflict"}

        state = runtime.repository.get(SCRIPTED_CASE_ID)
        assert state is not None
        assert state.execution_count == 1
        assert [item.value for item in state.provider.state_history].count(
            "confirmed"
        ) == 1

    _run(scenario)


def test_direct_readiness_names_the_direct_orchestration_mode() -> None:
    async def scenario() -> None:
        async with _client(create_app(ThinAgentRuntime())) as client:
            live = await client.get("/health/live")
            ready = await client.get("/health/ready")
        assert live.json() == {
            "status": "ok",
            "live": True,
            "adapter_mode": "scripted",
            "storage_mode": "memory",
        }
        assert ready.status_code == 200
        assert ready.json() == {
            "status": "ok",
            "ready": True,
            "dependency": "memory",
            "adapter_mode": "scripted",
            "storage_mode": "memory",
            "orchestration_mode": "direct",
        }

    _run(scenario)


def test_direct_mode_expires_a_pending_approval_exactly_once() -> None:
    clock = SteppingClock()
    sleep = GatedSleep()
    runtime = ThinAgentRuntime(clock=clock)
    app = create_app(runtime, approval_expiry_sleep=sleep)

    async def scenario() -> None:
        async with _client(app) as client:
            created = (await client.post("/cases", json=CREATE_CASE_REQUEST)).json()
            event_key = _key()
            event_body = {"content": "Please review the current offer."}
            waiting = await client.post(
                f"/cases/{created['case_id']}/events",
                headers=event_key,
                json=event_body,
            )
            assert waiting.status_code == 200
            pending = waiting.json()
            assert pending["completion"]["reason_codes"] == [
                "approval_or_execution_pending"
            ]
            expires_at = datetime.fromisoformat(pending["approval"]["expires_at"])
            await _settle(lambda: len(sleep.delays) == 1)
            assert 0 < sleep.delays[0] <= 3600

            # The timer re-reads the clock after waking and does not expire early.
            sleep.release()
            await _settle(lambda: len(sleep.delays) == 2)
            assert _expiry_receipts(runtime) == []

            clock.now = expires_at + timedelta(seconds=5)
            sleep.release()
            await _settle(lambda: len(_expiry_receipts(runtime)) == 1)

            # A deduplicated replay of the command that opened the approval
            # does not arm a second timer for the same approval.
            replay = await client.post(
                f"/cases/{created['case_id']}/events",
                headers=event_key,
                json=event_body,
            )
            assert replay.status_code == 200
            for _ in range(20):
                await asyncio.sleep(0)

            read = (await client.get(f"/cases/{created['case_id']}")).json()
            assert read["approval"]["decision"] == "expired"
            assert read["completion"] == {
                "decision": "not_done",
                "evidence_ids": [],
                "missing_evidence": ["verified_provider_confirmation"],
                "reason_codes": ["approval_expired"],
            }
            assert read["snapshot"]["completion"] == read["completion"]

            late = await client.post(
                f"/cases/{created['case_id']}/approvals/"
                f"{pending['approval']['approval_id']}",
                json={"decision": "approved"},
            )
            assert late.status_code == 409

        state = runtime.repository.get(SCRIPTED_CASE_ID)
        assert state is not None
        opening = next(
            item
            for item in state.transitions
            if item.command_type is CaseCommandType.APPEND_EVENT
        )
        receipts = _expiry_receipts(runtime)
        assert len(receipts) == 1
        assert receipts[0].command_id == expiry_command_id(SCRIPTED_CASE_ID, opening)
        assert len(sleep.delays) == 2
        assert state.execution_count == 0
        assert state.provider.confirmation is None

    _run(scenario)


def test_direct_mode_decision_before_the_deadline_leaves_the_timer_a_no_op() -> None:
    clock = SteppingClock()
    sleep = GatedSleep()
    runtime = ThinAgentRuntime(clock=clock)
    app = create_app(runtime, approval_expiry_sleep=sleep)

    async def scenario() -> None:
        async with _client(app) as client:
            created = (await client.post("/cases", json=CREATE_CASE_REQUEST)).json()
            waiting = (
                await client.post(
                    f"/cases/{created['case_id']}/events",
                    json={"content": "Please review the current offer."},
                )
            ).json()
            await _settle(lambda: len(sleep.delays) == 1)
            approval = waiting["approval"]
            completed = await client.post(
                f"/cases/{created['case_id']}/approvals/{approval['approval_id']}",
                json={
                    "decision": "approved",
                    "expected_revision": waiting["revision"],
                    "expected_case_revision": approval["case_revision"],
                    "expected_action_intent_revision": approval[
                        "action_intent_revision"
                    ],
                },
            )
            assert completed.status_code == 200
            before = runtime.repository.get(SCRIPTED_CASE_ID)
            assert before is not None

            clock.now = datetime.fromisoformat(approval["expires_at"]) + timedelta(
                minutes=1
            )
            sleep.release()
            await _settle(lambda: not app.state.approval_expiry.pending)

            after = runtime.repository.get(SCRIPTED_CASE_ID)
            assert after is not None
            assert after.snapshot.revision == before.snapshot.revision
            assert _expiry_receipts(runtime) == []
            read = (await client.get(f"/cases/{created['case_id']}")).json()
            assert read["completion"]["decision"] == "complete"

    _run(scenario)


def test_direct_mode_rejection_projects_approval_rejected() -> None:
    runtime = ThinAgentRuntime()

    async def scenario() -> None:
        async with _client(create_app(runtime)) as client:
            created = (await client.post("/cases", json=CREATE_CASE_REQUEST)).json()
            assert created["completion"]["reason_codes"] == [
                "approval_or_execution_pending"
            ]
            waiting = (
                await client.post(
                    f"/cases/{created['case_id']}/events",
                    json={"content": "Please review the current offer."},
                )
            ).json()
            approval = waiting["approval"]
            rejected = await client.post(
                f"/cases/{created['case_id']}/approvals/{approval['approval_id']}",
                json={"decision": "rejected", "expected_revision": waiting["revision"]},
            )
            assert rejected.status_code == 200
            body = rejected.json()
            assert body["approval"]["decision"] == "rejected"
            assert body["completion"]["decision"] == "not_done"
            assert body["completion"]["reason_codes"] == ["approval_rejected"]
            assert body["snapshot"]["completion"] == body["completion"]

    _run(scenario)


def test_direct_mode_shutdown_cancels_pending_expiry_timers() -> None:
    sleep = GatedSleep()
    runtime = ThinAgentRuntime(clock=SteppingClock())
    app = create_app(runtime, approval_expiry_sleep=sleep)

    async def scenario() -> None:
        async with app.router.lifespan_context(app), _client(app) as client:
            created = (await client.post("/cases", json=CREATE_CASE_REQUEST)).json()
            await client.post(
                f"/cases/{created['case_id']}/events",
                json={"content": "Please review the current offer."},
            )
            await _settle(lambda: len(sleep.delays) == 1)
            assert app.state.approval_expiry.pending
        assert sleep.cancelled == 1
        assert not app.state.approval_expiry.pending
        assert _expiry_receipts(runtime) == []

    _run(scenario)


def _run_failing_expiry(
    failures: int,
) -> tuple[ThinAgentRuntime, GatedSleep, dict[str, Any]]:
    """Fail the first ``failures`` expiry attempts, then let them through."""

    clock = SteppingClock()
    sleep = GatedSleep()
    runtime = ThinAgentRuntime(clock=clock)
    app = create_app(runtime, approval_expiry_sleep=sleep)
    original = runtime.apply_command
    attempts = {"expiry": 0}

    def flaky_expiry(command: Any) -> Any:
        if command.command_type is CaseCommandType.EXPIRE_APPROVAL:
            attempts["expiry"] += 1
            if attempts["expiry"] <= failures:
                raise RuntimeError("injected expiry failure")
        return original(command)

    runtime.apply_command = flaky_expiry  # type: ignore[method-assign]
    read: dict[str, Any] = {}

    async def scenario() -> None:
        async with _client(app) as client:
            created = (await client.post("/cases", json=CREATE_CASE_REQUEST)).json()
            waiting = (
                await client.post(
                    f"/cases/{created['case_id']}/events",
                    json={"content": "Please review the current offer."},
                )
            ).json()
            await _settle(lambda: len(sleep.delays) == 1)
            clock.now = datetime.fromisoformat(
                waiting["approval"]["expires_at"]
            ) + timedelta(seconds=1)
            while app.state.approval_expiry.pending:
                sleep.release()
                for _ in range(20):
                    await asyncio.sleep(0)
            response = await client.get(f"/cases/{created['case_id']}")
            assert response.status_code == 200
            read.update(response.json())

    _run(scenario)
    return runtime, sleep, read


def test_direct_mode_expiry_retries_a_transient_failure_then_expires_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="proxyloop_api.direct_expiry"):
        runtime, sleep, read = _run_failing_expiry(failures=1)

    assert sleep.delays[1:] == [15.0]
    assert len(_expiry_receipts(runtime)) == 1
    assert read["approval"]["decision"] == "expired"
    assert read["completion"]["reason_codes"] == ["approval_expired"]
    assert [record.getMessage() for record in caplog.records] == [
        "approval expiry attempt 1 failed: RuntimeError"
    ]


def test_direct_mode_expiry_gives_up_after_bounded_backoff_without_breaking_the_app(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="proxyloop_api.direct_expiry"):
        runtime, sleep, read = _run_failing_expiry(failures=EXPIRY_MAX_ATTEMPTS)

    assert sleep.delays[1:] == [15.0, 30.0, 60.0, 120.0, 240.0]
    assert _expiry_receipts(runtime) == []
    assert read["approval"]["decision"] == "pending"
    messages = [record.getMessage() for record in caplog.records]
    assert messages[-1] == (
        f"approval expiry abandoned after {EXPIRY_MAX_ATTEMPTS} attempts: RuntimeError"
    )
    assert all("injected" not in message for message in messages)


def test_expiry_backoff_mirrors_the_workflow_policy() -> None:
    assert [expiry_retry_backoff(n).total_seconds() for n in range(1, 9)] == [
        15.0,
        30.0,
        60.0,
        120.0,
        240.0,
        300.0,
        300.0,
        300.0,
    ]


def test_direct_mode_refuses_a_clock_that_does_not_advance_past_the_last_event() -> (
    None
):
    clock = SteppingClock()
    runtime = ThinAgentRuntime(clock=clock)

    async def scenario() -> None:
        async with _client(create_app(runtime)) as client:
            created = (await client.post("/cases", json=CREATE_CASE_REQUEST)).json()
            before = runtime.repository.get(SCRIPTED_CASE_ID)
            assert before is not None
            clock.now = BASE_TIME - timedelta(minutes=1)
            backwards = await client.post(
                f"/cases/{created['case_id']}/events",
                json={"content": "Please review the current offer."},
            )
            assert backwards.status_code == 409
            assert backwards.json() == {"detail": "case_conflict"}
            after = runtime.repository.get(SCRIPTED_CASE_ID)
            assert after is not None
            assert after.snapshot == before.snapshot
            assert after.transitions == before.transitions

    _run(scenario)
