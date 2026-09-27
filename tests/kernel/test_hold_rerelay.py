"""S1-SYS-26 bug 2 (liveness): an unchanged cp HOLD is relayed again once Slow
has completed a step that saw it and left it unanswered (no cp GUIDE since, no
wait of its own); otherwise it is deduped (ROOT-05 (e)). Reality smoke
20260927T054451Z-655087: a refused guide_fast, then FastC held twice more and
Slow never woke. An idle kernel on a manual clock; Slow's step is the real one."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

from tests.support.fakes import RepeatingLLM
from tests.support.manual_clock import ManualClock
from tests.support.sessions import act, fake_config
from tests.support.sessions import patient_task as task

from proxyloop.contract.events import Event
from proxyloop.contract.llm import LLMClient, LLMRole, ModelRef
from proxyloop.contract.protocol import Hold
from proxyloop.contract.views import Trigger
from proxyloop.kernel.lanes import _Ask  # pyright: ignore[reportPrivateUsage]
from proxyloop.kernel.session import ChannelSpec, Kernel
from proxyloop.llm.http import RecordSink

REFUSED = act(  # last4 is not public: Guard refuses, nothing reaches FastC
    "Identify.",
    {"tool": "guide_fast", "move": "identify", "slots": ["fact:account.last4"]},
)
GUIDED = act("Ask.", {"tool": "guide_fast", "move": "ask_discount"})
HELD = [Hold(reason="fact_request")]


def _kernel(tmp_path: Path, slow: list[str], fast_cp: str = "unused") -> Kernel:
    clock = ManualClock()

    def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
        script = {"slow": slow, "fast_cp": [fast_cp]}.get(role, ["unused"])
        return RepeatingLLM(ref, script, clock, on_record=sink)

    async def never(seconds: float) -> None:  # an idle kernel: no timer runs
        raise AssertionError(f"slept {seconds} s")

    specs: dict[str, ChannelSpec] = {"user": "sim", "cp": "sim"}
    return Kernel(fake_config(), task(), specs, tmp_path, clock, never, make, None)


def _holds(k: Kernel) -> list[Event]:
    return [
        e for e in k.bus.events if e.type == "f2s.msg" and e.payload["type"] == "HOLD"
    ]


def _woken(k: Kernel) -> bool:  # Slow's wake flag; cleared by the test
    assert k.slow
    woken = k.slow._wake.is_set()  # pyright: ignore[reportPrivateUsage]
    k.slow._wake.clear()  # pyright: ignore[reportPrivateUsage]
    return woken


def _hold(k: Kernel, turn: str, gen_id: str) -> None:  # FastC's turn held
    relay = k.lanes["cp"]._relay  # pyright: ignore[reportPrivateUsage]
    relay(list(HELD), turn, gen_id, None)


def _held_once(k: Kernel) -> str:
    """FastC's first hold: relayed, then the public hold (as ``generate``)."""
    turn = k.emit("user.msg", "kernel", {"text": "hi"}).event_id
    _hold(k, turn, "cp-g1")
    k.emit("chan.hold", "fast.cp", {"lane": "cp", "reason": "fact_request"}, [turn])
    assert [e.payload["text"] for e in _holds(k)] == ["fact_request"]
    assert _woken(k)
    return turn


def test_a_hold_slow_left_unanswered_is_relayed_again(tmp_path: Path) -> None:
    k = _kernel(tmp_path, [REFUSED])
    turn = _held_once(k)
    _hold(k, turn, "cp-g2")  # Slow has not looked yet: deduped
    assert (len(_holds(k)), k.counts["hold_repeat"], _woken(k)) == (1, 1, False)
    assert k.slow
    asyncio.run(k.slow.step(["relay"]))  # the refused guide_fast; no GUIDE, no wait
    tools = [e.payload for e in k.bus.events if e.type == "slow.tool"]
    assert any(t["name"] == "guide_fast" and not t["ok"] for t in tools)
    assert not [e for e in k.bus.events if e.type == "s2f.msg"]
    again = k.emit("user.msg", "kernel", {"text": "hello?"}).event_id
    _hold(k, again, "cp-g3")  # FastC holds again, same reason
    holds = _holds(k)
    assert [e.payload["text"] for e in holds] == ["fact_request"] * 2
    assert holds[-1].cause_ids == (again,)  # the turn that held
    assert (k.counts["hold_rerelay"], k.counts["hold_repeat"]) == (1, 1)
    assert _woken(k)  # Slow wakes on the relay
    _hold(k, again, "cp-g4")  # no step since: deduped again
    assert (len(_holds(k)), k.counts["hold_repeat"], _woken(k)) == (2, 2, False)
    k.bus.close()


