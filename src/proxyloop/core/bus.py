"""The bus: the session's single writer (ARCHITECTURE §11).

It owns its ``EventLog``. ``emit`` stamps seq, clock and epoch, folds (a
rejected event is never written), appends, then delivers in log order (a
nested ``emit`` after the current event). Errors of ``isolated`` subscribers
are logged; others, ``LLMUnavailable`` (I8) and rejected nested emits reach
the emitter after the event was appended, and the queue is dropped: nothing is
delivered after a failure (§14). Nothing follows ``session.ended``.
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
        self._bb, self._ended = Blackboard(), False
        self.subscriber_errors = 0
        self._log = EventLog(path, run_id)
        self._clock = clock
        self._subscribers: list[tuple[Subscriber, bool]] = []
        self._undelivered: deque[Event] = deque()
        self._delivering = False
        self._rejected: Exception | None = None  # a nested emit that failed

    @property
    def bb(self) -> Blackboard:
        return self._bb

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
            if self._ended:
                raise ValueError("the session has ended")
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
                epoch=self._bb.epoch,
                payload=dict(payload),
            )
            bb = apply(self._bb, Event.model_validate_json(event.model_dump_json()))
            stored = self._log.append(event)
        except Exception as err:
            if self._delivering:
                self._rejected = err
            raise
        self._bb, self._ended = bb, stored.type == "session.ended"
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
        except BaseException:
            self._undelivered.clear()
            raise
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
