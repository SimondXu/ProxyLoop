"""Regressions from review #123 (M2-M4 and the S0-ROOT-05 nits)."""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
from typing import cast

from tests.kernel.test_session import FINISH, SCRIPTS, UNTIL
from tests.support.sessions import Person, act, ear, only_bundle, run

from proxyloop.contract.events import Event
from proxyloop.env.counterparty.simrep import RepTurn, SimRep
from proxyloop.env.tasks.loader import load_task
from proxyloop.evidence.check import check_path
from proxyloop.kernel.channels import Channel, Incoming
from proxyloop.kernel.session import DISCLOSURE, SimRepChannel

WAIT = act("Waiting.", {"tool": "wait", "seconds": 15})


class Rep(Channel):
    """A rep that says ``lines`` at fixed times (ms), then hangs up."""

    def __init__(self, lines: list[tuple[int, str]], hangup_ms: int) -> None:
        super().__init__()
        for due, text in lines:
            self.incoming.put_nowait(Incoming(((text, None),), due_ms=due))
        self.incoming.put_nowait(Incoming((), due_ms=hangup_ms, end="hangup"))


def _of(events: tuple[Event, ...], type_: str) -> list[Event]:
    return [e for e in events if e.type == type_]


def test_one_wait_timer_bounds_slow_steps(tmp_path: Path) -> None:  # M2
    run(
        tmp_path,
        SCRIPTS | {"slow": [WAIT]},
        channels={"user": "sim", "cp": Rep([], 60_000)},
    )
    events = only_bundle(tmp_path).events
    steps, relays = len(_of(events, "slow.step.started")), len(_of(events, "f2s.msg"))
    assert steps <= relays + events[-1].t_ms // 15_000 + 2, (steps, relays)


def test_a_closed_call_closes_once_and_delivers_nothing_after(
    tmp_path: Path,
) -> None:  # M3
    scripts = SCRIPTS | {"ear": [ear("ask_supervisor")], "slow": [WAIT]}
    result = run(tmp_path, scripts, until={"slow": ("call_closed", FINISH)})
    assert result.reason == "info_only"
    events = only_bundle(tmp_path).events
    (closed,) = _of(events, "chan.closed")
    after = [e for e in events if e.seq > closed.seq and e.payload.get("lane") == "cp"]
    assert not [e for e in after if e.type == "utt.delivered"]
    wakes = [str(e.payload["wake_reasons"]) for e in _of(events, "slow.step.started")]
    assert sum("call_closed" in w for w in wakes) == 1


def test_the_disclosure_is_heard_whole_even_if_the_rep_talks(
    tmp_path: Path,
) -> None:  # M4
    rep = Rep([(10, "Hello, who is this?")], hangup_ms=30_000)
    run(tmp_path, SCRIPTS, channels={"user": "sim", "cp": rep})
    events = only_bundle(tmp_path).events
    cp = [e for e in _of(events, "utt.delivered") if e.payload["lane"] == "cp"]
    assert (
        cp[0].payload["text_heard"] == DISCLOSURE and not cp[0].payload["interrupted"]
    )
    fast = [e for e in _of(events, "fast.sentence") if e.payload["lane"] == "cp"]
    assert all(e.seq > cp[0].seq for e in fast)
    assert (
        not _of(events, "chan.barge_in")
        or _of(events, "chan.barge_in")[0].seq > cp[0].seq
    )


def test_a_rep_turn_counts_as_busy_from_its_spawn() -> None:  # nit: busy
    class Stub:
        async def tick(self, t_ms: int) -> RepTurn:
            return RepTurn((), strike_causes=(), end="")

    channel = SimRepChannel(cast(SimRep, Stub()))
    turn = channel.tick(0)
    assert channel.busy  # before it runs: a watchdog tick cannot overlap it
    asyncio.run(turn)
    assert not channel.busy


class Late(Person):
    """A person who answers each rep turn 20 s later (a slow typist)."""

    async def send(self, text: str | None, utt_id: str, cause: str, t_ms: int) -> None:
        if text and self.lines:
            line = self.lines.pop(0)
            end = "quit" if line == "/quit" else ""
            lines = () if end else ((line, None),)
            self.incoming.put_nowait(Incoming(lines, due_ms=t_ms + 20_000, end=end))


