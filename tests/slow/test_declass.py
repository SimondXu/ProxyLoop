"""guard.declass: a number enters public state only when it is source-bound (I4)."""

from __future__ import annotations

from proxyloop.contract.state import (
    Blackboard,
    ChannelState,
    Fact,
    Line,
    Mandate,
    PrivateState,
)
from proxyloop.guard.declass import declassify, numbers

REP = "I can do 75.00 a month for 12 months, or 1,068 for the year."


def _bb(**private: object) -> Blackboard:
    cp = ChannelState(
        lines=(
            Line(utt_id="rep-1", speaker="partner", text=REP),
            Line(utt_id="agent-1", speaker="agent", text="Could you do 60 instead?"),
        )
    )
    return Blackboard(
        channels={"user": ChannelState(), "cp": cp},
        private=PrivateState.model_validate(private),
    )


def test_numbers_are_values_not_spellings() -> None:
    assert numbers("$75, 75.00 and 1,068") == numbers("75 1068")


def test_numbers_the_rep_said_are_public() -> None:
    assert declassify("Offer: $75 a month for 12 months (1,068/yr).", _bb(), {}) == ()


def test_a_number_only_the_agent_said_is_not_source_bound() -> None:
    assert declassify("They might go to 60.", _bb(), {}) == (
        "number 60 is not source-bound",
    )


def test_a_shareable_fact_value_is_source_bound() -> None:
    shareable = {"competitor.price_usd": "60"}
    assert declassify("Brightwave quoted 60.", _bb(), shareable) == ()


def test_a_private_bound_is_denied() -> None:
    mandate = Mandate(
        mandate_id="m1",
        mandate_hash="h",
        status="granted",
        epoch=1,
        max_monthly_price_minor=7000,
        decided_by="ui",
    )
    violations = declassify("The customer accepts up to $70.", _bb(mandate=mandate), {})
    assert violations == (
        "number 70 is not source-bound",
        "the private value 70 is not public",
    )


def test_a_protected_value_is_denied_even_when_the_rep_said_it() -> None:
    pin = Fact(key="account.pin", value="12", protected=True)
    violations = declassify("PIN 12", _bb(case_facts={"account.pin": pin}), {})
    assert violations == ("the protected value of account.pin",)


def test_public_text_is_at_most_400_characters() -> None:
    assert declassify("x" * 401, _bb(), {}) == ("longer than 400 characters",)
