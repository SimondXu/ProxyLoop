"""In-process approval expiry for the direct (non-Temporal) orchestration mode.

Temporal mode expires a pending approval from a durable Workflow timer. Direct
mode has no Workflow, so this scheduler arms one asyncio task per pending
approval on the app's event loop and issues ``EXPIRE_APPROVAL`` through the
same ``apply_command`` path, with the command id the Workflow derives. The
timer lives only in this process: a restart loses it (and, with the default
in-memory storage, the Case too).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import UUID

from proxyloop_case_runtime import (
    CaseCommandType,
    CaseConflictError,
    CaseNotFoundError,
    CaseTransitionRef,
    ThinAgentRuntime,
)
from proxyloop_workflow_worker import CaseCommandRequest, expiry_command_id
from proxyloop_workflow_worker.workflow import (
    EXPIRY_RETRY_INITIAL_BACKOFF,
    EXPIRY_RETRY_MAXIMUM_BACKOFF,
)

logger = logging.getLogger(__name__)

# The Workflow retries a transient expiry failure indefinitely because its
# timer is durable; an in-process timer gives up after a bounded number of
# attempts (15 + 30 + 60 + 120 + 240 s of backoff) and leaves the approval
# pending, which the next command or a restart surfaces.
EXPIRY_MAX_ATTEMPTS = 6

Sleep = Callable[[float], Awaitable[None]]
_TimerKey = tuple[UUID, UUID, datetime]


class DirectApprovalExpiry:
    """Arm at most one expiry timer per pending approval, cancel on shutdown."""

    def __init__(
        self,
        runtime: ThinAgentRuntime,
        *,
        now: Callable[[], datetime],
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._runtime = runtime
        self._now = now
        self._sleep = sleep
        self._armed: set[_TimerKey] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def pending(self) -> bool:
        return bool(self._tasks)

    def observe(self, transition: CaseTransitionRef, *, observed_at: datetime) -> None:
        """Arm a timer when a receipt leaves an approval pending.

        ``observed_at`` is the command time the caller already read, so arming
        does not read the clock again; the timer reads it only after waking.
        """

        if transition.approval_id is None or transition.approval_expires_at is None:
            return
        key = (
            transition.case_id,
            transition.approval_id,
            transition.approval_expires_at,
        )
        if key in self._armed:
            return
        self._armed.add(key)
        task = asyncio.get_running_loop().create_task(
            self._expire(transition, observed_at)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def aclose(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _expire(
        self, transition: CaseTransitionRef, observed_at: datetime
    ) -> None:
        expires_at = transition.approval_expires_at
        approval_id = transition.approval_id
        if expires_at is None or approval_id is None:
            return
        remaining = (expires_at - observed_at).total_seconds()
        while remaining > 0:
            await self._sleep(remaining)
            remaining = (expires_at - self._now()).total_seconds()
        for attempt in range(1, EXPIRY_MAX_ATTEMPTS + 1):
            try:
                request = CaseCommandRequest(
                    command_id=expiry_command_id(transition.case_id, transition),
                    case_id=transition.case_id,
                    command_type=CaseCommandType.EXPIRE_APPROVAL,
                    expected_revision=transition.after_revision,
                    approval_id=approval_id,
                    approval_expires_at=expires_at,
                )
                self._runtime.apply_command(request.to_command(expires_at))
                return
            except (CaseConflictError, CaseNotFoundError):
                # Decided (or otherwise moved) before the deadline: the
                # Runtime's revision pin refuses the expiry and nothing is
                # written, as when an Update wins the Workflow's race.
                logger.info("approval expiry skipped: approval no longer pending")
                return
            except Exception as error:
                # A failed timer must never take the app down; the category
                # is the exception type only, never its message.
                category = type(error).__name__
                if attempt == EXPIRY_MAX_ATTEMPTS:
                    logger.warning(
                        "approval expiry abandoned after %d attempts: %s",
                        attempt,
                        category,
                    )
                    return
                logger.warning(
                    "approval expiry attempt %d failed: %s", attempt, category
                )
                await self._sleep(expiry_retry_backoff(attempt).total_seconds())


def expiry_retry_backoff(failures: int) -> timedelta:
    """Mirror the Workflow's expiry backoff: 15 s doubling, capped at 5 min."""

    doublings = min(max(failures - 1, 0), 5)
    return min(
        EXPIRY_RETRY_INITIAL_BACKOFF * (1 << doublings),
        EXPIRY_RETRY_MAXIMUM_BACKOFF,
    )


__all__ = [
    "EXPIRY_MAX_ATTEMPTS",
    "DirectApprovalExpiry",
    "Sleep",
    "expiry_retry_backoff",
]
