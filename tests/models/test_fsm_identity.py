"""The FSM's identity answer reads only what an LLM Fast is shown (S1-MOD-01).

After S1-SYS-27 (ADR-0013 A) the view carries only the newest cp guide, so the
identity values come from that guide if it is ``identify``, else from the FSM's
own earlier identify line in the rendered transcript, else the FSM deflects.
Guide history is never read. Views go through the contract renderer.
"""

from __future__ import annotations

from tests.models.views import request, view

from proxyloop.contract.protocol import (
    Hold,
    Relay,
    Speech,
    TurnItem,
    parse_turn,
    render_messages,
)
from proxyloop.contract.state import Line
from proxyloop.contract.views import FastView
from proxyloop.models.fsm import MOVES, NOTED, read_view, respond


def _fact(key: str, value: str) -> dict[str, str]:
    return {"key": key, "value": value, "source": "shareable", "source_ref": "task"}


FACTS = (_fact("account.holder_name", "Dana Reyes"), _fact("account.last4", "4821"))
IDENTIFY = {
    "move": "identify",
    "slots": ("fact:account.holder_name", "fact:account.last4"),
}
HOLD_FOR_FACT = {"move": "hold_for_fact", "slots": ()}
ASK_DISCOUNT = {"move": "ask_discount", "slots": ()}
ASK_AGAIN = "Sorry, can you verify the name on the account and the last four again?"
DEFLECT = Speech(text=MOVES["deflect_fact_request"])


def _turn(v: FastView) -> tuple[TurnItem, ...]:
    # pl_cp_v2: the live cp profile, the one with hold_for_fact (S1-CON-04)
    messages = request(render_messages(v, "pl_cp_v2")).messages
    return parse_turn(respond(read_view(messages)), v.lane)


def _said(items: tuple[TurnItem, ...]) -> list[str]:
    return [i.text for i in items if isinstance(i, Speech)]


def _lines(*pairs: tuple[str, str]) -> tuple[Line, ...]:
    return tuple(
        Line.model_validate({"utt_id": f"c{n}", "speaker": speaker, "text": text})
        for n, (speaker, text) in enumerate(pairs)
    )


def _guided(guide: object, facts: tuple[dict[str, str], ...] = FACTS) -> list[str]:
    """What the FSM itself says on a guide (never hand-written)."""

    v = view("cp", trigger="guidance", guidance=(guide,), public_facts=facts)
    return _said(_turn(v))


def _identify_line(facts: tuple[dict[str, str], ...] = FACTS) -> str:
    (line,) = _guided(IDENTIFY, facts)
    return line


def _asked(*lines: tuple[str, str], guidance: tuple[object, ...]) -> FastView:
    transcript = _lines(*lines, ("partner", ASK_AGAIN))
    return view("cp", transcript=transcript, public_facts=FACTS, guidance=guidance)


def _deflected(items: tuple[TurnItem, ...]) -> bool:
    return items[0] == DEFLECT and items[-1] == Hold(reason="fact_request")


def test_c_the_newest_identify_guide_supplies_the_values() -> None:
    items = _turn(_asked(guidance=(IDENTIFY,)))
    assert _said(items) == [_identify_line()]
    assert "Dana Reyes" in _said(items)[0] and "4821" in _said(items)[0]
    assert not [i for i in items if isinstance(i, Hold)]


def test_a_reverification_after_a_later_guide_repeats_the_own_identify_line() -> None:
    mine = _identify_line()
    lines = (("agent", mine), ("partner", "Thanks, you're verified."))
    for guide in (HOLD_FOR_FACT, ASK_DISCOUNT):
        items = _turn(_asked(("agent", "Hi."), *lines, guidance=(guide,)))
        assert _said(items) == [mine]
        assert [i for i in items if isinstance(i, Relay)]
        assert Hold(reason="fact_request") not in items


def test_the_newest_own_identify_line_wins() -> None:
    old = _identify_line()
    moved = tuple(
        f | {"value": "5502"} if f["key"] == "account.last4" else f for f in FACTS
    )
    new = _identify_line(moved)
    assert old != new
    lines = (("agent", old), ("partner", "Thanks."), ("agent", new))
    items = _turn(_asked(*lines, guidance=(ASK_DISCOUNT,)))
    assert _said(items) == [new]


def _split_line() -> list[str]:
    # "Dana J. Reyes": the FSM's own identify speech is two transcript lines.
    split = tuple(
        f | {"value": "Dana J. Reyes"} if f["key"] == "account.holder_name" else f
        for f in FACTS
    )
    said = _guided(IDENTIFY, split)
    assert len(said) == 2 and said[0].endswith("Dana J.")
    return said


def _never_partial(*lines: tuple[str, str]) -> None:
    items = _turn(_asked(*lines, guidance=(ASK_DISCOUNT,)))
    assert _deflected(items)
    assert not any("Dana J." in t for t in _said(items))


def test_a_split_identify_line_is_never_repeated_in_part() -> None:
    said = _split_line()
    _never_partial(*(("agent", t) for t in said), ("partner", "Thanks."))


def test_a_first_fragment_alone_then_a_rep_line_is_never_repeated() -> None:
    # barge-in: the second fragment was never heard, so it has no line
    _never_partial(("agent", _split_line()[0]), ("partner", "Sorry, hold on."))


def test_a_first_fragment_as_the_last_agent_line_is_never_repeated() -> None:
    # a superseded generation dropped the second fragment (S1-SYS-22)
    _never_partial(("agent", _split_line()[0]))


def test_a_complete_own_line_followed_by_another_own_line_is_repeated() -> None:
    (ask,) = _guided(ASK_DISCOUNT)
    mine = _identify_line()
    lines = (("agent", mine), ("agent", ask), ("partner", "Hmm."))
    items = _turn(_asked(*lines, guidance=(HOLD_FOR_FACT,)))
    assert _said(items) == [mine]
    assert Hold(reason="fact_request") not in items


def test_b_no_identify_guide_and_no_own_line_deflects() -> None:
    assert _deflected(_turn(_asked(("agent", "Hi."), guidance=(HOLD_FOR_FACT,))))


def test_a_partner_line_mimicking_the_template_is_never_the_source() -> None:
    mimic = _identify_line()
    items = _turn(_asked(("partner", mimic), guidance=(ASK_DISCOUNT,)))
    assert _deflected(items)
    assert mimic not in _said(items)


def test_an_older_identify_guide_is_not_read() -> None:
    items = _turn(_asked(guidance=(IDENTIFY, ASK_DISCOUNT)))
    assert _deflected(items)


def test_only_the_newest_guide_can_be_unvoiced() -> None:
    # The newest guide was voiced; an older unvoiced one is history, not guidance.
    tenure = {"move": "mention_tenure", "slots": ("fact:tenure_years",)}
    facts = (*FACTS, _fact("tenure_years", "6 years"))
    said = MOVES["mention_tenure"].format("6 years")
    transcript = _lines(("agent", said), ("partner", "Sure, go on."))
    v = view(
        "cp", transcript=transcript, public_facts=facts, guidance=(ASK_DISCOUNT, tenure)
    )
    assert _said(_turn(v)) == [NOTED]
