"""S1-SYS-58 follow-up: since #242 (S1-SYS-67) a turn voices only the GUIDE
its view rendered, so a cp GUIDE superseded before any turn voiced it has no
``s2f.voiced``. ``guide_to_heard_ms`` counts it ``superseded`` by the rule of
``slow.heard.fates`` (``Fate.superseded``), duplicated in obs because obs may
not import ``proxyloop.slow``; the parity test pins the two together."""

from __future__ import annotations

from itertools import product
from pathlib import Path

import pytest
from tests.obs.bundles import Log, manifest, write
from tests.obs.triage_bundle import heard, s2f, sentence, turn

from proxyloop.obs import detectors, guides, runs, triage
from proxyloop.slow import heard as slow_heard

_GUIDE: dict[str, object] = {"guide": {"move": "identify", "slots": []}}


def _request(log: Log, gen: str, cause: str, lane: str = "cp") -> str:
    request: dict[str, object] = {"lane": lane, "gen_id": gen, "trigger": "guidance"}
    request |= {"view_sha": "v", "prompt_sha": "p", "profile": f"pl_{lane}_v3"}
    request |= {"model_ref": {}, "basis_seq": 0}
    return log.add("fast.request", f"fast.{lane}", "agent", request, (cause,))


def _voiced(log: Log, msg: str, gen: str, cause: str) -> str:
    voiced: dict[str, object] = {"msg_id": msg, "gen_id": gen}
    return log.add("s2f.voiced", "fast.cp", "agent", voiced, (cause,))


def _value(tmp_path: Path, log: Log, window_s: float = 0.05) -> object:
    log.add("session.ended", "kernel", "ops", {"reason": "done"})
    run = write(tmp_path / log.run_id, log, manifest(log.run_id))
    x = triage.read(run, runs.Seal(), window_s)[1]
    return detectors.DETECTORS["guide_to_heard_ms"](x)


def test_a_guide_replaced_before_any_turn_voiced_it_is_superseded(
    tmp_path: Path,
) -> None:
    """#242's shape: g1 is never voiced; g2 comes later and the turn that
    renders it voices and speaks it. g1 is ``superseded``, not unheard."""
    log = Log("rG")
    s2f(log, "g1", "cp", "GUIDE", log.start, **_GUIDE)  # 1 (t=100)
    b = s2f(log, "g2", "cp", "GUIDE", log.start, **_GUIDE)  # 2 (t=200)
    t4 = turn(log, "cp", "cp-g1", "c-1", _request(log, "cp-g1", b))  # 3-4
    _voiced(log, "g2", "cp-g1", t4)  # 5
    s6 = sentence(log, "cp", "cp-g1", 0, "Sure.", t4)  # 6
    heard(log, "cp", "cp-g1-u0", "Sure.", False, s6)  # 7 (t=700)
    # g2: 700 - 200; g1: superseded, though the log runs past its window
    assert _value(tmp_path, log) == {
        "count": 1, "p50": 500, "p90": 500, "unheard": 0, "unknown": 0,
        "cancelled": 0, "superseded": 1, "ms": [500],
    }  # fmt: skip


@pytest.mark.parametrize(("window_s", "bucket"), [(0.05, "unheard"), (3.0, "unknown")])
def test_a_last_unvoiced_guide_stays_unheard_or_unknown(
    tmp_path: Path, window_s: float, bucket: str
) -> None:
    """No later cp GUIDE: nothing superseded it; unheard once the log runs
    past the relay window, unknown when the log ends inside it."""
    log = Log("rL")
    s2f(log, "g1", "cp", "GUIDE", log.start, **_GUIDE)  # 1 (t=100)
    s2f(log, "e1", "cp", "END", log.start)  # 2: a later cp s2f.msg, no GUIDE
    value = _value(tmp_path, log, window_s)  # the log ends at 3 (t=300)
    assert isinstance(value, dict)
    # e1 is no GUIDE, so it supersedes nothing: g1 is unheard past a 0.05 s
    # window, unknown inside a 3 s one
    assert (value["superseded"], value[bucket]) == (0, 1)


@pytest.mark.parametrize(
    ("between", "superseded"), [("open", 0), ("turn", 1), ("cancelled", 1)]
)
def test_an_open_generation_between_the_guides_keeps_it_unsuperseded(
    tmp_path: Path, between: str, superseded: int
) -> None:
    """A cp generation requested between g1 and g2 may have rendered g1 and
    could still voice it: only once that generation ended (a fast.turn or a
    fast.cancelled) is g1 superseded."""
    log = Log("rO")
    a = s2f(log, "g1", "cp", "GUIDE", log.start, **_GUIDE)  # 1
    r = _request(log, "cp-g1", a)  # 2: renders g1
    if between == "turn":
        turn(log, "cp", "cp-g1", "c-1", r)  # 3: ended, voiced nothing
    elif between == "cancelled":
        cancel: dict[str, object] = {"gen_id": "cp-g1", "reason": "barge_in"}
        log.add("fast.cancelled", "fast.cp", "agent", cancel, (r,))  # 3
    s2f(log, "g2", "cp", "GUIDE", log.start, **_GUIDE)  # g2, never voiced
    value = _value(tmp_path, log)
    assert isinstance(value, dict)
    # g2 is the last GUIDE: unheard; g1 unheard too unless superseded
    assert (value["superseded"], value["unheard"]) == (superseded, 2 - superseded)


# The parity alphabet: a cp GUIDE (G), a cp END s2f.msg (E), a cp request
# left open (O), one whose turn ends without voicing (T) or voices the newest
# cp GUIDE (V), one cancelled (C), a user-lane request left open (R).
_STEPS = "GEOTVCR"


def _build(pattern: tuple[str, ...]) -> Log:
    log = Log("rP")
    newest: str | None = None
    for i, step in enumerate(pattern):
        gen = f"g{i}"
        if step == "G":
            newest = f"m{i}"
            s2f(log, newest, "cp", "GUIDE", log.start, **_GUIDE)
            continue
        if step == "E":
            s2f(log, f"m{i}", "cp", "END", log.start)
            continue
        r = _request(log, gen, log.start, "user" if step == "R" else "cp")
        if step in "TV":
            t = turn(log, "cp", gen, f"c-{gen}", r)
            if step == "V" and newest is not None:
                _voiced(log, newest, gen, t)
        elif step == "C":
            cancel: dict[str, object] = {"gen_id": gen, "reason": "barge_in"}
            log.add("fast.cancelled", "fast.cp", "agent", cancel, (r,))
    return log


def test_the_superseded_set_equals_slow_heard_fates() -> None:
    """Every log of four steps over ``_STEPS``: obs's set is exactly the msg
    ids ``slow.heard.fates`` marks ``superseded``."""
    hits = 0
    for pattern in product(_STEPS, repeat=4):
        events = _build(pattern).events
        want = {m for m, f in slow_heard.fates(events, []).items() if f.superseded}
        assert guides.superseded(events) == want, pattern
        hits += bool(want)
    assert hits > 100  # the alphabet reaches the rule, not only the empty set
