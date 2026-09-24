"""B2-8: a blocking Runtime or storage call must not stall the event loop.

A request whose repository call blocks (standing in for a PostgreSQL round
trip or a model call) must leave the loop free to serve a sibling request.
Moving direct commands off the loop must not let two of them interleave the
API's clock guard: event times stay strictly increasing and no race ends in
a 500.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any
from uuid import UUID

import httpx
import pytest
from proxyloop_api import (
    CaseRuntimeState,
    InMemoryCaseRepository,
    ThinAgentRuntime,
    create_app,
)
from proxyloop_case_runtime import runtime as runtime_module

CREATE_CASE_REQUEST = {
    "current_monthly_total": {"amount_minor": 9200, "currency": "USD"},
    "target_monthly_total": {"amount_minor": 7500, "currency": "USD"},
    "mobile_hotspot_required": True,
    "device_financing_change_forbidden": True,
}
# Bounded so a blocked loop fails the test instead of hanging it.
BLOCK_TIMEOUT_SECONDS = 10.0
# How long the second racer may run before the first is released: enough to
# finish when commands are not serialized, spent parked on the lock when they
# are.
RACER_SETTLE_SECONDS = 1.0
BASE_TIME = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


class _BlockingRepository(InMemoryCaseRepository):
    """Block ``create`` until released, as a slow storage call would."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()

    def create(self, state: CaseRuntimeState) -> CaseRuntimeState:
        self.entered.set()
        try:
            self.release.wait(BLOCK_TIMEOUT_SECONDS)
            return super().create(state)
        finally:
            self.finished.set()


def test_blocking_runtime_call_does_not_block_sibling_request() -> None:
    asyncio.run(_test_blocking_runtime_call_does_not_block_sibling_request())


async def _test_blocking_runtime_call_does_not_block_sibling_request() -> None:
    repository = _BlockingRepository()
    app = create_app(ThinAgentRuntime(repository=repository))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        create = asyncio.create_task(client.post("/cases", json=CREATE_CASE_REQUEST))
        assert await asyncio.to_thread(repository.entered.wait, 5)

        live = await client.get("/health/live")
        blocked_while_served = not repository.finished.is_set()
        repository.release.set()
        created = await create

    assert live.status_code == 200
    assert blocked_while_served, "the event loop waited for the blocking call"
    assert created.status_code == 201


class _Clock:
    """Advance one second per read, or return one frozen reading."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reads = 0
        self.frozen: datetime | None = None

    def __call__(self) -> datetime:
        with self._lock:
            self._reads += 1
            if self.frozen is not None:
                return self.frozen
            return BASE_TIME + timedelta(seconds=self._reads)


class _StaleReadRepository(InMemoryCaseRepository):
    """Once armed, park the next worker-thread ``get`` after its read.

    The parked caller holds a view that goes stale while another request
    runs, which is the API clock guard's race window.
    """

    def __init__(self) -> None:
        super().__init__()
        self._arm_lock = threading.Lock()
        self._armed = False
        self.parked = threading.Event()
        self.release = threading.Event()

    def arm(self) -> None:
        with self._arm_lock:
            self._armed = True

    def get(self, case_id: UUID) -> CaseRuntimeState | None:
        state = super().get(case_id)
        if threading.current_thread() is threading.main_thread():
            return state
        with self._arm_lock:
            park, self._armed = self._armed, False
        if park:
            self.parked.set()
            self.release.wait(BLOCK_TIMEOUT_SECONDS)
        return state


@pytest.mark.parametrize("frozen_clock", [False, True], ids=["advancing", "equal"])
def test_concurrent_direct_events_keep_event_times_strictly_increasing(
    monkeypatch: pytest.MonkeyPatch, frozen_clock: bool
) -> None:
    # No approval after an event, so a second event reaches the time path.
    monkeypatch.setattr(
        runtime_module,
        "offer_compliance_violations_for_case",
        lambda *args, **kwargs: ("forced_for_race_test",),
    )
    asyncio.run(_test_concurrent_direct_events(frozen_clock=frozen_clock))


async def _test_concurrent_direct_events(*, frozen_clock: bool) -> None:
    clock = _Clock()
    repository = _StaleReadRepository()
    app = create_app(ThinAgentRuntime(repository=repository, clock=clock))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post("/cases", json=CREATE_CASE_REQUEST)
        assert created.status_code == 201
        case_id = UUID(created.json()["case_id"])
        if frozen_clock:
            clock.frozen = BASE_TIME + timedelta(hours=1)

        repository.arm()
        first = asyncio.create_task(
            client.post(f"/cases/{case_id}/events", json={"content": "first"})
        )
        assert await asyncio.to_thread(repository.parked.wait, 5)
        second = asyncio.create_task(
            client.post(f"/cases/{case_id}/events", json={"content": "second"})
        )
        await asyncio.wait({second}, timeout=RACER_SETTLE_SECONDS)
        repository.release.set()
        responses = [await first, await second]

    state = repository.get(case_id)
    assert state is not None
    for response in responses:
        assert response.status_code in {200, 409}, response.text
        if response.status_code == 409:
            body: Any = response.json()
            assert body == {"detail": "case_conflict"}
    assert any(response.status_code == 200 for response in responses)
    # A Runtime-authored assistant line shares its trigger's time (PR-8 I6).
    times = [
        event.occurred_at
        for event in state.snapshot.visible_events
        if event.event_type != "assistant_message"
    ]
    assert all(later > earlier for earlier, later in pairwise(times)), times
