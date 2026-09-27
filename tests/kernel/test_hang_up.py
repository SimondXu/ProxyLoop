"""S1-SYS-55: a rep hang-up moves the case to ABANDONED (Guard's ``hang_up``,
§9.5) before the session ends; a user's quit does not."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from tests.concurrency.harness import called
from tests.kernel.test_session import SCRIPTS
from tests.support.sessions import act, only_bundle, patient_task, run

from proxyloop.contract.events import Event
from proxyloop.contract.state import CaseStatus
from proxyloop.evidence.check import check_path
from proxyloop.kernel.channels import Channel, Incoming
from proxyloop.kernel.session import ChannelSpec

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
    """No event of its own to cause a move (I2): main's behaviour stays. The
    call opens at once (a task that needs nothing public, ADR-0012), so the
    rep's lines keep their times and the hang-up is at 20 s."""
    scripts, task = SCRIPTS | {"slow": [WAIT]}, called(patient_task())
    channels: dict[str, ChannelSpec] = {"user": "sim", "cp": Rep(())}
    result = run(tmp_path, scripts, channels=channels, task=task)
    assert result.reason == "abandoned"
    assert check_path(result.path, "offline").ok
    events = only_bundle(tmp_path).events
    moved = [e for e in events if e.type == "status.changed"]
    assert [e.payload["status"] for e in moved] == [CaseStatus.IN_CALL.value]
    assert not [e for e in events if e.type == "chan.closed"]
    # No extra Slow step after the hang-up, from the log: nothing wakes Slow
    # for it (it has no event: no call_closed, no strike), and the session
    # ends when it is taken in. A step the SimUser's reply woke just before
    # it is not one (a wall-clock bound raced that reply under load).
    steps = [e for e in events if e.type == "slow.step.started"]
    woken = [set(cast(list[str], e.payload["wake_reasons"])) for e in steps]
    assert not [w for w in woken if w & {"call_closed", "strike"}]
    ended = events[-1]
    assert ended.type == "session.ended" and ended.t_ms < 20_000 + 5_000


def test_a_user_quit_stops_without_abandoning(tmp_path: Path) -> None:
    scripts = SCRIPTS | {"slow": [WAIT]}
    result = run(tmp_path, scripts, channels={"user": Quitter(), "cp": "sim"})
    assert result.reason == "stopped"
    assert not _abandoned(only_bundle(tmp_path).events)
