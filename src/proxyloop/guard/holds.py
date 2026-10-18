"""When a standing cp hold ends without a FastC turn (ADR-0034). FastC's
``chan.hold`` sets and clears ``cp_hold`` (kernel/lanes.py); its answer ends it
too, so no view shows a hold the case no longer waits on:
- ``decided``: an ``offer``, ``decision`` or ``pressure`` hold, once a Guard
  accept or decline line is heard whole (its ``utt.delivered``, not cut);
- ``answered``: a ``fact_request`` hold, at a public fact from the user's
  message (``source: shareable``) that leaves no readiness key missing and no
  keyed need pending or replied (``guard.needs``).
A rep's fact, a private fact or a cut line ends nothing, and ``unclear`` waits
for FastC. Pure; the kernel folds it from every event (``kernel/calls.py``)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from proxyloop.contract.events import Event
from proxyloop.contract.state import HoldState
from proxyloop.guard.needs import Ledger

Ended = Literal["decided", "answered"]
DECIDED = frozenset({"offer", "decision", "pressure"})


def lines(said: frozenset[str], e: Event) -> frozenset[str]:
    """The ids of Guard's accept and decline lines and of their releases."""
    if e.type == "speak.verbatim" and e.payload["kind"] in ("accept", "decline"):
        return said | {e.event_id}
    if e.type == "speak.released" and e.cause_ids[0] in said:
        return said | {e.event_id}
    return said


def ended(
    hold: HoldState | None,
    e: Event,
    said: frozenset[str],
    ledger: Ledger,
    missing: Sequence[str],
) -> Ended | None:
    """Why ``e`` ends ``hold``, if it does (``ledger`` already has ``e``)."""
    p = e.payload
    if hold is None:
        return None
    if e.type == "utt.delivered" and hold.reason in DECIDED:
        heard = e.cause_ids[0] in said and not p["interrupted"]
        return "decided" if heard else None
    if e.type != "fact.recorded" or hold.reason != "fact_request":
        return None
    if (p["scope"], p["source"]) != ("public", "shareable") or missing:
        return None
    waiting = [n for n in ledger.needs.values() if n.state != "answered"]
    return None if waiting else "answered"
