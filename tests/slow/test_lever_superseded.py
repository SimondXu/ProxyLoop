"""S1-SYS-67 round 2 (rev-242 major, #238 N2): a lever counts toward "failed
to reach the rep twice" (``state.DIES``) only by a voicing that died
(cancelled, cut, no speech). A lever GUIDE Slow itself replaced before any
turn voiced it (``heard.Fate.superseded``) was never tried: it stays
available. And K2 leaves every voiced message's fate as it was: adding a
superseded, never-voiced GUIDE changes no voiced msg's fate or anchor."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests.slow import test_negotiate as neg
from tests.slow.test_authority import Host

from proxyloop.slow import heard

_outside = neg._outside  # pyright: ignore[reportPrivateUsage]
_levers = neg._levers  # pyright: ignore[reportPrivateUsage]
_cut = neg._cut  # pyright: ignore[reportPrivateUsage]
FAILED, TENURE = neg.FAILED, neg.TENURE
FINAL = {"tool": "guide_fast", "move": "ask_final_offer"}
DISCOUNT = {"tool": "guide_fast", "move": "ask_discount"}
AVAILABLE = "available: mention_tenure"


def _superseded(h: Host) -> None:
    """mention_tenure replaced by the final ask in one step: the turn voices
    the newest only (the rev-242 probe)."""
    h.act(TENURE, FINAL)
    h.voice()


def _died(h: Host) -> None:
    """mention_tenure voiced, then cut: a failure to reach the rep."""
    h.act(TENURE)
    _cut(h)


@pytest.mark.parametrize(
    ("first", "second", "failed"),
    [
        (_superseded, _superseded, False),  # never voiced: never tried
        (_died, _died, True),  # failed to reach the rep twice
        (_died, _superseded, False),  # one death only
        (_superseded, _died, False),
    ],
)
def test_only_a_voicing_that_died_counts_toward_failed_twice(
    tmp_path: Path,
    first: Callable[[Host], None],
    second: Callable[[Host], None],
    failed: bool,
) -> None:
    h = _outside(tmp_path)
    first(h)
    second(h)
    line = _levers(h)
    assert (FAILED in line) is failed, line
    assert (AVAILABLE in line) is not failed, line


def test_a_superseded_lever_is_not_waiting_either(tmp_path: Path) -> None:
    """The fold keeps a superseded GUIDE in ``s2f_pending`` (it drops a msg
    only on ``s2f.voiced``); its fate, not the queue, decides: available."""
    h = _outside(tmp_path)
    _superseded(h)
    (tenure,) = [m for m, move in h.tools.guides if move.value == "mention_tenure"]
    assert tenure in {m.msg_id for m in h.bb.s2f_pending["cp"]}
    line = _levers(h)
    assert AVAILABLE in line and "wait" not in line, line


# the nit: K2 leaves the voiced msgs' fates and anchors as they were


Step = Callable[[Host], Any]


def _heard(h: Host) -> None:
    h.voice()


def _playing(h: Host) -> None:
    h.voice(deliver=False)


def _silent(h: Host) -> None:
    h.voice(spoke=False)


def _answered(h: Host) -> None:
    h.voice()
    h.rep(f"cp-r{len(h.bb.channels['cp'].lines)}", "Let me see what I can do.")


CASES: dict[str, tuple[Step, ...]] = {
    "heard": (_heard,),
    "cut": (_cut,),
    "silent": (_silent,),
    "playing": (_playing,),
    "answered then heard": (_answered, _heard),
    "cut then answered": (_cut, _answered),
    "silent then playing": (_silent, _playing),
}


def _voiced(tmp_path: Path, steps: tuple[Step, ...], extra: bool) -> Host:
    """Each step voices one fresh GUIDE; with ``extra``, Slow first sends
    another GUIDE the fresh one supersedes before any turn."""
    tmp_path.mkdir()
    h = Host(tmp_path)
    h.call()
    h.rep("cp-0", "Hello, how can I help?")
    for step in steps:
        h.act(*([FINAL] if extra else []), DISCOUNT)
        step(h)
    return h


@pytest.mark.parametrize("case", list(CASES))
def test_a_superseded_guide_changes_no_voiced_msgs_fate_or_anchor(
    tmp_path: Path, case: str
) -> None:
    def read(h: Host) -> tuple[list[heard.Fate], list[int]]:
        lines = h.bb.channels["cp"].lines
        fates = heard.fates(h.bus.events, lines)
        voiced = list(
            dict.fromkeys(str(e.payload["msg_id"]) for e in h.of("s2f.voiced"))
        )
        return [fates[m] for m in voiced], list(
            heard.heard_at(h.bus.events, lines).values()
        )

    steps = CASES[case]
    plain = _voiced(tmp_path / "plain", steps, extra=False)
    mixed = _voiced(tmp_path / "mixed", steps, extra=True)
    assert read(mixed) == read(plain)
    superseded = [
        f
        for f in heard.fates(mixed.bus.events, mixed.bb.channels["cp"].lines).values()
        if f.superseded
    ]
    assert len(superseded) == len(steps)  # each extra GUIDE: dead, superseded
