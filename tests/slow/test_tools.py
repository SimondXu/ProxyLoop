"""Slow tool guards as pure functions: offers are source-bound, guide slots public."""

from __future__ import annotations

from proxyloop.contract.messages import Guide, GuideMove
from proxyloop.contract.state import Blackboard, ChannelState, Line
from proxyloop.slow.tools import public_guide, record_offer

REP = Line(
    utt_id="cp-3", speaker="partner", text="I can do 75.00 a month for 12 months."
)
BB = Blackboard(channels={"user": ChannelState(), "cp": ChannelState(lines=(REP,))})


def _slot(field: str, value: str, unit: str, role: str) -> dict[str, object]:
    return {
        "field": field,
        "value": value,
        "unit": unit,
        "role": role,
        "utt_ref": "cp-3",
    }


def test_an_offer_the_rep_said_is_recorded() -> None:
    price = _slot("monthly_price", "7500", "usd_minor", "recurring")
    result = record_offer(
        BB, "loyal-1", [price, _slot("term_months", "12", "months", "recurring")]
    )
    assert result.ok
    ((type_, payload),) = result.effects
    assert type_ == "offer.recorded" and payload["revision"] == 1


def test_an_offer_value_the_rep_never_said_is_denied() -> None:
    result = record_offer(
        BB, "loyal-1", [_slot("monthly_price", "7000", "usd_minor", "recurring")]
    )
    assert not result.ok
    assert [t for t, _ in result.effects] == ["declass.denied"]


def test_a_guide_slot_must_resolve_in_public_state() -> None:
    assert public_guide(BB, Guide(move=GuideMove.ASK_DISCOUNT))
    fact = Guide(move=GuideMove.CITE_COMPETITOR, slots=("fact:competitor.price_usd",))
    assert not public_guide(BB, fact)
