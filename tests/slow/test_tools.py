"""Slow tool guards as pure functions: offers are source-bound, guide slots public."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.messages import FastToSlow, Guide, GuideMove
from proxyloop.contract.protocol import render_messages
from proxyloop.contract.state import (
    Blackboard,
    ChannelState,
    Fact,
    Line,
    Mandate,
    PublicFact,
)
from proxyloop.contract.views import Trigger, view_cp, view_slow
from proxyloop.guard.declass import declassify
from proxyloop.slow.prompt import status_bar
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
        assert ("citing the utt" in result.text) == (key in KEYS)
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


ALL = frozenset(
    """account.holder_name account.last4 competitor.price_usd competitor.name
    tenure_years""".split()  # noqa: SIM905
)
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
    ("my last four are 4821.", L4, "4821", "4821"),  # a sentence's full stop
    ("4821, and my name is Dana", L4, "4821", "4821"),
    ("My name is Dana Reyes", H, "Dana Reyes", "Dana Reyes"),
    ("my name is dana reyes.", H, "Dana Reyes", "dana reyes"),
    ("It's Mary O'Brien-Lee", H, "mary o'brien-lee", "Mary O'Brien-Lee"),
    ("I\u2019m Mary O\u2019Brien", H, "mary o\u2019brien", "Mary O\u2019Brien"),
    # round 4: the narrow path; accepted false-privates
    ("last four 48-21", L4, "4821", None),
    ("4 8 2 1", L4, "4821", None),
    ("I've been with you 6 years", "tenure_years", "6", None),
    ("Brightwave charges 60", PRICE, "60", None),
    ("they quoted me at Brightwave", "competitor.name", "Brightwave", None),
    # round 3: M2 Slow's string must be the user's own
    ("My name is Dana Reyes", H, "Dana\nmax seventy", None),
    ("My name is Dana Reyes", H, "Dana $$ Reyes!!!", None),
    # M1: amounts and decimals
    ("fees up to 1,250", L4, "250", None),
    ("I pay 70.50 max", PRICE, "50", None),
    ("$1,250.00", L4, "00", None),
    ("last four 4821.0", L4, "4821", None),
    ("last four 1.4821", L4, "4821", None),
    ("last four 1,4821", L4, "4821", None),
    # M3: number words
    (SEVENTY, H, "as high as seventy", None),
    (SEVENTY, H, "seventy", None),
    ("call me Twenty-One", H, "Twenty-One", None),
    # round 3 B1 digit forms: not four plain ASCII digits
    ("PIN 7777", L4, "77-77", None),
    ("PIN 7777", L4, "77 77", None),
    ("PIN \uff17\uff17\uff17\uff17", L4, "\uff17\uff17\uff17\uff17", None),
    ("last four \uff14\uff18\uff12\uff11", L4, "4821", None),
    ("fees up to 1250", L4, "12-50", None),
    ("term 24 months max", L4, "2-4", None),
    ("I pay 70 now", PRICE, "70", None),
    # round 4: no token boundary, other scripts, confusables
    ("account AC4821993", L4, "4821", None),
    ("ref 4821abc", L4, "4821", None),
    ("balance -4821", L4, "4821", None),
    ("card 4821/1999", L4, "4821", None),
    ("card 1999/4821", L4, "4821", None),
    ("expires 12/27", L4, "1227", None),
    ("last four 48\u201321", L4, "4821", None),
    ("last four 48  21", L4, "4821", None),
    ("last four 4821_", L4, "4821", None),
    ("last four #4821", L4, "4821", None),
    ("last four +4821", L4, "4821", None),
    ("last four '4821'", L4, "4821", None),
    ("\u56db\u516b\u4e8c\u4e00", L4, "\u56db\u516b\u4e8c\u4e00", None),
    ("My name is D\u0430na", H, "D\u0430na", None),  # Cyrillic a
    ("My name is Dana", H, "D\u0430na", None),
    ("I am Dana \uff17\uff10", H, "Dana \uff17\uff10", None),
    ("Dana Reyes Smith Jones Brown", H, "Dana Reyes Smith Jones Brown", None),
    ("My name is Dana  Reyes", H, "Dana  Reyes", None),
    ("My name is Dana_Reyes", H, "Dana", None),
    ("My name is Dana-Reyes", H, "Dana", None),
    # round 5 M1: allow-listed boundaries only
    ("call 555\u2013482\u20131999", L4, "1999", None),
    ("acct 12\u200b4821", L4, "4821", None),
    ("call 555\u2011482\u20111999", L4, "1999", None),
    ("balance \u22124821", L4, "4821", None),
    ("mail 4821@x.com", L4, "4821", None),
    ("I owe $4821", L4, "4821", None),
    ("last four: 4821", L4, "4821", "4821"),
    ("last four (4821)", L4, "4821", "4821"),
    ("last four \u201c4821\u201d", L4, "4821", "4821"),
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
        assert fact["source"] == "user" and "citing the utt" in result.text


PROTECTED = {
    key: Fact(key=key, value=value, protected=True)
    for key, value in {
        "account.pin": "7777",
        "security_answer": "Fluffy",
        "mother.maiden_name": "O'Brien",
        "security.street": "Lee-Smith",
        "security.city": "St. John",
        "account.phone": "(555) 482-1999",
    }.items()
}
BOUNDS = Mandate(
    mandate_id="m1", mandate_hash="h", status="granted", epoch=1, decided_by="ui",
    max_monthly_price_minor=7000, max_one_time_fees_minor=125000, max_term_months=24,
)  # fmt: skip
LEAKS = [  # values the narrow path accepts, then the leak check refuses
    ("PIN 7777", L4, "7777"),
    ("my pet was Fluffy", H, "fluffy"),
    ("my pet was Fluffy", H, "FLUFFY"),
    ("I'm Fluffy Reyes", H, "Fluffy Reyes"),
    ("maiden name O Brien", H, "O Brien"),
    ("maiden name O'Brien", H, "O'Brien"),
    ("I'm Lee Smith", H, "Lee Smith"),
    ("from St John", H, "St John"),
    ("phone ends 1999", L4, "1999"),
    ("last four 4821", L4, "4821"),  # inside the protected phone number
    ("fees up to 1250", L4, "1250"),
    ("code 0070", L4, "0070"),  # $70 with leading zeros
    ("code 7000", L4, "7000"),  # $70 in minor units
    ("code 0024", L4, "0024"),  # 24 months
    # round 5 B1: protected names typed without their separators
    ("maiden name Obrien", H, "Obrien"),
    ("I'm LeeSmith", H, "LeeSmith"),
    ("from StJohn", H, "StJohn"),
]


@pytest.mark.parametrize(("text", "key", "value"), LEAKS)
def test_a_protected_value_or_bound_is_caught_in_any_form(
    text: str, key: str, value: str
) -> None:  # I4, #133 round 3 B1
    bb, tools = _message(text, case_facts=PROTECTED, mandate=BOUNDS)
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
    for key, value in (("account.last4", "7777"),):
        result = tools.fact(bb, key, value, "u-1")
        (_, fact), (denied, why) = result.effects
        assert (fact["scope"], denied) == ("private", "declass.denied"), key
        assert why["violations"] and "never public" in result.text
    assert tools.shareable == {}
    result = tools.fact(bb, "account.last4", "4821", "u-1")  # still works
    assert dict(result.effects[0][1])["scope"] == "public"


def test_a_protected_value_in_other_decimal_digits_is_caught() -> None:  # round 5 B2
    pin = Fact(key="account.pin", value="\u0667\u0667\u0667\u0667", protected=True)
    bb, tools = _message("PIN 7777", case_facts={"account.pin": pin})
    result = tools.fact(bb, L4, "7777", "u-1")
    (_, fact), (denied, _) = result.effects
    assert (fact["scope"], denied) == ("private", "declass.denied")


IDENTIFY = "guide_fast(identify, slots=[fact:account.holder_name, fact:account.last4])"


def _public(bb: Blackboard, *keys: str) -> Blackboard:
    values = {"account.holder_name": "Dana Reyes", "account.last4": "4821"}
    facts = {
        k: PublicFact(key=k, value=values[k], source="shareable", source_ref="u-7")
        for k in keys
    }
    return bb.model_copy(
        update={"public": bb.public.model_copy(update={"facts": facts})}
    )


def test_a_deflect_is_sent_and_says_how_to_hold_for_a_fact_instead() -> None:
    bb, _ = _told()  # S0-SYS-07 (run aeab91): deflect while waiting for the user
    ok, text, sent = _guide(bb, move="deflect_fact_request")
    assert ok and len(sent) == 1  # sent as asked: Slow decides, never refused
    assert "refus" in text and "hold_for_decision" in text and "ask_user" in text
    ok, text, _ = _guide(_public(bb, H, L4), move="deflect_fact_request")
    assert ok and IDENTIFY in text


def test_the_status_bar_tells_slow_how_to_give_or_get_identity_facts() -> None:
    bb, _ = _told()
    bar = status_bar(view_slow(bb, SlowViewMode.RELAY_ONLY, "b"), KEYS)
    assert "account.holder_name, account.last4 not given yet" in bar
    assert "ask_user" in bar and "hold_for_decision" in bar and "identify" not in bar
    half = status_bar(view_slow(_public(bb, L4), SlowViewMode.RELAY_ONLY, "b"), KEYS)
    assert "guide_fast(identify, slots=[fact:account.last4])" in half
    assert "account.holder_name not given yet" in half
    both = _public(bb, H, L4)
    bar = status_bar(view_slow(both, SlowViewMode.RELAY_ONLY, "b"), KEYS)
    assert IDENTIFY in bar and "not given yet" not in bar
    guide = Guide(move=GuideMove.IDENTIFY, slots=(f"fact:{H}", f"fact:{L4}"))
    assert public_guide(both, guide) and not public_guide(_public(bb, L4), guide)
    other = status_bar(view_slow(bb, SlowViewMode.RELAY_ONLY, "b"), frozenset({PRICE}))
    assert "identity" not in other  # no identity key, no hint


def test_a_hold_for_decision_renders_as_checking_with_the_customer() -> None:
    guide = Guide(move=GuideMove.HOLD_FOR_DECISION)
    public = BB.public.model_copy(update={"guidance_cp": (guide,)})
    view = view_cp(
        BB.model_copy(update={"public": public}), Trigger(kind="guidance"), ""
    )
    rendered = "".join(m.content for m in render_messages(view, "pl_cp_v1"))
    assert "check with your customer (@hold decision)" in rendered
