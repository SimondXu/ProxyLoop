"""Read-back slots (ARCHITECTURE §9.2): heard, confirmed, and what never confirms."""

from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st
from tests.guard.build import READBACK, agent, offer, rep, slot

from proxyloop.contract.state import Line, OfferPublic
from proxyloop.guard.readback import (
    LEXICON,
    missing_required,
    readback_status,
    readback_text,
    readback_update,
    said,
)
from proxyloop.guard.terms import (
    NO_EXPIRY,
    expiry_text,
    offer_terms,
    offer_terms_hash,
)

ASK = agent("a1", "Could you read the full terms back to me?")


def _fold(o: OfferPublic, lines: list[Line], asked_at: int | None) -> OfferPublic:
    """Apply ``readback_update`` to ``o`` the way the fold does."""
    update = readback_update(o, lines, asked_at)
    statuses = update["slot_statuses"]
    assert isinstance(statuses, dict)
    slots = tuple(s.model_copy(update={"status": statuses[s.field]}) for s in o.slots)
    return o.model_copy(update={"slots": slots, "terms_hash": update["terms_hash"]})


def _confirmed(o: OfferPublic, *after_ask: str) -> bool:
    lines = [rep("c1", "I can offer you something."), ASK]
    lines += [rep(f"c{n + 2}", text) for n, text in enumerate(after_ask)]
    return readback_status(_fold(o, lines, asked_at=2)) == "confirmed"


def test_a_full_readback_confirms_the_offer_and_binds_its_terms() -> None:
    done = _fold(offer(), [ASK, rep("c2", READBACK)], asked_at=1)
    assert {s.status for s in done.slots} == {"confirmed"}
    assert readback_status(done) == "confirmed"
    assert done.terms_hash == offer_terms_hash(done) is not None


def test_a_statement_before_the_readback_request_is_only_heard() -> None:
    o = offer().model_copy(update={"slots": offer().slots[:1]})
    o = o.model_copy(
        update={"slots": (o.slots[0].model_copy(update={"source_utt": "c1"}),)}
    )
    lines = [rep("c1", "It is $68 a month."), ASK]
    assert _fold(o, lines, asked_at=2).slots[0].status == "heard"
    assert _fold(o, lines, asked_at=None).slots[0].status == "heard"
    assert _fold(o, [rep("c1", "It is $75 a month.")], None).slots[0].status == (
        "unknown"
    )


def test_the_negation_window_is_four_tokens() -> None:
    assert said("a $20 activation fee", "fee:activation") == {"2000"}
    assert said("we waive the $20 activation fee", "fee:activation") == {"none"}
    assert said("the $20 activation fee is waived", "fee:activation") == {"none"}
    assert said("no activation fee", "fee:activation") == {"none"}
    assert said("no activation fee", "fees_none") == {"true"}
    assert said("a $20 activation fee", "fees_none") == {"false"}


def test_role_cues_decide_the_field() -> None:
    assert said("it is $68 a month", "monthly_price") == {"6800"}
    assert said("it is $68 a month", "fee:activation") == set()
    assert said("the monthly fee is $68", "monthly_price") == {"6800"}
    assert said("the monthly fee is $68", "fees_none") == set()  # "fee" yields
    # Both roles in one clause: the value counts for both (a contradiction).
    both = "a $20 activation fee on top of $68 a month"
    assert said(both, "monthly_price") == {"2000", "6800"}


def test_required_fields() -> None:
    assert missing_required(offer()) == ()
    no_fee = offer().model_copy(
        update={"slots": tuple(s for s in offer().slots if s.field != "fee:activation")}
    )
    assert missing_required(no_fee) == ("fee:*|fees_none",)
    assert readback_status(no_fee.model_copy(update={"slots": ()})) == "unconfirmed"


def test_lexicons_are_one_data_table() -> None:
    kinds = {"recurring", "one_time", "fee", "credit", "negation", "fees_none"}
    kinds |= {"changes_none", "change", "generic_fee", "expiry", "no_expiry"}
    kinds |= {"closing"}
    assert set(LEXICON) == kinds
    assert all(isinstance(cue, str) for cues in LEXICON.values() for cue in cues)


def test_readback_text_names_every_slot() -> None:
    text = readback_text(offer())
    assert "$68.00" in text and "24 months" in text and "$20.00" in text


def test_expiry_text_has_whole_seconds_and_fits_a_slot() -> None:
    t = datetime(2026, 10, 1, 12, 30, 5, 123456, tzinfo=UTC)
    assert expiry_text(t) == "2026-10-01T12:30:05Z"
    dated = offer(expires=expiry_text(t))
    terms = offer_terms(dated)
    assert terms is not None and terms.expires_at == t.replace(microsecond=0)
    none = offer_terms(offer())
    assert none is not None and none.expires_at == NO_EXPIRY


# Read-back properties: each defect leaves the offer not confirmed.
_DOLLARS = st.integers(10, 199)


@given(_DOLLARS, st.integers(1, 99), st.integers(1, 36))
def test_a_true_readback_confirms(m: int, f: int, t: int) -> None:
    o = offer(monthly=f"{m}00", fee=f"{f}00", term=str(t))
    line = f"It is ${m} a month for {t} months, with a ${f} activation fee"
    assert _confirmed(o, line + ", no other changes, and it does not expire.")


