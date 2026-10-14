"""One read-back window per offer (ADR-0020): an ask for any revision of the
offer, in the same call, confirms a revision when W1-W4 and W2' hold. Each
negative is red if one condition is dropped; the mutation each one pins is
named. A bare index is an ask for a revision with ``o``'s own terms."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from tests.guard.build import READBACK, agent, offer, rep

from proxyloop.contract.state import Line, OfferPublic
from proxyloop.guard.readback import (
    Ask,
    readback_status,
    readback_update,
    slot_statuses,
)

ASK = agent("a1", "Could you read the full terms back to me?")
NOTHING = rep("c1", "I can offer you something.")
Asks = Sequence[int | Ask]


def _asks(o: OfferPublic, asks: Asks) -> list[Ask]:
    terms = {s.field: s.value for s in o.slots}
    return [a if isinstance(a, Ask) else Ask(a, terms) for a in asks]


def _fold(
    o: OfferPublic,
    lines: Sequence[Line],
    asks: Asks,
    asked_at: int | None,
    rivals: Sequence[OfferPublic] = (),
) -> OfferPublic:
    update = readback_update(o, lines, asked_at, _asks(o, asks), rivals)
    statuses = update["slot_statuses"]
    assert isinstance(statuses, dict)
    slots = tuple(s.model_copy(update={"status": statuses[s.field]}) for s in o.slots)
    return o.model_copy(update={"slots": slots, "terms_hash": update["terms_hash"]})


def _confirmed(
    o: OfferPublic,
    lines: Sequence[Line],
    asks: Asks,
    asked_at: int | None = None,  # this revision's own ask: none by default
    rivals: Sequence[OfferPublic] = (),  # the other open offers
) -> bool:
    return readback_status(_fold(o, lines, asks, asked_at, rivals)) == "confirmed"


def _statuses(o: OfferPublic, lines: Sequence[Line], asks: Asks) -> set[str]:
    return set(slot_statuses(o, lines, None, _asks(o, asks)).values())


# Positives.


def test_21988c_confirms_after_one_ask() -> None:
    """21988c: the answer to the r1 ask stated all five terms; r3, recorded
    from it, needed no second read-back (env/reference.py accepts one)."""
    r3 = offer(monthly="7800", fee=None, revision=3)
    lines = [
        rep("cp-6", "I can offer a monthly price of 78.00 with a term of 24 months."),
        agent("g10", "Could you read back every term of that offer?"),
        rep("cp-7", "I'm afraid that is the best offer I can provide."),
        rep("cp-10", "It is 78.00 per month for 24 months with no fees. "
                     "There are no other changes and no expiry."),
        rep("cp-11", "The monthly price is 78.00 for 24 months with no fees, "
                     "no other changes, and no expiry."),
    ]  # fmt: skip
    assert not _confirmed(r3, lines, asks=())  # today's rule: no ask for r3
    r1 = Ask(2, {"monthly_price": "7800", "term_months": "24"})  # r1 = r3's
    assert _confirmed(r3, lines, asks=(r1,))


def test_a_hidden_fee_revealed_on_read_back_confirms() -> None:
    """r1 was price and term; the read-back revealed the fee, and r2 records it."""
    lines = [rep("c1", "It is $68 a month on a 24-month term."), ASK]
    lines.append(rep("c2", READBACK))  # reveals the $20 activation fee
    r2 = offer(revision=2)
    assert not _confirmed(r2, lines, asks=())
    r1 = Ask(2, {"monthly_price": "6800", "term_months": "24"})  # no fee field
    assert _confirmed(r2, lines, asks=(r1,))


# Negatives: each stays unconfirmed.


def test_n1_a_new_offer_given_as_the_answer_to_the_old_ask() -> None:
    """W2: the price changed across the ask."""
    lines = [rep("c1", "It is $68 a month on a 24-month term."), ASK]
    lines.append(rep("c2", READBACK.replace("$68", "$60")))
    assert not _confirmed(offer(monthly="6000", revision=2), lines, asks=(2,))


def test_n2_a_value_changes_after_the_ask() -> None:
    """W1: the stale $68 read-back is at or after the ask."""
    lines = [NOTHING, ASK, rep("c2", READBACK)]
    lines.append(rep("c3", "Sorry, I misspoke: it is $80 a month."))
    assert not _confirmed(offer(monthly="8000", revision=2), lines, asks=(2,))
    assert not _confirmed(offer(), lines, asks=(2,), asked_at=2)  # nor the $68 r1


def test_n3_a_package_change_through_an_added_slot_after_no_other_changes() -> None:
    """W1, the implied flag: r2 lists an applied change, so its changes_none
    is false, and "no other changes" after the ask contradicts it."""
    lines = [NOTHING, ASK, rep("c2", READBACK)]  # "... no other changes ..."
    lines.append(rep("c3", "We will also switch you to the sports package."))
    lines.append(rep("c4", "So: $68 a month on a 24-month term, with a $20 "
                           "activation fee, and we switch you to the sports "
                           "package; the offer does not expire."))  # fmt: skip
    r2 = offer(change="sports_package", revision=2)
    assert not _confirmed(r2, lines, asks=(2,))


def test_n4_a_package_change_with_no_fees_stated_only_before_it() -> None:
    """W3: the change was first stated after "no fees" and the expiry, which
    the rep never restated."""
    lines = [NOTHING, ASK]
    lines.append(rep("c2", "It is $68 a month on a 24-month term with no fees, "
                           "and the offer does not expire."))  # fmt: skip
    lines.append(rep("c3", "We will also switch you to the sports package."))
    lines.append(rep("c4", "That is $68 a month for 24 months."))
    r2 = offer(fee=None, change="sports_package", revision=2)
    assert not _confirmed(r2, lines, asks=(2,))


def test_n5_the_expiry_changes_after_the_ask_and_r1_reverts() -> None:
    """W1: "does not expire" after the ask; r1 reverts on the change."""
    lines = [NOTHING, ASK, rep("c2", READBACK)]
    assert _confirmed(offer(), lines, asks=(2,), asked_at=2)
    lines.append(rep("c3", "Actually, the offer expires on October 1."))
    r2 = offer(expires="2026-10-01T00:00:00Z", revision=2)
    assert not _confirmed(r2, lines, asks=(2,))
    r1 = slot_statuses(offer(), lines, 2, _asks(offer(), (2,)))
    assert (
        r1["expires"] != "confirmed"
        and readback_status(_fold(offer(), lines, (2,), 2)) == "unconfirmed"
    )


def test_n6_no_mixed_anchors() -> None:
    """W4: after ask 1 the price moved from $70 (W2 fails for it); after
    ask 2 only the price was restated (W3 fails for the rest). Each slot has
    an anchor of its own; no one anchor confirms them all."""
    lines = [rep("c1", "It is $70 a month on a 24-month term."), ASK]
    lines += [rep("c2", READBACK), agent("a2", "Could you read it back again?")]
    lines.append(rep("c3", "It is $68 a month."))
    assert _statuses(offer(), lines, (2, 4)) <= {"heard", "unknown"}
    assert not _confirmed(offer(), lines, asks=(2, 4))


def test_n7_no_ask_no_anchor() -> None:
    """Asks for another offer, or from an earlier call, never reach Guard
    (slow.tools filters them; tests/slow/test_readback_window.py): with no
    ask, a full read-back is only heard."""
    lines = [NOTHING, ASK, rep("c2", READBACK)]
    assert not _confirmed(offer(), lines, asks=())


def test_n8_no_fees_then_an_activation_fee() -> None:
    """W1, the implied flag: "no fees" after the ask contradicts r2's fee,
    though the rep later restated every term with it."""
    lines = [NOTHING, ASK]
    lines.append(
        rep(
            "c2",
            "It is $68 a month on a 24-month term, no fees, no "
            "other changes, and the offer does not expire.",
        )
    )
    lines.append(rep("c3", "Actually, there is a $30 activation fee."))
    lines.append(rep("c4", "So it is $68 a month on a 24-month term, with a $30 "
                           "activation fee, no other changes, and the offer does "
                           "not expire."))  # fmt: skip
    assert not _confirmed(offer(fee="3000", revision=2), lines, asks=(2,))
    assert not _confirmed(offer(fee=None), lines, asks=(2,), asked_at=2)


def test_n9_a_later_contradiction_reverts_a_window_confirmation() -> None:
    lines = [NOTHING, ASK, rep("c2", READBACK)]
    r2 = offer(revision=2)
    assert _confirmed(r2, lines, asks=(2,))
    lines.append(rep("c3", "Sorry, I misspoke: it is $75 a month."))
    assert not _confirmed(r2, lines, asks=(2,))
    assert _statuses(r2, lines, (2,)) <= {"heard", "unknown"}  # all or none


def test_a_single_line_check_is_unchanged() -> None:
    """slow.state.restated calls ``slot_statuses(o, (line,), 0)``: no asks, the
    strict rule alone."""
    got = slot_statuses(offer(), (rep("c2", READBACK),), 0)
    assert set(got.values()) == {"confirmed"}
    half = slot_statuses(offer(), (rep("c2", "It is $68 a month."),), 0)
    assert half["monthly_price"] == "confirmed" and half["term_months"] != "confirmed"


def test_a_revision_missing_a_required_field_takes_no_window() -> None:
    """21988c r2 (fees_none, changes_none, expires only): no slot shows as
    confirmed through the window; the complete r3 still is."""
    r2 = offer(fee=None, revision=2)
    r2 = r2.model_copy(update={"slots": r2.slots[2:]})
    lines = [
        rep("cp-6", "I can offer a monthly price of 78.00 with a term of 24 months."),
        agent("g10", "Could you read back every term of that offer?"),
        rep("cp-10", "It is 78.00 per month for 24 months with no fees. "
                     "There are no other changes and no expiry."),
    ]  # fmt: skip
    assert _statuses(r2, lines, (2,)) <= {"heard", "unknown"}
    assert _confirmed(offer(monthly="7800", fee=None, revision=3), lines, (2,))


@pytest.mark.parametrize("price", ["$68", "sixty-eight dollars"])
def test_n11_an_answer_that_changes_the_asked_revision(price: str) -> None:
    """W2': r1 was recorded at $68 from a line with no role cue (so the
    lexicon never saw a price before the ask); the answer said $60, and r2
    at $60 differs from the asked revision in a field both carry."""
    lines = [rep("c1", f"It is {price}, on a 24-month term."), ASK]
    lines.append(rep("c2", READBACK.replace("$68", "$60")))
    r1 = Ask(2, {"monthly_price": "6800", "term_months": "24"})
    r2 = offer(monthly="6000", revision=2)
    assert not _confirmed(r2, lines, asks=(r1,))
    assert _confirmed(r2, lines, asks=(2,))  # W2' alone: an ask for $60 confirms


# Two offers in one call (S1-SYS-115): a lexical W2 statement (before the ask)
# whose one value is another recorded offer's (a slot, or an implied flag whose
# fee the same sentence states) and not r's is about that offer, so it is
# ignored. After the ask (W1) every statement counts as about r.

O1_READBACK = (
    "It's just $55 a month for 12 months with a $99 activation fee. "
    "There are no other changes, and this offer has no expiry!"
)
O2_READBACK = (
    "You're looking at $62 a month on a 12-month term with no fees! "
    "There are no other changes, and it has no expiry."
)
O2_R1 = {"monthly_price": "6200", "term_months": "12"}  # the asked revision


def _o2() -> OfferPublic:
    return offer("o2", monthly="6200", term="12", fee=None, revision=2)


def test_d893db_the_first_offers_price_before_the_ask_is_its_own() -> None:
    """d893db seq 392: cp-9 read o1 back ($78) after o2's $69 and before the
    o2 ask; o2 r2, recorded from the answer, confirms when it is recorded.
    Kills: dropping the W2 filter, or matching an absent value."""
    o1 = offer("o1", monthly="7800", fee=None)
    o2 = offer("o2", monthly="6900", fee=None, revision=2)
    lines = [
        rep("cp-6", "This is my best and final offer: 69.00 monthly for 24 months."),
        rep("cp-9", "That is correct, it is 78.00 per month for 24 months with no "
                    "fees, no other changes, and no expiry."),
        ASK,
        rep("cp-11", "The monthly price is 69.00 for a 24 months term with no "
                     "fees, no other changes, and no expiry."),
    ]  # fmt: skip
    r1 = Ask(3, {"monthly_price": "6900", "term_months": "24"})
    assert not _confirmed(o2, lines, (r1,))  # before S1-SYS-115: W2 failed
    assert _confirmed(o2, lines, (r1,), rivals=(o1,))
    other = offer("o1", monthly="8000", fee=None)  # no open offer holds $78
    assert not _confirmed(o2, lines, (r1,), rivals=(other,))


def test_247b62_the_first_offers_fee_before_the_ask_is_its_own() -> None:
    """247b62 seq 496: cp-11 read o1 back ($55, its $99 fee: o1's implied
    fees_none is false) before the o2 ask. Kills: dropping the implied flags
    from the rival's values."""
    o1 = offer("o1", monthly="5500", term="12", fee="9900")
    lines = [rep("c1", O1_READBACK), ASK, rep("c2", O2_READBACK)]
    assert not _confirmed(_o2(), lines, (Ask(2, O2_R1),))
    assert _confirmed(_o2(), lines, (Ask(2, O2_R1),), rivals=(o1,))


