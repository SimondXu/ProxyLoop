"""Watchdog (§11): the rep's clock ticks on a free floor, and only once the cp
call's disclosure was said (ADR-0012); the user lane has no patience (I7). Past
the run budget the session ends with ``timeout``. The S0 runaway guard (root
decision under PLAN §0.5a, 2026-09-26) sets the budget."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

TICK_S, MAX_SESSION_S = 1.0, 480.0  # a stop for one S0 call, not a target


class SessionEnd(Exception):  # a normal end with ``reason``
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Abort(RuntimeError):  # a loud failure end: ``reason``, then re-raised
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


async def watchdog(k: Kernel) -> None:
    rep, speaker = k.channels["cp"], k.speakers["cp"]
    while True:
        await k.sleep(TICK_S)
        if (t := k.now()) > 1000 * MAX_SESSION_S:
            raise SessionEnd("timeout")
        human = "cp_agent" in k.channels  # a person types: no rep patience
        called = k.calls.disclosed.is_set()  # no rep clock in the intake (R2)
        if called and not (speaker.speaking or rep.busy or k.closed or human):
            k.spawn(rep.tick(t))
