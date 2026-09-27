"""Kernel fixes from the failed S0-ROOT-05 live smokes (S0-SYS-07): TTFS (l),
HOLD relay dedupe (e) and stale rep replies (i)."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from tests.kernel.test_session import FINISH, SCRIPTS, UNTIL
from tests.support.sessions import act, fake, fake_config, only_bundle, run

from proxyloop.contract.config import SessionConfig
from proxyloop.contract.events import Event
from proxyloop.kernel import session
from proxyloop.kernel.channels import Channel, End, Incoming
from proxyloop.llm.spend import SESSION_CAP_MICRO_USD, Rate, RunawaySpend, SpendLedger


def _of(events: tuple[Event, ...], type_: str, lane: str = "cp") -> list[Event]:
    return [e for e in events if e.type == type_ and e.payload.get("lane") == lane]


def test_ttfs_is_set_when_the_only_sentence_is_released_at_close(
    tmp_path: Path,
) -> None:  # (l): a one-sentence reply closes only at parser.close()
    last = "@slow: fact monthly_price=75.00\nCould you lower the monthly price?"
    run(tmp_path, SCRIPTS | {"fast_cp": [last]}, until=UNTIL)
    events = only_bundle(tmp_path).events
    asked = {e.payload["gen_id"]: e.t_ms for e in _of(events, "fast.request")}
    turns = _of(events, "fast.turn")
    assert turns
    for turn in turns:
        items = cast(list[dict[str, object]], turn.payload["items"])
        assert [i["kind"] for i in items] == ["relay", "speech"]
        ttfs = turn.payload["ttfs_ms"]
        assert isinstance(ttfs, int), turn.payload
        streamed = turn.t_ms - asked[turn.payload["gen_id"]]  # request to turn
        assert 0 <= ttfs <= streamed, (ttfs, streamed)


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


class Rep(Channel):
    """A rep whose line lands 2 s into the agent's next speech. A ``thinking``
    rep has an unanswered line (``busy``, as a ``SimRepChannel`` turn in flight):
    its reply is stale. It hangs up after ``turns`` lines."""

    def __init__(self, turns: int, thinking: bool) -> None:
        super().__init__()
        self.turns, self.thinking, self.unanswered = turns, thinking, 0

    @property
    def busy(self) -> bool:
        return self.thinking and self.unanswered > 0

    async def send(self, text: str | None, utt_id: str, cause: str, t_ms: int) -> None:
        self.unanswered += bool(text)

    def floor(self, free: bool, t_ms: int) -> None:
        if free or self.turns <= 0 or not self.unanswered:  # the next speech
            return
        self.turns, self.unanswered = self.turns - 1, 0
        end: End = "hangup" if self.turns <= 0 else ""
        line = (("Sorry, say that again?", None),)
        self.incoming.put_nowait(Incoming(line, due_ms=t_ms + 2_000, end=end))


def _overlaps(events: tuple[Event, ...]) -> tuple[list[Event], list[Event]]:
    """FastC's lines, and the rep lines that landed while one was spoken."""
    fast = [
        e for e in _of(events, "utt.delivered") if e.payload["utt_id"] != "disclosure"
    ]
    rep = [e for e in _of(events, "utt.final") if e.payload["speaker"] == "partner"]
    starts = {  # when each of FastC's lines took the floor
        e.payload["utt_id"]: e.t_ms for e in _of(events, "fast.sentence")
    }
    during = [
        r for r in rep for f in fast if starts[f.payload["utt_id"]] < r.t_ms < f.t_ms
    ]
    return fast, during


def test_a_stale_rep_reply_waits_for_the_floor(tmp_path: Path) -> None:  # (i)
    rep = Rep(turns=3, thinking=True)
    run(tmp_path, GUIDED, channels={"user": "sim", "cp": rep})
    events = only_bundle(tmp_path).events
    fast, during = _overlaps(events)
    assert len(fast) >= 3 and rep.turns == 0  # each reply was due mid-speech
    assert not _of(events, "chan.barge_in") and not during
    assert not [e for e in fast if e.payload["interrupted"]]


def test_a_current_rep_line_still_barges_in(tmp_path: Path) -> None:  # (i)
    rep = Rep(turns=1, thinking=False)
    run(tmp_path, GUIDED, channels={"user": "sim", "cp": rep})
    events = only_bundle(tmp_path).events
    (cut,) = _of(events, "chan.barge_in")
    (heard,) = [e for e in _of(events, "utt.delivered") if e.payload["interrupted"]]
    assert heard.payload["text_heard"] != LONG and cut.seq > heard.seq


def _budget(
    tmp_path: Path, match: str, cfg: SessionConfig | None = None
) -> tuple[Event, ...]:
    """The breach re-raises, ends with ``budget`` and keeps the crossing call."""
    scripts = SCRIPTS | {"slow": [act("Waiting.", {"tool": "wait", "seconds": 1})]}
    with pytest.raises(RunawaySpend, match=match) as caught:
        run(tmp_path, scripts, cfg=cfg)
    events = only_bundle(tmp_path).events
    assert events[-1].payload["reason"] == "budget"
    by_id = {e.event_id: e for e in events}
    crossing = caught.value.charge.call_id
    (charged,) = [
        e
        for e in events
        if e.type == "spend.charged" and e.payload["call_id"] == crossing
    ]
    (call,) = [by_id[c] for c in charged.cause_ids]  # the crossing call, recorded
    assert call.type == "llm.call" and call.payload["call_id"] == crossing
    return events


@pytest.mark.parametrize(
    ("projected", "message"),
    [((10, 1_000), "runaway tokens"), ((10**9, 2), "runaway calls")],
)
def test_a_ledger_breach_ends_the_session_with_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    projected: tuple[int, int],
    message: str,
) -> None:  # (j): every fake call is unpriced and reports usage
    monkeypatch.setattr(session, "PROJECTED", projected)
    _budget(tmp_path, message)


def test_the_2_usd_cap_ends_the_session_with_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # (j): a test-only rate prices Slow at $1 per call
    rate = {"slow-fake": Rate(1_000_000.0, 1_000_000.0)}

    def ledger(tokens: int, calls: int) -> SpendLedger:
        return SpendLedger(tokens, calls, rates=rate)

    monkeypatch.setattr(session, "SpendLedger", ledger)
    slow = fake("slow").model_copy(update={"endpoint": "relay"})
    cfg = fake_config().model_copy(update={"slow": slow})
    events = _budget(tmp_path, "runaway spend", cfg)
    priced = [e for e in events if e.type == "spend.charged" and e.payload["micro_usd"]]
    assert (
        sum(cast(int, e.payload["micro_usd"]) for e in priced) > SESSION_CAP_MICRO_USD
    )
