"""Speakers (§11): chat at once; cp holds the floor with the speech clock
``min(12 s, words / 2.8)``, and a partner barging in cuts the line and the turn."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING

from proxyloop.contract.base import Lane
from proxyloop.contract.events import Event

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

WORDS_PER_S, MAX_LINE_S = 2.8, 12.0
Sleep = Callable[[float], Awaitable[None]]


def heard_prefix(text: str, seconds: float) -> str:  # a prefix of text
    words = list(re.finditer(r"\S+", text))
    n = min(len(words), int(seconds * WORDS_PER_S))
    return text[: words[n - 1].end()] if n else ""


class Speaker:
    def __init__(self, k: Kernel, lane: Lane) -> None:
        self._k, self.lane, self._channel = k, lane, k.channels[lane]
        self._lock, self._barge = asyncio.Lock(), asyncio.Event()
        self.speaking = False

    async def speak(self, lines: Sequence[tuple[str, str, str]]) -> None:  # one turn
        k, realtime = self._k, self.lane == "cp"
        async with self._lock:
            self._barge.clear()
            self.speaking = realtime
            self._channel.floor(False, k.now())
            heard: list[str] = []
            last: Event | None = None
            for utt_id, text, cause in lines:
                said = await self._clock(text) if realtime else text
                out = {"lane": self.lane, "utt_id": utt_id, "text_generated": text}
                out |= {"text_heard": said, "interrupted": said != text}
                last = k.emit("utt.delivered", "kernel", out, [cause])
                heard.append(said)
                if said != text:
                    cut = {"lane": self.lane, "utt_id": utt_id}
                    k.emit("chan.barge_in", "kernel", cut, [last.event_id])
                    break
            self.speaking = False
            self._channel.floor(True, k.now())
        text = " ".join(h for h in heard if h)
        if last is not None and text:
            utt_id = str(last.payload["utt_id"])
            k.spawn(self._channel.send(text, utt_id, last.event_id, k.now()))

    async def barge_in(self) -> None:  # cut the line; wait for the floor
        self._barge.set()
        async with self._lock:
            return

    async def _clock(self, text: str) -> str:
        if self._barge.is_set():
            return ""
        start, seconds = self._k.now(), min(MAX_LINE_S, len(text.split()) / WORDS_PER_S)
        timer = asyncio.ensure_future(self._k.sleep(seconds))
        barge = asyncio.ensure_future(self._barge.wait())
        await asyncio.wait((timer, barge), return_when=asyncio.FIRST_COMPLETED)
        timer.cancel()
        barge.cancel()
        if not self._barge.is_set():
            return text
        return heard_prefix(text, (self._k.now() - start) / 1000)
