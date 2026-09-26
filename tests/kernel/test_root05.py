"""Kernel fixes from the failed S0-ROOT-05 live smokes (S0-SYS-07): TTFS (l),
HOLD relay dedupe (e) and stale rep replies (i)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

from tests.kernel.test_review import Rep
from tests.kernel.test_session import FINISH, SCRIPTS, UNTIL
from tests.support.sessions import act, only_bundle, run

from proxyloop.contract.events import Event
from proxyloop.kernel.channels import Channel, End, Incoming
from proxyloop.kernel.session import Turn


def _of(events: tuple[Event, ...], type_: str, lane: str = "cp") -> list[Event]:
    return [e for e in events if e.type == type_ and e.payload.get("lane") == lane]


def test_ttfs_is_set_when_the_only_sentence_is_released_at_close(
    tmp_path: Path,
) -> None:  # (l): a one-sentence reply closes only at parser.close()
    last = "@slow: fact monthly_price=75.00\nCould you lower the monthly price?"
    run(tmp_path, SCRIPTS | {"fast_cp": [last]}, until=UNTIL)
    turns = _of(only_bundle(tmp_path).events, "fast.turn")
    assert turns
    for turn in turns:
        items = cast(list[dict[str, object]], turn.payload["items"])
        assert [i["kind"] for i in items] == ["relay", "speech"]
        assert turn.payload["ttfs_ms"] is not None, turn.payload


def test_an_unchanged_hold_is_relayed_once(tmp_path: Path) -> None:  # (e)
    waits = [act("Waiting.", {"tool": "wait", "seconds": 15})] * 4
    scripts = SCRIPTS | {
        "fast_cp": ["Let me check that with the account holder.\n@hold decision"],
        "slow": [*waits, FINISH],
    }
    run(tmp_path, scripts)
    events = only_bundle(tmp_path).events
    held = [
        t
        for t in _of(events, "fast.turn")
        if any(
            i["kind"] == "hold"
            for i in cast(list[dict[str, object]], t.payload["items"])
        )
    ]
    assert len(held) >= 3  # not vacuous: FastC held on every turn
    relays = [e for e in _of(events, "f2s.msg") if e.payload["type"] == "HOLD"]
    assert [e.payload["text"] for e in relays] == ["decision"]
    counts = cast(dict[str, int], events[-1].payload["counts"])
    assert counts["hold_repeat"] == len(held) - 1


LONG = " ".join(["Could you tell me whether a lower monthly price is possible"] * 3)
GUIDED = SCRIPTS | {
    "fast_cp": [LONG],  # about 11 s of speech
    "slow": [
        act("Steer.", {"tool": "guide_fast", "move": "ask_discount"}),
        act("Waiting.", {"tool": "wait", "seconds": 15}),
    ],
}


class Thinker(Channel):
    """A rep who answers each line it heard 1 s later, busy from the spawn (as
    ``SimRepChannel``), and hangs up after ``turns`` answers."""

    def __init__(self, turns: int) -> None:
        super().__init__()
        self.thinking, self.turns = 0, turns

    @property
    def busy(self) -> bool:
        return self.thinking > 0

    def send(self, text: str | None, utt_id: str, cause: str, t_ms: int) -> Turn:
        self.thinking += 1

        async def answer() -> None:
            await asyncio.sleep(0.01)  # 1 s at the sessions' 100x clock
            self.thinking -= 1
            self.turns -= 1
            end: End = "hangup" if self.turns <= 0 else ""
            self.incoming.put_nowait(
                Incoming((("Sorry, say that again?", None),), end=end)
            )

        return answer()


def test_a_stale_rep_reply_waits_for_the_floor(tmp_path: Path) -> None:  # (i)
    run(tmp_path, GUIDED, channels={"user": "sim", "cp": Thinker(turns=3)})
    events = only_bundle(tmp_path).events
    fast = [
        e for e in _of(events, "utt.delivered") if e.payload["utt_id"] != "disclosure"
    ]
    assert len(fast) >= 2  # FastC spoke while the rep was still answering a line
    assert not _of(events, "chan.barge_in")
    assert not [e for e in fast if e.payload["interrupted"]]
    for said in fast:  # every rep line lands after the agent's line it overlapped
        start = said.t_ms - 1000 * len(LONG.split()) / 2.8
        during = [
            e
            for e in _of(events, "utt.final")
            if e.payload["speaker"] == "partner" and start < e.t_ms < said.t_ms - 100
        ]
        assert not during, (said.t_ms, [e.t_ms for e in during])


def test_a_current_rep_line_still_barges_in(tmp_path: Path) -> None:  # (i)
    rep = Rep([(9_000, "Hold on, let me stop you there.")], hangup_ms=40_000)
    run(tmp_path, GUIDED, channels={"user": "sim", "cp": rep})
    events = only_bundle(tmp_path).events
    (cut,) = _of(events, "chan.barge_in")
    (heard,) = [e for e in _of(events, "utt.delivered") if e.payload["interrupted"]]
    assert heard.payload["text_heard"] != LONG and cut.seq > heard.seq
