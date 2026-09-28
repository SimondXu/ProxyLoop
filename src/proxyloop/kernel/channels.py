"""Channels (§2, §10): a lane's partner hears the agent (``send``, as heard) and
queues its turns (``incoming``); ``tick`` runs only on a free, idle floor. The
SimUser's channel also fires its unprompted stop on a trigger (#143, N6).
``make_channels`` builds a session's partners from their specs."""

from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Coroutine, Mapping
from dataclasses import dataclass
from types import CoroutineType
from typing import Any, Literal

from proxyloop.contract.config import SessionConfig
from proxyloop.contract.llm import LLMClient, LLMRole
from proxyloop.env.counterparty.simrep import RepTurn, SimRep
from proxyloop.env.tasks.schema import Task
from proxyloop.env.user.approver import Approver
from proxyloop.env.user.simuser import SimUser
from proxyloop.env.world import World

End = Literal["", "hangup", "closed", "quit"]
StrikeKind = Literal["identity", "timer"]  # a heard line's, or the clock's
type Turn = CoroutineType[Any, Any, None]


@dataclass(frozen=True, slots=True)
class Incoming:  # One partner turn: lines with the world event behind each, if any
    lines: tuple[tuple[str, str | None], ...]
    due_ms: int = 0  # not before (the SimUser's reply delay)
    strike: bool = False
    end: End = ""
    delivered: asyncio.Event | None = None  # set once its lines are emitted
    strike_kind: StrikeKind | None = None  # chan.strike's ``kind`` (S1-SYS-43)

    def __post_init__(self) -> None:
        if self.strike != (self.strike_kind is not None):
            raise ValueError("a strike, and only a strike, has a kind")


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


class SimRepChannel(Channel):  # hears text_heard; ticks on a free floor
    """A strike's kind by the rep call that made it: a heard utterance strikes
    only for identity, a tick only for the clock (``env.counterparty.policy``)."""

    def __init__(self, rep: SimRep) -> None:
        super().__init__()
        self._rep = rep

    def send(self, text: str | None, utt_id: str, cause: str, t_ms: int) -> Turn:
        heard = (
            self._rep.on_agent_utterance(utt_id, text, cause, t_ms) if text else None
        )
        return self._run(heard, "identity")

    def tick(self, t_ms: int) -> Turn:
        return self._run(self._rep.tick(t_ms), "timer")

    def floor(self, free: bool, t_ms: int) -> None:
        self._rep.floor(free, t_ms)

    def _run(self, turn: Coroutine[Any, Any, RepTurn] | None, kind: StrikeKind) -> Turn:
        self.composing(1)  # busy from the spawn: a tick never overlaps a turn

        async def run() -> None:
            try:
                done = await turn if turn else None
                if done is None:
                    return
                end: End = ("hangup" if done.strike else "closed") if done.ended else ""
                if done.lines or end or done.strike:
                    lines = tuple((text, ev) for text, ev in done.lines)
                    struck = kind if done.strike else None
                    inc = Incoming(
                        lines, strike=done.strike, end=end, strike_kind=struck
                    )
                    self.incoming.put_nowait(inc)  # queued before it is quiet
            finally:
                self.composing(-1)

        return run()


class HumanWebChannel(Channel):  # a person in the browser (S1-SYS-05)
    """serve's POSTs call ``say`` (on the kernel's loop): the line is queued,
    due at once. It hears nothing here: the page reads the event stream.
    Known gap (N4): the page sends no composing signal, so a human rep is never
    ``busy`` and #156's wait-while-composing (D1) cannot see them typing; the
    partner fences still apply once their line lands."""

    def say(self, text: str) -> None:
        if not text.strip():
            raise ValueError("an empty line")
        self.incoming.put_nowait(Incoming(((text, None),)))


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


ChannelSpec = Literal["sim", "human"] | Channel


def make_channels(
    cfg: SessionConfig,
    task: Task,
    specs: Mapping[str, ChannelSpec],
    clients: Mapping[LLMRole, LLMClient],
    world: World,
) -> dict[str, Channel]:
    """Each lane's partner: a given ``Channel`` as is (a web person, a test),
    ``"human"`` a person at the terminal, ``"sim"`` the world's SimUser/SimRep."""

    def make(key: str, spec: ChannelSpec) -> Channel:
        if spec == "human":
            return HumanChannel({"user": "ASSISTANT", "cp": "AGENT"}.get(key, "REP"))
        if spec != "sim":
            return spec
        if key == "user":
            return SimUserChannel(SimUser(task, clients["simuser"], world, cfg.seed))
        return SimRepChannel(SimRep(task, clients["ear"], clients["mouth"], world))

    return {key: make(key, spec) for key, spec in specs.items()}
