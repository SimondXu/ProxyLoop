"""Watchdog (§11): the rep's clock ticks on a free floor; the user lane has no
patience (I7). Past the run budget the session ends with ``timeout``."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

TICK_S, MAX_SESSION_S = 1.0, 900.0  # [E] a stop for one S0 call, not a target


class SessionEnd(Exception):
    """Ends the session normally with ``reason`` (``session.ended``)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def watchdog(k: Kernel) -> None:
    rep, speaker = k.channels["cp"], k.speakers["cp"]
    while True:
        await k.sleep(TICK_S)
        if (t := k.now()) > 1000 * MAX_SESSION_S:
            raise SessionEnd("timeout")
        if not speaker.speaking and not rep.busy:
            k.spawn(rep.tick(t))
