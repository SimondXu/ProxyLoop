"""Slow's wake contract (S1-SYS-29, ARCHITECTURE §11): W1 must-see wakes, L2 the
in-call heartbeat, L3 one step at a time with wakes coalesced, L4 a schedule that
no step's content moves but a successful wait or finish (rule 12), L5 fixed wake
reasons. A real ``Kernel`` on virtual time; Slow answers from a script."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Coroutine, Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.concurrency.harness import SCRIPTS, Sim, VirtualTime
from tests.support.fakes import RepeatingLLM
from tests.support.manual_clock import ManualClock
from tests.support.sessions import act, fake_config, patient_task

from proxyloop.contract.events import Event
from proxyloop.contract.llm import (
    LLMCallRecord,
    LLMClient,
    LLMRole,
    ModelRef,
    TextRequest,
    ToolRequest,
)
from proxyloop.core.bus import Bus
from proxyloop.kernel import session, wake, watchdog
from proxyloop.kernel.channels import Channel, Incoming
from proxyloop.kernel.session import ChannelSpec, Kernel
from proxyloop.llm.http import RecordSink
from proxyloop.slow import loop

NOTED = act("Noted.")
STEP = {  # Slow's step kinds; only a successful wait or finish may move the schedule
    "normal": act("Noted.", public="Calling Northwind for the account holder."),
    "no_tool": json.dumps({"text": "Thinking.", "tool_calls": []}),
    "refused": act(  # run 655087: a guide refused, then nothing
        "Steering.",
        {"tool": "guide_fast", "move": "identify", "slots": ["fact:account.last4"]},
    ),
    "bad_wait": act("Waiting.", {"tool": "wait", "seconds": 30}),  # refused
    "content_filter": json.dumps({"text": "", "tool_calls": []}),
}


def wait(seconds: int) -> str:
    return act("Waiting.", {"tool": "wait", "seconds": seconds})


class Steps(RepeatingLLM):
    """Slow's steps in order (the last repeats), each ``step_ms`` of virtual time;
    a ``content_filter`` step is recorded with that finish reason."""

    def __init__(
        self,
        ref: ModelRef,
        vt: VirtualTime,
        sink: RecordSink,
        kinds: Sequence[str],
        step_ms: int,
    ) -> None:
        cut = "content_filter"
        filtered = {f"slow:{n}" for n, x in enumerate(kinds, 1) if x == cut}

        def record(r: LLMCallRecord) -> None:
            reason = "content_filter" if r.call_id in filtered else r.finish_reason
            sink(r.model_copy(update={"finish_reason": reason}))

        said = [STEP.get(x, x) for x in kinds] or [NOTED]
        super().__init__(ref, said, vt, False, record)
        self._vt, self._step_ms = vt, step_ms

    async def _next(self, request: TextRequest | ToolRequest) -> tuple[str, int]:
        if self._step_ms:
            await self._vt.sleep(self._step_ms / 1000)
        return await super()._next(request)


class Call(Sim):
    """A session: Slow answers ``kinds`` (see ``Steps``), FastC says ``fast_cp``."""

    def __init__(
        self,
        root: Path,
        kinds: Sequence[str] = ("normal",),
        step_ms: int = 0,
        fast_cp: str = "Okay.",
    ) -> None:
        self.vt, self.rep, self.user = VirtualTime(), Channel(), Channel()
        self._run, self._rep = None, 0
        self.rep_turns, self.rep_busy = [], []
        vt = self.vt

        def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
            if role == "slow":
                return Steps(ref, vt, sink, kinds, step_ms)
            said = [fast_cp] if role == "fast_cp" else SCRIPTS.get(role, ["unused"])
            return RepeatingLLM(ref, list(said), vt, False, sink)

        specs: dict[str, ChannelSpec] = {"user": self.user, "cp": self.rep}
        cfg, task = fake_config(), patient_task()
        self.k = Kernel(cfg, task, specs, root, vt, vt.sleep, make, None)

    def steps(self) -> list[tuple[Event, Event | None]]:  # (started, completed)
        started, done = self.of("slow.step.started"), self.of("slow.step.completed")
        return [(s, done[n] if n < len(done) else None) for n, s in enumerate(started)]

    def strike(self) -> None:
        self.rep.incoming.put_nowait(Incoming((), strike=True))

    def hang_up(self, text: str) -> None:  # the rep closes the call
        self.rep.incoming.put_nowait(Incoming(((text, None),), end="closed"))


def play(case: Callable[[], Coroutine[Any, Any, None]]) -> None:
    asyncio.run(asyncio.wait_for(case(), timeout=60))


def reasons(e: Event) -> list[str]:
    return list(cast(list[str], e.payload["wake_reasons"]))


def one_at_a_time(sim: Call) -> None:
    steps = sim.steps()
    for (s, d), (nxt, _) in pairwise(steps):
        assert d is not None and s.seq < d.seq < nxt.seq, (s.seq, nxt.seq)


# W1: the must-see wakes, gated on the open call (a unit test of the subscriber).
class Host:
    """What ``Wakes`` reads of a ``Kernel``: Slow's wakes and the timers spawned."""

    def __init__(self) -> None:
        self.slow, self.woken, self.timers = self, list[str](), 0

    def wake(self, reason: str) -> None:
        self.woken.append(reason)

    def spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        self.timers += 1
        coro.close()

    def now(self) -> int:
        return 0


