"""What became of each voiced s2f message (#219 D1, D-A): heard by the rep,
still playing, or dead. Only cp deliveries count, so a user-lane message is
never heard here. A pure read of the event log; ``SlowTools`` delegates to it."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, NamedTuple

from proxyloop.contract.events import Event
from proxyloop.contract.state import Line
from proxyloop.guard.needs import spoke

State = Literal["heard", "playing", "dead"]
_RANK: dict[State, int] = {"dead": 0, "playing": 1, "heard": 2}


class Fate(NamedTuple):
    state: State
    at: int | None  # heard: the first cp line after its delivery; else None


def fates(events: Sequence[Event], lines: Sequence[Line]) -> dict[str, Fate]:
    """Each voiced s2f msg id, by the ``s2f.voiced`` events citing it: heard
    iff one cites a ``fast.turn`` that spoke, was never cancelled, and whose
    every sentence was delivered uninterrupted (the first such one anchors,
    at the first cp line after its delivery); else playing iff one's turn
    spoke, was not cancelled, and has no sentence cut but not every sentence
    delivered yet; else dead (cancelled, cut, or no speech). Deliberately
    stricter than the needs ledger's ``heard`` (a spoken turn):
    ``s2f.voiced`` comes before the playout. ``lines``: the cp transcript."""
    turns = {e.event_id: e for e in events if e.type == "fast.turn"}
    cut = {e.payload["gen_id"] for e in events if e.type == "fast.cancelled"}
    sentences: dict[str, list[str]] = {}  # gen id -> its utt ids
    for p in (e.payload for e in events if e.type == "fast.sentence"):
        sentences.setdefault(str(p["gen_id"]), []).append(str(p["utt_id"]))
    cp = [
        e
        for e in events
        if e.type in ("utt.final", "utt.delivered") and e.payload["lane"] == "cp"
    ]
    delivered = {str(e.payload["utt_id"]): e for e in cp if e.type == "utt.delivered"}
    said = {str(e.payload["utt_id"]): e.seq for e in cp}  # a line -> its seq
    seqs = [said[x.utt_id] for x in lines]
    out: dict[str, Fate] = {}
    for e in events:
        if e.type != "s2f.voiced":
            continue
        turn = turns.get(e.cause_ids[0])
        fate = Fate("dead", None)  # cancelled, cut, or no speech
        if turn is not None and spoke(turn) and turn.payload["gen_id"] not in cut:
            gen = str(turn.payload["gen_id"])
            played = [delivered.get(u) for u in sentences.get(gen, ())]
            done = [d for d in played if d is not None]
            if not any(d.payload["interrupted"] for d in done):  # none cut
                if played and len(done) == len(played):
                    end = max(d.seq for d in done)
                    fate = Fate("heard", sum(q <= end for q in seqs))
                else:
                    fate = Fate("playing", None)  # not heard yet
        msg = str(e.payload["msg_id"])
        if msg not in out or _RANK[fate.state] > _RANK[out[msg].state]:
            out[msg] = fate
    return out


def heard_at(events: Sequence[Event], lines: Sequence[Line]) -> dict[str, int]:
    """The s2f msg ids the rep heard, each with the first cp line after its
    delivery (``fates``' heard ones)."""
    return {m: f.at for m, f in fates(events, lines).items() if f.at is not None}
