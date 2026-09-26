"""The bus: the session's single writer (ARCHITECTURE §11).

The bus owns its ``EventLog`` (no other appender, so log and ``bb`` agree).
``emit`` stamps seq, clock and epoch, folds (a rejected event is never
written), appends, then delivers in log order; a nested ``emit`` is delivered
after the current event. Subscriber errors reach the emitter unless the
subscriber is ``isolated`` (exporters): then they are logged and counted.
``LLMUnavailable`` (I8) and a rejected nested ``emit`` always propagate.
``emit`` never awaits, so on one event loop it is atomic.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from proxyloop.contract.events import Event, Stream, event_id
from proxyloop.contract.llm import LLMUnavailable
from proxyloop.contract.state import Blackboard
from proxyloop.core.clock import Clock
from proxyloop.core.fold import apply
from proxyloop.core.log import EventLog

Subscriber = Callable[[Event], None]
_log = logging.getLogger(__name__)


class Bus:
    def __init__(self, path: Path, run_id: str, clock: Clock) -> None:
        self.bb = Blackboard()
        self.subscriber_errors = 0
        self._log = EventLog(path, run_id)
        self._clock = clock
        self._subscribers: list[tuple[Subscriber, bool]] = []
        self._undelivered: deque[Event] = deque()
        self._delivering = False
        self._rejected: Exception | None = None  # a nested emit that failed

    @property
    def events(self) -> tuple[Event, ...]:
        return self._log.events

    def close(self) -> None:
        self._log.close()

    def subscribe(self, subscriber: Subscriber, isolated: bool = False) -> None:
        self._subscribers.append((subscriber, isolated))

    def emit(
        self,
        type_: str,
        actor: str,
        stream: Stream,
        payload: Mapping[str, object],
        cause_ids: Sequence[str] = (),
    ) -> Event:
        seq, run_id = self._log.next_seq, self._log.run_id
        try:
            event = Event(
                run_id=run_id,
                seq=seq,
                event_id=event_id(run_id, seq),
                t_ms=self._clock.monotonic_ms(),
                wall=self._clock.wall(),
                type=type_,
                actor=actor,
                stream=stream,
                cause_ids=tuple(cause_ids),
                epoch=self.bb.epoch,
                payload=dict(payload),
            )
            bb = apply(self.bb, Event.model_validate_json(event.model_dump_json()))
            stored = self._log.append(event)
        except Exception as err:
            if self._delivering:
                self._rejected = err
            raise
        self.bb = bb
        self._undelivered.append(stored)
        if not self._delivering:
            self._deliver()
        return stored

    def _deliver(self) -> None:
        self._delivering = True
        try:
            while self._undelivered:
                event = self._undelivered.popleft()
                for subscriber, isolated in tuple(self._subscribers):
                    self._call(subscriber, isolated, event)
        finally:
            self._delivering = False

    def _call(self, subscriber: Subscriber, isolated: bool, event: Event) -> None:
        try:
            subscriber(event)
        except Exception as err:
            fatal = isinstance(err, LLMUnavailable) or self._rejected is not None
            if not isolated or fatal:
                self._rejected = None
                raise
            self.subscriber_errors += 1
            _log.exception("subscriber %r failed on %s", subscriber, event.event_id)
        if (rejected := self._rejected) is not None:
            self._rejected = None
            raise rejected
