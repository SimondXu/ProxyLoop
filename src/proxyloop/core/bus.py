"""The bus: the session's single writer (ARCHITECTURE §11).

``emit`` stamps seq, clock and epoch, appends through the ``EventLog``, folds
the stored event into ``bb`` and then delivers it to subscribers in log
order. A subscriber that raises is logged and isolated: the exception never
reaches the emitter or the other subscribers. An ``emit`` made from inside a
subscriber is appended at once and delivered after the current event.
``emit`` never awaits, so on one event loop it is atomic.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Mapping, Sequence

from proxyloop.contract.events import Event, Stream, event_id
from proxyloop.contract.state import Blackboard
from proxyloop.core.clock import Clock
from proxyloop.core.fold import apply
from proxyloop.core.log import EventLog

Subscriber = Callable[[Event], None]
_log = logging.getLogger(__name__)


class Bus:
    def __init__(self, log: EventLog, clock: Clock) -> None:
        self.log = log
        self.bb = Blackboard()
        self.subscriber_errors = 0
        self._clock = clock
        self._subscribers: list[Subscriber] = []
        self._undelivered: deque[Event] = deque()
        self._delivering = False

    def subscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.append(subscriber)

    def emit(
        self,
        type_: str,
        actor: str,
        stream: Stream,
        payload: Mapping[str, object],
        cause_ids: Sequence[str] = (),
    ) -> Event:
        seq = self.log.next_seq
        draft = Event(
            run_id=self.log.run_id,
            seq=seq,
            event_id=event_id(self.log.run_id, seq),
            t_ms=self._clock.monotonic_ms(),
            wall=self._clock.wall(),
            type=type_,
            actor=actor,
            stream=stream,
            cause_ids=tuple(cause_ids),
            epoch=self.bb.epoch,
            payload=dict(payload),
        )
        return self.publish(draft)

    def publish(self, event: Event) -> Event:
        """Append an already-built event. It is folded before it is written,
        so an event the fold rejects never reaches the log."""

        bb = apply(self.bb, Event.model_validate_json(event.model_dump_json()))
        stored = self.log.append(event)
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
                for subscriber in tuple(self._subscribers):
                    try:
                        subscriber(event)
                    except Exception:
                        self.subscriber_errors += 1
                        _log.exception(
                            "subscriber %r failed on %s", subscriber, event.event_id
                        )
        finally:
            self._delivering = False
