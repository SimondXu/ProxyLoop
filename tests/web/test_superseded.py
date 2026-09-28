"""S1-SYS-69 drift guard: the web timeline (apps/web/src/timeline.ts) marks a cp
GUIDE "Replaced by a newer instruction before it was spoken" exactly when
``proxyloop.slow.heard.fates`` gives it ``superseded``. The TS re-implements the
rule, so both runners read one committed fixture, ``superseded/events.jsonl``,
and one golden, ``superseded/golden.json`` (the superseded msg ids):
- here, ``heard.fates`` over the fixture must give exactly the golden;
- ``apps/web/src/superseded.test.ts``: the timeline marks exactly the golden.

The fixture is synthetic (I11): hand-built ``Event`` models (every line
validates), one per branch of the rule, no session behind it. It lives outside
``tests/web/fixtures`` (the replay fixture's directory, which must hold one
run). Both files are checked, never silently rewritten: after a deliberate
change to ``_build`` or to ``heard.fates``, regenerate them with
``PL_UPDATE_SNAPSHOTS=1 uv run pytest tests/web/test_superseded.py`` and review
the diff.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proxyloop.contract.events import Event
from proxyloop.contract.state import Line
from proxyloop.slow import heard

DIR = Path(__file__).parent / "superseded"
EVENTS = DIR / "events.jsonl"
GOLDEN = DIR / "golden.json"
RUN = "superseded-fixture"
START = datetime(2026, 9, 26, tzinfo=UTC)
SHA = "0" * 64
MODEL = {
    "kind": "test_fake",
    "endpoint": None,
    "model_id": "fast_cp-fake",
    "reasoning_effort": None,
}


class _Log:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(
        self, type_: str, actor: str, payload: Mapping[str, object], *causes: Event
    ) -> Event:
        seq = len(self.events)
        e = Event(
            run_id=RUN,
            seq=seq,
            event_id=f"{RUN}:{seq}",
            t_ms=seq * 100,
            wall=START + timedelta(milliseconds=seq * 100),
            type=type_,
            actor=actor,
            stream="agent",
            cause_ids=tuple(c.event_id for c in causes),
            epoch=0,
            payload=dict(payload),
        )
        self.events.append(e)
        return e

    def s2f(
        self, cause: Event, msg: str, lane: str, type_: str, move: str | None = None
    ) -> Event:
        slots: list[str] = []
        guide = None if move is None else {"move": move, "slots": slots}
        text = "An update for you." if lane == "user" else ""
        payload = {
            "msg_id": msg,
            "lane": lane,
            "type": type_,
            "text": text,
            "guide": guide,
            "approval_id": None,
        }
        return self.emit("s2f.msg", "guard", payload, cause)

    def request(self, lane: str, gen: str) -> Event:
        payload = {
            "lane": lane,
            "gen_id": gen,
            "trigger": "slow_msg",
            "view_sha": SHA,
            "prompt_sha": SHA,
            "profile": "pl_cp_v2" if lane == "cp" else "pl_user_v1",
            "basis_seq": len(self.events) - 1,
            "model_ref": MODEL,
        }
        return self.emit("fast.request", f"fast.{lane}", payload)

    def turn(self, req: Event, msg: str, speech: bool) -> Event:
        """The cp turn of ``req``: it voices ``msg`` (with or without speech)."""
        gen = str(req.payload["gen_id"])
        items = [{"kind": "speech", "text": "unheard"}] if speech else []
        payload = {
            "lane": "cp",
            "gen_id": gen,
            "call_id": f"fast_cp:{gen}",
            "items": items,
            "ttft_ms": 1,
            "ttfs_ms": 1,
        }
        turn = self.emit("fast.turn", "fast.cp", payload, req)
        self.emit("s2f.voiced", "fast.cp", {"msg_id": msg, "gen_id": gen}, turn)
        return turn

    def say(self, turn: Event, heard_text: str, interrupted: bool) -> Event:
        gen = str(turn.payload["gen_id"])
        utt = f"{gen}-u0"
        s = self.emit(
            "fast.sentence",
            "fast.cp",
            {"lane": "cp", "gen_id": gen, "utt_id": utt, "text": "unheard"},
            turn,
        )
        payload = {
            "lane": "cp",
            "utt_id": utt,
            "text_generated": "g",
            "text_heard": heard_text,
            "interrupted": interrupted,
        }
        return self.emit("utt.delivered", "kernel", payload, s)


def _build() -> list[Event]:
    """One cp GUIDE per branch, in lane order (each pair is (it, the next)):
    - g1 superseded: the only cp request before g2 was cancelled (not open);
    - g2 heard; g3 voiced by a turn with no speech (dead); g4 voiced, then its
      turn cancelled (verbatim) before any sentence (dead: the older cancelled
      GUIDE keeps "Passed to the voice"); g5 voiced, cut before any word
      (dead): voiced, so none of them is superseded, though each is replaced;
    - g6 not superseded: a cp request before g7 is still open;
    - g7 superseded by g8, across two user-lane messages (never superseded)
      and an open user-lane request (only cp requests count);
    - g8 the newest: nothing replaced it."""
    log = _Log()
    step = log.emit("slow.step.started", "slow", {"basis_seq": 0, "wake_reasons": []})
    log.s2f(step, "s2f-g1", "cp", "GUIDE", "open_call")
    stale = log.request("cp", "cp-g1")
    log.emit("fast.cancelled", "fast.cp", {"gen_id": "cp-g1", "reason": "epoch"}, stale)
    log.s2f(step, "s2f-g2", "cp", "GUIDE", "identify")
    log.say(
        log.turn(log.request("cp", "cp-g2"), "s2f-g2", speech=True),
        "It is Dana.",
        interrupted=False,
    )
    log.s2f(step, "s2f-g3", "cp", "GUIDE", "ask_discount")
    log.turn(log.request("cp", "cp-g3"), "s2f-g3", speech=False)
    log.s2f(step, "s2f-g4", "cp", "GUIDE", "mention_tenure")
    t4 = log.turn(log.request("cp", "cp-g4"), "s2f-g4", speech=True)
    log.emit("fast.cancelled", "fast.cp", {"gen_id": "cp-g4", "reason": "verbatim"}, t4)
    log.s2f(step, "s2f-g5", "cp", "GUIDE", "cite_competitor")
    log.say(
        log.turn(log.request("cp", "cp-g5"), "s2f-g5", speech=True),
        "",
        interrupted=True,
    )
    log.s2f(step, "s2f-g6", "cp", "GUIDE", "ask_final_offer")
    log.request("cp", "cp-g6")  # never ends
    log.s2f(step, "s2f-g7", "cp", "GUIDE", "ask_readback")
    log.s2f(step, "s2f-u1", "user", "TELL_USER")
    log.s2f(step, "s2f-u2", "user", "ASK_USER")
    log.request("user", "user-g1")  # never ends
    log.s2f(step, "s2f-g8", "cp", "GUIDE", "close_call")
    return log.events


def _lines(events: list[Event]) -> list[Line]:
    """The cp transcript: the agent's delivered lines."""
    return [
        Line(
            utt_id=str(e.payload["utt_id"]),
            speaker="agent",
            text=str(e.payload["text_heard"]),
        )
        for e in events
        if e.type == "utt.delivered" and e.payload["lane"] == "cp"
    ]


