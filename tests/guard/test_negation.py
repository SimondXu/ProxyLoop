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
    ("f15e98", "fees_none", "The rate is 78.00 per month for a 24 month "
     "term with no added fees. There are no other changes to the account, and the "
     "price will not expire after the term ends."),
    ("f480ee", "fees_none changes_none expires", "You've got it, that's just 62.00 a "
     "month for a 12-month term! There are no fees, no expiry, and no other changes "
     "at all."),  # "at all": an intensifier of the negation
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


# M3 lines the inverted rule leaves unconfirmed, fail closed (#324 round 2): a
# tail after the list that is no account phrase, joiner or end voids it
M3_UNCONFIRMED = [
    ("a84f71-so-all-set", "You've got it, that's just 55.00 a month for 12 months "
     "with a 99.00 installation fee! Everything else stays the same with no expiry, "
     "so we're all set."),
    ("daa474-to-worry-about", "It's just 55.00 a month with a 12-month term! "
     "There\u2019s an installation fee of 99.00, but no other service changes and no "
     "expiry date to worry about."),
    ("571229-after-that", "It is just 55.00 a month for a 12-month term with a 99.00 "
     "installation fee. There is no expiry and no other changes after that!"),
]  # fmt: skip


@pytest.mark.parametrize("text", [t for _, t in M3_UNCONFIRMED],
                         ids=[c for c, _ in M3_UNCONFIRMED])  # fmt: skip
def test_m3_lines_with_an_unclean_tail_stay_unconfirmed(text: str) -> None:
    assert not _confirms(CHANGES, text)
    assert not _confirms(NO_EXPIRY, text)


@pytest.mark.parametrize(
    ("field", "text"),
    [  # #324 round 2 fix A: the "after the term ends" tail voids the sentence
        (
            "changes_none",
            "The rate is 78.00 per month for a 24 month term with no "
            "added fees. There are no other changes to the account, and the price will "
            "not expire after the term ends.",
        ),
    ],
    ids=["f15e98-A"],
)
def test_m3_lines_voided_by_the_round_2_rules(field: str, text: str) -> None:
    assert not _confirms(SLOTS[field], text)


# "just" right before an amount minimises the price, not the negation (#324)
M3_JUST = [
    ("a6bc6f", "fees_none",
     "It's just 62.00 a month for 12 months with no fees! There are no other "
     "changes and no expiry."),
    ("f480ee", "fees_none",
     "You're looking at just 62.00 a month for 12 months with no fees! There are"
     " no other changes to the service and no expiry."),
    ("f480ee", "fees_none",
     "It's just 62.00 a month for 12 months with no extra fees! There are no "
     "other changes to the service and this offer has no expiry."),
    ("146ce0", "changes_none expires",
     "It's just 55.00 a month for 12 months with a 99.00 installation fee, plus "
     "no other changes and no expiry!"),
    ("343a7e", "fees_none changes_none expires",
     "It's just 62.00 a month with no fees, no other changes, and no expiry "
     "date! That rate is locked in for 12 months."),
    ("343a7e", "fees_none",
     "It\u2019s just 62.00 a month for a 12 months term with no fees! There are "
     "no other changes to the account, and this offer has no expiry."),
    ("cfd03b", "fees_none changes_none expires",
     "It's just 62.00 a month for 12 months with no fees, no account changes, "
     "and no expiration date!"),
    ("571229", "fees_none",
     "It's just 62.00 a month on a 12-month term with no extra fees! There are "
     "no other service changes, and this offer has no expiry date."),
    ("365464", "changes_none expires",
     "It's just 55.00 a month with no expiry and no other changes! That comes "
     "with a 12 month term and a 99.00 installation fee."),
    ("365464", "fees_none",
     "It's just 62.00 a month for 12 months with no fees at all! There are no "
     "other changes to the service, and this offer has no expiry."),
    ("365464", "fees_none changes_none expires",
     "It's just 62.00 a month for 12 months with no fees, no other changes, and "
     "no expiry! That covers all the full terms for you."),
]  # fmt: skip


