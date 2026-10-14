"""Sim rep realism (ADR-0032): one reply per caller turn, an ack once an offer
exists, one block's Mouth calls at once, the levers before a read-back ask,
silence strikes in a row only, and the S1 read-back terms on every rung.
Scripted fakes, writing through the real Bus."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest
from tests.env.bus_sink import BusSink
from tests.env.test_backlog import (
    CANCEL,
    DISCOUNT,
    EQUIVALENT,
    ID,
    NAME,
    NAME_ONLY,
    OTHER,
    READBACK,
    TASK,
    Echo,
    Line,
    Play,
)
from tests.support.fakes import fake_ref

from proxyloop.contract.llm import LLMUnavailable, TextRequest, ToolRequest
from proxyloop.env.counterparty import ear
from proxyloop.env.counterparty.ear import EarAct, Fact
from proxyloop.env.counterparty.mouth import Mouth
from proxyloop.env.counterparty.policy import Decision, Policy, PublicIntent
from proxyloop.env.counterparty.simrep import voiced
from proxyloop.env.tasks.loader import load_task

LAST4_ONLY: Line = (
    "Last four 4821.",
    {"act": "provide_fact", "facts": [{"key": "account.last4", "value": "4821"}]},
)
THANKS: Line = ("Thank you, let me check with Marcus.", {"act": "smalltalk"})


def _d(kind: str, **kw: Any) -> Decision:
    return Decision("OFFER", "OFFER", PublicIntent(kind=kind, **kw), 0)  # type: ignore[arg-type]


def _intents(play: Play, type_: str) -> list[str]:
    return [cast(dict[str, str], e.payload["intent"])["kind"] for e in play.of(type_)]


def _texts(play: Play) -> list[str]:
    return [str(e.payload["text"]) for e in play.of("rep.mouth")]


# 1. One reply per caller turn ------------------------------------------------


def test_a_read_back_with_a_clarify_voices_only_the_read_back() -> None:
    readback = _d("readback", offer_ref="loyal-1", say=(("monthly_price", "75"),))
    assert voiced([readback, _d("clarify")]) == [0]
    assert voiced([_d("clarify"), readback]) == [1]
    assert voiced([_d("ack"), readback, _d("ack")]) == [1]
    assert voiced([_d("clarify"), _d("ack")]) == [1]  # fillers alone: the last
    assert voiced([_d("no_better"), readback, _d("no_better")]) == [1, 2]  # dedupe
    assert voiced([_d("offer_expired", offer_ref="loyal-1")]) == []


def test_a_block_with_a_read_back_and_smalltalk_says_the_terms_only(
    tmp_path: Path,
) -> None:
    play = Play(tmp_path, [ID, DISCOUNT, READBACK, THANKS], alone=1)
    turns = play.run()
    assert _intents(play, "rep.policy")[-2:] == ["readback", "ack"]  # decided
    assert _intents(play, "rep.mouth")[-1] == "readback"
    (line,) = turns[2].lines
    assert line[0].startswith("Here are the full terms:")


def test_a_block_passing_identity_never_says_it_still_needs_to_verify(
    tmp_path: Path,
) -> None:
    play = Play(tmp_path, [OTHER, NAME_ONLY, LAST4_ONLY], alone=0)
    turns = play.run()
    assert _intents(play, "rep.policy")[-2:] == ["ask_identity", "how_can_help"]
    (line,) = turns[1].lines
    assert line[0].startswith("Thanks, you are verified.")
    assert not any("still need to verify" in t for t in _texts(play)[1:])


def test_identity_asked_again_when_the_block_does_not_pass_it(tmp_path: Path) -> None:
    play = Play(tmp_path, [OTHER, NAME_ONLY], alone=2)
    play.run()
    assert _intents(play, "rep.mouth")[-1] == "ask_identity"


# 2. An ack once an offer exists ----------------------------------------------


def test_smalltalk_before_any_offer_is_clarified(tmp_path: Path) -> None:
    play = Play(tmp_path, [ID, THANKS], alone=2)
    turns = play.run()
    assert turns[1].lines[0][0] == "Sorry, how can I help with your account?"


def test_smalltalk_after_an_offer_gets_an_ack(tmp_path: Path) -> None:
    play = Play(tmp_path, [ID, DISCOUNT, THANKS, OTHER], alone=4)
    turns = play.run()
    assert _intents(play, "rep.mouth")[-2:] == ["ack", "ack"]
    assert [t.lines[0][0] for t in turns[2:]] == ["Sure, take your time."] * 2
    assert all(e.payload["fidelity_ok"] for e in play.of("rep.mouth"))


# 3. One block's Mouth calls at once ------------------------------------------


class Gate(Echo):
    """A faithful Mouth that answers only once ``n`` calls are in flight, the
    first started answering last."""

    def __init__(self, sink: BusSink, n: int) -> None:
        super().__init__(fake_ref(), [], on_record=sink.world.record)
        self.n, self.started, self.finished = n, 0, list[str]()
        self.all_in = asyncio.Event()

    async def _next(self, request: TextRequest | ToolRequest) -> tuple[str, int]:
        self.started += 1
        k = self.started
        if k == self.n:
            self.all_in.set()
        await asyncio.wait_for(self.all_in.wait(), 2)  # times out if serial
        await asyncio.sleep(0.01 * (self.n - k))
        self.finished.append(request.call_id)
        return await super()._next(request)


def _three(sink: BusSink) -> list[tuple[PublicIntent, str, str]]:
    intents = [
        PublicIntent(kind="offer", say=(("monthly_price", "75.00"),)),
        PublicIntent(kind="final_offer", say=(("monthly_price", "68.00"),)),
        PublicIntent(kind="no_better"),
    ]
    return [(i, "", sink.heard(f"line {n}").event_id) for n, i in enumerate(intents)]


def test_one_blocks_mouth_calls_run_at_once_and_keep_their_order(
    tmp_path: Path,
) -> None:
    sink = BusSink(tmp_path)
    gate = Gate(sink, 3)
    lines = _three(sink)
    mouth = Mouth(gate, sink.world, TASK.counterparty)
    said = asyncio.run(mouth.say_all(lines))
    assert gate.started == 3
    assert [c[len("mouth:") : c.rindex(":")] for c in gate.finished] == [
        c for *_, c in reversed(lines)
    ]
    assert [t for t, _ in said] == [
        "I can offer you this: monthly price: 75.00.",
        "This is my best and final offer: monthly price: 68.00.",
        "I am afraid I cannot do better than what I offered.",
    ]
    events = sink.of("rep.mouth")
    assert [e.event_id for e in events] == [ev for _, ev in said]  # in line order
    assert [e.cause_ids[0] for e in events] == [c for *_, c in lines]


def test_a_dead_mouth_in_a_block_aborts_loudly_and_voices_nothing(
    tmp_path: Path,
) -> None:
    sink = BusSink(tmp_path)
    mouth = Mouth(sink.llm(dead=True), sink.world, TASK.counterparty)
    with pytest.raises(LLMUnavailable):
        asyncio.run(mouth.say_all(_three(sink)))
    assert sink.of("rep.mouth") == []


# 4. The levers before a read-back ask -----------------------------------------


def test_the_verified_ear_ranks_tenure_before_a_read_back_ask() -> None:
    order = ear.ORDER_VERIFIED
    first = ["accept", "decline", "cite_competitor", "cancel_intent", "tenure"]
    then = ["ask_readback", "ask_discount", "provide_fact"]
    at = [order.index(a) for a in first + then]
    assert at == sorted(at)


# 5. The read-back terms on every rung ----------------------------------------


@pytest.mark.parametrize("mode", ["info_only", "full"])
def test_cp_direct_discount_rungs_say_no_other_changes_and_no_expiry(
    mode: str,
) -> None:
    task = load_task("cp-direct-discount", mode=mode)
    assert task.version == 2
    for rung in task.counterparty.ladder:
        assert rung.hidden["changes_none"] == "true"
        assert rung.hidden["expires"] == "none"


# 6. Silence strikes in a row --------------------------------------------------


def _verified() -> Policy:
    cp = TASK.counterparty
    p = Policy(cp, {k: TASK.profile.facts[k] for k in cp.identity})
    facts = (
        Fact(key=NAME, value="Dana Reyes"),
        Fact(key="account.last4", value="4821"),
    )
    p.step(EarAct(act="provide_fact", facts=facts), "u0", "", 0)
    return p


def _silence(p: Policy, t_ms: int) -> Decision:
    p.floor(True, t_ms)
    (d,) = p.tick(t_ms + int(TASK.counterparty.patience.silence_s * 1000))
    return d


def test_silence_strikes_start_again_after_a_heard_act() -> None:
    p, n = _verified(), TASK.counterparty.patience.strikes
    t = 1_000
    for _ in range(3):  # n - 1 unanswered check-ins, then an answer, three times
        for _ in range(n - 1):
            assert _silence(p, t).intent.kind == "check_in"
            t += 100_000
        p.step(EarAct(act="smalltalk"), f"u{t}", "I'm here.", t)
    assert not p.done and p.timer_strikes == 3 * (n - 1)  # every strike counted
    kinds = [_silence(p, t + 100_000 * i).intent.kind for i in range(n)]
    assert kinds == ["check_in"] * (n - 1) + ["hang_up"]  # n in a row hang up


def test_identity_strikes_do_not_start_again() -> None:
    cp = TASK.counterparty
    p = Policy(cp, {k: TASK.profile.facts[k] for k in cp.identity})
    p.step(EarAct(act="other"), "u0", "", 0)  # the greeting
    kinds = [
        p.step(EarAct(act=a), f"u{i}", "", i)[-1].intent.kind  # type: ignore[arg-type]
        for i, a in enumerate(["refuse_fact", "smalltalk", "refuse_fact"], 1)
    ]
    assert kinds == ["ask_identity", "ask_identity", "hang_up"]


# The equality test: the collapse changes only what is voiced -----------------


def _bare(play: Play) -> tuple[list[tuple[Any, ...]], dict[str, object]]:
    """Step the run's own Ear acts through a bare ``Policy`` (no SimRep, no
    voicing), block by block as the SimRep did: every decision, and the
    policy state."""
    cp = TASK.counterparty
    p = Policy(cp, {k: TASK.profile.facts[k] for k in cp.identity})
    text = {play.utt(i): (line[0], i * play.gap) for i, line in enumerate(play.lines)}
    out: list[tuple[Any, ...]] = []
    blocks: list[list[Any]] = []
    for e in play.of("rep.ear"):
        block = e.payload["heard_utt_ids"]
        if not blocks or block != blocks[-1][0].payload["heard_utt_ids"]:
            blocks.append([])
        blocks[-1].append(e)
    for block in blocks:
        listed = frozenset(p.made())
        for e in block:
            args = cast(dict[str, Any], e.payload["args"])
            act = EarAct.model_validate_json(
                json.dumps({"act": e.payload["act"], **args})
            )
            heard, t_ms = text[str(e.payload["utt_id"])]
            utt = str(e.payload["utt_id"])
            for d in p.step(act, utt, heard, t_ms, listed=listed):
                c = d.commit
                commit = None if c is None else (c.offer_ref, c.confirmation_id)
                intent = d.intent.model_dump(mode="json")
                out.append((d.from_, d.to, intent, d.rung, commit))
    return out, {k: v for k, v in vars(p).items() if k != "ledger"}


def _d4_lines(decisions: list[tuple[Any, ...]]) -> int:
    """How many lines ADR-0021 D4 voiced: a run of equal intents once."""
    n = 0
    for i, (_, _, intent, _, commit) in enumerate(decisions):
        again = i + 1 < len(decisions) and decisions[i + 1][2] == intent
        n += intent["kind"] != "offer_expired" and (commit is not None or not again)
    return n


REALISM: list[tuple[str, list[Line], int]] = [
    ("read-back beside smalltalk", [ID, DISCOUNT, READBACK, THANKS, OTHER], 1),
    (
        "identity passed in one block",
        [OTHER, NAME_ONLY, DISCOUNT, LAST4_ONLY, DISCOUNT],
        0,
    ),
    ("levers and fillers", [ID, DISCOUNT, THANKS, CANCEL, OTHER, DISCOUNT], 1),
]


@pytest.mark.parametrize(
    ("lines", "alone"),
    [pytest.param(lines, alone, id=name) for name, lines, alone, _ in EQUIVALENT]
    + [pytest.param(lines, alone, id=name) for name, lines, alone in REALISM],
)
def test_the_collapse_changes_only_the_rep_lines(
    tmp_path: Path, lines: list[Line], alone: int
) -> None:
    play = Play(tmp_path, lines, alone)
    play.run()
    want, state = _bare(play)
    got = [
        (e.payload["from"], e.payload["to"], e.payload["intent"], e.payload["rung"])
        for e in play.of("rep.policy")
    ]
    assert got == [w[:4] for w in want]  # every decision, as stepped bare
    commits = [w[4] for w in want if w[4] is not None]
    heard = [str(e.payload["offer_ref"]) for e in play.of("rep.commit_heard")]
    written = [str(e.payload["confirmation_id"]) for e in play.of("ledger.write")]
    assert heard == [ref for ref, _ in commits]
    assert written == [cid for _, cid in commits]  # the same ledger
    rep = {k: v for k, v in vars(play.rep.policy).items() if k != "ledger"}
    assert rep == state  # strikes (both kinds), rung, offers, state
    assert len(play.of("rep.mouth")) <= _d4_lines(want)  # only lines differ


@pytest.mark.parametrize(
    ("lines", "alone"), [pytest.param(lines, a, id=n) for n, lines, a in REALISM]
)
def test_the_collapse_drops_lines_d4_would_have_said(
    tmp_path: Path, lines: list[Line], alone: int
) -> None:
    play = Play(tmp_path, lines, alone)
    play.run()
    want, _ = _bare(play)
    assert len(play.of("rep.mouth")) < _d4_lines(want)
