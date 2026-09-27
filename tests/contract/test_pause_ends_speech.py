"""ADR-0017: under ``pl_cp_v3`` a pause (``@hold``/``@wait``) ends the turn's
speech; every later non-directive line is a counted ``speech_after_pause``
issue, never a ``Speech``. ``pl_cp_v1``/``pl_cp_v2`` parse exactly as before."""

from __future__ import annotations

from dataclasses import fields

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.contract.test_protocol import ANY_TEXT, CORPUS, TOLERANT

from proxyloop.contract.base import HoldReason, Lane
from proxyloop.contract.protocol import (
    PROFILES,
    EndCall,
    Hold,
    ParseIssue,
    Relay,
    Speech,
    StreamParser,
    TurnItem,
    Wait,
    format_turn,
    parse_turn,
)

V2, V3 = "pl_cp_v2", "pl_cp_v3"
ASK = "Could you please continue holding for a moment?"
DETAIL = "I\u2019m still getting that detail from my customer."
HOLD_LINE = "@hold fact_request"

# Raw FastC responses from real runs (trimmed; no identity values): runs
# 20260927T091443Z-289b86 fast.turn seq 249 (length), 518 (length), 770 (stop)
# and 20260927T081031Z-93f96b seq 207 (stop).
R249 = (
    f"{DETAIL} {ASK}  \n{HOLD_LINE}\n оттур \n 天天中彩票买\n"
    f"{DETAIL} {ASK}  \n{HOLD_LINE}\nไทยฟรี\n"
)
R518 = (
    f"{DETAIL} Could you please hold for a moment longer?  \n{HOLD_LINE}\n"
    "રી\n) \n} \n} \n}"
)
R770 = (
    f"{DETAIL} {ASK}  \n{HOLD_LINE}\n tshemb_RGCTX}} \n、】【 \n (Do not add extra "
    "stray characters; output only speech and directive.) \n\n\n"
    f"{DETAIL} {ASK}\n{HOLD_LINE}"
)
DETAILS = "I\u2019m still getting those details from my customer."
R207 = (
    f"{DETAILS} Could you please hold a moment longer?  \n{HOLD_LINE}\nરસમીle\n\n"
    f"{DETAILS} Could you please hold a moment longer?\n{HOLD_LINE}"
)

FACT = Hold(reason="fact_request")
DUP = ParseIssue(reason="duplicate_pause", text=HOLD_LINE)


def _s(*texts: str) -> tuple[TurnItem, ...]:
    return tuple(Speech(text=t) for t in texts)


def _late(*texts: str) -> tuple[TurnItem, ...]:
    return tuple(ParseIssue(reason="speech_after_pause", text=t) for t in texts)


LATE_249 = f"{DETAIL} {ASK}"
# fmt: off
REAL: list[tuple[str, tuple[TurnItem, ...], tuple[TurnItem, ...]]] = [
    # (raw, parse under pl_cp_v2 = today, parse under pl_cp_v3)
    (R249,
     (*_s(DETAIL, ASK), FACT, *_s("оттур", "天天中彩票买", DETAIL, ASK), DUP,
      *_s("ไทยฟรี")),
     (*_s(DETAIL, ASK), FACT, *_late("оттур", "天天中彩票买", LATE_249), DUP,
      *_late("ไทยฟรี"))),
    (R518,
     (*_s(DETAIL, "Could you please hold for a moment longer?"), FACT,
      *_s("રી", ")", "}", "}", "}")),
     (*_s(DETAIL, "Could you please hold for a moment longer?"), FACT,
      *_late("રી", ")", "}", "}", "}"))),
    (R770,
     (*_s(DETAIL, ASK), FACT,
      *_s("tshemb_RGCTX}", "、】【",
          "(Do not add extra stray characters; output only speech and directive.)",
          DETAIL, ASK), DUP),
     (*_s(DETAIL, ASK), FACT,
      *_late("tshemb_RGCTX}", "、】【",
             "(Do not add extra stray characters; output only speech and "
             "directive.)", LATE_249), DUP)),
    (R207,
     (*_s(DETAILS, "Could you please hold a moment longer?"), FACT,
      *_s("રસમીle", DETAILS, "Could you please hold a moment longer?"), DUP),
     (*_s(DETAILS, "Could you please hold a moment longer?"), FACT,
      *_late("રસમીle", f"{DETAILS} Could you please hold a moment longer?"), DUP)),
]
# fmt: on


