"""A manual clock for tests (ARCHITECTURE §11): time moves only on ``advance``."""

from __future__ import annotations

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
