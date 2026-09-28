"""No new work starts after a session end (S1-SYS-55 follow-up). A task that
ends the session raises ``SessionEnd``, but the TaskGroup aborts only in the
failed task's done callback: every task already ready runs one more step. So a
line landing in the same instant as the end must start no Slow step and no
Fast generation, for every end kind; a model call already in flight still
records. On virtual time, where only ``run_for`` moves the clock."""

from __future__ import annotations

import asyncio
import heapq
import logging
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import cast

import pytest
from tests.concurrency.harness import (
    SCRIPTS,
    Sim,
    SlowGate,
    VirtualTime,
    called,
    settle,
)
from tests.kernel.test_calls import Clocked
from tests.support.fakes import RepeatingLLM
from tests.support.sessions import fake_config, patient_task

from proxyloop.contract.events import Event
from proxyloop.contract.llm import LLMClient, LLMRole, ModelRef
from proxyloop.kernel import watchdog
from proxyloop.kernel.channels import Channel, End, Incoming
from proxyloop.kernel.session import ChannelSpec, Kernel, RunResult
from proxyloop.llm.http import RecordSink

NEW_WORK = ("slow.step.started", "fast.request")


class SameInstant(VirtualTime):
    """Timers due at one instant fire together, as on a real loop: every task
    they wake is ready before any of them runs."""

    async def run_for(self, ms: int) -> None:
        end = self.monotonic_ms() + ms
        await settle()
        while self._timers and self._timers[0][0] <= end:
            due = self._timers[0][0]
            self.advance(max(0, due - self.monotonic_ms()))
            while self._timers and self._timers[0][0] == due:
                _, _, wake = heapq.heappop(self._timers)
                if not wake.done():  # cancelled
                    wake.set_result(None)
            await settle(12)
        self.advance(max(0, end - self.monotonic_ms()))
        await settle()


class Case:
    """A kernel on virtual time over silent channels the test speaks for."""

    def __init__(self, root: Path, *keys: str) -> None:
        self.vt = SameInstant()
        self.ch = {key: Clocked() if key == "cp" else Channel() for key in keys}

        def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
            said = SCRIPTS.get(role, ["unused"])
            return RepeatingLLM(ref, said, self.vt, False, sink)

        specs: Mapping[str, ChannelSpec] = self.ch
        task, vt = called(patient_task()), self.vt
        self.k = Kernel(fake_config(), task, specs, root, vt, vt.sleep, make, None)
        self.t_end = -1  # the instant the end lands

    def says(self, key: str, text: str = "", end: End = "", due_ms: int = 0) -> None:
        lines = ((text, None),) if text else ()
        self.ch[key].incoming.put_nowait(Incoming(lines, due_ms=due_ms, end=end))

    async def run(self, end: Callable[[Case], None]) -> RunResult:
        """Past the disclosure and a rep line, then ``end`` and on to the end."""
        run = asyncio.ensure_future(self.k.run())
        await self.vt.run_for(5_000)
        if "cp_agent" not in self.ch:  # FastC has answered a rep line
            self.says("cp", "Hello?")
            await self.vt.run_for(5_000)
        self.t_end = self.vt.monotonic_ms()
        end(self)
        for _ in range(60):
            if run.done():
                break
            await self.vt.run_for(1_000)
        return await run

    @property
    def events(self) -> tuple[Event, ...]:
        return self.k.bus.events


def _ends_cleanly(case: Case, result: RunResult, reason: str, *landed: str) -> None:
    """The end's reason, ``landed`` (lines said in the end's instant) in the
    log, no new work from that instant on and ``session.ended`` last."""
    events = case.events
    assert result.reason == reason
    (ended,) = [e for e in events if e.type == "session.ended"]
    assert events[-1] == ended and ended.payload["reason"] == reason
    at_end = [e for e in events if e.t_ms >= case.t_end]
    texts = [e.payload.get("text") for e in at_end]
    assert all(text in texts for text in landed), texts
    assert not [e for e in at_end if e.type in NEW_WORK], [e.type for e in at_end]
    assert case.k.bus.subscriber_errors == 0


def _session(end: Callable[[Case], None], case: Case) -> RunResult:
    return asyncio.run(asyncio.wait_for(case.run(end), timeout=30))


