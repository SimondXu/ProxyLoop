"""S1-SYS-85: a fee or credit code is named by the rep's words. Runs dd5094 and
f828f1 recorded ``fee:activation_fee`` for "an activation fee"; the lenient
read-back confirmed it, Guard authorised it, the world committed its
``fee:activation``, and verify could never bind the deal (the code is in the
terms hash). ``record_offer`` now refuses a code with a generic word or a word
the cited rep line does not say, naming the word; it never repairs one."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from proxyloop.contract.state import Blackboard, ChannelState, Line
from proxyloop.slow import offer_slots
from proxyloop.slow.offer_slots import record_offer
from proxyloop.slow.prompt import (
    _SYSTEM_TRANSCRIPT,  # pyright: ignore[reportPrivateUsage]
    SYSTEM,
)

NOW = datetime(2026, 9, 26, tzinfo=UTC)
# run dd5094, events seq 396: the rep's read-back that Slow cited (cp-17)
DD5094 = (
    "The full terms are a monthly price of 75.00 for 12 months, with an "
    "activation fee of 20.00."
)


def _bb(*texts: str) -> Blackboard:
    lines = tuple(
        Line(utt_id=f"cp-{i}", speaker="partner", text=t)
        for i, t in enumerate(texts, 1)
    )
    cp = ChannelState(lines=lines)
    return Blackboard(channels={"user": ChannelState(), "cp": cp})


def _slot(field: str, value: str, ref: str = "cp-1") -> dict[str, Any]:
    return {"field": field, "value": value, "utt_ref": ref}


DD = [_slot("monthly_price", "7500"), _slot("term_months", "12")]


def test_dd5094_a_fee_named_with_fee_is_refused_and_its_rep_name_records() -> None:
    bb = _bb(DD5094)
    bad = record_offer(bb, "offer1", [*DD, _slot("fee:activation_fee", "2000")], 0, NOW)
    assert not bad.ok and not bad.effects and bad.code == "invalid_args"
    assert (
        "fee:activation_fee: 'fee' is a generic word; name a fee by the words the "
        "rep used for it without 'fee' (e.g. a porting fee is fee:porting)"
    ) in bad.text
    good = record_offer(bb, "offer1", [*DD, _slot("fee:activation", "2000")], 0, NOW)
    assert good.ok, good.text
    ((_, payload),) = good.effects
    slots = cast(list[dict[str, str]], payload["slots"])
    assert [s["field"] for s in slots][-1] == "fee:activation"


@pytest.mark.parametrize(
    ("said", "field", "value"),
    [
        ("There is an early termination fee of 150.00.", "fee:early_termination",
         "15000"),
        # cp-hidden-fee-readback's trap: the world's fee:installation, as voiced
        ("It is 75.00 per month, plus a one-time installation fee of 99.00.",
         "fee:installation", "9900"),
        ("You also get a loyalty credit of 10.00 on your first bill.",
         "credit:loyalty", "1000"),
        ("There is a credit check fee of 20.00.", "fee:credit_check", "2000"),
    ],
)  # fmt: skip
def test_a_code_in_the_reps_words_records(said: str, field: str, value: str) -> None:
    result = record_offer(_bb(said), "o1", [_slot(field, value)], 0, NOW)
    assert result.ok, result.text


@pytest.mark.parametrize(
    ("said", "field", "why"),
    [
        (DD5094, "fee:setup", "fee:setup: 'setup' is not in the cited line cp-1"),
        ("An activation charge of 20.00 applies.", "fee:activation_charge",
         "fee:activation_charge: 'charge' is a generic word"),
        ("Activation fees of 20.00 apply.", "fee:activation_fees",
         "fee:activation_fees: 'fees' is a generic word"),
        ("There is a one-time activation fee of 20.00.", "fee:one_time",
         "fee:one_time: 'one' is a generic word"),
        ("You also get a loyalty credit of 10.00.", "credit:welcome",
         "credit:welcome: 'welcome' is not in the cited line cp-1"),
        ("You get a 10.00 credit for the activation fee.", "credit:activation_fee",
         "credit:activation_fee: 'fee' is a generic word"),
        ("You get 10.00 in loyalty credits.", "credit:loyalty_credits",
         "credit:loyalty_credits: 'credits' is a generic word"),
        ("You get a loyalty rebate of 10.00.", "credit:loyalty_rebate",
         "credit:loyalty_rebate: 'rebate' is a generic word"),
    ],
)  # fmt: skip
def test_a_code_word_generic_or_unsaid_is_refused_naming_it(
    said: str, field: str, why: str
) -> None:
    value = "1000" if field.startswith("credit:") else "2000"
    result = record_offer(_bb(said), "o1", [_slot(field, value)], 0, NOW)
    assert not result.ok and not result.effects and result.code == "invalid_args"
    assert why in result.text, result.text
    assert offer_slots.NAMED in result.text  # the rule, with the table


def test_a_credit_named_with_credit_is_refused_and_its_rep_name_records() -> None:
    """For a credit, "credit" is generic as "fee" is for a fee (L-CORE r2)."""
    bb = _bb("You also get a loyalty credit of 10.00 on your first bill.")
    bad = record_offer(bb, "o1", [_slot("credit:loyalty_credit", "1000")], 0, NOW)
    assert not bad.ok and not bad.effects and bad.code == "invalid_args"
    assert (
        "credit:loyalty_credit: 'credit' is a generic word; name a credit by the "
        "words the rep used for it without 'credit' (e.g. a paperless credit is "
        "credit:paperless)"
    ) in bad.text
    assert record_offer(bb, "o1", [_slot("credit:loyalty", "1000")], 0, NOW).ok


def test_one_bad_code_among_several_slots_refuses_the_whole_record() -> None:
    said = (
        "The full terms are 75.00 per month for 12 months, with an activation fee "
        "of 20.00 and an installation fee of 99.00."
    )
    slots = [
        *DD,
        _slot("fee:activation", "2000"),
        _slot("fee:setup_fee", "9900"),  # neither word is right
    ]
    result = record_offer(_bb(said), "o1", slots, 0, NOW)
    assert not result.ok and not result.effects and result.code == "invalid_args"
    assert "fee:setup_fee: 'setup' is not in the cited line cp-1" in result.text
    assert "fee:setup_fee: 'fee' is a generic word" in result.text
    assert "fee:activation:" not in result.text  # the good slot is not named


def test_the_code_is_checked_against_its_own_cited_line() -> None:
    bb = _bb("The activation fee is 20.00.", "The installation fee is 99.00.")
    crossed = [_slot("fee:installation", "2000", "cp-1")]
    result = record_offer(bb, "o1", crossed, 0, NOW)
    assert "'installation' is not in the cited line cp-1" in result.text
    cited = [_slot("fee:installation", "9900", "cp-2")]
    assert record_offer(bb, "o1", cited, 0, NOW).ok


def test_fees_none_is_untouched() -> None:
    bb = _bb("It is $75 a month for 12 months, with no fees.")
    slots = [*DD, _slot("fees_none", "true")]
    assert record_offer(bb, "o1", slots, 0, NOW).ok


def test_the_rule_is_in_slows_prompt_with_both_examples() -> None:
    assert offer_slots.NAMED in offer_slots.TABLE and offer_slots.NAMED in SYSTEM
    for example in ("fee:porting, never fee:porting_fee",
                    "credit:paperless, never credit:paperless_credit"):  # fmt: skip
        assert example in offer_slots.NAMED


def test_no_familys_fee_code_is_in_slows_prompt() -> None:
    """Review rev-264 D1: an example that is a family's hidden world code is
    family-specific help (rule 12); the examples are codes no family uses."""
    texts = (offer_slots.NAMED, offer_slots.TABLE, SYSTEM, _SYSTEM_TRANSCRIPT)
    for text in (*texts, *offer_slots.EXAMPLE.values()):
        assert "activation" not in text and "installation" not in text


# S1-SYS-87 D2 (review of #264): a code that differs from the world's in any
# byte can never verify (the code is in the terms hash), so a fee:/credit:
# code is strict lower snake_case and each of its words, of any length, is a
# whole word of the cited line.


@pytest.mark.parametrize(
    ("said", "field", "why"),
    [
        (DD5094, "fee:Activation",
         "fee:Activation: a code is lower snake_case (fee:activation)"),
        ("There is an early termination fee of 20.00.", "fee:early-termination",
         "fee:early-termination: a code is lower snake_case "
         "(fee:early_termination)"),
        (DD5094, "fee:activation_20",
         "fee:activation_20: '20' is not in the cited line cp-1 as a whole "
         "word; use the rep's words"),
        (DD5094, "fee:act",
         "fee:act: 'act' is not in the cited line cp-1 as a whole word; use "
         "the rep's words"),
        (DD5094, "fee:tv",
         "fee:tv: 'tv' is not in the cited line cp-1 as a whole word; use the "
         "rep's words"),
        ("A porting fee of 20.00 applies.", "fee:port",
         "fee:port: 'port' is not in the cited line cp-1 as a whole word"),
        ("Porting fees of 20.00 apply.", "fee:portings",
         "fee:portings: 'portings' is not in the cited line cp-1 as a whole"),
    ],
)  # fmt: skip
def test_d2_a_code_not_in_the_worlds_form_is_refused_naming_the_rule(
    said: str, field: str, why: str
) -> None:
    result = record_offer(_bb(said), "o1", [_slot(field, "2000")], 0, NOW)
    assert not result.ok and not result.effects and result.code == "invalid_args"
    assert why in result.text, result.text
    assert "did not name" not in result.text  # the rep did name it


TEMPLATE = (  # the Mouth's template line, as a fidelity fallback voices it
    "Here are the full terms: monthly price: 75.00; term: 12 months; fee porting: 5.00."
)


@pytest.mark.parametrize(
    ("said", "field", "value"),
    [
        (DD5094, "fee:activation", "2000"),
        ("It is 75.00 per month, plus a one-time installation fee of 99.00.",
         "fee:installation", "9900"),
        ("There is an early termination fee of 150.00.", "fee:early_termination",
         "15000"),
        ("There is an early-termination fee of 150.00.", "fee:early_termination",
         "15000"),
        (TEMPLATE, "fee:porting", "500"),
        ("An Activation Fee of 20.00 applies.", "fee:activation", "2000"),
        ("There is an upfront activation fee of 20.00.", "fee:activation", "2000"),
    ],
)  # fmt: skip
def test_d2_the_worlds_form_in_the_reps_words_records(
    said: str, field: str, value: str
) -> None:
    result = record_offer(_bb(said), "o1", [_slot(field, value)], 0, NOW)
    assert result.ok, result.text


# S1-SYS-87 D3 (root option (a)): a line that names the fee only by generic
# words refuses every code; the refusal says so instead of implying words.


def _unnamed(kind: str, ref: str = "o1") -> str:
    return (
        f"the rep did not name this {kind} (only generic words): record_offer "
        f'the other slots, then guide_fast(ask_readback, ["offer:{ref}"]) once '
        f"more; a {kind} must be named by the rep to be recorded"
    )


@pytest.mark.parametrize(
    ("said", "field"),
    [
        ("There is an upfront fee of 20.00.", "fee:upfront"),
        ("There is an upfront fee of 20.00.", "fee:setup"),
        ("There is a one-time charge of 20.00.", "fee:one_time"),
        ("There is a one-time fee of 20.00.", "fee:activation"),
        ("It is 75.00 per month, plus an upfront fee of 20.00.", "fee:monthly"),
        ("There is a credit of 20.00 on your first bill.", "credit:welcome"),
    ],
)  # fmt: skip
def test_d3_a_fee_named_only_by_generic_words_says_so(said: str, field: str) -> None:
    kind = field.partition(":")[0]
    result = record_offer(_bb(said), "o1", [_slot(field, "2000")], 0, NOW)
    assert not result.ok and not result.effects and result.code == "invalid_args"
    assert f"{field}: {_unnamed(kind)}" in result.text, result.text
    assert "use the rep's words" not in result.text  # no words to use
    assert "a generic word; name a" not in result.text


def test_d3_names_the_offer_ref_it_records() -> None:
    bb = _bb("There is an upfront fee of 20.00.")
    result = record_offer(bb, "promo-1", [_slot("fee:upfront", "2000")], 0, NOW)
    assert _unnamed("fee", "promo-1") in result.text, result.text


def test_d3_a_line_with_a_generic_and_a_naming_word_records_the_naming_word() -> None:
    bb = _bb("There is an upfront activation fee of 20.00.")
    bad = record_offer(bb, "o1", [_slot("fee:upfront", "2000")], 0, NOW)
    assert "fee:upfront: 'upfront' is a generic word" in bad.text, bad.text
    assert "did not name" not in bad.text
    assert record_offer(bb, "o1", [_slot("fee:activation", "2000")], 0, NOW).ok


def test_d3_the_template_names_its_fee_after_the_fee_word() -> None:
    """The Mouth voices "fee porting: 5.00": the name follows the fee word, so
    a wrong code on that line gets the word refusal, never "not named"."""
    result = record_offer(_bb(TEMPLATE), "o1", [_slot("fee:setup", "500")], 0, NOW)
    assert not result.ok
    assert "fee:setup: 'setup' is not in the cited line cp-1" in result.text
    assert "did not name" not in result.text, result.text


def test_d3_reads_the_clause_that_states_the_fee() -> None:
    """Another fee's name elsewhere in the line does not name this one."""
    said = "There is an activation fee of 20.00, and an upfront fee of 10.00."
    bb = _bb(said)
    result = record_offer(bb, "o1", [_slot("fee:upfront", "1000")], 0, NOW)
    assert _unnamed("fee") in result.text, result.text
    named = record_offer(bb, "o1", [_slot("fee:setup", "2000")], 0, NOW)
    assert "'setup' is not in the cited line" in named.text, named.text
