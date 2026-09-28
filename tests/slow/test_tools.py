"""Slow tool guards as pure functions: offers are source-bound, guide slots public."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Literal, cast

import pytest

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
from proxyloop.contract.views import Trigger, view_cp
from proxyloop.guard.declass import declassify
from proxyloop.slow.offer_slots import record_offer
from proxyloop.slow.tools import SlowTools, case_ref, public_guide

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

REP = Line(
    utt_id="cp-3", speaker="partner", text="I can do 75.00 a month for 12 months."
)
BB = Blackboard(channels={"user": ChannelState(), "cp": ChannelState(lines=(REP,))})
NOW = datetime(2026, 9, 26, tzinfo=UTC)
CASE = case_ref("case-1")


def _slot(field: str, value: str) -> dict[str, object]:  # role, unit: derived
    return {"field": field, "value": value, "utt_ref": "cp-3"}


def test_an_offer_the_rep_said_is_recorded() -> None:
    price = _slot("monthly_price", "7500")
    result = record_offer(
        BB,
        "loyal-1",
        [price, _slot("term_months", "12")],
        0,
        NOW,
    )
    assert result.ok
    ((type_, payload),) = result.effects
    assert type_ == "offer.recorded" and payload["revision"] == 1


def test_an_offer_value_the_rep_never_said_is_denied() -> None:
    result = record_offer(
        BB,
        "loyal-1",
        [_slot("monthly_price", "7000")],
        0,
        NOW,
    )
    assert not result.ok
    assert [t for t, _ in result.effects] == ["declass.denied"]


def test_a_guide_slot_must_resolve_in_public_state() -> None:
    assert public_guide(BB, Guide(move=GuideMove.ASK_DISCOUNT))
    fact = Guide(move=GuideMove.CITE_COMPETITOR, slots=("fact:competitor.price_usd",))
    assert not public_guide(BB, fact)


def test_every_offer_slot_is_bound_to_a_cited_rep_line() -> None:  # review B1
    cases = [
        _slot("feature:x", "user pays 85"),  # a number, any unit
        _slot("term_months", "12") | {"utt_ref": "nope"},
        _slot("monthly_price", "1200"),  # "12 months"
    ]
    for slot in cases:
        result = record_offer(BB, "loyal-1", [slot], 0, NOW)
        assert not result.ok, slot
        assert [t for t, _ in result.effects] == ["declass.denied"]


def test_a_relay_alone_never_makes_a_fact_public() -> None:  # review M1, #133
    note = FastToSlow(
        msg_id="e1", lane="user", gen_id="g", utt_ref=None, type="NOTE",
        text="I pay 85 a month now",
    )  # fmt: skip
    bb = BB.model_copy(update={"f2s_pending": (note,)})
    tools = SlowTools(
        cast("Kernel", SimpleNamespace(bb=bb)), frozenset({"tenure_years"}), CASE
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
    for field, value in (
        ("monthly_price", "7.5E+3"),
        ("term_months", "12.0"),
        ("term_months", "-12"),
    ):
        result = record_offer(BB, "loyal-1", [_slot(field, value)], 0, NOW)
        assert not result.ok, value


USER = Line(
    utt_id="u-7", speaker="partner", text="It's Dana Reyes, and my last four are 4821."
)
SAID = Line(utt_id="u-8", speaker="agent", text="Thanks, is 4822 your last four?")
KEYS = frozenset({"account.holder_name", "account.last4"})


def _told() -> tuple[Blackboard, SlowTools]:
    user = ChannelState(lines=(USER, SAID))
    bb = BB.model_copy(update={"channels": {"user": user, "cp": BB.channels["cp"]}})
    return bb, SlowTools(cast("Kernel", SimpleNamespace(bb=bb)), KEYS, CASE)


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
    tools = SlowTools(cast("Kernel", SimpleNamespace(bb=bb)), KEYS, CASE)
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
    # S1-SYS-15 relabel: tenure in an allow-listed context ("been with you")
    ("I've been with you 6 years", "tenure_years", "6", "6"),
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
    return bb, SlowTools(cast("Kernel", SimpleNamespace(bb=bb)), ALL, CASE)


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


# S1-SYS-15: the per-key formats of the user-message path (message, key, value,
# published value or None), run with a public competitor.name (#153 round 3:
# competitor facts never go public from a user message; tenure only in context)
TENURE, NAME = "tenure_years", "competitor.name"
Source = Literal["cp_utt", "shareable"]
FORMATS = [
    ("I've been with you for 6 years", TENURE, "6", "6"),
    ("I've been with you 6 years", TENURE, "6", "6"),
    ("I have been a customer for 12 years", TENURE, "12", "12"),
    ("I've been a customer for 12 Years now.", TENURE, "12", "12"),
    ("I've been with you for 1 year", TENURE, "1", "1"),
    ("I've been with you for 06 years", TENURE, "06", "06"),  # as written
    # round 4: first person only, and never with a negation
    ("been a customer for 12 Years now.", TENURE, "12", None),
    ("We have been with you for 1 year", TENURE, "1", None),
    ("my wife has been a customer for 20 years", TENURE, "20", None),
    ("I have never been a customer for 3 years", TENURE, "3", None),
    ("I haven't been with you for 6 years", TENURE, "6", None),
    ("I haven\u2019t been with you for 6 years", TENURE, "6", None),
    ("we've been with you for 6 years", TENURE, "6", None),
    ("been with you for 6 years", TENURE, "6", None),
    ("I've been with you for 6 years? not really", TENURE, "6", None),
    ("I've been with you for 6 years, isn't that enough", TENURE, "6", None),
    ("AI've been with you for 6 years", TENURE, "6", None),
    ("I ve been with you for 6 years", TENURE, "6", None),
    ("I`ve been with you for 6 years", TENURE, "6", None),
    # #153 round 3: tenure outside its context, or next to an age word
    ("I'm 36 years old", TENURE, "36", None),
    ("I am 36 years of age", TENURE, "36", None),
    ("my kid is 12 years", TENURE, "12", None),
    ("my contract is 2 years", TENURE, "2", None),
    ("I moved here 6 years ago", TENURE, "6", None),
    ("6 years", TENURE, "6", None),
    ("I've been with you for 6 years, I'm 36 years old", TENURE, "6", None),
    ("been with you for 6 years since I was 20, aged 26", TENURE, "6", None),
    ("I'll stay with you for 2 years", TENURE, "2", None),
    ("customer for 2 years if the price is right", TENURE, "2", None),
    ("2 years with you max", TENURE, "2", None),
    ("I've been with you for 6 years", TENURE, "36", None),
    ("I've been with you for 36 years", TENURE, "6", None),
    ("I've been with you for 1.6 years", TENURE, "6", None),
    ("I've been with you for 6.5 years", TENURE, "6", None),
    ("I've been with you for 100 years", TENURE, "100", None),
    ("I've been with you for 6 years", TENURE, "06", None),
    ("I've been with you for 6 years", TENURE, "6 years", None),
    ("I've been with you for 6years", TENURE, "6", None),
    ("I've been with you for 6  years", TENURE, "6", None),
    ("I've been with you for 6\u00a0years", TENURE, "6", None),
    ("I've been with you for 6 yearsx", TENURE, "6", None),
    ("I've been with you for 6 year-old", TENURE, "6", None),
    ("I've been with you for 6 yea\u0280s", TENURE, "6", None),
    ("I've been with you for 6 year\u017f", TENURE, "6", None),
    ("I've been with you for \uff16 years", TENURE, "\uff16", None),
    ("I've been with you for \uff16 years", TENURE, "6", None),
    ("I've been with you for \u0666 years", TENURE, "6", None),
    ("I've been with you for six years", TENURE, "six", None),
    ("I've been with you for 36 years \u043eld", TENURE, "36", None),
    ("I've been with you for 36 years, \u0430ged 36", TENURE, "36", None),
    ("I\u2019ve been with you for 6 years", TENURE, "6", "6"),
    ("I've BEEN WITH YOU FOR 6 YEARS", TENURE, "6", None),
    ("I've been with you for 6 years-old", TENURE, "6", None),
    ("I've been with youfor 6 years", TENURE, "6", None),
    ("I've been with you for 6 lines", TENURE, "6", None),
    # S1-SYS-20: the first person starts the message or a sentence
    ("She said I've been with you for 6 years", TENURE, "6", None),
    ("my wife says I've been with you for 6 years", TENURE, "6", None),
    ("I've been with you for 6 years.", TENURE, "6", "6"),
    ("Thanks. I've been with you for 6 years", TENURE, "6", "6"),
    ("Thanks!  I've been with you for 6 years", TENURE, "6", "6"),
    # #153 round 3: competitor facts stay private, whatever the message says
    ("Brightwave charges 60", PRICE, "60", None),
    ("Brightwave charges $60.", PRICE, "60", None),
    ("Brightwave is fine but I won't pay more than 65", PRICE, "65", None),
    ("I pay 85 now, Brightwave is way cheaper", PRICE, "85", None),
    ("I pay 85", PRICE, "85", None),
    ("Brightwave charges 60, I pay a grand a year", PRICE, "60", None),
    ("they quoted me at Brightwave", NAME, "Brightwave", None),
    ("Northwind Mobile raised my bill again", NAME, "Northwind Mobile", None),
    ("My name is Dana Reyes", NAME, "Dana Reyes", None),
    ("I pay 85", NAME, "I", None),
    ("max I'd pay is 70", NAME, "max", None),
    # N1: plural number words are never a name
    ("I'm in my sixties", H, "sixties", None),
    ("in my twenties", H, "twenties", None),
    ("Dana Sixties", H, "Dana Sixties", None),
    ("hundreds", H, "hundreds", None),
    ("thousands", H, "Thousands", None),
    ("tens of dollars", H, "tens", None),
    ("sixes and sevens", H, "sixes", None),
]  # fmt: skip


def _named(
    text: str, source: Source | None = "shareable", **private: object
) -> Blackboard:
    bb, _ = _message(text, **private)
    facts: dict[str, PublicFact] = {}
    if source is not None:
        name = "Brightwave"
        facts[NAME] = PublicFact(key=NAME, value=name, source=source, source_ref="u-0")
    return bb.model_copy(
        update={"public": bb.public.model_copy(update={"facts": facts})}
    )


def _tools(bb: Blackboard, keys: frozenset[str] = ALL) -> SlowTools:
    return SlowTools(cast("Kernel", SimpleNamespace(bb=bb)), keys, CASE)


@pytest.mark.parametrize(("text", "key", "value", "published"), FORMATS)
def test_a_value_goes_public_only_in_its_keys_format(
    text: str, key: str, value: str, published: str | None
) -> None:  # I4: the user's exact span, in the key's declared format
    bb = _named(text)
    tools = _tools(bb)
    result = tools.fact(bb, key, value, "u-1")
    fact = dict(result.effects[0][1])
    assert (fact["scope"] == "public") == (published is not None), (text, value)
    assert tools.shareable.get(key) == published
    if published is not None:
        assert (fact["value"], fact["source_ref"]) == (published, "u-1")
    else:
        assert fact["source"] == "user" and "citing the utt" in result.text


def test_a_shareable_key_without_a_format_never_goes_public() -> None:  # I4
    keys = ALL | {"card.last4", "account.zip", "plan.current_price_usd"}
    for text, key, value in (
        ("card last four 4821", "card.last4", "4821"),  # public by suffix in S0
        ("my zip is 94110", "account.zip", "94110"),
        ("I pay 85 now", "plan.current_price_usd", "85"),
        ("they quoted me at Brightwave", NAME, "Brightwave"),
        ("Brightwave charges 60", PRICE, "60"),
    ):
        bb = _named(text)
        tools = _tools(bb, keys)
        result = tools.fact(bb, key, value, "u-1")
        assert dict(result.effects[0][1])["scope"] == "private", key
        assert tools.shareable == {} and "citing the utt" in result.text
        assert "competitor" not in result.text  # the hint names no such rule


@pytest.mark.parametrize(
    ("text", "key", "value"),
    [
        ("I've been with you for 24 years", TENURE, "24"),  # 24 months
        ("code 0070", L4, "0070"),  # $70
        ("my pet was Fluffy", H, "Fluffy"),  # protected
    ],
)
def test_the_leak_checks_apply_to_every_format(
    text: str, key: str, value: str
) -> None:  # I4: protected values and mandate bounds
    bb = _named(text, case_facts=PROTECTED, mandate=BOUNDS)
    tools = _tools(bb)
    result = tools.fact(bb, key, value, "u-1")
    (_, fact), (denied, _) = result.effects
    assert (fact["scope"], denied) == ("private", "declass.denied"), value
    assert tools.shareable == {} and "never public" in result.text


def _with(bb: Blackboard, *facts: PublicFact) -> Blackboard:
    public = bb.public.model_copy(update={"facts": {f.key: f for f in facts}})
    return bb.model_copy(update={"public": public})


def test_cite_competitor_needs_a_shareable_competitor_quote() -> None:  # I11
    bb = _named("they quoted me at Brightwave, it's 60 a month")  # name public
    tools = _tools(bb)
    for key, value in ((NAME, "Brightwave"), (PRICE, "60")):  # never from the user
        assert dict(tools.fact(bb, key, value, "u-1").effects[0][1])["scope"] == (
            "private"
        )
    name = bb.public.facts[NAME]
    for slots in ([f"fact:{NAME}"], [f"fact:{NAME}", f"fact:{PRICE}"], []):
        ok, text, denied = _guide(bb, move="cite_competitor", slots=slots)
        assert not ok and "no fabricated quotes" in text, slots  # a name alone
        assert denied == [
            {"intent": "guide_fast", "reason": "competitor_quote_not_shareable"}
        ]
    said = PublicFact(key=PRICE, value="60", source="cp_utt", source_ref="cp-3")
    ok, _, _ = _guide(_with(bb, name, said), move="cite_competitor",
                      slots=[f"fact:{PRICE}"])  # fmt: skip
    assert not ok  # the rep's word is no quote the user shared
    quote = said.model_copy(update={"source": "shareable", "source_ref": "u-0"})
    ok, text, sent = _guide(
        _with(bb, name, quote), move="cite_competitor", slots=[f"fact:{PRICE}"]
    )
    assert ok and len(sent) == 1, text


def _public(bb: Blackboard, *keys: str) -> Blackboard:
    values = {"account.holder_name": "Dana Reyes", "account.last4": "4821"}
    facts = {
        k: PublicFact(key=k, value=values[k], source="shareable", source_ref="u-7")
        for k in keys
    }
    return bb.model_copy(
        update={"public": bb.public.model_copy(update={"facts": facts})}
    )


def test_a_deflect_is_sent_and_says_the_rep_hears_a_refusal() -> None:
    bb, _ = _told()  # S0-SYS-07 (run aeab91): deflect while waiting for the user
    ok, text, sent = _guide(bb, move="deflect_fact_request")
    assert ok and len(sent) == 1  # sent as asked: Slow decides, never refused
    assert text == "sent s2f-1; the rep hears a refusal to share"  # F-b: no hint


def test_identify_is_public_only_once_both_identity_facts_are() -> None:
    """The readiness line replaced the identity hint (ADR-0018 F-b); Guard's
    renderer still judges the identify guide."""
    bb, _ = _told()
    guide = Guide(move=GuideMove.IDENTIFY, slots=(f"fact:{H}", f"fact:{L4}"))
    assert public_guide(_public(bb, H, L4), guide)
    assert not public_guide(_public(bb, L4), guide)


@pytest.mark.parametrize("slots", [[], None, ["offer:save-2.monthly_price"]])
def test_an_identify_with_no_fact_slot_is_refused_and_nothing_is_sent(
    slots: list[str] | None,
) -> None:
    """S1-SYS-74 D1: the renderer accepts identify with no slot and FastC
    would be told to identify with nothing: refused, with what to do instead."""
    bb = _public(_told()[0], H, L4)  # identity facts public: still refused
    tools = SlowTools(cast("Kernel", SimpleNamespace(bb=bb)), KEYS, CASE)
    call: dict[str, object] = {"tool": "guide_fast", "move": "identify"}
    call |= {} if slots is None else {"slots": slots}
    result = tools._run("guide_fast", call)  # pyright: ignore[reportPrivateUsage]
    assert not result.ok and not tools.guides
    assert result.effects == (
        ("action.denied", {"intent": "guide_fast", "reason": "identify_without_facts"}),
    )
    assert "ask_user" in result.text and "hold_for_fact" in result.text
    ok, _, sent = _guide(bb, move="identify", slots=[f"fact:{H}", f"fact:{L4}"])
    assert ok and len(sent) == 1  # with its facts: sent


def test_a_hold_for_fact_is_a_public_guide() -> None:
    """The cp profile Slow judges with (pl_cp_v2, ADR-0011) renders the move."""
    assert public_guide(BB, Guide(move=GuideMove.HOLD_FOR_FACT))


def test_a_hold_for_decision_renders_as_checking_with_the_customer() -> None:
    guide = Guide(move=GuideMove.HOLD_FOR_DECISION)
    public = BB.public.model_copy(update={"guidance_cp": (guide,)})
    view = view_cp(
        BB.model_copy(update={"public": public}), Trigger(kind="guidance"), ""
    )
    rendered = "".join(m.content for m in render_messages(view, "pl_cp_v2"))
    assert "check with your customer (@hold decision)" in rendered