@pytest.fixture(autouse=True)
def no_errors(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    caplog.set_level(logging.WARNING)
    yield
    # A gate-ended worker is a normal end: no error, no traceback.
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_hang_up_with_a_line_starts_no_new_work(tmp_path: Path) -> None:
    def end(c: Case) -> None:  # the user's line wakes FastU and Slow
        c.says("user", "Any news?")
        c.says("cp", "Goodbye.", end="hangup")

    case = Case(tmp_path, "user", "cp")
    result = _session(end, case)
    _ends_cleanly(case, result, "abandoned", "Any news?", "Goodbye.")


def test_a_hang_up_without_a_line_starts_no_new_work(tmp_path: Path) -> None:
    def end(c: Case) -> None:
        c.says("user", "Any news?")
        c.says("cp", end="hangup")

    case = Case(tmp_path, "user", "cp")
    _ends_cleanly(case, _session(end, case), "abandoned", "Any news?")


def test_a_quit_starts_no_new_work(tmp_path: Path) -> None:
    def end(c: Case) -> None:  # the rep's line wakes FastC
        c.says("cp", "One moment.")
        c.says("user", end="quit")

    case = Case(tmp_path, "user", "cp")
    _ends_cleanly(case, _session(end, case), "stopped", "One moment.")


def test_a_drain_starts_no_new_work(tmp_path: Path) -> None:
    def end(c: Case) -> None:  # Slow's finish, as SlowTools calls it
        c.says("cp", "One moment.")
        c.k.finish("info_only")

    case = Case(tmp_path, "user", "cp")
    _ends_cleanly(case, _session(end, case), "info_only", "One moment.")


def test_a_rep_chat_close_starts_no_new_work(tmp_path: Path) -> None:
    """Rep-chat (a person speaks for the agent, no Slow) with a user lane: its
    FastU is the only model work there is to start."""

    def end(c: Case) -> None:
        c.says("cp", "Bye now.", end="closed")
        c.says("user", "Any news?")

    case = Case(tmp_path, "user", "cp", "cp_agent")
    assert case.k.slow is None and set(case.k.lanes) == {"user"}
    _ends_cleanly(case, _session(end, case), "stopped", "Bye now.", "Any news?")


def test_a_timeout_starts_no_new_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user's line is due at the watchdog's tick that times out."""
    monkeypatch.setattr(watchdog, "MAX_SESSION_S", 20.0)

    def end(c: Case) -> None:
        opened, ticks = c.k.calls.opened, cast(Clocked, c.ch["cp"]).ticks
        assert opened is not None and ticks
        # the first tick past, in the watchdog's phase: the fake calls' 1 ms
        # steps shift it (S1-SYS-74: Slow's call_opened step at the start)
        due = ticks[-1] + 1_000 * ((opened.t_ms + 20_000 - ticks[-1]) // 1_000 + 1)
        c.t_end = due
        c.says("user", "Any news?", due_ms=due)

    case = Case(tmp_path, "user", "cp")
    _ends_cleanly(case, _session(end, case), "timeout", "Any news?")


@pytest.mark.parametrize(
    ("first", "reason"), [("cp", "abandoned"), ("user", "stopped")]
)
def test_the_first_end_keeps_its_reason(
    tmp_path: Path, first: str, reason: str
) -> None:
    """A hang-up and a quit in one instant: the first taken in is the end, and
    the second never overwrites its reason."""

    def end(c: Case) -> None:
        ends: dict[str, End] = {"cp": "hangup", "user": "quit"}
        for key in (first, "user" if first == "cp" else "cp"):
            c.says(key, end=ends[key])

    case = Case(tmp_path, "user", "cp")
    _ends_cleanly(case, _session(end, case), reason)
    assert case.k._ending == reason  # pyright: ignore[reportPrivateUsage]


def test_a_call_in_flight_at_the_end_still_records(tmp_path: Path) -> None:
    """Slow's call returns in the hang-up's instant: its ``llm.call`` and
    ``spend.charged`` are written, never gated."""
    case = Case(tmp_path, "user", "cp")
    held = SlowGate(cast(Sim, case))  # it needs only ``.k``
    held.let(0)  # Slow's next call waits

    def end(c: Case) -> None:
        c.says("cp", end="hangup")
        held.let(None)  # the held call returns just after

    result = _session(end, case)
    at_end = [e for e in case.events if e.t_ms >= case.t_end]
    assert [e.type for e in at_end if e.type != "session.ended"][:2] == [
        "llm.call",
        "spend.charged",
    ]
    _ends_cleanly(case, result, "abandoned")
