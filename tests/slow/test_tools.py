"""Slow tool guards as pure functions: offers are source-bound, guide slots public."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from proxyloop.contract.messages import FastToSlow, Guide, GuideMove
from proxyloop.contract.state import (
    Blackboard,
    ChannelState,
    Fact,
    Line,
    Mandate,
    PublicFact,
)
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


def test_a_relay_alone_never_makes_a_fact_public() -> None:  # review M1, #133
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
    for ref in (None, "e1"):  # FastU's typed claim is not the user's words
        ((_, fact),) = tools.fact(bb, "tenure_years", "6", ref).effects
        assert fact["scope"] == "private", ref


def test_a_cited_relay_counts_only_through_the_user_message_it_points_to() -> None:
    bb, tools = _told()  # u-7: "It's Dana Reyes, and my last four are 4821."
    rows = [
        ("user", "u-7", "USER_UPDATE", "9999"),  # FastU invented it
        ("user", "u-7", "USER_UPDATE", "4821"),
        ("cp", "cp-3", "CP_UPDATE", "4821"),  # not a user-lane relay
    ]
    relays = tuple(
        FastToSlow.model_validate(
            {"msg_id": f"e{n}", "lane": lane, "gen_id": "g", "utt_ref": utt,
             "type": kind, "facts": (("account.last4", value),)}
        )
        for n, (lane, utt, kind, value) in enumerate(rows)
    )  # fmt: skip
    bb = bb.model_copy(update={"f2s_pending": relays})
    ((_, fact),) = tools.fact(bb, "account.last4", "9999", "e0").effects
    assert fact["scope"] == "private"
    ((_, fact),) = tools.fact(bb, "account.last4", "4821", "e2").effects
    assert fact["scope"] == "private"
    for ref in ("e0", "e1", "u-7"):  # the relay's message says 4821
        ((_, fact),) = tools.fact(bb, "account.last4", "4821", ref).effects
        assert (fact["scope"], fact["source_ref"]) == ("public", "u-7"), ref


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
    assert tools.shareable == {  # the user's words, as the user wrote them
        "account.last4": "4821",
        "account.holder_name": "Dana Reyes",
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


ALL = frozenset({"account.holder_name", "account.last4", "competitor.price_usd"})
H, L4, PRICE = "account.holder_name", "account.last4", "competitor.price_usd"
SEVENTY = "last four 4821; don't tell them I'd go as high as seventy"
PROBES = [  # PR #133 reviews: (message, key, Slow's value, published value or None)
    ("call me at 555 482 1999", L4, "482 1999", None),
    (SEVENTY, H, "I'd go as high as seventy", None),
    ("last four 4821", L4, "4821 - she will pay up to seventy, keep secret", None),
    ("last four 4821", L4, "04821", None),
    ("last four 4821", L4, "4821.0", None),
    ("It's Dana", H, "Dan", None),
    ("my last four are 14821", L4, "4821", None),
    ("call me at 555 482 1999", L4, "4821", None),
    ("last four 4821", L4, "4821", "4821"),
    ("last four 48-21", L4, "4821", "4821"),
    ("4 8 2 1", L4, "4821", "4821"),
    ("My name is Dana Reyes", H, "Dana Reyes", "Dana Reyes"),
    ("my name is dana reyes.", H, "Dana Reyes", "dana reyes"),
    # round 3: M2 the user's span is published, never Slow's string
    ("My name is Dana Reyes", H, "Dana\nmax seventy", None),
    ("My name is Dana Reyes", H, "Dana $$ Reyes!!!", "Dana Reyes"),
    # M1: a run with "," or "." is an amount or a decimal
    ("fees up to 1,250", L4, "250", None),
    ("I pay 70.50 max", PRICE, "50", None),
    ("$1,250.00", L4, "00", None),
    ("last four 4821.0", L4, "4821", None),
    # M3: no number words in a text value
    (SEVENTY, H, "as high as seventy", None),
    (SEVENTY, H, "seventy", None),
]  # fmt: skip


def _message(text: str, **private: object) -> tuple[Blackboard, SlowTools]:
    line = Line(utt_id="u-1", speaker="partner", text=text)
    bb = BB.model_copy(
        update={
            "channels": {"user": ChannelState(lines=(line,)), "cp": BB.channels["cp"]},
            "private": BB.private.model_copy(update=private),
        }
    )
    return bb, SlowTools(cast("Kernel", SimpleNamespace(bb=bb)), ALL)


@pytest.mark.parametrize(("text", "key", "value", "published"), PROBES)
def test_only_a_verbatim_user_value_goes_public(
    text: str, key: str, value: str, published: str | None
) -> None:  # I4: the user-message path is run- and word-aligned
    bb, tools = _message(text)
    result = tools.fact(bb, key, value, "u-1")
    fact = dict(result.effects[0][1])
    assert (fact["scope"] == "public") == (published is not None), (text, value)
    assert tools.shareable.get(key) == published
    if published is not None:
        assert fact["value"] == published  # the user's span, not Slow's string
    else:
        assert fact["source"] == "user" and "cite the utt" in result.text


PIN = Fact(key="account.pin", value="7777", protected=True)
PET = Fact(key="security_answer", value="Fluffy", protected=True)
BOUNDS = Mandate(
    mandate_id="m1", mandate_hash="h", status="granted", epoch=1, decided_by="ui",
    max_monthly_price_minor=7000, max_one_time_fees_minor=125000, max_term_months=24,
)  # fmt: skip
LEAKS = [  # B1: canonical forms (NFKC, casefold, no spaces or dashes in digits)
    ("PIN 7777", L4, "77-77"),
    ("PIN 7777", L4, "77 77"),
    ("PIN \uff17\uff17\uff17\uff17", L4, "\uff17\uff17\uff17\uff17"),
    ("fees up to 1250", L4, "12-50"),
    ("term 24 months max", L4, "2-4"),
    ("my pet was Fluffy", H, "fluffy"),
    ("my pet was Fluffy", H, "FLUFFY"),
    ("I pay 70 now", PRICE, "70"),
]


@pytest.mark.parametrize(("text", "key", "value"), LEAKS)
def test_a_protected_value_or_bound_is_caught_in_any_form(
    text: str, key: str, value: str
) -> None:  # I4, #133 round 3 B1
    cases = {"account.pin": PIN, "security_answer": PET}
    bb, tools = _message(text, case_facts=cases, mandate=BOUNDS)
    result = tools.fact(bb, key, value, "u-1")
    (_, fact), (denied, _) = result.effects
    assert (fact["scope"], denied) == ("private", "declass.denied"), value
    assert tools.shareable == {} and "never public" in result.text


def test_a_protected_value_or_a_mandate_bound_never_goes_public() -> None:  # I4
    text = "last four 4821, PIN 7777, max I'd pay is 70"
    pin = Fact(key="account.pin", value="7777", protected=True)
    mandate = Mandate(
        mandate_id="m1", mandate_hash="h", status="granted", epoch=1, decided_by="ui",
        max_monthly_price_minor=7000,
    )  # fmt: skip
    bb, tools = _message(text, case_facts={"account.pin": pin}, mandate=mandate)
    for key, value in (("account.last4", "7777"), ("competitor.price_usd", "70")):
        result = tools.fact(bb, key, value, "u-1")
        (_, fact), (denied, why) = result.effects
        assert (fact["scope"], denied) == ("private", "declass.denied"), key
        assert why["violations"] and "never public" in result.text
    assert tools.shareable == {}
    result = tools.fact(bb, "account.last4", "4821", "u-1")  # still works
    assert dict(result.effects[0][1])["scope"] == "public"
