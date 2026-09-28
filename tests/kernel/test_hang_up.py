"""S1-SYS-55: a rep hang-up moves the case to ABANDONED (Guard's ``hang_up``,
§9.5) before the session ends; a user's quit does not."""

from __future__ import annotations

import asyncio
from pathlib import Path

from tests.kernel.test_session import SCRIPTS
from tests.kernel.test_session_end import Case
from tests.support.sessions import act, only_bundle, run

from proxyloop.contract.events import Event
from proxyloop.contract.state import CaseStatus
from proxyloop.evidence.check import check_path
from proxyloop.kernel.channels import Channel, Incoming

WAIT = act("Waiting.", {"tool": "wait", "seconds": 15})


class Rep(Channel):
    """Says one line, then hangs up with a last line (or none: a CLI /hangup)."""

    def __init__(self, last: tuple[tuple[str, None], ...]) -> None:
        super().__init__()
        self.incoming.put_nowait(Incoming((("Hello?", None),), due_ms=100))
        self.incoming.put_nowait(Incoming(last, due_ms=20_000, end="hangup"))


class Quitter(Channel):
    """A user who types /quit."""

    def __init__(self) -> None:
        super().__init__()
        self.incoming.put_nowait(Incoming((), due_ms=1_000, end="quit"))


def _abandoned(events: tuple[Event, ...]) -> list[Event]:
    return [
        e
        for e in events
        if e.type == "status.changed"
        and e.payload["status"] == CaseStatus.ABANDONED.value
    ]


def test_a_rep_hang_up_abandons_the_case_before_the_session_ends(
    tmp_path: Path,
) -> None:
    scripts = SCRIPTS | {"slow": [WAIT]}
    result = run(
        tmp_path, scripts, channels={"user": "sim", "cp": Rep((("Goodbye.", None),))}
    )
    assert result.reason == "abandoned"
    events = only_bundle(tmp_path).events
    (moved,) = _abandoned(events)
    (bye,) = [
        e
        for e in events
        if e.type == "utt.final" and e.payload.get("text") == "Goodbye."
    ]
    assert moved.cause_ids == (bye.event_id,)
    assert moved.payload["previous"] == CaseStatus.IN_CALL.value
    (ended,) = [e for e in events if e.type == "session.ended"]
    assert bye.seq < moved.seq < ended.seq
    assert check_path(result.path, "offline").ok


class StruckOut(Channel):
    """Hangs up on a silence strike, with no line (the world rep's hang-up)."""

    def __init__(self) -> None:
        super().__init__()
        self.incoming.put_nowait(Incoming((("Hello?", None),), due_ms=100))
        struck = Incoming((), due_ms=20_000, strike=True, end="hangup")
        self.incoming.put_nowait(struck)


def test_a_strike_hang_up_abandons_the_case_from_the_strike(tmp_path: Path) -> None:
    scripts = SCRIPTS | {"slow": [WAIT]}
    result = run(tmp_path, scripts, channels={"user": "sim", "cp": StruckOut()})
    assert result.reason == "abandoned"
    events = only_bundle(tmp_path).events
    (moved,) = _abandoned(events)
    strikes = [e for e in events if e.type == "chan.strike"]
    assert moved.cause_ids == (strikes[-1].event_id,)
    assert strikes[-1].seq < moved.seq


def test_a_hang_up_without_a_line_changes_no_status(tmp_path: Path) -> None:
    """No event of its own to cause a move (I2): main's behaviour stays. On
    virtual time, with the user's line landing in the hang-up's instant: it
    wakes FastU and Slow, yet no Slow step and no Fast turn starts once the
    hang-up is taken in, and ``session.ended`` is last."""

    def end(c: Case) -> None:
        c.says("user", "Any news?")
        c.says("cp", end="hangup")

    case = Case(tmp_path, "user", "cp")
    result = asyncio.run(asyncio.wait_for(case.run(end), timeout=30))
    assert result.reason == "abandoned"
    assert check_path(result.path, "offline").ok
    events = case.events
    moved = [e for e in events if e.type == "status.changed"]
    assert [e.payload["status"] for e in moved] == [CaseStatus.IN_CALL.value]
    assert not [e for e in events if e.type == "chan.closed"]
    (said,) = [e for e in events if e.type == "user.msg" and e.t_ms >= case.t_end]
    after = [e.type for e in events if e.seq > said.seq]
    assert not set(after) & {"slow.step.started", "fast.request"}, after
    assert events[-1].type == "session.ended"
    assert events[-1].payload["reason"] == "abandoned"


def test_a_user_quit_stops_without_abandoning(tmp_path: Path) -> None:
    scripts = SCRIPTS | {"slow": [WAIT]}
    result = run(tmp_path, scripts, channels={"user": Quitter(), "cp": "sim"})
    assert result.reason == "stopped"
    assert not _abandoned(only_bundle(tmp_path).events)
