"""Channels (§2, §10): a lane's partner hears the agent (``send``, as heard) and
queues its turns (``incoming``); ``tick`` runs only on a free, idle floor."""

from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

End = Literal["", "hangup", "closed", "quit"]


@dataclass(frozen=True, slots=True)
class Incoming:  # One partner turn: lines with the world event behind each, if any
    lines: tuple[tuple[str, str | None], ...]
    due_ms: int = 0  # not before (the SimUser's reply delay)
    strike: bool = False
    end: End = ""


class Channel:  # The base: a partner that never speaks first and has no clock
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[Incoming] = asyncio.Queue()

    @property
    def busy(self) -> bool:
        return False

    async def send(self, text: str | None, utt_id: str, cause: str, t_ms: int) -> None:
        return None

    async def tick(self, t_ms: int) -> None:
        return None

    def floor(self, free: bool, t_ms: int) -> None:
        return None


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
