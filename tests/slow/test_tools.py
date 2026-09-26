"""Slow tool guards as pure functions: offers are source-bound, guide slots public."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from proxyloop.contract.messages import FastToSlow, Guide, GuideMove
from proxyloop.contract.state import Blackboard, ChannelState, Line, PublicFact
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


def test_money_and_term_values_are_plain_integers() -> None:  # R2 N3
    for value, unit in (("7.5E+3", "usd_minor"), ("12.0", "months"), ("-12", "months")):
        result = record_offer(
            BB, "loyal-1", [_slot("monthly_price", value, unit, "recurring")]
        )
        assert not result.ok, value


USER = Line(
    utt_id="u-7", speaker="partner", text="It's Dana Reyes, and my last four are 4821."
)
SAID = Line(utt_id="u-8", speaker="agent", text="Thanks, is 4822 your last four?")
KEYS = frozenset({"account.holder_name", "account.last4"})


def _told() -> tuple[Blackboard, SlowTools]:
    user = ChannelState(lines=(USER, SAID))
    bb = BB.model_copy(update={"channels": {"user": user, "cp": BB.channels["cp"]}})
    return bb, SlowTools(cast("Kernel", SimpleNamespace(bb=bb)), KEYS)


def test_a_shareable_value_the_user_said_in_the_cited_message_is_public() -> None:
    bb, tools = _told()  # ROOT-05 (a): the relay named it account_last_4
    for key, value in (
        ("account.last4", "4821"),
        ("account.holder_name", "dana reyes"),
    ):
        ((type_, fact),) = tools.fact(bb, key, value, "u-7").effects
        assert type_ == "fact.recorded"
        assert (fact["scope"], fact["source"], fact["source_ref"]) == (
            "public",
            "shareable",
            "u-7",
        )
    assert tools.shareable == {
        "account.last4": "4821",
        "account.holder_name": "dana reyes",
    }
    assert not declassify("last four 4821", bb, tools.shareable)


def test_a_value_not_in_the_cited_user_message_stays_private() -> None:
    bb, tools = _told()
    cases = [
        ("account.last4", "4822", "u-7"),  # not what the user said
        ("account.last4", "4822", "u-8"),  # the agent's line, not the user's
        ("account.last4", "4821", "cp-3"),  # a rep line without it
        ("account.last4", "4821", None),  # nothing cited
        ("account.last4", "4821", "u-99"),  # no such message
        ("plan.current_price_usd", "4821", "u-7"),  # said, but not shareable
    ]
    for key, value, ref in cases:
        result = tools.fact(bb, key, value, ref)
        ((_, fact),) = result.effects
        assert (fact["scope"], fact["source"]) == ("private", "user"), (key, ref)
        assert ("cite the utt" in result.text) == (key in KEYS)
    assert tools.shareable == {}


def _guide(bb: Blackboard, **call: object) -> tuple[bool, str, list[object]]:
    tools = SlowTools(cast("Kernel", SimpleNamespace(bb=bb)), KEYS)
    run = tools._run  # pyright: ignore[reportPrivateUsage]
    result = run("guide_fast", {"tool": "guide_fast"} | call)
    return result.ok, result.text, [p for _, p in result.effects]


def test_guide_fast_refuses_free_text_loudly() -> None:  # ROOT-05 (g)
    bb, _ = _told()
    ok, text, denied = _guide(
        bb, move="identify", text="Give them the name Dana Reyes", key=""
    )
    assert not ok and "text" in text and "ask_user" in text
    assert denied == [{"intent": "guide_fast", "reason": "guide_extra_fields"}]
    ok, _, _ = _guide(bb, move="ask_discount", slots=[], text="", value=None)
    assert ok  # an empty field carries nothing


def test_a_guide_denial_names_the_slot_and_what_is_public() -> None:  # ROOT-05 (g)
    bb, _ = _told()
    last4 = PublicFact(
        key="account.last4", value="4821", source="shareable", source_ref="u-7"
    )
    public = bb.public.model_copy(update={"facts": {"account.last4": last4}})
    bb = bb.model_copy(update={"public": public})
    slots = ["fact:account.last4", "fact:account.holder_name"]
    ok, text, denied = _guide(bb, move="identify", slots=slots)
    assert not ok
    missing, _, public_part = text.partition(";")
    assert "fact:account.holder_name" in missing and "last4" not in missing
    assert "fact:account.last4" in public_part and "record_fact" in public_part
    assert denied == [{"intent": "guide_fast", "reason": "guide_slot_not_public"}]
