"""The "none" read-back slots (fees_none, changes_none, expires=none) are read
by negation scope over closed word classes (guard/negation.py), per sentence.

Positives are the sim rep's M3 read-back lines (runs/m3-3d90a32) that the old
phrase lists missed, each id naming its run. Negatives fail closed: a false
"no fees" confirmation is the hidden-fee hazard."""

from __future__ import annotations

import pytest
from tests.guard.build import rep, slot

from proxyloop.contract.state import ReadbackSlot
from proxyloop.guard.negation import denied
from proxyloop.guard.readback import said, slot_status

FEES = slot("fees_none", "true", "bool", "one_time")
CHANGES = slot("changes_none", "true", "bool", "change")
NO_EXPIRY = slot("expires", "none", "iso", "expiry")
MAY_3 = slot("expires", "2027-05-03T00:00:00Z", "iso", "expiry")
SLOTS = {"fees_none": FEES, "changes_none": CHANGES, "expires": NO_EXPIRY}


def _confirms(s: ReadbackSlot, text: str) -> bool:
    """One rep line, after the read-back request, confirms ``s``."""
    return slot_status(s, [rep("c1", text)], asked_at=0) == "confirmed"


M3 = [  # (run id, fields the line confirms, the rep's line)
    ("fe1291", "changes_none", "The offer is 73.00 a month for 12 months with no "
     "fees, no service changes, and no expiry."),
    ("20cbc6", "changes_none expires", "The offer is 73.00 a month for 12 months "
     "with no extra fees or service changes. It also doesn't have an expiration "
     "date!"),
    ("a6bc6f", "changes_none expires", "It\u2019s just 55.00 a month with a 12-month "
     "term and a 99.00 installation fee. There are no other service changes, and "
     "this offer has no expiry date!"),
    ("81722f", "changes_none expires", "Here are the full terms: the monthly price "
     "is 69.00 for a 24-month term with no fees. There are no service changes and "
     "no expiry date."),
    ("f480ee", "changes_none expires", "It's 55.00 a month on a 12-month term with "
     "an installation fee of 99.00, and there's no expiration or any other changes!"),
    ("664735", "fees_none changes_none expires", "The monthly price is 69.00 on a "
     "24-month term with no added fees. There are no other account changes, and the "
     "offer has no expiration date."),
    ("664735", "changes_none expires", "The offer is 69.00 per month for a term of "
     "24 months, with no fees, no account changes, and no expiration date."),
    ("146ce0", "expires", "That comes to 55.00 a month for a 12-month term with a "
     "99.00 installation fee, and there are no other changes or expiration date!"),
    ("d7a1f9", "changes_none expires", "I can confirm it is 69.00 per month for 24 "
     "months with no fees and no plan changes. There is also no expiry."),
    ("718c74", "fees_none changes_none expires", "It's 76.00 a month for 12 months "
     "with no fees, no other changes, and that rate doesn't expire."),
    ("ca1906", "fees_none changes_none expires", "The monthly price is 73.00 with a "
     "12 months term, and there are no fees, changes, or expiry."),
    ("ca1906", "fees_none changes_none expires", "The offer is 73.00 a month for 12 "
     "months with no extra fees, no service changes, and no expiration date."),
    ("e0351c", "fees_none changes_none expires", "The offer is 69.00 a month for 24 "
     "months with no fees and no service changes. This offer does not have an "
     "expiry date."),
    ("f15e98", "fees_none changes_none", "The rate is 78.00 per month for a 24 month "
     "term with no added fees. There are no other changes to the account, and the "
     "price will not expire after the term ends."),
    ("daa474", "changes_none expires", "It's just 55.00 a month with a 12-month "
     "term! There\u2019s an installation fee of 99.00, but no other service changes "
     "and no expiry date to worry about."),
    ("365464", "changes_none expires", "It's just 55.00 a month with a 12 month "
     "term, plus a 99.00 installation fee. There are no service changes and the "
     "offer has no expiry!"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("field", "text"),
    [(f, t) for _, fs, t in M3 for f in fs.split()],
    ids=[f"{run}-{f}" for run, fs, _ in M3 for f in fs.split()],
)
def test_m3_paraphrases_confirm(field: str, text: str) -> None:
    assert _confirms(SLOTS[field], text)


NEVER = [  # (case id, field, a line that must not confirm the field's "none")
    ("plus-fee", "fees_none", "There are no other changes, plus a $99 installation "
     "fee."),
    ("except", "changes_none", "There are no changes except the router swap."),
    ("other-than", "fees_none", "There are no fees other than the $20 activation fee."),
    ("and-your-plan", "changes_none", "There are no fees and your plan changes to "
     "Basic 100."),
    ("price-wont-change", "changes_none", "Your price won't change for 12 months."),
    ("changes-to-rate", "changes_none", "There are no changes to your rate."),
    ("cant-confirm", "fees_none", "I can't confirm the fees."),
    ("no-way", "fees_none", "There's no way to remove the fee."),
    ("until", "expires", "It won't expire until May 3."),
    ("lock-f15e98", "expires", "There are no other changes to the account, and the "
     "price will not expire after the term ends."),
    ("lock-718c74", "expires", "Best of all, that rate won't expire after the term "
     "ends!"),
    ("after-718c74", "expires", "It doesn't expire after that, either!"),
    ("but-fee", "fees_none", "No fees today, but there is a $99 installation fee."),
    ("question-fees", "fees_none", "Are there any fees?"),
    ("question-no-fees", "fees_none", "So there are no fees?"),
    ("question-changes", "changes_none", "No other changes, right?"),
    ("question-expiry", "expires", "Does it have no expiry?"),
    ("beyond", "fees_none", "There are no additional fees beyond the setup charge."),
    ("apart-from", "changes_none", "No changes apart from the new router."),
    ("unless", "fees_none", "No fees unless you cancel early."),
    ("besides", "fees_none", "There are no fees besides the installation charge."),
    ("price-change", "changes_none", "No price changes or service changes."),
    ("bill", "changes_none", "No changes to your bill."),
    ("deadline-before", "expires", "There's no deadline before Friday."),
    ("verb-change", "changes_none", "That won't change anything."),
]  # fmt: skip


@pytest.mark.parametrize(
    ("field", "text"), [(f, t) for _, f, t in NEVER], ids=[c for c, *_ in NEVER]
)
def test_never_confirmed(field: str, text: str) -> None:
    assert not _confirms(SLOTS[field], text)


def test_a_date_after_a_voided_expiry_is_the_date() -> None:
    assert said("it won't expire until may 3.", "expires") == {"05-03"}
    assert _confirms(MAY_3, "It won't expire until May 3.")
    assert said("there's no expiry, and it is valid until may 3.", "expires") == {
        "none", "05-03"
    }  # fmt: skip


def test_the_contradiction_stays_per_clause() -> None:
    line = "No fees today, but there is a $99 installation fee."
    assert said(line.lower(), "fees_none") == {"true", "false"}
    assert said("no other changes, plus a $99 installation fee", "fees_none") == {
        "false"
    }
    assert said("we will switch you to basic, no other changes", "changes_none") == {
        "true", "false"
    }  # fmt: skip
    assert said("no expiry, but it expires friday", "expires") == {"none", "date?"}


def test_the_list_and_its_breaks() -> None:
    assert denied("no fees, changes, or expiry", "changes")
    assert denied("no fees, changes, or expiry", "expires")
    assert denied("no extra fees or service changes", "changes")
    assert denied("nothing else changes", "changes")
    assert denied("nothing changes", "changes")
    assert denied("without any fees", "fees")
    assert denied("there's no expiration or any other changes", "changes")
    assert not denied("no extra fees and your plan changes", "changes")  # pronoun
    assert not denied("no service changes and a fee", "fees")  # determiner
    assert not denied("no changes, plus an installation fee", "fees")  # contrast
    assert not denied("no changes but a fee", "fees")
    assert not denied("no changes or $20 fees", "fees")  # an amount
    assert not denied("no great big extra new fees", "fees")  # 4 modifiers


def test_not_with_an_existence_verb() -> None:
    assert denied("it doesn't have an expiration date", "expires")
    assert denied("it does not expire", "expires")
    assert denied("this offer won\u2019t expire", "expires")  # a curly apostrophe
    assert denied("the plan doesn't include any fees", "fees")
    assert denied("there will not be any charges", "fees")
    assert denied("it does not carry a fee", "fees")
    assert not denied("i can't confirm the fees", "fees")  # not an existence verb
    assert not denied("i'm not sure about the fees", "fees")
    assert not denied("your plan won't change", "changes")  # the verb, not the noun
    assert not denied("that won't change any fees", "fees")  # "change" denies no fee


def test_role_words_are_closed_classes() -> None:
    assert denied("no costs", "fees") and denied("no charges", "fees")
    assert denied("no deadline", "expires")
    assert not denied("no fee", "changes") and not denied("no change", "fees")
    assert not denied("fee-free", "fees")  # not a role word: fails closed
