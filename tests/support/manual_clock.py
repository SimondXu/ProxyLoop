"""A manual clock for tests (ARCHITECTURE §11): time moves only on ``advance``."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta


class ManualClock:
    """Implements ``proxyloop.core.clock.Clock``."""

    def __init__(self, start: datetime = datetime(2026, 9, 26, tzinfo=UTC)) -> None:
        self._start = start
        self._ms = 0

    def advance(self, ms: int) -> None:
        if ms < 0:
            raise ValueError("a clock never goes back")
        self._ms += ms

    def monotonic_ms(self) -> int:
        return self._ms

    def wall(self) -> datetime:
        return self._start + timedelta(milliseconds=self._ms)


class ScaledClock(ManualClock):
    """Wall time sped up ``factor`` times, for whole sessions: time flows on
    its own (``advance`` is a no-op), and ``sleep`` waits the scaled time, so
    concurrent timers keep their real order."""

    def __init__(self, factor: float = 100.0) -> None:
        super().__init__()
        self._factor, self._t0 = factor, time.monotonic()

    def advance(self, ms: int) -> None:
        return None

    def monotonic_ms(self) -> int:
        """Strictly increasing: every read is at least 1 ms after the last."""

        scaled = int((time.monotonic() - self._t0) * 1000 * self._factor)
        self._ms = max(scaled, self._ms + 1)
        return self._ms

    def wall(self) -> datetime:
        return self._start + timedelta(milliseconds=self.monotonic_ms())

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds / self._factor)
