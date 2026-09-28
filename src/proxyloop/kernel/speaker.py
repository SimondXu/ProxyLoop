"""Speakers (§11): chat at once; cp holds the floor with the speech clock
``min(12 s, words / 2.8)``, and a partner barging in cuts the line and the turn.

Guard's verbatim lines (§9.4) take the floor in turn with Fast's. There an
accept is revalidated (``guard.revalidate`` at now plus its speech time): it is
released with its ``cap_id`` (M7), or revoked with the reason, ``fence`` under
a user fence (or one raised while it waited). Under partner fences only
(S1-SYS-23) it gives the floor back and waits until they clear (Slow saw the
rep's turn) or the epoch moves, then is revalidated; a wait that lasts until
the line could no longer end before its capability expires ends it
``expired`` (fail closed, bounded: no line wedges the case on
``accept_in_flight``). So every accept line ends in exactly one
``speak.released`` or ``speak.revoked`` (unless the session ends first: N3).
Its status follows only from what happened: heard whole, cut by a barge-in
(``accept_truncated``) or revoked.

A partner turn goes before a queued verbatim line: while the partner composes
it, while it is queued, and from its barge-in until its lines have landed, no
verbatim line takes the floor, so an accept is revalidated only on a board that
has the partner's turn (I6 timing). A wait past the capability's expiry ends
the line ``expired`` there. While a verbatim line waits for the floor, Fast
starts no new turn (it finishes the one it is speaking): the partner's
backlog drains, and the line takes the floor as its last reply lands
(S1-SYS-56)."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from proxyloop.contract.base import Lane
from proxyloop.contract.events import Event
from proxyloop.guard.capability import revalidate

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

WORDS_PER_S, MAX_LINE_S = 2.8, 12.0
Sleep = Callable[[float], Awaitable[None]]


def heard_prefix(text: str, seconds: float) -> str:  # a prefix of text
    words = list(re.finditer(r"\S+", text))
    n = min(len(words), int(seconds * WORDS_PER_S))
    return text[: words[n - 1].end()] if n else ""


def speech_s(text: str) -> float:
    return min(MAX_LINE_S, len(text.split()) / WORDS_PER_S)


class Speaker:
    def __init__(self, k: Kernel, lane: Lane) -> None:
        self._k, self.lane, self._channel = k, lane, k.channels[lane]
        self._lock, self._barge = asyncio.Lock(), asyncio.Event()
        self.speaking = False
        self._stale = False  # the partner was mid-turn when this speech began
        self._partner = 0  # partner turns begun whose lines have not landed
        self._partner_idle = asyncio.Event()
        self._partner_idle.set()
        self._queued = 0  # verbatim lines waiting for the floor
        self._no_queued = asyncio.Event()
        self._no_queued.set()

    async def speak(
        self, lines: Sequence[tuple[str, str, str]], interruptible: bool = True
    ) -> None:
        while True:  # no new turn while a verbatim line waits for the floor
            await self._no_queued.wait()
            await self._lock.acquire()
            if not self._queued:
                break
            self._lock.release()
        try:
            last, heard = await self._deliver(lines, interruptible)
        finally:
            self._lock.release()
        self._send(last, heard)

    async def verbatim(self, said: Event) -> None:
        """Guard's accept or decline line: revalidated and released or revoked
        on the floor; an accept's status follows from its delivery."""
        k, p = self._k, said.payload
        text, kind, cap = str(p["text"]), p["kind"], p.get("cap_id")
        held = {} if cap is None else {"cap_id": cap}
        why = await self._floor_revalidated(None if cap is None else str(cap), text)
        try:  # in turn with Fast's lines, after any pending partner turn
            if why is not None:
                out = {"lane": self.lane, "reason": why} | held
                revoked = k.emit("speak.revoked", "kernel", out, [said.event_id])
                if kind == "accept":
                    k.authority.move("accept_revoked", revoked.event_id)
                return
            out = {"lane": self.lane} | held
            released = k.emit("speak.released", "kernel", out, [said.event_id])
            line = (f"{kind}-{said.seq}", text, released.event_id)
            last, heard = await self._deliver([line], True)
            if kind == "accept" and last is not None:
                cut = bool(last.payload["interrupted"])
                heard_as = "accept_truncated" if cut else "accept_heard"
                k.authority.move(heard_as, last.event_id)
        finally:
            self._lock.release()
        self._send(last, heard)

    async def _floor_revalidated(self, cap: str | None, text: str) -> str | None:
        """Take the floor, then revalidate ``cap``: why the line may not go out.
        Under partner fences only, give the floor back and wait until a fence
        or the epoch moves, or the line would end past its capability's
        expiry. A user fence raised while it waits revokes it ``fence``."""
        k, speech, users = self._k, round(1000 * speech_s(text)), None
        while True:
            await self._floor_after_partner()
            end = k.now() + speech
            why = "call_closed" if k.closed else None
            if why is None and cap is not None:
                why = revalidate(k.bb, cap, end)
            if why in (None, "fence") and users not in (None, k.authority.user_fences):
                return "fence"  # a user fence rose (even if it cleared) meanwhile
            if why != "fence" or cap is None or not k.authority.partner_only():
                return why
            users = k.authority.user_fences if users is None else users
            expires = k.bb.capabilities[cap].expires_ms  # revalidate found it
            if expires <= end:
                return "expired"
            self._lock.release()
            await self._first(k.authority.moved(), k.sleep((expires - end) / 1000))

    @staticmethod
    async def _first(*waits: Awaitable[object]) -> None:
        tasks = [asyncio.ensure_future(w) for w in waits]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()

    def _partner_pending(self) -> bool:  # a turn begun, queued or composed
        ch = self._channel
        return self._partner > 0 or ch.busy or not ch.incoming.empty()

    async def _floor_after_partner(self) -> None:
        """Take the floor (the lock, acquired) with no partner turn pending: not
        begun, queued, or being composed, as a reply the stale path (ROOT-05 i)
        would not let cut the line. Meanwhile Fast starts no new turn."""
        self._queued += 1
        self._no_queued.clear()
        try:
            while True:
                await self._partner_idle.wait()
                await self._channel.quiet()
                if not self._channel.incoming.empty():  # the ingress takes it next
                    await asyncio.sleep(0)
                    continue
                await self._lock.acquire()
                if not self._partner_pending():
                    return
                self._lock.release()  # a partner turn began while this line queued
        finally:
            self._queued -= 1
            if not self._queued:
                self._no_queued.set()

    async def _deliver(
        self, lines: Sequence[tuple[str, str, str]], interruptible: bool
    ) -> tuple[Event | None, list[str]]:
        k, realtime = self._k, self.lane == "cp"
        self._barge.clear()
        self.speaking, self._stale = realtime, self._channel.busy
        self._channel.floor(False, k.now())
        heard: list[str] = []
        last: Event | None = None
        for utt_id, text, cause in lines:
            if realtime and k.closed:
                break  # the call is over
            said = await self._clock(text, interruptible) if realtime else text
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
        return last, heard

    def _send(self, last: Event | None, heard: list[str]) -> None:
        k, text = self._k, " ".join(h for h in heard if h)
        if last is not None and text:
            utt_id = str(last.payload["utt_id"])
            k.spawn(self._channel.send(text, utt_id, last.event_id, k.now()))

    @asynccontextmanager
    async def partner_turn(self) -> AsyncGenerator[None]:
        """A partner turn: it cuts the line and waits for the floor, and its
        lines land inside the block; until then no verbatim line is released.
        A partner turn begun before this speech answers an older line: it waits
        for the floor instead of cutting the line (ROOT-05 i)."""
        self._partner += 1
        self._partner_idle.clear()
        try:
            if not (self.speaking and self._stale):
                self._barge.set()
            async with self._lock:
                pass
            yield
        finally:
            self._partner -= 1
            if self._partner == 0:
                self._partner_idle.set()

    async def _clock(self, text: str, interruptible: bool) -> str:
        start, seconds = self._k.now(), speech_s(text)
        if not interruptible:  # the disclosure is heard whole (I11)
            await self._k.sleep(seconds)
            return text
        if self._barge.is_set():
            return ""
        timer = asyncio.ensure_future(self._k.sleep(seconds))
        barge = asyncio.ensure_future(self._barge.wait())
        await asyncio.wait((timer, barge), return_when=asyncio.FIRST_COMPLETED)
        timer.cancel()
        barge.cancel()
        if not self._barge.is_set():
            return text
        return heard_prefix(text, (self._k.now() - start) / 1000)
