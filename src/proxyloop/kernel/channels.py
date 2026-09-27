"""Channels (§2, §10): a lane's partner hears the agent (``send``, as heard) and
queues its turns (``incoming``); ``tick`` runs only on a free, idle floor. The
SimUser's channel also fires its unprompted stop on a trigger (#143, N6)."""

from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from proxyloop.env.user.approver import Approver
from proxyloop.env.user.simuser import SimUser

End = Literal["", "hangup", "closed", "quit"]


@dataclass(frozen=True, slots=True)
class Incoming:  # One partner turn: lines with the world event behind each, if any
    lines: tuple[tuple[str, str | None], ...]
    due_ms: int = 0  # not before (the SimUser's reply delay)
    strike: bool = False
    end: End = ""
    delivered: asyncio.Event | None = None  # set once its lines are emitted


class Channel:  # The base: a partner that never speaks first and has no clock
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[Incoming] = asyncio.Queue()
        self._composing, self._quiet = 0, asyncio.Event()
        self._quiet.set()

    @property
    def busy(self) -> bool:  # the partner is hearing a line or composing a reply
        return self._composing > 0

    def composing(self, delta: int) -> None:
        """A partner turn starts (+1) or ends (-1); queue its reply first."""
        self._composing += delta
        (self._quiet.clear if self._composing else self._quiet.set)()

    async def quiet(self) -> None:  # until the partner composes nothing
        await self._quiet.wait()

    async def send(self, text: str | None, utt_id: str, cause: str, t_ms: int) -> None:
        return None

    async def tick(self, t_ms: int) -> None:
        return None

    def floor(self, free: bool, t_ms: int) -> None:
        return None


class SimUserChannel(Channel):  # replies delay_s after each message
    def __init__(self, user: SimUser) -> None:
        super().__init__()
        self._user, self._lock = user, asyncio.Lock()

    @property
    def approver(self) -> Approver | None:  # the principal's approval button
        return self._user.approver

    async def send(self, text: str | None, utt_id: str, cause: str, t_ms: int) -> None:
        async with self._lock:  # one reply at a time, in message order
            reply = await self._user.on_agent_message(text, cause)
        if reply is None:  # the user stays silent: nothing to deliver
            return
        due = 0 if text is None else t_ms + round(1000 * reply.delay_s)
        self.incoming.put_nowait(Incoming(((reply.text, reply.event_id),), due))

    async def trigger(
        self, kind: Literal["after_card", "after_offer"], cause: str, t_ms: int
    ) -> asyncio.Event | None:
        """``cause`` (at ``t_ms``) may be the user's stop trigger: the stop is
        queued ``delay_s`` after it, and the returned event is set once its
        ``user.msg`` is emitted (``None``: no stop)."""
        async with self._lock:  # serialised with the replies
            reply = await self._user.on_trigger(kind, cause)
        if reply is None:
            return None
        done, due = asyncio.Event(), t_ms + round(1000 * reply.delay_s)
        line = ((reply.text, reply.event_id),)
        self.incoming.put_nowait(Incoming(line, due, delivered=done))
        return done


class HumanChannel(Channel):  # a person at the terminal
    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label

    async def send(self, text: str | None, utt_id: str, cause: str, t_ms: int) -> None:
        if text:
            print(f"{self.label}: {text}", flush=True)

    def line(self, text: str) -> None:
        ends: dict[str, End] = {"/hangup": "hangup", "/quit": "quit"}
        if text in ends:
            self.incoming.put_nowait(Incoming((), end=ends[text]))
        elif text:
            self.incoming.put_nowait(Incoming(((text, None),)))


def read_stdin(humans: Mapping[str, HumanChannel]) -> None:  # u:/r: when two
    loop = asyncio.get_running_loop()

    def route(raw: str) -> None:
        key, _, rest = raw.partition(":")
        target = {"u": "user", "r": "cp"}.get(key.strip()) if len(humans) > 1 else None
        if len(humans) == 1:
            next(iter(humans.values())).line(raw.strip())
        elif target in humans:
            humans[str(target)].line(rest.strip())
        else:
            print("prefix the line with u: (user) or r: (rep)", flush=True)

    def reader() -> None:  # a daemon thread: an unread stdin never blocks exit
        for raw in sys.stdin:
            loop.call_soon_threadsafe(route, raw)
        for channel in humans.values():
            loop.call_soon_threadsafe(channel.line, "/quit")

    threading.Thread(target=reader, daemon=True).start()