@given(_DOLLARS, st.integers(1, 99), st.integers(1, 36))
def test_a_role_swap_never_confirms(m: int, f: int, t: int) -> None:
    if m == f:
        return
    o = offer(monthly=f"{m}00", fee=f"{f}00", term=str(t))
    swapped = f"It is ${f} a month for {t} months, with a ${m} activation fee"
    assert not _confirmed(o, swapped + ", no other changes, and it does not expire.")


@given(_DOLLARS, st.integers(1, 99), st.sampled_from(["no", "waived"]))
def test_a_negated_fee_never_confirms(m: int, f: int, cue: str) -> None:
    o = offer(monthly=f"{m}00", fee=f"{f}00")
    fee = "no activation fee" if cue == "no" else f"the ${f} activation fee is waived"
    line = f"It is ${m} a month for 24 months, {fee}, no other changes"
    assert not _confirmed(o, line + ", and it does not expire.")


@given(_DOLLARS, st.sampled_from(["fee", "changes", "expires", "term"]))
def test_an_omitted_required_field_never_confirms(m: int, omit: str) -> None:
    drop = {
        "fee": "fee:activation",
        "changes": "changes_none",
        "expires": "expires",
        "term": "term_months",
    }[omit]
    o = offer(monthly=f"{m}00")
    o = o.model_copy(update={"slots": tuple(s for s in o.slots if s.field != drop)})
    line = f"It is ${m} a month on a 24-month term, with a $20 activation fee"
    assert not _confirmed(o, line + ", no other changes, and it does not expire.")


@given(_DOLLARS, st.integers(1, 50))
def test_a_later_contradiction_never_confirms(m: int, delta: int) -> None:
    o = offer(monthly=f"{m}00")
    line = f"It is ${m} a month on a 24-month term, with a $20 activation fee"
    full = line + ", no other changes, and it does not expire."
    assert _confirmed(o, full)
    assert not _confirmed(o, full, f"Sorry, I misspoke: it is ${m + delta} a month.")
    assert not _confirmed(o, full, "Actually the offer expires on Friday.")
    assert not _confirmed(o, full, f"Sorry, the fee is ${20 + delta}.")  # the sole fee


def test_a_second_fee_does_not_contradict_the_first() -> None:
    o = offer()
    setup = slot("fee:setup", "1000", "usd_minor", "one_time")
    o = o.model_copy(update={"slots": (*o.slots, setup)})
    assert _confirmed(o, READBACK, "There is also a $10 setup fee.")
    assert not _confirmed(
        o, READBACK, "There is also a $10 setup fee.", "The fee is $30."
    )


# Regressions from the #126 review probes (probe_rb.py, probe_dup.py): M6.
BASE = READBACK


def test_a_fee_named_otherwise_is_not_generic() -> None:
    assert said("with a $20 early termination fee", "fee:activation") == set()
    other = BASE.replace("activation fee", "early termination fee")
    assert not _confirmed(offer(), other)
    assert said("the one-time fee is $20", "fee:activation") == {"2000"}  # generic


def test_fees_none_with_a_paid_amount_is_a_contradiction() -> None:
    clause = "there are no additional fees beyond the $20 setup charge"
    assert said(clause, "fees_none") == {"true", "false"}
    line = f"It is $68 a month on a 24-month term, {clause}, no other changes, "
    assert not _confirmed(offer(fee=None), line + "and it does not expire.")


def test_a_later_change_contradicts_changes_none() -> None:
    later = "Also we will switch you to the premium sports package."
    assert not _confirmed(offer(), BASE, later)
    assert said("we will also change your plan to premium", "changes_none") == {"false"}
    assert said("we cannot change your plan", "changes_none") == set()


def test_a_dated_expiry_must_name_the_slot_day() -> None:
    dated = offer(expires="2026-10-01T00:00:00Z")
    on_day = BASE.replace("the offer does not expire", "the offer expires on October 1")
    assert _confirmed(dated, on_day)
    assert not _confirmed(dated, on_day.replace("October 1", "October 2"))
    vague = BASE.replace("does not expire", "expires at the end of December")
    assert not _confirmed(dated, vague)
    assert not _confirmed(dated, on_day, "Actually, it expires next year.")
    assert said("the offer doesn't expire until Friday", "expires") == {"date?"}
    until = BASE.replace("does not expire", "doesn't expire until Friday")
    assert not _confirmed(offer(), until)  # a "none" slot is not confirmed
    assert not _confirmed(offer(), BASE, "No deadline today, but it expires Friday.")


def test_repeated_fields_are_unconfirmable() -> None:
    o = offer()
    twice = (*o.slots, slot("monthly_price", "9900", "usd_minor", "recurring"))
    o = o.model_copy(update={"slots": twice})
    assert not _confirmed(o, BASE.replace("$68", "$99"))
    assert offer_terms(o) is None


def test_negations_and_money_forms() -> None:
    assert said("we cannot change your plan", "applied_change:plan_change") == {"false"}
    assert said("we don't charge the $20 activation fee", "fee:activation") == {"none"}
    assert said("never a $20 activation fee", "fee:activation") == {"none"}
    assert said("$1,068.50 a month", "monthly_price") == {"106850"}
    assert said("it's 68 dollars and 50 cents a month", "monthly_price") == {"6850"}
