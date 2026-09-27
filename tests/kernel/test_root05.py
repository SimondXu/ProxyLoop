"""Kernel fixes from the failed S0-ROOT-05 live smokes (S0-SYS-07): TTFS (l),
HOLD relay dedupe (e) and stale rep replies (i)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import cast

import pytest
from tests.contract.samples import SONNET, call_record
from tests.kernel.test_session import FINISH, SCRIPTS, UNTIL
from tests.support.fakes import RepeatingLLM
from tests.support.manual_clock import ScaledClock
from tests.support.sessions import act, fake, fake_config, only_bundle, run
from tests.support.sessions import patient_task as task

from proxyloop.contract.config import SessionConfig
from proxyloop.contract.events import Event
from proxyloop.contract.llm import LLMClient, LLMRole, LLMUnavailable, ModelRef
from proxyloop.contract.protocol import Hold
from proxyloop.env.world import WorldError
from proxyloop.kernel import session
from proxyloop.kernel.channels import Channel, End, Incoming
from proxyloop.kernel.session import ChannelSpec, Kernel
from proxyloop.llm.http import RecordSink
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

    def ledger(tokens: int, calls: int, refs: Iterable[ModelRef]) -> SpendLedger:
        return SpendLedger(tokens, calls, rates=rate, refs=refs)

    monkeypatch.setattr(session, "SpendLedger", ledger)
    slow = fake("slow").model_copy(update={"endpoint": "relay"})
    cfg = fake_config().model_copy(update={"slow": slow})
    events = _budget(tmp_path, "runaway spend", cfg)
    priced = [e for e in events if e.type == "spend.charged" and e.payload["micro_usd"]]
    assert (
        sum(cast(int, e.payload["micro_usd"]) for e in priced) > SESSION_CAP_MICRO_USD
    )


def _guard(tmp_path: Path, cfg: SessionConfig) -> Mapping[str, object]:
    run(tmp_path, SCRIPTS, cfg=cfg, until=UNTIL)
    started = only_bundle(tmp_path).events[0]
    return cast(Mapping[str, object], started.payload["runaway"])


def test_an_unpriced_model_sets_the_guard_factor_to_1_at_the_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # main root decision, #133 round 2
    unpriced = _guard(tmp_path / "a", fake_config())  # every fake is unpriced
    assert unpriced == {
        "factor": 1,
        "tokens": session.PROJECTED[0],
        "unpriced_calls": session.PROJECTED[1],
        "cap_micro_usd": SESSION_CAP_MICRO_USD,
    }
    cfg = fake_config()
    roles = ("fast_user", "fast_cp", "slow")
    world = {r: fake(r, True) for r in ("ear", "mouth", "simuser")}
    relay = {r: fake(r).model_copy(update={"endpoint": "relay"}) for r in roles}
    world = {r: w.model_copy(update={"endpoint": "relay"}) for r, w in world.items()}
    cfg = cfg.model_copy(update=relay | {"world": cfg.world.model_copy(update=world)})
    rate = {f"{r}-fake": Rate(0.001, 0.001) for r in (*roles, *world)}

    def ledger(tokens: int, calls: int, refs: Iterable[ModelRef]) -> SpendLedger:
        return SpendLedger(tokens, calls, rates=rate, refs=refs)

    monkeypatch.setattr(session, "SpendLedger", ledger)
    priced = _guard(tmp_path / "b", cfg)
    assert (priced["factor"], priced["tokens"]) == (3, 3 * session.PROJECTED[0])


def test_only_a_cp_hold_is_deduped_against_the_cp_hold(tmp_path: Path) -> None:
    clock = ScaledClock(100)  # (e), #133 round 3 N2: an idle kernel, never run

    def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
        return RepeatingLLM(ref, ["unused"], clock, on_record=sink)

    specs: dict[str, ChannelSpec] = {"user": "sim", "cp": "sim"}
    k = Kernel(fake_config(), task(), specs, tmp_path, clock, clock.sleep, make, None)
    said = k.emit("user.msg", "kernel", {"text": "hi"}).event_id
    held = k.emit("chan.hold", "fast.cp", {"lane": "cp", "reason": "decision"}, [said])
    hold = [Hold(reason="decision")]
    relay = k.lanes["user"]._relay  # pyright: ignore[reportPrivateUsage]
    relay(list(hold), held.event_id, "user-g1")  # a user-lane Hold: never compared
    assert (k.counts["hold_repeat"], k.counts["relay_rejected"]) == (0, 1)
    relay = k.lanes["cp"]._relay  # pyright: ignore[reportPrivateUsage]
    relay(list(hold), held.event_id, "cp-g1")  # the cp hold, unchanged: deduped
    assert (k.counts["hold_repeat"], k.counts["relay_rejected"]) == (1, 1)
    k.bus.close()


def test_budget_outranks_a_world_error_when_both_end_the_session() -> None:
    charge = SpendLedger(1, 1).price(  # main root, #133 round 3: the matrix aborts
        call_record(SONNET, usage=None, error="x", response_sha=None)
    )
    spent, world = RunawaySpend("runaway calls", charge), WorldError("ear timeout")
    outcome = session._outcome  # pyright: ignore[reportPrivateUsage]
    for leaves in ([world, spent], [spent, world]):
        assert outcome(BaseExceptionGroup("both", leaves)) == ("budget", spent)
    record = call_record(SONNET, usage=None, error="HTTP 503", response_sha=None)
    dead = LLMUnavailable("endpoint is dead", record)  # N5: a dead endpoint first
    for leaves in ([world, spent, dead], [dead, spent, world]):
        assert outcome(BaseExceptionGroup("all", leaves)) == ("llm_unavailable", dead)
