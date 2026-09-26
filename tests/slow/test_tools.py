"""Slow tool guards as pure functions: offers are source-bound, guide slots public."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from proxyloop.contract.messages import FastToSlow, Guide, GuideMove
from proxyloop.contract.state import Blackboard, ChannelState, Line
from proxyloop.guard.declass import declassify
from proxyloop.slow.tools import SlowTools, public_guide, record_offer

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

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


def test_every_offer_slot_is_bound_to_a_cited_rep_line() -> None:  # review B1
    cases = [
        _slot("feature:x", "user pays 85", "bool", "feature"),  # a number, any unit
        _slot("term_months", "12", "months", "recurring") | {"utt_ref": "nope"},
        _slot("monthly_price", "1200", "usd_minor", "recurring"),  # "12 months"
    ]
    for slot in cases:
        result = record_offer(BB, "loyal-1", [slot])
        assert not result.ok, slot
        assert [t for t, _ in result.effects] == ["declass.denied"]


def test_a_shareable_fact_needs_a_typed_user_relay() -> None:  # review M1
    note = FastToSlow(
        msg_id="e1", lane="user", gen_id="g", utt_ref=None, type="NOTE",
        text="I pay 85 a month now",
    )  # fmt: skip
    bb = BB.model_copy(update={"f2s_pending": (note,)})
    tools = SlowTools(
        cast("Kernel", SimpleNamespace(bb=bb)), frozenset({"tenure_years"})
    )
    ((_, fact),) = tools.fact(bb, "tenure_years", "85", None).effects
    assert fact["scope"] == "private"
    assert declassify("current price 85", bb, tools.shareable)
    typed = note.model_copy(
        update={"facts": (("tenure_years", "6"),), "type": "USER_UPDATE"}
    )
    bb = BB.model_copy(update={"f2s_pending": (typed,)})
    ((_, fact),) = tools.fact(bb, "tenure_years", "6", None).effects
    assert (fact["scope"], fact["source_ref"]) == ("public", "e1")