def test_rep_turns_and_strikes_wake_slow_only_while_the_call_is_open(
    tmp_path: Path,
) -> None:
    host = Host()
    bus = Bus(tmp_path / "events.jsonl", "r", ManualClock())
    bus.subscribe(wake.Wakes(cast(Kernel, host)).on_event)
    root = bus.emit("user.msg", "kernel", "agent", {"text": "Hi"})
    n = iter(range(1, 100))

    def emit(type_: str, cause: Event = root, **payload: object) -> Event:
        return bus.emit(type_, "kernel", "agent", payload, [cause.event_id])

    def rep(speaker: str = "partner") -> None:
        emit("utt.final", speaker=speaker, utt_id=f"cp-{next(n)}", lane="cp", text="Hi")

    def step(*calls: dict[str, object]) -> None:
        started = emit("slow.step.started", basis_seq=bus.bb.seq, wake_reasons=[])
        for c in calls:
            emit("slow.tool", started, name=c["tool"], args=c, result_text="", ok=True)
        emit("slow.step.completed", started, basis_seq=started.seq)

    rep()
    emit("chan.strike", lane="cp")
    step()  # before the call: no heartbeat
    assert (host.woken, host.timers) == ([], 0)
    emit("chan.opened", lane="user")
    assert host.woken == []
    emit("chan.opened", lane="cp")
    rep()
    emit("chan.strike", lane="cp")
    rep("agent")
    assert host.woken == ["rep_turn", "strike"]
    step()  # in the call: the heartbeat
    assert host.timers == 1
    emit("chan.closed", lane="cp")
    rep()
    emit("chan.strike", lane="cp")
    assert host.woken == ["rep_turn", "strike", "call_closed"]
    step()  # after the call: no heartbeat
    assert host.timers == 1
    step({"tool": "wait", "seconds": 5})  # but a wait still wakes
    assert host.timers == 2
    bus.close()


def test_every_wake_reason_in_the_source_is_enumerated() -> None:  # S5b: signals
    src = Path(wake.__file__).parents[1]
    said = re.compile(r"\b_?wake\(\s*\"([a-z_.]+)\"")
    found = {m for p in src.rglob("*.py") for m in said.findall(p.read_text())}
    assert found and found <= wake.REASONS, found - wake.REASONS
    authority = {"approval.decided", "mandate.decided", "speak.revoked"}  # e.type
    assert authority <= wake.REASONS
    assert all(re.fullmatch(r"[a-z_.]+", r) for r in wake.REASONS)  # no text


# L3: one step at a time, wakes merged.
def test_wakes_during_a_step_coalesce_into_one_next_step(tmp_path: Path) -> None:
    sim = Call(tmp_path, step_ms=8_000)

    async def case() -> None:
        await sim.start()
        sim.rep_says("Hello, who is this?")
        await sim.vt.run_for(2_000)
        sim.rep_says("Are you there?")
        await sim.vt.run_for(2_000)
        sim.strike()
        await sim.vt.run_for(2_000)
        sim.rep_says("Hello?")
        await sim.vt.run_for(9_000)  # step 1 ends at +8 s; step 2 runs to +16 s
        await sim.stop()

    play(case)
    (first, done), (second, _) = sim.steps()
    assert reasons(first) == ["rep_turn"]
    assert done is not None and second.t_ms == done.t_ms
    assert reasons(second) == ["rep_turn", "strike"]
    one_at_a_time(sim)