@pytest.mark.parametrize(
    ("field", "text"),
    [(f, t) for _, fs, t in M3_JUST for f in fs.split()],
    ids=[f"{r}-{f}-{n}" for n, (r, fs, _) in enumerate(M3_JUST) for f in fs.split()],
)
def test_m3_just_a_price_confirms(field: str, text: str) -> None:
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
    ("question-other-term", "fees_none", "So no fees, and the offer expires on June "
     "30?"),
    ("beyond", "fees_none", "There are no additional fees beyond the setup charge."),
    ("apart-from", "changes_none", "No changes apart from the new router."),
    ("unless", "fees_none", "No fees unless you cancel early."),
    ("besides", "fees_none", "There are no fees besides the installation charge."),
    ("price-change", "changes_none", "No price changes or service changes."),
    ("bill", "changes_none", "No changes to your bill."),
    ("deadline-before", "expires", "There's no deadline before Friday."),
    ("verb-change", "changes_none", "That won't change anything."),
    ("same-except", "changes_none", "Everything else stays the same except the "
     "router."),
    ("same-except-rate", "changes_none", "Everything else stays the same except your "
     "rate."),
    ("same-question", "changes_none", "Everything else stays the same?"),
    ("same-until", "changes_none", "Everything else remains the same until May."),
    # an un-negated role word in the sentence voids the none statement
    ("plain-fee", "fees_none", "No fees today, but there's an installation fee."),
    ("plain-change", "changes_none", "No other changes, but your plan changes to "
     "Basic."),
    ("plain-expiry", "expires", "There's no deadline, and the offer expires soon."),
    # the role word must head its item
    ("fee-waiver", "fees_none", "There's no fee waiver."),
    ("change-fee", "changes_none", "There's no change fee."),
    ("expiry-notice", "expires", "There's no expiry notice."),
    # a temporal word after any role word voids it
    ("fees-until", "fees_none", "No fees until next year."),
    ("changes-until", "changes_none", "No changes until your renewal."),
    ("fees-after", "fees_none", "There are no fees after the first month."),
    # PR #324 round 1 blockers: an existence verb that is no denial ("include")
    ("include-taxes", "fees_none", "That price doesn't include taxes and fees."),
    ("include-or", "fees_none", "The price is 68.00, and it doesn't include taxes or "
     "fees."),
    ("include-any", "fees_none", "The plan doesn't include any fees."),
    # time qualifiers past the old temporal words
    ("another-week", "expires", "This offer won't expire for another week."),
    ("48-hours", "expires", "It won't expire for 48 hours."),
    ("30-days", "expires", "The offer doesn't expire for 30 days."),
    ("first-12-months", "fees_none", "There are no fees for the first 12 months."),
    ("first-year", "changes_none", "Nothing changes for the first year."),
    ("same-12-months", "changes_none", "Everything stays the same for 12 months."),
    # conditions and restrictions
    ("etf-if", "fees_none", "No early termination fee if you stay 24 months."),
    ("sign-up-today", "fees_none", "No activation fee if you sign up today."),
    ("only-install", "fees_none", "No hidden fees, only the 99 install."),
    ("only-activation", "fees_none", "No fees, only the activation."),
    ("with-exception", "fees_none", "There are no fees, with the exception of the "
     "activation."),
    ("save-for", "fees_none", "No fees, save for the activation."),
    # an enclosing negation or hedge
    ("cant-promise", "fees_none", "I can't promise there won't be any fees."),
    ("cant-confirm-none", "fees_none", "I can't confirm there are no other fees."),
    ("not-sure", "fees_none", "I'm not sure there are no fees."),
    ("cancel-without", "fees_none", "You can't cancel early without fees."),
    ("not-everything", "changes_none", "Not everything stays the same."),
    ("i-think", "fees_none", "I think there are no fees."),
    # the void word is not next to the role word (the round 1 surviving mutants)
    ("plan-until", "changes_none", "There are no changes to your plan until May."),
    ("plan-unless", "fees_none", "No fees on this plan unless you cancel early."),
    ("services-other-than", "changes_none", "No changes to your services other than "
     "the router swap."),
    ("under-review", "changes_none", "Everything else remains under review."),
    ("same-will-stay", "changes_none", "Everything else will stay the same."),
    ("and-bare-item", "fees_none", "No service changes and standard installation "
     "fees."),
    ("and-if", "fees_none", "No fees and no changes if you stay 24 months."),
    ("next-sentence", "fees_none", "No fees. Well, apart from the activation charge."),
    # a clause on another term carrying an amount or a condition (#324 round 3)
    ("expires-if-99", "fees_none", "No fees, and the offer expires if you add the $99 "
     "install."),
    ("expires-once-20", "fees_none", "No fees, and the offer expires once you pay the "
     "20 dollar setup."),
    ("at-all-if", "fees_none", "No fees at all if you stay 24 months."),
    ("at-first", "fees_none", "No fees at first."),  # "at all" only intensifies
    ("just-activation", "fees_none", "Just the activation, no other fees."),
    ("just-activation-fee", "fees_none", "Just the activation fee, no other fees."),
    # #324 round 2 (A): a bad tail voids the whole sentence
    ("A-except", "fees_none", "No fees, it has no expiry date, except the activation."),
    ("A-swap", "changes_none", "There are no other changes, there are no fees, "
     "except we swap the router."),
    # (B) a clause on another term carries no qualifier, nor (for expiry) a date
    ("B-by-june", "expires", "There's no expiry date, and the change has to be "
     "accepted by June 30."),
    ("B-tomorrow", "expires", "No expiry, and the plan change locks in tomorrow."),
    ("B-through", "expires", "There's no expiry date, and the fee waiver is good "
     "through Friday."),
    # (C) a qualifier before the first statement voids the sentence
    ("C-unless", "fees_none", "Unless you cancel early, there are no fees."),
    ("C-if", "fees_none", "If you sign up today, there's no activation fee."),
    ("C-other-than", "fees_none", "Other than the activation, there are no fees."),
    ("C-except-for", "changes_none", "Except for the router, there are no other "
     "changes."),
    ("C-once", "expires", "Once you accept, there's no expiration date."),
    ("C-first-12", "fees_none", "For the first 12 months, there are no fees."),
    ("C-this-month", "fees_none", "This month there are no fees."),
    ("C-besides", "fees_none", "Besides the activation charge there are no fees."),
    ("C-apart", "fees_none", "Apart from the activation, there are no fees."),
    ("C-aside", "fees_none", "Aside from installation, there are no fees."),
    ("C-before", "fees_none", "Before Friday, there are no fees."),
    ("C-through", "changes_none", "Through the renewal, there are no other changes."),
    ("bridge-besides", "fees_none", "No fees, and besides the activation there's no "
     "expiry."),
    # (D) a further list item is headed by a role word
    ("D-activation-extra", "fees_none", "No fees, activation extra."),
    ("D-installation-extra", "fees_none", "No monthly fees, installation extra."),
    ("D-may-3", "expires", "No expiry date, May 3."),
    # (E) number words are amounts in a clause on another term
    ("E-ninety-nine", "fees_none", "No other fees, and the router change runs "
     "ninety-nine."),
]  # fmt: skip