def test_rep_chat_suspends_patience_and_builds_no_slow(tmp_path: Path) -> None:  # nits
    person = Late(["Hi, this is Dana Reyes calling about my bill.", "/quit"])
    task = load_task("cp-direct-discount")  # default patience: 3 x 6 s
    name = {"key": "account.holder_name", "value": "Dana Reyes"}  # no identity strike
    scripts = SCRIPTS | {"ear": [ear("other"), ear("provide_fact", facts=[name])]}
    result = run(
        tmp_path, scripts, channels={"cp": "sim", "cp_agent": person}, task=task
    )
    assert result.reason == "stopped"  # not abandoned: the rep never struck out
    bundle = only_bundle(tmp_path)
    assert not _of(bundle.events, "chan.strike")
    assert "slow" not in bundle.manifest.reality
    assert check_path(result.path, "offline").ok


def test_rep_chat_speaks_after_the_disclosure(tmp_path: Path) -> None:  # nit
    eager = Person(["/quit"])
    eager.incoming.put_nowait(Incoming((("Hi there, straight away.", None),)))
    run(tmp_path, SCRIPTS, channels={"cp": "sim", "cp_agent": eager})
    events = only_bundle(tmp_path).events
    disclosed = next(
        e for e in _of(events, "utt.delivered") if e.payload["lane"] == "cp"
    )
    agent = [e for e in _of(events, "utt.final") if e.payload["speaker"] == "agent"]
    assert agent and agent[0].seq > disclosed.seq
    assert Counter(e.type for e in events)["session.ended"] == 1


class QuitAfterClose(Person):
    """Rep-chat: says one line, then types /quit after each rep turn."""

    async def send(self, text: str | None, utt_id: str, cause: str, t_ms: int) -> None:
        if text:
            self.heard.append(text)
            self.incoming.put_nowait(Incoming((), end="quit"))


def test_rep_chat_ends_promptly_when_the_rep_closes(tmp_path: Path) -> None:  # R2 M1
    person = QuitAfterClose([])
    person.incoming.put_nowait(Incoming((("Hi, calling about my bill.", None),)))
    scripts = SCRIPTS | {"ear": [ear("ask_supervisor")]}
    result = run(tmp_path, scripts, channels={"cp": "sim", "cp_agent": person})
    assert result.reason == "stopped"  # no Slow judged it: never a claim reason
    events = only_bundle(tmp_path).events
    assert len(_of(events, "chan.closed")) == 1
    assert events[-1].t_ms < 60_000  # prompt, not the 900 s timeout
    assert person.heard  # the person read the rep's closing line


def test_nothing_runs_on_the_cp_lane_after_it_closes(tmp_path: Path) -> None:  # N5
    scripts = SCRIPTS | {"ear": [ear("ask_supervisor")], "slow": [WAIT]}
    run(tmp_path, scripts, until={"slow": ("call_closed", FINISH)})
    events = only_bundle(tmp_path).events
    (closed,) = _of(events, "chan.closed")
    late = [
        e
        for e in events
        if e.seq > closed.seq
        and e.type in ("llm.call", "fast.request", "fast.turn", "fast.sentence")
        and "cp" in (e.payload.get("lane"), str(e.payload.get("role"))[5:])
    ]
    assert not late


def test_only_the_cp_lane_can_close(tmp_path: Path) -> None:  # N6
    class User(Channel):
        def __init__(self) -> None:
            super().__init__()
            self.incoming.put_nowait(
                Incoming((("hi", None),), due_ms=100, end="closed")
            )

    scripts = SCRIPTS | {"slow": [WAIT]}
    run(tmp_path, scripts, channels={"user": User(), "cp": "sim"}, until=UNTIL)
    events = only_bundle(tmp_path).events
    assert not _of(events, "chan.closed")
    assert [e for e in _of(events, "utt.delivered") if e.payload["lane"] == "cp"]
