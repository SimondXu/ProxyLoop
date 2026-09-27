"""S1-SYS-55: a rep hang-up moves the case to ABANDONED (Guard's ``hang_up``,
§9.5) before the session ends; a user's quit does not."""

from __future__ import annotations

from pathlib import Path

from tests.kernel.test_session import SCRIPTS
from tests.support.sessions import act, only_bundle, run

from proxyloop.contract.events import Event
from proxyloop.contract.state import CaseStatus
from proxyloop.evidence.check import check_path
from proxyloop.kernel.channels import Channel, Incoming

WAIT = act("Waiting.", {"tool": "wait", "seconds": 15})


class Rep(Channel):
    """Says one line, then hangs up with a last line."""

    def __init__(self) -> None:
        super().__init__()
        self.incoming.put_nowait(Incoming((("Hello?", None),), due_ms=100))
        bye = Incoming((("Goodbye.", None),), due_ms=20_000, end="hangup")
        self.incoming.put_nowait(bye)


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
    result = run(tmp_path, scripts, channels={"user": "sim", "cp": Rep()})
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


def test_a_user_quit_stops_without_abandoning(tmp_path: Path) -> None:
    scripts = SCRIPTS | {"slow": [WAIT]}
    result = run(tmp_path, scripts, channels={"user": Quitter(), "cp": "sim"})
    assert result.reason == "stopped"
    assert not _abandoned(only_bundle(tmp_path).events)