@pytest.mark.parametrize(
    ("field", "text"), [(f, t) for _, f, t in NEVER], ids=[c for c, *_ in NEVER]
)
def test_never_confirmed(field: str, text: str) -> None:
    assert not _confirms(SLOTS[field], text)


REVIEW = [  # the PR #324 round 1 battery (rev109/adv.py): realistic false readings
    ("fees_none", "The $68 a month doesn't include taxes and fees."),
    ("fees_none", "That price does not include fees."),
    ("fees_none", "It's $68 a month, which doesn't include the fees."),
    ("fees_none", "The monthly price is 68.00, and it doesn't include taxes or fees."),
    ("fees_none", "There are no fees if you keep autopay on."),
    ("fees_none", "No activation fee if you sign up today."),
    ("fees_none", "There's no fee as long as you stay the full term."),
    ("fees_none", "No fees while you're on autopay."),
    ("fees_none", "No fees provided you keep paperless billing."),
    ("fees_none", "No activation fee with autopay."),
    ("fees_none", "There are no fees for the first 12 months."),
    ("fees_none", "No cancellation fees within the first 30 days."),
    ("fees_none", "No fees during the promo period."),
    ("fees_none", "There are no fees this year."),
    ("fees_none", "There are no fees yet."),
    ("fees_none", "No fees for now."),
    ("expires", "The offer doesn't expire for 30 days."),
    ("expires", "This offer won't expire for another week."),
    ("expires", "It won't expire for 48 hours."),
    ("expires", "There's no deadline for 30 days."),
    ("expires", "It doesn't expire anytime soon."),
    ("expires", "The offer doesn't expire, but you have to accept by Friday."),
    ("expires", "It does not expire within the next week."),
    ("expires", "This offer doesn't expire today."),
    ("expires", "No expiration date yet."),
    ("fees_none", "I can't promise there won't be any fees."),
    ("fees_none", "I can't guarantee there are no fees."),
    ("fees_none", "I can't confirm there are no other fees."),
    ("fees_none", "I'm not sure there are no fees."),
    ("fees_none", "I don't think there are no fees."),
    ("changes_none", "I can't say there are no other changes."),
    ("changes_none", "Not everything stays the same."),
    ("fees_none", "You can't cancel early without fees."),
    ("fees_none", "There's no way to cancel without fees."),
    ("fees_none", "No fees. Well, apart from the activation charge."),
    ("fees_none", "No fees. Except the $35 activation."),
    ("fees_none", "No fees, except taxes."),
    ("fees_none", "There's no fee, just a $5 regulatory surcharge."),
    ("fees_none", "There are no fees, just taxes and surcharges."),
    ("fees_none", "No fees, the activation is $35."),
    ("fees_none", "We'll send the router at no cost, and the install is $99."),
    ("fees_none", "No fees, just ninety-nine dollars for installation."),
    ("fees_none", "No other changes, fees of ninety-nine dollars."),
    ("fees_none", "No service changes and standard installation fees."),
    ("fees_none", "No monthly fees. Installation is $99."),
    ("fees_none", "No monthly fees, just a one-time 99.00 installation."),
    ("fees_none", "There's a $0 activation fee."),
    ("fees_none", "There is a one-time fee of zero."),
    ("fees_none", "The $99 installation fee is waived."),
    ("fees_none", "No fees\u2014well, the $35 activation."),
    ("fees_none", "There\u2019s no fee unless you cancel."),
    ("fees_none", "No fees on the new plan, the old one had a $20 fee."),
    ("fees_none", "There's no fee, it's a ninety-nine dollar charge."),
    ("fees_none", "No early termination fee if you stay 24 months."),
    ("fees_none", "No fees, assuming you return the old modem."),
    ("fees_none", "No fees on top of the 99.00 install."),
    ("fees_none", "No fees other than the install."),
    ("fees_none", "No hidden fees, only the 99 install."),
    ("fees_none", "No fees, only the activation."),
    ("fees_none", "No fees, only a ninety-nine dollar installation."),
    ("fees_none", "There are no fees, with the exception of the activation."),
    ("fees_none", "No fees excluding the activation."),
    ("fees_none", "No fees, save for the activation."),
    ("fees_none", "No fees outside the activation."),
    ("fees_none", "No fees aside from activation."),
    ("fees_none", "No fees except for installation."),
    ("fees_none", "No additional fees on top of installation."),
    ("fees_none", "No fees, minus the activation."),
    ("fees_none", "No fees, not counting the activation."),
    ("fees_none", "No fees, not including the activation."),
    ("changes_none", "No changes, other than the router swap."),
    ("changes_none", "No changes on top of the router swap."),
    ("changes_none", "No other changes, just the new router."),
    ("changes_none", "No other changes, only the router swap."),
    ("changes_none", "No other changes besides switching you to Basic."),
    ("changes_none", "No changes if you keep the same plan."),
    ("changes_none", "No changes for the first year."),
    ("changes_none", "Nothing changes for the first year."),
    ("changes_none", "Everything stays the same for 12 months."),
    ("changes_none", "Everything else stays the same for now."),
    ("changes_none", "No other changes, we'll swap your router."),
    ("changes_none", "No other changes, we'll replace your router."),
    ("changes_none", "No contract changes."),
    ("changes_none", "No fee changes."),
    ("changes_none", "No changes to the plan, the speed drops to 100."),
    ("changes_none", "No changes to your services, but your speed goes to 300."),
    ("expires", "No expiry on the price, and the offer ends Friday."),
    ("expires", "It doesn't expire if you accept today."),
    ("expires", "No expiry as long as you stay on autopay."),
    ("expires", "The credit has no expiry, the offer ends Friday."),
    ("expires", "The credit doesn't expire, the offer's valid for 7 days."),
    ("expires", "The discount doesn't expire, but the offer ends on the 30th."),
    ("expires", "The promo doesn't expire, but this quote does."),
    ("expires", "This won't expire through the term."),
    ("expires", "There's no expiry date on the credit, but the offer lapses Friday."),
    ("expires", "It does not expire for the life of the plan."),
]  # fmt: skip


