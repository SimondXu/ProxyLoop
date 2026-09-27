"""guard.declass regressions (#126): a shareable value never whitelists a mandate
bound or a protected value, and protected values are compared canonically."""

from __future__ import annotations

import pytest
from tests.guard.build import board, mandate, rep

from proxyloop.contract.state import Fact
from proxyloop.guard.declass import declassify

# max_monthly_price_minor=7000 ($70), max_term_months=24, fees 2500 ($25)
BOUND = mandate()
FULLWIDTH_7777 = "\N{FULLWIDTH DIGIT SEVEN}" * 4


@pytest.mark.parametrize("value", ["070", "70", "70.00", "$70", "24", "25"])
def test_a_shareable_value_equal_to_a_bound_does_not_launder_it(value: str) -> None:
    said = value.lstrip("$0") or value
    violations = declassify(
        f"The customer can go to {said}.", board(mandate=BOUND), {"x.y": value}
    )
    assert any(v.startswith("the private value") for v in violations), violations


def test_a_bound_the_rep_said_stays_public() -> None:
    bb = board(mandate=BOUND, cp=(rep("c1", "I can do $70 a month."),))
    assert declassify("The rep offered 70.", bb, {"x.y": "70"}) == ()


def test_a_shareable_value_that_is_no_bound_stays_source_bound() -> None:
    bb = board(mandate=BOUND)
    assert declassify("Brightwave quoted 60.", bb, {"competitor.price": "60"}) == ()


def test_a_shareable_value_equal_to_a_protected_value_does_not_launder_it() -> None:
    pin = Fact(key="account.pin", value="7777", protected=True)
    violations = declassify("Code 7777.", board(facts=(pin,)), {"x.y": "7777"})
    assert "number 7777 is not source-bound" in violations
    assert "the protected value of account.pin" in violations


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("O'Brien", "The holder is OBRIEN."),
        ("O'Brien", "The holder is o brien."),
        ("Lee-Smith", "The holder is lee smith."),
        ("Lee-Smith", "The holder is LEESMITH."),
        ("7777", "The code is 77-77."),
        ("7777", f"The code is {FULLWIDTH_7777}."),
        ("7777", "The code is 7 7 7 7."),
        ("7777", "It ends in 77."),  # part of it
        ("\u738b\u5c0f\u660e", "Holder: \u738b\u5c0f\u660e."),  # any script
    ],
)
def test_a_protected_value_is_denied_in_any_spelling(value: str, text: str) -> None:
    fact = Fact(key="account.secret", value=value, protected=True)
    violations = declassify(text, board(facts=(fact,)), {})
    assert "the protected value of account.secret" in violations


def test_text_without_the_protected_value_passes() -> None:
    fact = Fact(key="account.secret", value="O'Brien", protected=True)
    bb = board(facts=(fact,), cp=(rep("c1", "It is $68 a month."),))
    assert declassify("The rep offered 68 a month.", bb, {}) == ()