@pytest.mark.parametrize(
    "before",
    [
        "The $62 a month plan for 12 months comes with a $99 activation fee.",
        "I can also do $62 a month for 12 months. "
        "That one also has the $99 activation fee.",
    ],
)
def test_the_other_offers_fee_said_of_this_offer_blocks(before: str) -> None:
    """Tier C round 1: a fee equal to o1's, said of o2 before the ask, is o2's
    hidden fee. The implied flag is o1's only if its sentence also states o1's
    price or term that o2 does not hold. Kills: crediting it on the fee alone."""
    o1 = offer("o1", monthly="5500", term="12", fee="9900")
    after = (
        "Sure: $62 a month for 12 months, no other fees, no other changes, no expiry."
    )
    lines = [rep("c1", O1_READBACK), rep("c2", before), ASK, rep("c3", after)]
    assert not _confirmed(_o2(), lines, (Ask(3, O2_R1),), rivals=(o1,))


def test_a_fee_the_other_offer_does_not_hold_still_blocks() -> None:
    """The rival's implied fees_none=false counts only for a sentence stating
    the rival's own fee: a $20 fee said of the $62 plan before the ask is a
    hidden fee, not o1's $99. Kills: an implied flag matched without its fee."""
    o1 = offer("o1", monthly="5500", term="12", fee="9900")
    lines = [
        rep("c1", O1_READBACK),
        rep("c2", "The $62 plan has a $20 activation fee."),
    ]
    lines += [ASK, rep("c3", O2_READBACK)]
    assert not _confirmed(_o2(), lines, (Ask(3, O2_R1),), rivals=(o1,))
    assert _confirmed(_o2(), [*lines[:1], *lines[2:]], (Ask(2, O2_R1),), rivals=(o1,))