@pytest.mark.parametrize(("field", "text"), REVIEW)
def test_the_review_battery_never_confirms(field: str, text: str) -> None:
    assert not _confirms(SLOTS[field], text)


def test_a_date_after_a_voided_expiry_is_the_date() -> None:
    assert said("it won't expire until may 3.", "expires") == {"05-03"}
    assert _confirms(MAY_3, "It won't expire until May 3.")
    both = said("there's no expiry, and it is valid until may 3.", "expires")
    assert "05-03" in both and "none" not in both


def test_the_contradiction_stays_per_clause() -> None:
    line = "No fees today, but there is a $99 installation fee."
    assert said(line.lower(), "fees_none") == {"false"}  # a plain "fee": void
    assert said("no other changes, plus a $99 installation fee", "fees_none") == {
        "false"
    }
    assert said("we will switch you to basic, no other changes", "changes_none") == {
        "true", "false"
    }  # fmt: skip
    assert said("no expiry, but it expires friday", "expires") == {"date?"}


def test_the_list_and_its_breaks() -> None:
    assert denied("no fees, changes, or expiry", "changes")
    assert denied("no fees, changes, or expiry", "expires")
    assert denied("no extra fees or service changes", "changes")
    assert denied("nothing else changes", "changes")
    assert denied("nothing changes", "changes")
    assert denied("without any fees", "fees")
    assert denied("there's no expiration or any other changes", "changes")
    assert denied("no changes to your service, and that rate doesn't expire", "changes")
    assert denied("no changes to your service, and that rate doesn't expire", "expires")
    assert denied("no other changes, and this offer has no expiry date", "changes")
    assert not denied("no fees, the activation is $35", "fees")  # no clean tail
    assert not denied("no changes for the first year", "changes")
    assert not denied("no contract changes", "changes")  # another term kind
    assert not denied("no extra fees and your plan changes", "changes")  # pronoun
    assert not denied("no service changes and a fee", "fees")  # determiner
    assert not denied("no changes, plus an installation fee", "fees")  # contrast
    assert not denied("no changes but a fee", "fees")
    assert not denied("no changes or $20 fees", "fees")  # an amount
    assert not denied("no great big extra new fees", "fees")  # 4 modifiers
    assert denied("no expiry date", "expires") and denied("no expiry period", "expires")
    assert not denied("no fee waiver", "fees")  # the role word must head its item
    assert not denied("no change fee", "changes")
    assert not denied("no fees, but a fee", "fees")  # a plain role word