def _stream(chunks: list[str], lane: Lane, profile: str | None) -> list[TurnItem]:
    parser = StreamParser(lane, profile)
    items: list[TurnItem] = []
    for chunk in chunks:
        items += parser.feed(chunk)
    return [*items, *parser.close()]


@pytest.mark.parametrize(("raw", "v2", "v3"), REAL)
def test_real_garbage_after_hold_is_never_speech_under_v3(
    raw: str, v2: tuple[TurnItem, ...], v3: tuple[TurnItem, ...]
) -> None:
    assert parse_turn(raw, "cp", V3) == v3
    assert list(v3) == _stream(list(raw), "cp", V3)
    first_pause = next(n for n, i in enumerate(v3) if isinstance(i, Hold))
    spoken = [n for n, i in enumerate(v3) if isinstance(i, Speech)]
    assert spoken and max(spoken) < first_pause  # the speech before @hold is voiced


@pytest.mark.parametrize(("raw", "v2", "v3"), REAL)
def test_real_responses_parse_as_today_under_v2_and_v1(
    raw: str, v2: tuple[TurnItem, ...], v3: tuple[TurnItem, ...]
) -> None:
    """The regression pin: pl_cp_v1/v2 (and the lane-only call) keep the grammar."""
    assert parse_turn(raw, "cp", V2) == v2
    assert parse_turn(raw, "cp", "pl_cp_v1") == v2
    assert parse_turn(raw, "cp") == v2
    assert list(v2) == _stream(list(raw), "cp", V2)


def _h(reason: HoldReason) -> Hold:
    return Hold(reason=reason)


def _note(text: str) -> Relay:
    return Relay(type="note", text=text)


def _fact(*pairs: tuple[str, str]) -> Relay:
    return Relay(type="fact", facts=pairs)


# Normal cp turns in ARCHITECTURE §6.2's canonical order: speech, @slow lines,
# one @hold/@wait, then optionally @end_call.
# fmt: off
NORMAL: list[tuple[TurnItem, ...]] = [
    (*_s(DETAIL, ASK), FACT),
    (*_s("Thanks for that offer."), _fact(("monthly_price", "6500")), _h("offer")),
    (*_s("Let me check with my customer before deciding."), _h("decision")),
    (*_s("I understand.", "I need a moment to confirm that."), _h("pressure")),
    (*_s("Sorry, could you say that again?"), _h("unclear")),
    (*_s("One moment please."), _note("rep wants the account PIN"), FACT),
    (*_s("Thank you, I will pass that along."),
     _fact(("monthly_price", "6500"), ("term_months", "12")),
     _note("rep says this is the final offer"), _h("offer")),
    (Wait(),),
    (*_s("Okay."), Wait()),
    (*_s("Thanks for waiting."), _h("decision"), EndCall()),
    (*_s("Thank you for your time.", "Goodbye."), Wait(), EndCall()),
    (*_s("I appreciate the details."), _fact(("activation_fee", "3000")), _h("offer")),
    (*_s("Could you hold while I confirm the term?"), _h("decision")),
    (*_s("That sounds like a big change."), _note("rep pushes a 24 month term"),
     _h("pressure")),
    (_note("rep is checking the system"), Wait()),
    (*_s("Of course, take your time."), Wait()),
    (*_s("I cannot share that detail, sorry."), FACT),
    (*_s("Is this your best and final offer?"), _note("asked for final"), _h("offer")),
    (*_s("I will check that with my customer.", "Please hold."), _h("decision")),
    (*_s("Great, thank you.", "I am still waiting on one detail."), FACT, EndCall()),
]
# fmt: on


def test_normal_corpus_is_twenty_distinct_turns_with_a_pause() -> None:
    assert len(set(NORMAL)) >= 20
    assert all(any(isinstance(i, Hold | Wait) for i in t) for t in NORMAL)


@pytest.mark.parametrize("turn", NORMAL)
def test_normal_speech_then_pause_parses_identically(
    turn: tuple[TurnItem, ...],
) -> None:
    text = format_turn(turn)
    assert parse_turn(text, "cp", V3) == parse_turn(text, "cp", V2) == turn
    for i in range(len(text) + 1):
        assert tuple(_stream([text[:i], text[i:]], "cp", V3)) == turn, i


