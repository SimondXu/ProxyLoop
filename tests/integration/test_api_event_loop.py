"""B2-8: a blocking Runtime or storage call must not stall the event loop.

A request whose repository call blocks (standing in for a PostgreSQL round
trip or a model call) must leave the loop free to serve a sibling request.
"""

from __future__ import annotations

import asyncio
import threading

import httpx
from proxyloop_api import (
    CaseRuntimeState,
    InMemoryCaseRepository,
    ThinAgentRuntime,
    create_app,
)

CREATE_CASE_REQUEST = {
    "current_monthly_total": {"amount_minor": 9200, "currency": "USD"},
    "target_monthly_total": {"amount_minor": 7500, "currency": "USD"},
    "mobile_hotspot_required": True,
    "device_financing_change_forbidden": True,
}
# Bounded so a blocked loop fails the test instead of hanging it.
BLOCK_TIMEOUT_SECONDS = 1.0


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