def test_a_hold_slow_answered_with_a_guide_is_not_relayed_again(
    tmp_path: Path,
) -> None:
    k = _kernel(tmp_path, [GUIDED])
    turn = _held_once(k)
    assert k.slow
    asyncio.run(k.slow.step(["relay"]))  # Slow answers the hold with a cp GUIDE
    guides = [e for e in k.bus.events if e.type == "s2f.msg"]
    assert [(g.payload["lane"], g.payload["type"]) for g in guides] == [("cp", "GUIDE")]
    _hold(k, turn, "cp-g2")  # FastC holds again, same reason
    assert len(_holds(k)) == 1
    assert (k.counts["hold_rerelay"], k.counts["hold_repeat"]) == (0, 1)
    assert not _woken(k)
    k.bus.close()


def test_an_empty_hold_is_a_parse_issue_that_clears_the_public_hold(
    tmp_path: Path,
) -> None:  # spec 3, pinned: "@hold" alone is no Hold, relays nothing
    k = _kernel(tmp_path, ["unused"], fast_cp="@hold")
    _held_once(k)
    cp = k.lanes["cp"]
    cause = k.emit("user.msg", "kernel", {"text": "still there?"}).event_id
    asyncio.run(cp.generate(_Ask(Trigger(kind="rep_spoke"), cause)))
    (turn,) = [e for e in k.bus.events if e.type == "fast.turn"]
    items = cast(list[dict[str, object]], turn.payload["items"])
    assert [(i["kind"], i["reason"]) for i in items] == [
        ("issue", "bad_hold_reason"),
        ("issue", "empty_turn"),  # nothing said, nothing held
    ]
    assert len(_holds(k)) == 1  # nothing relayed, nothing counted
    assert k.counts["hold_repeat"] == k.counts["hold_rerelay"] == 0
    assert k.counts["relay_rejected"] == 0
    cleared = [e for e in k.bus.events if e.type == "chan.hold"][-1]
    assert (cleared.payload["reason"], cleared.cause_ids) == (None, (turn.event_id,))
    assert k.bb.public.cp_hold is None
    k.bus.close()


def _step(k: Kernel, *tools: str) -> None:
    """A Slow step as its events (the loop's shapes): the tools all succeed."""
    basis = {"basis_seq": k.bb.seq}
    wake = basis | {"wake_reasons": ["timer"]}
    started = k.emit("slow.step.started", "slow", wake).event_id
    for name in tools:
        done: dict[str, object] = {"name": name, "args": {}, "ok": True}
        done["result_text"] = "ok"
        k.emit("slow.tool", "slow", done, [started])
    k.emit("slow.step.completed", "slow", basis, [started])


def test_a_hold_is_left_only_by_a_step_that_did_not_wait(tmp_path: Path) -> None:
    k = _kernel(tmp_path, ["unused"])  # ROOT-05 (e): a wait is Slow's own wake
    turn = _held_once(k)
    _step(k, "wait")
    _hold(k, turn, "cp-g2")
    assert (len(_holds(k)), k.counts["hold_repeat"], _woken(k)) == (1, 1, False)
    _step(k, "record_fact")  # the timer's step: no wait, no GUIDE
    _hold(k, turn, "cp-g3")
    assert (len(_holds(k)), k.counts["hold_rerelay"], _woken(k)) == (2, 1, True)
    k.bus.close()
