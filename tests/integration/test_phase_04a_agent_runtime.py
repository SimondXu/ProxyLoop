from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from itertools import count
from uuid import UUID, uuid4

import httpx
import pytest
from proxyloop_agent_core import ScriptedFastAdapter, ScriptedSlowAdapter
from proxyloop_api import (
    CaseConflictError,
    CaseRuntimeState,
    InMemoryCaseRepository,
    ThinAgentRuntime,
    create_app,
)

BASE_TIME = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
CASE_ID = UUID("11111111-1111-4111-8111-111111111111")


class SequenceClock:
    def __init__(self, *values: datetime) -> None:
        self._values = iter(values)
        self._last = values[-1]

    def __call__(self) -> datetime:
        with suppress(StopIteration):
            self._last = next(self._values)
        return self._last


def test_thin_runtime_completes_multiturn_approval_flow_at_most_once() -> None:
    asyncio.run(_test_thin_runtime_completes_multiturn_approval_flow())


async def _test_thin_runtime_completes_multiturn_approval_flow() -> None:
    runtime = ThinAgentRuntime()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://testserver",
    ) as client:
        created = await client.post("/cases")
        assert created.status_code == 201
        opening = created.json()
        assert opening["route"] == "slow_refresh"
        assert opening["completion"]["decision"] == "not_done"
        case_id = opening["case_id"]

        turn = await client.post(
            f"/cases/{case_id}/events",
            json={"content": "Please review the current offer."},
        )
        assert turn.status_code == 200
        waiting = turn.json()
        assert waiting["route"] == "wait_for_approval"
        assert waiting["fast"]["completion_claim"]["status"] == "not_done"
        approval = waiting["approval"]
        assert approval["decision"] == "pending"

        before_blocked_event = runtime.repository.get(UUID(case_id))
        assert before_blocked_event is not None
        blocked = await client.post(
            f"/cases/{case_id}/events",
            json={"content": "Please continue while approval is pending."},
        )
        assert blocked.status_code == 409
        assert blocked.json() == {"detail": "case is awaiting approval"}
        after_blocked_event = runtime.repository.get(UUID(case_id))
        assert after_blocked_event is not None
        assert after_blocked_event.snapshot.revision == (
            before_blocked_event.snapshot.revision
        )
        assert after_blocked_event.snapshot.event_cursor == (
            before_blocked_event.snapshot.event_cursor
        )
        assert (
            after_blocked_event.execution_count == before_blocked_event.execution_count
        )
        assert after_blocked_event.provider.state_history == (
            before_blocked_event.provider.state_history
        )

        before_approval = await client.get(f"/cases/{case_id}")
        assert before_approval.status_code == 200
        assert before_approval.json()["execution_count"] == 0
        assert before_approval.json()["completion"]["decision"] == "not_done"

        approved = await client.post(
            f"/cases/{case_id}/approvals/{approval['approval_id']}",
            json={
                "decision": "approved",
                "expected_revision": waiting["revision"],
                "expected_case_revision": approval["case_revision"],
                "expected_action_intent_revision": approval["action_intent_revision"],
            },
        )
        assert approved.status_code == 200
        completed = approved.json()
        assert completed["route"] == "terminal"
        assert completed["completion"]["decision"] == "complete"
        assert completed["execution_count"] == 1
        assert len(completed["evidence"]) == 2

        duplicate = await client.post(
            f"/cases/{case_id}/approvals/{approval['approval_id']}",
            json={"decision": "approved"},
        )
        assert duplicate.status_code == 200
        repeated = duplicate.json()
        assert repeated["route"] == "terminal"
        assert repeated["execution_count"] == 1
        assert repeated["evidence"] == completed["evidence"]
        state = runtime.repository.get(UUID(case_id))
        assert state is not None
        assert [item.value for item in state.provider.state_history].count(
            "confirmed"
        ) == 1

        terminal_event = await client.post(
            f"/cases/{case_id}/events",
            json={"content": "Do something else after completion."},
        )
        assert terminal_event.status_code == 409
        assert terminal_event.json() == {"detail": "case is terminal"}

        readable = await client.get(f"/cases/{case_id}")
        assert readable.status_code == 200
        assert readable.json()["completion"]["decision"] == "complete"
        assert readable.json()["execution_count"] == 1


