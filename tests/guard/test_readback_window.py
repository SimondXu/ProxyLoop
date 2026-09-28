"""One read-back window per offer (ADR-0020): an ask for any revision of the
offer, in the same call, confirms a revision when W1-W4 hold. Each negative
is red if one condition is dropped; the mutation each one pins is named."""

from __future__ import annotations

from collections.abc import Sequence

from tests.guard.build import READBACK, agent, offer, rep

from proxyloop.contract.state import Line, OfferPublic
from proxyloop.guard.readback import readback_status, readback_update, slot_statuses

ASK = agent("a1", "Could you read the full terms back to me?")
NOTHING = rep("c1", "I can offer you something.")


def _fold(
    o: OfferPublic, lines: Sequence[Line], asks: Sequence[int], asked_at: int | None
) -> OfferPublic:
    update = readback_update(o, lines, asked_at, asks)
    statuses = update["slot_statuses"]
    assert isinstance(statuses, dict)
    slots = tuple(s.model_copy(update={"status": statuses[s.field]}) for s in o.slots)
    return o.model_copy(update={"slots": slots, "terms_hash": update["terms_hash"]})


def _confirmed(
    o: OfferPublic,
    lines: Sequence[Line],
    asks: Sequence[int],
    asked_at: int | None = None,  # this revision's own ask: none by default
) -> bool:
    return readback_status(_fold(o, lines, asks, asked_at)) == "confirmed"


def _statuses(o: OfferPublic, lines: Sequence[Line], asks: Sequence[int]) -> set[str]:
    return set(slot_statuses(o, lines, None, asks).values())


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
    assert _confirmed(r3, lines, asks=(2,))


def test_a_hidden_fee_revealed_on_read_back_confirms() -> None:
    """r1 was price and term; the read-back revealed the fee, and r2 records it."""
    lines = [rep("c1", "It is $68 a month on a 24-month term."), ASK]
    lines.append(rep("c2", READBACK))  # reveals the $20 activation fee
    r2 = offer(revision=2)
    assert not _confirmed(r2, lines, asks=())
    assert _confirmed(r2, lines, asks=(2,))


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
    r1 = slot_statuses(offer(), lines, 2, (2,))
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