# L2: the heartbeat, and a wait that can only shorten it.
@pytest.mark.parametrize(
    ("kind", "after_ms", "why"),
    [
        (wait(5), 5_000, "timer"),
        (wait(15), 15_000, "timer"),
        ("bad_wait", 15_000, "heartbeat"),  # wait(30) in a call: woken at 15 s
        ("no_tool", 15_000, "heartbeat"),
    ],
    ids=["wait5", "wait15", "wait30", "no_tool"],
)
def test_in_a_call_slow_is_woken_by_its_wait_or_the_heartbeat(
    tmp_path: Path, kind: str, after_ms: int, why: str
) -> None:
    sim = Call(tmp_path, [kind, NOTED])

    async def case() -> None:
        await sim.start()
        sim.rep_says("Hello, who is this?")
        await sim.vt.run_for(40_000)
        await sim.stop()

    play(case)
    (_, done), (nxt, _), *_ = sim.steps()
    assert done is not None and (nxt.t_ms - done.t_ms, reasons(nxt)) == (
        after_ms,
        [why],
    )


@pytest.mark.parametrize("seconds", [5.0, 7.5, True, "5"], ids=str)
def test_a_wait_that_is_not_a_json_integer_is_refused(
    tmp_path: Path, seconds: object
) -> None:  # review D1: refused and counted, never coerced (rule 12)
    sim = Call(tmp_path, [act("Waiting.", {"tool": "wait", "seconds": seconds}), NOTED])

    async def case() -> None:
        await sim.start()
        sim.rep_says("Hello, who is this?")
        await sim.vt.run_for(20_000)
        await sim.stop()

    play(case)
    assert [e.payload["reason"] for e in sim.of("session.ended")] == ["stopped"]
    assert [t.payload["ok"] for t in sim.of("slow.tool", name="wait")] == [False]
    (_, done), (nxt, _) = sim.steps()
    assert done is not None and nxt.t_ms - done.t_ms == 15_000
    assert reasons(nxt) == ["heartbeat"]


@pytest.mark.parametrize(
    ("kind", "woken"), [(NOTED, 0), (wait(5), 1)], ids=["noted", "wait5"]
)
def test_after_the_call_only_a_wait_wakes_slow(
    tmp_path: Path, kind: str, woken: int
) -> None:
    sim = Call(tmp_path, [kind, NOTED])

    async def case() -> None:
        await sim.start()
        sim.hang_up("Goodbye.")
        await sim.vt.run_for(60_000)
        await sim.stop()

    play(case)
    (first, done), *rest = sim.steps()
    assert reasons(first) == ["call_closed", "rep_turn"]
    assert len(rest) == woken
    if rest:
        assert done is not None and rest[0][0].t_ms == done.t_ms + 5_000


# Regressions shaped like the live runs.
def test_a_refused_guide_then_silence_gets_a_heartbeat_step(tmp_path: Path) -> None:
    sim = Call(tmp_path, ["refused", NOTED])  # run 655087

    async def case() -> None:
        await sim.start()
        sim.rep_says("Can you verify the account?")
        await sim.vt.run_for(16_000)
        await sim.stop()

    play(case)
    assert [t.payload["ok"] for t in sim.of("slow.tool", name="guide_fast")] == [False]
    (_, done), (nxt, _) = sim.steps()
    assert done is not None and nxt.t_ms - done.t_ms == 15_000
    assert reasons(nxt) == ["heartbeat"]


def seen_within_one_step(sim: Call) -> None:
    """L1: each rep turn is seen by the next step, which starts at once, or as
    soon as the step running when the rep spoke ends."""
    steps = sim.steps()
    for u in sim.of("utt.final", speaker="partner"):
        nxt = next(s for s, _ in steps if s.seq > u.seq)
        assert int(str(nxt.payload["basis_seq"])) >= u.seq
        running = [
            d for s, d in steps if s.seq < u.seq and (d is None or d.seq > u.seq)
        ]
        due = u.t_ms if not running else cast(Event, running[0]).t_ms
        # the same instant, but for the 1 ms each fake call (here FastC's) takes
        assert 0 <= nxt.t_ms - due <= 2, (u.seq, u.t_ms, nxt.t_ms, due)


def test_slow_sees_every_rep_turn_while_fastc_keeps_holding(tmp_path: Path) -> None:
    sim = Call(tmp_path, step_ms=3_000, fast_cp="One moment.\n@hold offer")  # f3a106

    async def case() -> None:
        await sim.start()
        for n in range(12):
            sim.rep_says(f"Hello? Are you still there, caller {n}?")
            await sim.vt.run_for(5_000)
        await sim.vt.run_for(1_000)
        await sim.stop()

    play(case)
    assert len(sim.of("f2s.msg", type="HOLD")) == 1  # FastC's repeats are deduped
    assert len(sim.of("utt.final", speaker="partner")) == 12
    seen_within_one_step(sim)
    one_at_a_time(sim)