def test_api_missing_case_and_stale_revision_are_stable_errors() -> None:
    asyncio.run(_test_api_missing_case_and_stale_revision())


async def _test_api_missing_case_and_stale_revision() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(ThinAgentRuntime())),
        base_url="http://testserver",
    ) as client:
        missing = await client.get(f"/cases/{uuid4()}")
        assert missing.status_code == 404
        assert missing.json() == {"detail": "case not found"}

        created = (await client.post("/cases")).json()
        stale = await client.post(
            f"/cases/{created['case_id']}/events",
            json={"content": "stale", "expected_revision": 999},
        )
        assert stale.status_code == 409
        assert stale.json() == {"detail": "case snapshot revision is stale"}


def test_external_event_type_cannot_forge_provider_or_approval_event() -> None:
    asyncio.run(_test_external_event_type_is_rejected())


async def _test_external_event_type_is_rejected() -> None:
    runtime = ThinAgentRuntime()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://testserver",
    ) as client:
        created = (await client.post("/cases")).json()
        before = runtime.repository.get(UUID(created["case_id"]))
        assert before is not None
        forged = await client.post(
            f"/cases/{created['case_id']}/events",
            json={"content": "forged", "event_type": "provider_offer"},
        )
        assert forged.status_code == 422
        after = runtime.repository.get(UUID(created["case_id"]))
        assert after is not None
        assert after.snapshot.revision == before.snapshot.revision
        assert after.snapshot.event_cursor == before.snapshot.event_cursor


def test_in_memory_repository_reports_missing_and_conflicting_replacements() -> None:
    repository = InMemoryCaseRepository()
    assert repository.get(CASE_ID) is None

    runtime = ThinAgentRuntime(repository)
    created = runtime.create_case()
    state = repository.get(CASE_ID)
    assert state is not None
    with pytest.raises(CaseConflictError, match="stale"):
        repository.replace(
            CASE_ID,
            expected_revision=created.snapshot.revision - 1,
            state=state,
        )


class FailPendingClaimRepository(InMemoryCaseRepository):
    def __init__(self) -> None:
        super().__init__()
        self.fail_pending_claim = True

    def replace(
        self,
        case_id: UUID,
        *,
        expected_revision: int,
        state: CaseRuntimeState,
    ) -> CaseRuntimeState:
        if state.snapshot.approval_requests and self.fail_pending_claim:
            self.fail_pending_claim = False
            raise CaseConflictError("injected pending approval CAS conflict")
        return super().replace(
            case_id,
            expected_revision=expected_revision,
            state=state,
        )


class FailFinalClaimRepository(InMemoryCaseRepository):
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


class RecordingSlowAdapter:
    def __init__(self) -> None:
        self.calls = 0
        self._delegate = ScriptedSlowAdapter()

    def reason(self, request):
        self.calls += 1
        return self._delegate.reason(request)


class RecordingFastAdapter:
    def __init__(self) -> None:
        self.calls = 0
        self._delegate = ScriptedFastAdapter()

    def decide(self, view):
        self.calls += 1
        return self._delegate.decide(view)