def test_a_different_value_for_the_second_offer_before_the_ask_still_blocks() -> None:
    """ "o2 is $65" before the ask, then r2 at $62: that is a change across the
    ask, about o2 (no open offer holds $65). W2 (lexical) still fails."""
    o1 = offer("o1", monthly="5500", term="12", fee="9900")
    lines = [
        rep("c1", O1_READBACK),
        rep("c2", "The new offer is $65 a month for 12 months."),
    ]
    lines += [ASK, rep("c3", O2_READBACK)]
    assert not _confirmed(_o2(), lines, (Ask(3, _o2_terms()),), rivals=(o1,))


def test_a_rival_value_counts_only_in_its_own_field() -> None:
    """$65 is o1's fee, not its price: "$65 a month" before the ask is about
    o2. Kills: matching a rival's value in any field."""
    lines = [rep("c1", "The new offer is $65 a month for 12 months."), ASK]
    lines.append(rep("c2", O2_READBACK))
    o1 = offer("o1", monthly="5500", term="12", fee="6500")
    assert not _confirmed(_o2(), lines, (Ask(2, _o2_terms()),), rivals=(o1,))
    o1 = offer("o1", monthly="6500", term="12", fee="9900")  # o1's price: o1's
    assert _confirmed(_o2(), lines, (Ask(2, _o2_terms()),), rivals=(o1,))


