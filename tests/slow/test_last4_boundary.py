"""S1-SYS-26 bug 1 (I4): the last-four token boundary. A closing ``)`` or quote
may follow the digits before one sentence mark ("(account ending in 4821),"),
and an opener before the digits must itself start a token (no ``$"4821"``).
No cue lexicon: the rule is about marks, never about the words around them."""

from __future__ import annotations

import pytest
from tests.slow.test_tools import (
    L4,
    PROTECTED,
    _message,  # pyright: ignore[reportPrivateUsage]
)

SEQ10 = (  # reality smoke 20260927T054451Z-655087, user.msg seq 10, verbatim
    "My bill went up to 85, which is ridiculous after 6 years with Northwind. "
    "I'm Dana Reyes (account ending in 4821), and Brightwave has an offer for 60. "
    "Find the lowest monthly price Northwind will offer to keep my current plan "
    "and terms, without agreeing to anything yet."
)
PUBLIC = [  # (message, value): the user's own last four goes public
    (SEQ10, "4821"),
    ("I'm Dana (account ending in 4821), and", "4821"),
    ("account ending in 4821).", "4821"),
    ("last four: 4821)", "4821"),
    ('my last four are "4821".', "4821"),
    ("my last four are “4821”, thanks", "4821"),
    ("(4821)", "4821"),
]
PRIVATE = [  # (message, value): not a standalone token of the user's words
    ("4821-5555", "4821"),
    ("4821.50", "4821"),
    ("$4821)", "4821"),
    ("(4821-1999)", "4821"),
    ("(4821-1999)", "1999"),
    ("(555) 482-1999", "4821"),
    ("(555) 482-1999", "1999"),
    ("(4821-4821)", "4821"),
    ('costs $"4821", ok', "4821"),  # an opener after "$" starts no token
    ("costs $“4821”, ok", "4821"),
    ("costs $(4821), ok", "4821"),
    ("costs $(4821) ok", "4821"),
    ('costs $"4821" ok', "4821"),  # public on main (#162 review)
    ("x(4821)", "4821"),  # public on main (#162 review)
    ("ending in 4821)).", "4821"),  # one closer at most
    ("ending in 4821),.", "4821"),  # one mark at most
    ("ending in 4821.)", "4821"),  # the closer comes before the mark
    ("ending in 4821)x", "4821"),
]
PINNED = [  # what the rule does, documented (main root decision 2026-09-27)
    # a card's standalone group equal to the value: public today, kept
    ("card 1234 5678 4821 9999", "4821"),
    # a year has the shape of "(account ending in 4821),": a wrong-value risk
    # (the value is the user's own words), not an I4 leak; _leaks still blocks
    # protected facts and mandate bounds. No cue lexicon separates them.
    ("I joined in 2024), I", "2024"),
    ("customer since (2021), I", "2021"),
]


def _publishes(text: str, value: str) -> bool:
    bb, tools = _message(text)
    result = tools.fact(bb, L4, value, "u-1")
    fact = dict(result.effects[0][1])
    public = fact["scope"] == "public"
    assert (tools.shareable.get(L4) == value) == public, (text, value)
    return public


@pytest.mark.parametrize(("text", "value"), PUBLIC)
def test_a_last_four_closed_by_a_bracket_or_quote_goes_public(
    text: str, value: str
) -> None:
    assert _publishes(text, value), text


@pytest.mark.parametrize(("text", "value"), PRIVATE)
def test_a_last_four_that_is_no_standalone_token_stays_private(
    text: str, value: str
) -> None:
    assert not _publishes(text, value), text


@pytest.mark.parametrize(("text", "value"), PINNED)
def test_the_boundary_rule_is_pinned_where_it_cannot_judge_meaning(
    text: str, value: str
) -> None:
    assert _publishes(text, value), text


def test_the_seq10_last_four_still_meets_the_leak_check() -> None:  # I4
    bb, tools = _message(SEQ10, case_facts=PROTECTED)  # phone "(555) 482-1999"
    result = tools.fact(bb, L4, "4821", "u-1")
    (_, fact), (denied, _) = result.effects
    assert (fact["scope"], denied) == ("private", "declass.denied")