@pytest.mark.parametrize(("lane", "turn"), [(ln, t) for ln, t in CORPUS if ln == "cp"])
def test_p4_round_trip_holds_under_v3(lane: Lane, turn: tuple[TurnItem, ...]) -> None:
    """format_turn emits speech first, so canonical text never trips the rule."""
    text = format_turn(turn)
    assert parse_turn(text, lane, V3) == turn
    assert tuple(_stream(list(text), lane, V3)) == turn


@pytest.mark.parametrize(
    ("text", "expected"),
    [(t, e) for lane, t, e in TOLERANT if lane == "cp"],
)
def test_tolerant_cp_vectors_are_unchanged_under_v3(
    text: str, expected: tuple[TurnItem, ...]
) -> None:
    assert parse_turn(text, "cp", V3) == expected


# fmt: off
AFTER_SLOW_OR_END: list[str] = [
    "Hi.\n@slow: they offered 65\nAnything else?",
    "Sure. @slow: x\nMore words here.",
    "Bye.\n@end_call\nStill here.",
    "@end_call\nHello?",
    "@slow: fact price=6500\nThat is noted.",
]
# fmt: on


@pytest.mark.parametrize("text", AFTER_SLOW_OR_END)
def test_lines_after_slow_or_end_call_are_unchanged(text: str) -> None:
    v2 = parse_turn(text, "cp", V2)
    assert parse_turn(text, "cp", V3) == v2
    assert any(isinstance(i, Speech) for i in v2[1:])


def test_wait_ends_speech_too_and_relays_still_parse() -> None:
    text = "One sec.\n@wait\nStill there?\n@slow: fact price=6500\n@end_call"
    assert parse_turn(text, "cp", V3) == (
        Speech(text="One sec."),
        Wait(),
        *_late("Still there?"),
        Relay(type="fact", facts=(("price", "6500"),)),
        EndCall(),
    )


def test_a_whole_mixed_line_after_a_pause_is_one_issue() -> None:
    text = "Ok.\n@hold offer\nNo. Wait. @slow: fact price=1\n  \n"
    assert parse_turn(text, "cp", V3) == (
        Speech(text="Ok."),
        Hold(reason="offer"),
        *_late("No. Wait. @slow: fact price=1"),
    )


def test_a_pause_only_turn_with_trailing_garbage_is_not_empty() -> None:
    assert parse_turn("@hold offer\n}}", "cp", V3) == (
        Hold(reason="offer"),
        *_late("}}"),
    )


def test_a_refused_pause_does_not_end_speech() -> None:
    """Only an emitted Hold/Wait ends the speech: a bad reason is just an issue."""
    text = "Hi.\n@hold maybe\nThere."
    assert parse_turn(text, "cp", V3) == parse_turn(text, "cp", V2)


@settings(max_examples=500, deadline=None)
@given(text=ANY_TEXT, cuts=st.lists(st.integers(0, 80), max_size=4))
def test_streaming_equals_batch_on_any_text_under_v3(
    text: str, cuts: list[int]
) -> None:
    points = sorted({min(c, len(text)) for c in cuts})
    chunks = [
        text[a:b] for a, b in zip([0, *points], [*points, len(text)], strict=True)
    ]
    assert tuple(_stream(chunks, "cp", V3)) == parse_turn(text, "cp", V3)


def test_the_parser_refuses_a_profile_of_the_other_lane() -> None:
    with pytest.raises(ValueError, match="parses the cp lane"):
        StreamParser("user", V3)


def test_pl_cp_v3_is_pl_cp_v2_plus_the_grammar_flag() -> None:
    v2, v3 = PROFILES[V2], PROFILES[V3]
    assert v3.pause_ends_speech and not v2.pause_ends_speech
    assert not PROFILES["pl_cp_v1"].pause_ends_speech
    assert not PROFILES["pl_user_v1"].pause_ends_speech
    rendering = {f.name for f in fields(v2)} - {
        "name",
        "pause_ends_speech",
        "p2_ids_sha256",
    }
    assert all(getattr(v2, f) == getattr(v3, f) for f in rendering)
