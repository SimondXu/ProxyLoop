"""The session clock: the wall clock only (ARCHITECTURE §11; I7).

Tests inject ``tests/support/manual_clock.ManualClock`` through constructors;
there is no manual-clock value in ``SessionConfig``.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """``monotonic_ms``: ms since start, never decreasing; ``wall``: tz-aware."""

    def monotonic_ms(self) -> int: ...

    def wall(self) -> datetime: ...


class WallClock:
    def __init__(self) -> None:
        self._start = time.monotonic()

    def monotonic_ms(self) -> int:
        return int((time.monotonic() - self._start) * 1000)

    def wall(self) -> datetime:
        return datetime.now(UTC)
