"""Slow's wake contract (S1-SYS-29, ARCHITECTURE §11): W1 must-see wakes, L2 the
in-call heartbeat, L3 one step at a time with wakes coalesced, L4 a schedule that
no step's content moves but a successful wait or finish (rule 12), L5 fixed wake
reasons. A real ``Kernel`` on virtual time; Slow answers from a script."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from collections.abc import Callable, Coroutine, Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from tests.concurrency.harness import SCRIPTS, Sim, VirtualTime, called
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
from proxyloop.kernel.watchdog import Abort
from proxyloop.llm.http import RecordSink
from proxyloop.slow import loop, prompt

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
    """A session: Slow answers ``kinds`` (see ``Steps``); FastC says ``fast_cp``,
    each generation taking ``fast_ms``."""

    def __init__(
        self,
        root: Path,
        kinds: Sequence[str] = ("normal",),
        step_ms: int = 0,
        fast_cp: str = "Okay.",
        fast_ms: int = 0,
    ) -> None:
        self.vt, self.rep, self.user = VirtualTime(), Channel(), Channel()
        self._run, self._rep = None, 0
        self.rep_turns, self.rep_busy = [], []
        vt = self.vt

        def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
            if role == "slow":
                return Steps(ref, vt, sink, kinds, step_ms)
            if role == "fast_cp":
                return Steps(ref, vt, sink, [fast_cp], fast_ms)
            return RepeatingLLM(
                ref, list(SCRIPTS.get(role, ["unused"])), vt, False, sink
            )

        specs: dict[str, ChannelSpec] = {"user": self.user, "cp": self.rep}
        cfg, task = fake_config(), called(patient_task())
        self.k = Kernel(cfg, task, specs, root, vt, vt.sleep, make, None)

    def steps(self) -> list[tuple[Event, Event | None]]:  # (started, completed)
        started, done = self.of("slow.step.started"), self.of("slow.step.completed")
        return [(s, done[n] if n < len(done) else None) for n, s in enumerate(started)]

    def strike(self) -> None:
        self.rep.incoming.put_nowait(
            Incoming((), strike=True, strike_kind="identity", strikes=1)
        )

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
        self.lanes: dict[str, object] = {}  # no FastC: a rep turn wakes at once

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


def test_the_wait_bounds_in_slow_s_prompt_are_the_heartbeat() -> None:  # D4
    assert f"wait(seconds 1-{wake.HEARTBEAT_S})" in prompt.SYSTEM
    calls = cast(dict[str, Any], prompt.ACT.parameters["properties"])["calls"]
    seconds = calls["items"]["properties"]["seconds"]
    assert (seconds["minimum"], seconds["maximum"]) == (1, wake.HEARTBEAT_S)


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


def seen_after_fastc(sim: Call, fast_ms: int = 0) -> None:
    """L1 with the W1 rate limit: each rep turn wakes Slow once the FastC
    generation that saw it ends; the next step starts then, or as soon as the
    step running then ends. The lag is at most that generation plus the rest of
    a running step (and the 1 ms each fake call takes)."""
    steps, events = sim.steps(), sim.events
    ends = {
        str(e.payload["gen_id"]): e
        for e in events
        if e.type in ("fast.turn", "fast.cancelled")
    }
    asked = [e for e in sim.of("fast.request", lane="cp")]
    for u in sim.of("utt.final", speaker="partner"):
        saw = next(r for r in asked if int(str(r.payload["basis_seq"])) >= u.seq)
        end = ends[str(saw.payload["gen_id"])]
        nxt = next(s for s, _ in steps if s.seq > end.seq)
        assert int(str(nxt.payload["basis_seq"])) >= u.seq
        running = [
            d for s, d in steps if s.seq < end.seq and (d is None or d.seq > end.seq)
        ]
        due = end.t_ms if not running else cast(Event, running[0]).t_ms
        assert 0 <= nxt.t_ms - due <= 2, (u.seq, end.t_ms, nxt.t_ms, due)
        if not running:
            assert end.t_ms - saw.t_ms <= fast_ms + 2


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
    seen_after_fastc(sim)
    one_at_a_time(sim)


RELAYING = "Noted.\n@slow: fact monthly_price=75.00"


@pytest.mark.parametrize("fast_cp", ["Okay.", RELAYING], ids=["quiet", "relays"])
def test_one_slow_step_per_rep_turn_after_fastc_answers(
    tmp_path: Path, fast_cp: str
) -> None:  # the W1 rate limit (main root, round 2)
    sim = Call(tmp_path, step_ms=4_500, fast_cp=fast_cp, fast_ms=2_000)

    async def case() -> None:
        await sim.start()
        for n in range(10):
            sim.rep_says(f"Let me look at the account, one moment {n}.")
            await sim.vt.run_for(7_000)
        await sim.stop()

    play(case)
    turns, steps = sim.of("utt.final", speaker="partner"), sim.steps()
    assert len(turns) == len(steps) == 10  # one step per rep turn, not two
    relays = sim.of("f2s.msg", lane="cp")
    want = ["relay", "rep_turn"] if fast_cp == RELAYING else ["rep_turn"]
    assert [reasons(s) for s, _ in steps] == [want] * 10
    assert len(relays) == (10 if fast_cp == RELAYING else 0)
    for u, (s, _) in zip(turns, steps, strict=True):
        assert 2_000 <= s.t_ms - u.t_ms <= 2_000 + 2  # the lag: one generation
    seen_after_fastc(sim, 2_000)
    within_the_lag_bound(sim)
    one_at_a_time(sim)


def within_the_lag_bound(sim: Call) -> None:
    """ADR-0015 M1: each rep line is seen (a step with basis at or after it)
    by the later of the end of the step running when it was said and the end
    of the FastC generation that saw it; with no terminal for that generation,
    HEARTBEAT_S after the line (or that step's end, if later)."""
    steps, heartbeat = sim.steps(), 1000 * wake.HEARTBEAT_S
    ends = {
        str(e.payload["gen_id"]): e.t_ms
        for e in sim.events
        if e.type in ("fast.turn", "fast.cancelled")
    }
    asked = sim.of("fast.request", lane="cp")
    for u in sim.of("utt.final", speaker="partner"):
        saw = [r for r in asked if int(str(r.payload["basis_seq"])) >= u.seq]
        end = ends.get(str(saw[0].payload["gen_id"])) if saw else None
        answered = u.t_ms + heartbeat if end is None else min(end, u.t_ms + heartbeat)
        running = [
            d.t_ms
            for s, d in steps
            if s.seq < u.seq and d is not None and d.seq > u.seq
        ]
        nxt = next(s for s, _ in steps if s.seq > u.seq)
        assert int(str(nxt.payload["basis_seq"])) >= u.seq
        assert nxt.t_ms <= max([answered, *running]) + 2, (u.t_ms, nxt.t_ms)


def test_a_cancelled_generation_lets_slow_see_the_line_at_once(
    tmp_path: Path,
) -> None:  # ADR-0015 M1 (a)
    sim = Call(tmp_path, fast_ms=3_000)

    async def case() -> None:
        await sim.start()
        sim.rep_says("Hello, who is this?")
        await sim.vt.run_for(1_000)  # the epoch moves while FastC streams
        bump = {"new": sim.bb.epoch + 1, "reason": "f2s_revoke"}
        sim.k.emit("authority.epoch", "kernel", bump, [sim.k.authority.root])
        await sim.vt.run_for(10_000)
        await sim.stop()

    play(case)
    (u,) = sim.of("utt.final", speaker="partner")
    cancelled, *_ = sim.of("fast.cancelled")
    first, *_ = sim.steps()
    assert (first[0].t_ms - cancelled.t_ms, reasons(first[0])) == (0, ["rep_turn"])
    assert int(str(first[0].payload["basis_seq"])) >= u.seq
    within_the_lag_bound(sim)


@pytest.mark.parametrize(
    ("step_ms", "gap_ms"),
    [(0, 17_000), (20_000, 17_000), (0, 2_000), (0, 5_000)],
    ids=["idle", "long_steps", "lines_every_2s", "lines_every_5s"],
)
def test_a_generation_with_no_end_still_lets_slow_see_the_line(
    tmp_path: Path, step_ms: int, gap_ms: int
) -> None:  # ADR-0015 M1 (b): FastC hangs from the first rep line on; lines
    # under HEARTBEAT_S apart never push the backstop out (review D-A)
    sim = Call(tmp_path, step_ms=step_ms, fast_ms=10**9)

    async def case() -> None:
        await sim.start()
        for _ in range(max(3, 30_000 // gap_ms)):
            sim.rep_says("Hello, who is this?")
            await sim.vt.run_for(gap_ms)
        await sim.vt.run_for(40_000)
        await sim.stop()

    play(case)
    assert sim.of("fast.turn", lane="cp") == sim.of("fast.cancelled") == []
    (u, *_), (first, _) = sim.of("utt.final", speaker="partner"), sim.steps()[0]
    assert first.t_ms - u.t_ms == 15_000 and reasons(first) == ["heartbeat"]
    within_the_lag_bound(sim)
    one_at_a_time(sim)


def test_a_rep_turn_waits_for_the_fastc_generation_that_saw_it(
    tmp_path: Path,
) -> None:  # the rate limit, from the log alone
    host = Host()
    host.lanes = {"cp": object()}
    bus = Bus(tmp_path / "events.jsonl", "r", ManualClock())
    bus.subscribe(wake.Wakes(cast(Kernel, host)).on_event)
    root = bus.emit("user.msg", "kernel", "agent", {"text": "Hi"}).event_id

    def emit(type_: str, **payload: object) -> Event:
        return bus.emit(type_, "kernel", "agent", payload, [root])

    def rep() -> Event:
        said = {"speaker": "partner", "utt_id": f"cp-{bus.bb.seq}", "lane": "cp"}
        return emit("utt.final", **said, text="Hi")

    ref = {"kind": "test_fake", "endpoint": None, "model_id": "f"}

    def asked(gen: str, basis: int) -> None:
        emit("fast.request", lane="cp", gen_id=gen, trigger="rep_spoke",
             view_sha="v", prompt_sha="p", profile="pl_cp_v2", basis_seq=basis,
             model_ref=ref)  # fmt: skip

    emit("chan.opened", lane="cp")
    before = bus.bb.seq
    first = rep()
    asked("cp-g1", before)  # a generation that began before the line
    bus.emit("fast.cancelled", "fast.cp", "agent", {"gen_id": "cp-g1",
             "reason": "epoch"}, [root])  # fmt: skip
    assert host.woken == []
    asked("cp-g2", first.seq)
    second = rep()  # it waits for a later generation
    assert host.woken == []
    bus.emit("fast.cancelled", "fast.cp", "agent", {"gen_id": "cp-g2",
             "reason": "epoch"}, [root])  # fmt: skip
    assert host.woken == ["rep_turn"]
    asked("cp-g3", second.seq)
    rep()  # pending at the close: the close wakes Slow, once
    emit("chan.closed", lane="cp")
    bus.emit("fast.cancelled", "fast.cp", "agent", {"gen_id": "cp-g3",
             "reason": "epoch"}, [root])  # fmt: skip
    assert host.woken == ["rep_turn", "rep_turn", "call_closed"]
    bus.close()


@pytest.mark.parametrize(
    ("step_ms", "ended"), [(10_000, "stopped"), (4_500, "slow_step_cap")], ids=str
)
def test_a_rep_turn_every_2_s_for_720_s_stays_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step_ms: int, ended: str
) -> None:
    monkeypatch.setattr(watchdog, "MAX_SESSION_S", 800.0)  # two calls (S1-SYS-24)
    # the fake FastC's 360 calls are unpriced here; live FastC is vLLM (gpu_time)
    monkeypatch.setattr(session, "PROJECTED", (600_000, 1_000))
    sim = Call(tmp_path, step_ms=step_ms)

    async def case() -> None:
        await sim.start()
        for _ in range(360):
            sim.rep_says("Hello?")
            await sim.vt.run_for(2_000)
        await sim.vt.run_for(11_000)
        with contextlib.suppress(Abort):
            await sim.stop()

    play(case)
    assert [e.payload["reason"] for e in sim.of("session.ended")] == [ended]
    steps = sim.steps()
    one_at_a_time(sim)
    if ended == "stopped":  # about one step per step_ms, every rep turn seen
        assert 70 <= len(steps) < loop.MAX_STEPS == 120
        seen_after_fastc(sim)
    else:  # review D2: Slow is never idle, so 4.5 s steps reach the cap by ~540 s
        assert len(steps) == loop.MAX_STEPS and steps[-1][0].t_ms < 600_000


# L4 (rule 12): the schedule is a function of external events and the clock.
def schedule(
    root: Path, kinds: Sequence[str], rep_ms: Sequence[int], fast_ms: int
) -> list[Any]:
    sim = Call(root, [*kinds, "normal"], step_ms=1_000, fast_ms=fast_ms)

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


@settings(max_examples=40, deadline=None)
@given(
    kinds=st.lists(st.sampled_from(sorted(STEP)), min_size=1, max_size=6),
    rep_ms=st.lists(st.integers(0, 60_000), min_size=1, max_size=4, unique=True),
    fast_ms=st.sampled_from([0, 2_500]),  # 2.5 s: steps land while FastC runs (D-B)
)
@example(kinds=["bad_wait"], rep_ms=[0, 1], fast_ms=2_500)  # a refused tool, pending
@example(kinds=["refused", "no_tool"], rep_ms=[0, 1], fast_ms=2_500)  # FastC turns
def test_no_step_content_moves_the_wake_schedule(
    tmp_path_factory: pytest.TempPathFactory,
    kinds: list[str],
    rep_ms: list[int],
    fast_ms: int,
) -> None:
    root = tmp_path_factory.mktemp("l4")
    base = schedule(root / "base", ["normal"] * len(kinds), rep_ms, fast_ms)
    assert schedule(root / "kinds", kinds, rep_ms, fast_ms) == base
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