def test_a_two_valued_statement_is_never_ascribed() -> None:
    """Only a statement of one value is another offer's. Kills: matching any
    overlap with the rival's values."""
    o1 = offer("o1", monthly="5500", term="12", fee=None)
    lines = [rep("c1", "It is either $55 or $62 a month for 12 months."), ASK]
    lines.append(rep("c2", O2_READBACK))
    assert not _confirmed(_o2(), lines, (Ask(2, O2_R1),), rivals=(o1,))


def test_after_the_ask_every_statement_is_about_r() -> None:
    """W1 fails closed: o1's ask, its answer, o2's offer and ask, o2's answer.
    o2 confirms (o1's read-back before o2's ask is o1's); o1 does not, since
    o2's $69 after o1's ask counts against o1 (d893db seq 350, accepted).
    Kills: filtering W1 too."""
    o1 = offer("o1", monthly="7800", fee=None)
    o2 = offer("o2", monthly="6900", fee=None, revision=2)
    full = "{} per month for 24 months with no fees, no other changes, and no expiry."
    lines = [
        rep("c0", "I can offer 78.00 per month for 24 months."), ASK,
        rep("c1", "It is " + full.format("78.00")),
        rep("c2", "This is my best and final offer: 69.00 monthly for 24 months."), ASK,
        rep("c3", "The terms are " + full.format("69.00")),
    ]  # fmt: skip
    a1, a2 = Ask(2, _terms(o1)), Ask(5, {"monthly_price": "6900", "term_months": "24"})
    assert not _confirmed(o1, lines, (a1,), rivals=(o2,))
    assert _confirmed(o2, lines, (a2,), rivals=(o1,))


