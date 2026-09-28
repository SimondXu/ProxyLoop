"""S1-SYS-67: ``slow.heard.fates`` marks a cp GUIDE dead and ``superseded`` only
when a later cp GUIDE replaced it before any turn voiced it; a voicing that
died (no speech, cut) is dead but not superseded, even once replaced, so a
count of a lever's failures to reach the rep can tell them apart."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.slow.test_authority import Host

from proxyloop.slow import heard

DISCOUNT = {"tool": "guide_fast", "move": "ask_discount"}
FINAL = {"tool": "guide_fast", "move": "ask_final_offer"}


def _sent(h: Host, *calls: dict[str, Any]) -> list[str]:
    out = h.act(*calls)
    assert all("sent" in line for line in out), out
    return [str(e.payload["msg_id"]) for e in h.of("s2f.msg")][-len(calls) :]


def test_only_a_guide_replaced_unvoiced_is_superseded(tmp_path: Path) -> None:
    h = Host(tmp_path)
    h.call()
    (mute,) = _sent(h, DISCOUNT)
    h.voice(spoke=False)  # voiced by a turn with no speech: dead
    (cut,) = _sent(h, FINAL)
    h.deliver(h.voice(deliver=False), interrupted=True)  # voiced, then cut: dead
    old, new = _sent(h, FINAL, DISCOUNT)
    h.voice()  # the newest only, heard
    fates = heard.fates(h.bus.events, h.bb.channels["cp"].lines)
    assert fates[mute] == heard.Fate("dead", None)  # replaced since, not superseded
    assert fates[cut] == heard.Fate("dead", None)
    assert fates[old] == heard.Fate("dead", None, superseded=True)
    assert fates[new].state == "heard" and not fates[new].superseded
    lines = h.bb.channels["cp"].lines
    assert set(heard.heard_at(h.bus.events, lines)) == {new}
