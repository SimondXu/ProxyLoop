"""S1-SYS-43: the bundle records each ``chan.strike``'s ``kind`` and the Slow
harness a session ran (``slow_fp``, ``slow_view``); the ``world_error`` key is
in ``test_loud_ends``."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import pytest
from tests.kernel.test_session import SCRIPTS, UNTIL
from tests.support.sessions import only_bundle, run

from proxyloop.contract.config import SlowViewMode
from proxyloop.env.counterparty.simrep import RepTurn, SimRep
from proxyloop.kernel.channels import Incoming, SimRepChannel
from proxyloop.slow.prompt import slow_fp


class _Rep:  # strikes on every heard line and every tick
    async def on_agent_utterance(self, *args: object) -> RepTurn:
        return RepTurn((), strike=True, ended=False)

    async def tick(self, t_ms: int) -> RepTurn:
        return RepTurn((), strike=True, ended=False)


def test_a_heard_line_strikes_for_identity_and_a_tick_for_the_timer() -> None:
    channel = SimRepChannel(cast(SimRep, _Rep()))

    async def both() -> list[Incoming]:
        await channel.send("No.", "u1", "c", 0)
        await channel.tick(1_000)
        return [channel.incoming.get_nowait() for _ in range(2)]

    heard, ticked = asyncio.run(both())
    assert (heard.strike, heard.strike_kind) == (True, "identity")
    assert (ticked.strike, ticked.strike_kind) == (True, "timer")


@pytest.mark.parametrize(
    ("strike", "kind"), [(True, None), (False, "timer")], ids=["no_kind", "no_strike"]
)
def test_a_strike_has_a_kind_and_only_a_strike_has_one(
    strike: bool, kind: str | None
) -> None:
    with pytest.raises(ValueError, match="only a strike"):
        Incoming((), strike=strike, strike_kind=kind)  # type: ignore[arg-type]


def test_session_started_names_the_slow_harness(tmp_path: Path) -> None:
    result = run(tmp_path, SCRIPTS, until=UNTIL)
    started = only_bundle(tmp_path).events[0]
    assert started.type == "session.started" and result.reason == "info_only"
    mode = SlowViewMode(started.payload["slow_view"])
    assert mode is SlowViewMode.TRANSCRIPT  # the SessionConfig default
    assert started.payload["slow_fp"] == slow_fp(mode, "info_only")
