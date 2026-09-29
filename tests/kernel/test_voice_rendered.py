"""S1-SYS-67 on the real kernel (``run_session``): Slow sends ask_discount and
ask_final_offer in one step, so both are pending when FastC's turn starts. The
turn's view renders only the newest GUIDE (``guidance_cp``), so every
``s2f.voiced`` of a cp GUIDE names a GUIDE its turn's stored view carried; the
superseded ask is never voiced and ``slow.heard`` calls it dead (S1-SYS-94: a
slot-free move, as mention_tenure now needs its fact)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from tests.kernel.test_session import SCRIPTS, UNTIL
from tests.support.sessions import act, only_bundle, run

from proxyloop.contract.bundle import Bundle
from proxyloop.contract.events import Event
from proxyloop.core.fold import fold
from proxyloop.slow import heard

TWO = act(
    "Steer.",
    {"tool": "guide_fast", "move": "ask_discount"},
    {"tool": "guide_fast", "move": "ask_final_offer"},
)
WAIT = act("Waiting.", {"tool": "wait", "seconds": 5})


def _of(events: tuple[Event, ...], type_: str) -> list[Event]:
    return [e for e in events if e.type == type_]


def _rendered(b: Bundle, turn_id: str) -> list[str]:
    """The GUIDE moves in the stored view of the turn ``turn_id``'s request."""
    by_id = {e.event_id: e for e in b.events}
    request = by_id[by_id[turn_id].cause_ids[0]]
    assert request.type == "fast.request"
    view = json.loads(b.prompts[str(request.payload["view_sha"])].content)
    return [str(g["move"]) for g in view["guidance"]]


def test_a_turn_voices_only_the_guide_its_view_rendered(tmp_path: Path) -> None:
    run(tmp_path, SCRIPTS | {"slow": [TWO, WAIT]}, until=UNTIL)
    b = only_bundle(tmp_path)
    guides = {
        str(e.payload["msg_id"]): str(
            cast(dict[str, object], e.payload["guide"])["move"]
        )
        for e in _of(b.events, "s2f.msg")
        if e.payload.get("guide")
    }
    first, final = guides  # sent in this order, in one step
    assert (guides[first], guides[final]) == ("ask_discount", "ask_final_offer")
    voiced = [e for e in _of(b.events, "s2f.voiced") if e.payload["msg_id"] in guides]
    assert voiced, "the final ask is voiced"
    for v in voiced:
        assert guides[str(v.payload["msg_id"])] in _rendered(b, v.cause_ids[0])
    assert not [v for v in voiced if v.payload["msg_id"] == first]
    lines = fold(b.events).channels["cp"].lines
    dead = heard.Fate("dead", None, superseded=True)
    assert heard.fates(b.events, lines)[first] == dead
