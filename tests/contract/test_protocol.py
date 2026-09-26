"""The Fast grammar (P4, TalkAct tolerance) and renderer rules (GUIDE slots, budget)."""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from proxyloop.contract.base import Lane
from proxyloop.contract.messages import Guide, GuideMove
from proxyloop.contract.protocol import (
    PROFILES,
    ContextBudgetError,
    EndCall,
    GuideSlotError,
    Hold,
    ParseIssue,
    Relay,
    Speech,
    StreamParser,
    TurnItem,
    Wait,
    fingerprint,
    format_turn,
    parse_turn,
    render_messages,
)
from proxyloop.contract.state import (
    Blackboard,
    Fact,
    OfferPublic,
    PrivateState,
    PublicFact,
    PublicState,
    ReadbackSlot,
)
from proxyloop.contract.views import Trigger, view_cp

SNAPSHOTS = Path(__file__).resolve().parent / "snapshots"

# ---------------------------------------------------------------- P4

WORDS = [
    "okay",
    "the",
    "price",
    "is",
    "$65",
    "$6.50",
    "per",
    "month",
    "Dana",
    "12",
    "fees",
    "we",
    "can",
    "check",
    "that",
    "thanks",
    "hello",
    "one",
    "moment",
]


def _words(rng: random.Random, n: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(n))


def _sentences(rng: random.Random) -> list[TurnItem]:
    out: list[TurnItem] = []
    count = rng.randint(0, 3)
    for i in range(count):
        end = rng.choice(".!?") if i < count - 1 else rng.choice([".", "?", "!", ""])
        out.append(Speech(text=_words(rng, rng.randint(1, 6)) + end))
    return out


def _relay(rng: random.Random, lane: Lane) -> Relay:
    kinds = ["note", "fact"] + (
        ["correction", "request", "revoke"] if lane == "user" else []
    )
    kind = rng.choice(kinds)
    key = rng.choice(["price", "term_months", "fee.activation", "name", "plan_b"])
    if kind == "fact":
        n = rng.randint(1, 3)
        pairs = tuple((f"{key}{i}", _words(rng, rng.randint(1, 3))) for i in range(n))
        return Relay(type="fact", facts=pairs)
    if kind == "correction":
        return Relay(type="correction", facts=((key, _words(rng, 2)),))
    text = _words(rng, rng.randint(1, 5))
    if kind == "request":
        return Relay(type="request", text=text)
    if kind == "revoke":
        return Relay(type="revoke", text=text)
    return Relay(type="note", text=text)


def canonical_turn(rng: random.Random, lane: Lane) -> tuple[TurnItem, ...]:
    items = _sentences(rng)
    items += [_relay(rng, lane) for _ in range(rng.randint(0, 3))]
    pause = rng.choice(["none", "wait"] + (["hold"] if lane == "cp" else []))
    if pause == "hold":
        items.append(Hold(reason=rng.choice(["offer", "decision", "pressure"])))
    elif pause == "wait":
        items.append(Wait())
    if rng.random() < 0.3:
        items.append(EndCall())
    return tuple(items) if items else (Wait(),)


def _corpus() -> list[tuple[Lane, tuple[TurnItem, ...]]]:
    rng = random.Random(20260926)
    lanes: list[Lane] = ["user", "cp"]
    return [(lanes[i % 2], canonical_turn(rng, lanes[i % 2])) for i in range(64)]


CORPUS = _corpus()


def _stream(chunks: list[str], lane: Lane) -> tuple[TurnItem, ...]:
    parser = StreamParser(lane)
    items: list[TurnItem] = []
    for chunk in chunks:
        items += parser.feed(chunk)
    return (*items, *parser.close())


def test_corpus_has_at_least_60_distinct_canonical_turns() -> None:
    assert len({(lane, turn) for lane, turn in CORPUS}) >= 60


@pytest.mark.parametrize(("lane", "turn"), CORPUS)
def test_p4_round_trip_and_every_prefix_split(
    lane: Lane, turn: tuple[TurnItem, ...]
) -> None:
    text = format_turn(turn)
    assert parse_turn(text, lane) == turn
    for i in range(len(text) + 1):
        assert _stream([text[:i], text[i:]], lane) == turn, i
    assert _stream(list(text), lane) == turn


@settings(max_examples=300, deadline=None)
@given(
    text=st.text(alphabet="ab .!?:@\n$5THENFIRSTslowendcalhodwitfc=;", max_size=80),
    cuts=st.lists(st.integers(0, 80), max_size=4),
    lane=st.sampled_from(["user", "cp"]),
)
def test_streaming_equals_batch_on_any_text(
    text: str, cuts: list[int], lane: Lane
) -> None:
    points = sorted({min(c, len(text)) for c in cuts})
    chunks = [
        text[a:b] for a, b in zip([0, *points], [*points, len(text)], strict=True)
    ]
    assert _stream(chunks, lane) == parse_turn(text, lane)