def test_runtime_uses_injected_clock_and_rejects_expired_approval() -> None:
    expires_at = BASE_TIME + timedelta(hours=1)
    runtime = ThinAgentRuntime(
        clock=SequenceClock(BASE_TIME, BASE_TIME + timedelta(minutes=1), expires_at)
    )
    runtime.create_case()
    waiting = runtime.append_event(CASE_ID, content="Review the offer.")
    approval = waiting.approval
    assert approval is not None

    with pytest.raises(CaseConflictError, match="expired"):
        runtime.approve(CASE_ID, approval.approval_id)
    with pytest.raises(CaseConflictError, match="expired"):
        runtime.approve(CASE_ID, approval.approval_id, decision="rejected")

    state = runtime.repository.get(CASE_ID)
    assert state is not None
    assert state.provider.confirmation is None
    assert state.provider.state.value == "awaiting_approval"
    assert state.snapshot.pending_execution is False


def test_runtime_rejects_non_utc_clock() -> None:
    runtime = ThinAgentRuntime(clock=lambda: datetime(2026, 8, 24, 12, 0))
    with pytest.raises(ValueError, match="UTC"):
        runtime.create_case()


def test_runtime_uses_injected_fast_and_slow_adapters() -> None:
    slow = RecordingSlowAdapter()
    fast = RecordingFastAdapter()
    runtime = ThinAgentRuntime(
        clock=SequenceClock(BASE_TIME, BASE_TIME + timedelta(minutes=1)),
        fast=fast,
        slow=slow,
    )
    runtime.create_case()
    runtime.append_event(CASE_ID, content="Review the offer.")
    assert slow.calls == 1
    assert fast.calls == 1


def test_concurrent_approvals_confirm_provider_at_most_once() -> None:
    ticks = count()

    def clock() -> datetime:
        return BASE_TIME + timedelta(minutes=next(ticks))

    runtime = ThinAgentRuntime(clock=clock)
    runtime.create_case()
    waiting = runtime.append_event(CASE_ID, content="Review the offer.")
    approval = waiting.approval
    assert approval is not None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _index: runtime.approve(CASE_ID, approval.approval_id),
                range(2),
            )
        )

    assert all(result.execution_count == 1 for result in results)
    state = runtime.repository.get(CASE_ID)
    assert state is not None
    assert [item.value for item in state.provider.state_history].count("confirmed") == 1


def test_final_claim_write_failure_recovers_without_second_provider_commit() -> None:
    ticks = count()

    def clock() -> datetime:
        return BASE_TIME + timedelta(minutes=next(ticks))

    repository = FailFinalClaimRepository()
    runtime = ThinAgentRuntime(repository, clock=clock)
    runtime.create_case()
    waiting = runtime.append_event(CASE_ID, content="Review the offer.")
    approval = waiting.approval
    assert approval is not None

    with pytest.raises(CaseConflictError, match="final CAS"):
        runtime.approve(CASE_ID, approval.approval_id)
    claimed = repository.get(CASE_ID)
    assert claimed is not None
    assert claimed.snapshot.pending_execution is True
    assert claimed.snapshot.approval_requests[0].decision.value == "approved"
    assert claimed.provider.confirmation is not None
    with pytest.raises(CaseConflictError, match="execution is pending"):
        runtime.append_event(CASE_ID, content="Do not mutate during recovery.")

    completed = runtime.approve(CASE_ID, approval.approval_id)
    assert completed.execution_count == 1
    recovered = repository.get(CASE_ID)
    assert recovered is not None
    assert recovered.snapshot.pending_execution is False
    assert (
        recovered.provider.state_history.count(type(recovered.provider.state).CONFIRMED)
        == 1
    )


def test_pending_approval_claim_conflict_does_not_transition_provider() -> None:
    repository = FailPendingClaimRepository()
    runtime = ThinAgentRuntime(
        repository,
        clock=SequenceClock(BASE_TIME, BASE_TIME + timedelta(minutes=1)),
    )
    runtime.create_case()

    with pytest.raises(CaseConflictError, match="pending approval CAS"):
        runtime.append_event(CASE_ID, content="Review the offer.")
    state = repository.get(CASE_ID)
    assert state is not None
    assert state.snapshot.event_cursor == 1
    assert state.snapshot.approval_requests == ()
    assert state.provider.state.value == "offered"