def _superseded(events: list[Event]) -> list[str]:
    return sorted(
        m for m, f in heard.fates(events, _lines(events)).items() if f.superseded
    )


def test_the_fixture_is_the_builders_output() -> None:
    lines = [e.model_dump_json() for e in _build()]
    if os.environ.get("PL_UPDATE_SNAPSHOTS"):
        DIR.mkdir(exist_ok=True)
        EVENTS.write_text("\n".join(lines) + "\n", "utf-8")
    assert EVENTS.read_text("utf-8").splitlines() == lines


def test_heard_fates_supersedes_exactly_the_golden() -> None:
    events = [
        Event.model_validate_json(x) for x in EVENTS.read_text("utf-8").splitlines()
    ]
    got = _superseded(events)
    if os.environ.get("PL_UPDATE_SNAPSHOTS"):
        GOLDEN.write_text(json.dumps(got, indent=1) + "\n", "utf-8")
    assert json.loads(GOLDEN.read_text("utf-8")) == got


def test_the_fixture_reaches_every_branch() -> None:
    """What each GUIDE's fate is, so a builder edit cannot drop a branch unseen."""
    events = _build()
    fates = heard.fates(events, _lines(events))
    dead = heard.Fate("dead", None)
    assert fates == {
        "s2f-g1": heard.Fate("dead", None, superseded=True),
        "s2f-g2": heard.Fate("heard", 1),
        "s2f-g3": dead,
        "s2f-g4": dead,
        "s2f-g5": dead,
        "s2f-g7": heard.Fate("dead", None, superseded=True),
    }
