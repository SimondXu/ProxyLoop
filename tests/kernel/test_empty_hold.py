"""S1-SYS-26 spec 3, pinned: FastC's ``@hold`` with no reason is no Hold. It is
a parse issue, nothing is relayed or counted, and the turn clears the public cp
hold. An idle kernel on a manual clock."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

from tests.support.fakes import RepeatingLLM
from tests.support.manual_clock import ManualClock
from tests.support.sessions import fake_config
from tests.support.sessions import patient_task as task

from proxyloop.contract.llm import LLMClient, LLMRole, ModelRef
from proxyloop.contract.protocol import Hold
from proxyloop.contract.views import Trigger
from proxyloop.kernel.lanes import _Ask  # pyright: ignore[reportPrivateUsage]
from proxyloop.kernel.session import ChannelSpec, Kernel
from proxyloop.llm.http import RecordSink


def _kernel(tmp_path: Path, fast_cp: str) -> Kernel:
    clock = ManualClock()

    def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
        script = [fast_cp] if role == "fast_cp" else ["unused"]
        return RepeatingLLM(ref, script, clock, on_record=sink)

    async def never(seconds: float) -> None:  # an idle kernel: no timer runs
        raise AssertionError(f"slept {seconds} s")

    specs: dict[str, ChannelSpec] = {"user": "sim", "cp": "sim"}
    return Kernel(fake_config(), task(), specs, tmp_path, clock, never, make, None)


def test_an_empty_hold_is_a_parse_issue_that_clears_the_public_hold(
    tmp_path: Path,
) -> None:
    k = _kernel(tmp_path, fast_cp="@hold")
    first = k.emit("user.msg", "kernel", {"text": "hi"}).event_id
    relay = k.lanes["cp"]._relay  # pyright: ignore[reportPrivateUsage]
    relay([Hold(reason="fact_request")], first, "cp-g1", None)  # a real hold first
    held = {"lane": "cp", "reason": "fact_request"}
    k.emit("chan.hold", "fast.cp", held, [first])
    cause = k.emit("user.msg", "kernel", {"text": "still there?"}).event_id
    asyncio.run(k.lanes["cp"].generate(_Ask(Trigger(kind="rep_spoke"), cause)))
    (turn,) = [e for e in k.bus.events if e.type == "fast.turn"]
    items = cast(list[dict[str, object]], turn.payload["items"])
    assert [(i["kind"], i["reason"]) for i in items] == [
        ("issue", "bad_hold_reason"),
        ("issue", "empty_turn"),  # nothing said, nothing held
    ]
    relays = [e for e in k.bus.events if e.type == "f2s.msg"]
    assert [e.payload["type"] for e in relays] == ["HOLD"]  # nothing new relayed
    assert k.counts["hold_repeat"] == k.counts["relay_rejected"] == 0
    cleared = [e for e in k.bus.events if e.type == "chan.hold"][-1]
    assert (cleared.payload["reason"], cleared.cause_ids) == (None, (turn.event_id,))
    assert k.bb.public.cp_hold is None
    k.bus.close()
