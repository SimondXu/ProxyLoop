"""cp GUIDEs superseded before any turn voiced them (S1-SYS-67, #242).

A copy of the rule in ``slow.heard.fates`` (``Fate.superseded``): obs reads
bundles only and may not import ``proxyloop.slow`` (.importlinter), so the
rule lives here twice; tests/obs/test_guide_superseded.py pins the two sets
equal. Change both or neither."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from proxyloop.contract.events import Event


def superseded(events: Sequence[Event]) -> set[str]:
    """The msg ids of cp GUIDEs (an s2f.msg on lane cp with a ``guide``) that
    no s2f.voiced cites, that a later cp GUIDE followed, and between which
    and that next GUIDE no cp fast.request's generation is still open (not
    ended by a fast.turn or a fast.cancelled): a turn voices only the GUIDE
    its view rendered, so such a GUIDE can never be voiced."""
    voiced = {str(e.payload["msg_id"]) for e in events if e.type == "s2f.voiced"}
    ended = {
        str(e.payload["gen_id"])
        for e in events
        if e.type in ("fast.cancelled", "fast.turn")
    }
    asked = [
        (e.seq, str(e.payload["gen_id"]))
        for e in events
        if e.type == "fast.request" and e.payload["lane"] == "cp"
    ]
    guides = [
        e
        for e in events
        if e.type == "s2f.msg" and e.payload["lane"] == "cp" and e.payload.get("guide")
    ]
    out: set[str] = set()
    for old, new in pairwise(guides):
        msg = str(old.payload["msg_id"])
        rendered = any(old.seq < q < new.seq and g not in ended for q, g in asked)
        if msg not in voiced and not rendered:
            out.add(msg)
    return out