# TalkAct-style outputs (fast_agent.py:168-191) and our extensions.
# fmt: off
TOLERANT: list[tuple[Lane, str, tuple[TurnItem, ...]]] = [
    ("cp", "Sure, one moment. @slow: they offered 65", (
        Speech(text="Sure, one moment."), Relay(type="note", text="they offered 65"))),
    ("user", "FIRST: Hello there.\nTHEN: @slow: name is Dana", (
        Speech(text="Hello there."), Relay(type="note", text="name is Dana"))),
    ("cp", "A. @slow: x @SLOW: y", (
        Speech(text="A."), Relay(type="note", text="x"), Relay(type="note", text="y"))),
    ("cp", "Bye now. @end_call", (Speech(text="Bye now."),)),  # inline: not honoured
    ("cp", "Thanks!\n@END_CALL now", (Speech(text="Thanks!"), EndCall())),
    ("user", "Okay. THEN:", (Speech(text="Okay."),)),
    ("user", "Hi.\nHow are you?", (Speech(text="Hi."), Speech(text="How are you?"))),
    ("cp", "@slow: fact price=6500; term_months = 12", (
        Relay(type="fact", facts=(("price", "6500"), ("term_months", "12"))),)),
    ("user", "@slow: correction name=Dana R", (
        Relay(type="correction", facts=(("name", "Dana R"),)),)),
    ("user", "Stopping now.\n@slow: revoke do not accept anything", (
        Speech(text="Stopping now."),
        Relay(type="revoke", text="do not accept anything"))),
    ("cp", "One moment.\n@hold offer", (
        Speech(text="One moment."), Hold(reason="offer"))),
    ("cp", "@wait", (Wait(),)),
    ("cp", "@slow: fact price is 65", (
        Relay(type="note", text="fact price is 65"),
        ParseIssue(reason="malformed_fact", text="fact price is 65"))),
    ("cp", "Hm.\n@slow: revoke stop", (
        Speech(text="Hm."), ParseIssue(reason="wrong_lane", text="revoke stop"))),
    ("user", "Hi.\n@hold offer", (
        Speech(text="Hi."), ParseIssue(reason="wrong_lane", text="@hold offer"))),
    ("cp", "Hi.\n@hold maybe", (
        Speech(text="Hi."), ParseIssue(reason="bad_hold_reason", text="@hold maybe"))),
    ("cp", "@hold offer\n@wait", (
        Hold(reason="offer"), ParseIssue(reason="duplicate_pause", text="@wait"))),
    ("cp", "@frobnicate", (
        ParseIssue(reason="unknown_directive", text="@frobnicate"),
        ParseIssue(reason="empty_turn"))),
    ("user", "", (ParseIssue(reason="empty_turn"),)),
]
# fmt: on


@pytest.mark.parametrize(("lane", "text", "expected"), TOLERANT)
def test_tolerant_vectors(
    lane: Lane, text: str, expected: tuple[TurnItem, ...]
) -> None:
    assert parse_turn(text, lane) == expected
    assert _stream(list(text), lane) == expected


def test_parse_issues_have_no_canonical_text() -> None:
    with pytest.raises(ValueError, match="parse issue"):
        format_turn((ParseIssue(reason="empty_turn"),))


def test_closed_parser_refuses_input() -> None:
    parser = StreamParser("cp")
    parser.close()
    with pytest.raises(ValueError, match="closed"):
        parser.feed("more")


# ---------------------------------------------------------------- renderer


def _cp_bb(guide: Guide) -> Blackboard:
    slot = ReadbackSlot(
        field="monthly_price", value="6500", unit="usd_minor", role="recurring"
    )
    public = PublicState(
        facts={
            "rep.name": PublicFact(
                key="rep.name", value="Jo", source="cp_utt", source_ref="c1"
            )
        },
        offers={"o1": OfferPublic(offer_ref="o1", revision=1, slots=(slot,))},
        guidance_cp=(guide,),
    )
    private = PrivateState(
        case_facts={
            "account.pin": Fact(key="account.pin", value="4921", protected=True)
        }
    )
    return Blackboard(public=public, private=private)


def _render_cp(bb: Blackboard) -> str:
    return render_messages(view_cp(bb, Trigger(kind="guidance"), "b"), "pl_cp_v1")[
        1
    ].content


@pytest.mark.parametrize(
    "slot", ["fact:account.pin", "fact:missing", "offer:o2", "offer:o1.term_months"]
)
def test_guide_slot_not_in_public_state_fails_at_render(slot: str) -> None:
    bb = _cp_bb(Guide(move=GuideMove.IDENTIFY, slots=(slot,)))
    with pytest.raises(GuideSlotError, match="does not resolve"):
        _render_cp(bb)


def test_public_guide_slots_resolve() -> None:
    guide = Guide(
        move=GuideMove.ASK_READBACK, slots=("offer:o1.monthly_price", "fact:rep.name")
    )
    assert "(offer:o1.monthly_price = $65.00; fact:rep.name = Jo)" in _render_cp(
        _cp_bb(guide)
    )


def test_over_budget_without_anything_to_trim_is_an_error() -> None:
    view = view_cp(Blackboard(), Trigger(kind="rep_spoke"), "x" * 20_000)
    with pytest.raises(ContextBudgetError):
        render_messages(view, "pl_cp_v1")


def test_profile_must_match_the_lane() -> None:
    view = view_cp(Blackboard(), Trigger(kind="rep_spoke"), "b")
    with pytest.raises(ValueError, match="renders the user lane"):
        render_messages(view, "pl_user_v1")


def test_fingerprints_match_the_snapshot() -> None:
    """A fingerprint change is a contract change: update ADR and pull-through."""

    current = {name: fingerprint(name) for name in PROFILES}
    path = SNAPSHOTS / "fingerprints.json"
    if os.environ.get("PL_UPDATE_SNAPSHOTS"):
        path.write_text(json.dumps(current, indent=1) + "\n", "utf-8")
    assert json.loads(path.read_text("utf-8")) == current