def test_a_rep_turn_every_2_s_for_720_s_stays_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(watchdog, "MAX_SESSION_S", 800.0)  # two calls (S1-SYS-24)
    # the fake FastC's 360 calls are unpriced here; live FastC is vLLM (gpu_time)
    monkeypatch.setattr(session, "PROJECTED", (600_000, 1_000))
    sim = Call(tmp_path, step_ms=10_000)

    async def case() -> None:
        await sim.start()
        for _ in range(360):
            sim.rep_says("Hello?")
            await sim.vt.run_for(2_000)
        await sim.vt.run_for(11_000)
        await sim.stop()

    play(case)
    assert [e.payload["reason"] for e in sim.of("session.ended")] == ["stopped"]
    steps = sim.steps()
    assert 70 <= len(steps) <= loop.MAX_STEPS == 80
    one_at_a_time(sim)
    seen_within_one_step(sim)


# L4 (rule 12): the schedule is a function of external events and the clock.
def schedule(root: Path, kinds: Sequence[str], rep_ms: Sequence[int]) -> list[Any]:
    sim = Call(root, [*kinds, "normal"], step_ms=1_000)

    async def case() -> None:
        await sim.start()
        t = 0
        for due in sorted(rep_ms):
            await sim.vt.run_for(due - t)
            sim.rep_says("Hello?")
            t = due
        await sim.vt.run_for(90_000 - t)
        await sim.stop()

    play(case)
    return [(s.t_ms, reasons(s)) for s, _ in sim.steps()]


@settings(max_examples=25, deadline=None)
@given(
    kinds=st.lists(st.sampled_from(sorted(STEP)), min_size=1, max_size=6),
    rep_ms=st.lists(st.integers(0, 60_000), min_size=1, max_size=4, unique=True),
)
def test_no_step_content_moves_the_wake_schedule(
    tmp_path_factory: pytest.TempPathFactory, kinds: list[str], rep_ms: list[int]
) -> None:
    root = tmp_path_factory.mktemp("l4")
    base = schedule(root / "base", ["normal"] * len(kinds), rep_ms)
    assert schedule(root / "kinds", kinds, rep_ms) == base
    gaps = [b[0] - a[0] for a, b in pairwise(base)]
    assert base and max(gaps, default=0) <= 16_001  # L2: 15 s after a 1 s step


# S5b: the timer's due time is derivable from the log and constants.
def derived_due(events: Sequence[Event]) -> dict[int, tuple[int, str]]:
    """Each completed step's timer, by its seq: due at its t_ms plus its successful
    wait, or HEARTBEAT_S in a call without one (a wait can only shorten it); no
    timer outside a call without a wait, or after a finish."""
    out: dict[int, tuple[int, str]] = {}
    call, waited, done = False, None, False
    for e in events:
        p = e.payload
        if e.type in ("chan.opened", "chan.closed") and p["lane"] == "cp":
            call = e.type == "chan.opened"
        elif e.type == "slow.step.started":
            waited, done = None, False
        elif e.type == "slow.tool" and p["ok"] and p["name"] in ("wait", "finish"):
            args = cast(dict[str, object], p["args"])
            waited = int(str(args["seconds"])) if p["name"] == "wait" else waited
            done |= p["name"] == "finish"
        elif e.type == "slow.step.completed" and not done:
            if waited is not None and (not call or waited <= wake.HEARTBEAT_S):
                out[e.seq] = (e.t_ms + 1000 * waited, "timer")
            elif call:
                out[e.seq] = (e.t_ms + 1000 * wake.HEARTBEAT_S, "heartbeat")
    return out


def test_the_timer_due_time_is_derived_from_the_log(tmp_path: Path) -> None:
    kinds = ["no_tool", wait(4), "refused", wait(9), "normal", "normal", wait(6)]
    sim = Call(tmp_path, [*kinds, NOTED])

    async def case() -> None:
        await sim.start()
        sim.rep_says("Hello?")
        await sim.vt.run_for(60_000)
        sim.hang_up("Bye.")
        await sim.vt.run_for(30_000)
        await sim.stop()

    play(case)
    due, steps, timed = derived_due(sim.events), sim.steps(), 0
    for (_, done), (nxt, _) in pairwise(steps):
        assert done is not None
        if reasons(nxt) in (["timer"], ["heartbeat"]):
            timed += 1
            assert (nxt.t_ms, reasons(nxt)[0]) == due[done.seq]
        else:  # another wake came first
            assert done.seq not in due or nxt.t_ms <= due[done.seq][0]
    last = steps[-1][1]
    assert last is not None and last.seq not in due  # after the call, no heartbeat
    assert timed == 6, [(s.t_ms, reasons(s)) for s, _ in steps]