def test_a_correction_to_the_other_offers_value_after_the_ask_blocks() -> None:
    """A "sorry, it's $55 after all" after o2's read-back names o1's price: after
    the ask it counts as about o2, so o2 reverts. Kills: filtering W1."""
    o1 = offer("o1", monthly="5500", term="12", fee="9900")
    lines = [rep("c1", O1_READBACK), ASK, rep("c2", O2_READBACK)]
    assert _confirmed(_o2(), lines, (Ask(2, O2_R1),), rivals=(o1,))
    lines.append(rep("c3", "Sorry, it's $55 a month after all."))
    assert not _confirmed(_o2(), lines, (Ask(2, O2_R1),), rivals=(o1,))
    lines[-1] = rep("c3", O1_READBACK)  # o1 read back again, after o2's ask
    assert not _confirmed(_o2(), lines, (Ask(2, O2_R1),), rivals=(o1,))


def test_the_strict_rule_ignores_no_statement() -> None:
    """Only the window ascribes statements to another offer; this revision's
    own ask keeps the strict rule (o1's $78 after it is a contradiction)."""
    o1 = offer("o1", monthly="7800", fee=None)
    lines = [NOTHING, ASK, rep("c2", O2_READBACK)]
    lines.append(rep("c3", O2_READBACK.replace("$62", "$78")))
    got = slot_statuses(_o2(), lines, 2, (), (o1,))
    assert got["monthly_price"] != "confirmed"


def _terms(o: OfferPublic) -> dict[str, str]:
    return {s.field: s.value for s in o.slots}


def _o2_terms() -> dict[str, str]:
    return _terms(_o2())