def test_not_with_an_existence_verb() -> None:
    assert denied("it doesn't have an expiration date", "expires")
    assert denied("it does not expire", "expires")
    assert denied("this offer won\u2019t expire", "expires")  # a curly apostrophe
    assert not denied("the plan doesn't include any fees", "fees")  # no denial
    assert denied("there will not be any charges", "fees")
    assert denied("it does not carry a fee", "fees")
    assert not denied("i can't confirm the fees", "fees")  # not an existence verb
    assert not denied("i'm not sure about the fees", "fees")
    assert not denied("your plan won't change", "changes")  # the verb, not the noun
    assert not denied("that won't change any fees", "fees")  # "change" denies no fee


def test_everything_stays_the_same_is_the_second_closed_form() -> None:
    assert denied("everything else stays the same", "changes")
    assert denied("everything remains the same", "changes")
    assert not denied("everything else stays the same", "fees")
    assert not denied("everything else will be the same", "changes")  # closed form


def test_bridges_and_phrases_carry_no_qualifier() -> None:
    """A joiner into a new statement passes only plain words (#324 mutants)."""
    assert denied("no fees, and this offer has no deadline", "fees")
    assert not denied("no fees, and for a year no other charges", "fees")
    # the next statement names the same field, so the bridge must be plain
    assert not denied("no fees, and if you stay no other charges", "fees")
    assert not denied("no fees, and today no other charges", "fees")
    assert not denied("no changes, and other than that nothing changes", "changes")
    assert not denied("no fees, and unless you move no other charges", "fees")
    assert not denied("no fees, and only then no other charges", "fees")
    assert not denied("no fees, but there's no guarantee", "fees")
    assert not denied("no fees, and until may no other charges", "fees")
    assert denied("no fees, and the offer also has no deadline", "fees")  # 4 words
    assert not denied(  # more than BRIDGE_MAX words
        "there are no fees, and the people at the store say there are no charges",
        "fees",
    )
    assert not denied("no fees on your first year plan", "fees")  # a time in a phrase
    assert not denied("no other fees, and there's no deadline, right?", "fees")
    assert denied("no other changes to this offer", "changes")
    assert denied("there are no extra one-time installation fees", "fees")  # 3 mods


