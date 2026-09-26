"""``events.jsonl``: append-only, single writer, dense ``seq`` (I2).

``append`` re-validates every event through its JSON form: ``Event.payload``
is a mutable dict, and ``model_copy``/``model_construct`` skip validation, so
the stored event is the parsed line that went to disk, never the caller's
object.
"""

from __future__ import annotations

import os
from pathlib import Path

from proxyloop.contract.events import Event, check_causes


class EventLog:
    """One run's log. Opening a path that exists fails: one writer per file."""

    def __init__(self, path: Path, run_id: str) -> None:
        self.run_id = run_id
        self._events: list[Event] = []
        self._ids: set[str] = set()
        self._file = path.open("x", encoding="utf-8")

    @property
    def events(self) -> tuple[Event, ...]:
        return tuple(self._events)

    @property
    def next_seq(self) -> int:
        return len(self._events)

    def append(self, event: Event) -> Event:
        """Validate, write and flush one event; return a copy of the stored form."""

        line = event.model_dump_json()
        stored = Event.model_validate_json(line)
        if stored.run_id != self.run_id:
            raise ValueError(f"event of run {stored.run_id!r} in log {self.run_id!r}")
        if stored.seq != self.next_seq:
            raise ValueError(f"seq {stored.seq} appended, {self.next_seq} expected")
        if self._events and stored.t_ms < self._events[-1].t_ms:
            raise ValueError("t_ms went backwards")
        if unknown := [c for c in stored.cause_ids if c not in self._ids]:
            raise ValueError(f"{stored.event_id} cites unknown events {unknown}")
        if stored.type in ("approval.decided", "mandate.decided"):
            check_causes([*self._events, stored])  # the decision rules
        self._file.write(line + "\n")
        self._file.flush()
        self._events.append(stored)
        self._ids.add(stored.event_id)
        return stored.model_copy(deep=True)

    def close(self) -> None:
        if not self._file.closed:
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()