def test_a_semicolon_joins_like_a_comma() -> None:
    """The world's template read-back: "...; no other changes; no expiry." """
    line = "here are the terms: price: 68.00; no fees; no other changes; no expiry."
    assert denied(line, "fees") and denied(line, "changes")
    assert denied(line, "expires")
    assert not denied("no fees; the activation is $35", "fees")


def test_a_clause_on_another_term_ends_the_sentence_cleanly() -> None:
    """tests/slow f11 (M2): "..., no other changes, and the offer expires on June
    30": the clause states another field, read per clause on its own."""
    dated = "no fees, no other changes, and the offer expires on june 30, 2026"
    assert denied(dated, "fees") and denied(dated, "changes")
    assert not denied(dated, "expires")
    assert denied("no fees, and the offer expires on the 30th", "fees")
    # the clause carries no amount, non-date number, condition or restriction
    assert not denied("no expiry, and there's a $35 installation fee", "expires")
    assert not denied("no fees, and the offer expires in 30 days", "fees")
    assert not denied("no fees, and the offer expires unless you sign", "fees")
    assert not denied("no other changes, and the offer expires just today", "changes")
    assert not denied("no fees, and the activation is $35", "fees")  # no other term
    assert not denied("no fees, and the installation charge is $99", "fees")  # same


def test_at_all_intensifies_a_negated_item() -> None:
    assert denied("no fees at all", "fees") and denied(
        "no changes at all, and no fees", "changes"
    )
    assert not denied("no fees at all until may", "fees")
    assert not denied("no fees at your store", "fees")  # "at" alone: a phrase


def test_every_role_word_must_be_negated() -> None:
    assert not denied("there's an installation fee, and no other fees", "fees")
    assert not denied("everything is mostly the same, with no other changes", "changes")
    assert not denied("everything else looks the same", "changes")  # closed form


def test_role_words_are_closed_classes() -> None:
    assert denied("no costs", "fees") and denied("no charges", "fees")
    assert denied("no deadline", "expires")
    assert not denied("no fee", "changes") and not denied("no change", "fees")
    assert not denied("fee-free", "fees")  # not a role word: fails closed
