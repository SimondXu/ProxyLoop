"""S1-SYS-28: offer recording converges. A slot Guard's read-back or terms code
could never confirm or hash is refused when recorded, whole, with the slot
table; re-recording the same terms is a no-op; a confirmed offer outside the
mandate shows the request_approval step in the status bar (run ed5063; the
bus-backed cases are in ``test_authority``)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from proxyloop.contract.state import Blackboard, ChannelState, Line
from proxyloop.slow.authority import HINTS
from proxyloop.slow.prompt import SYSTEM
from proxyloop.slow.tools import record_offer

REP = Line(
    utt_id="cp-3",
    speaker="partner",
    text="It is $75 a month for 12 months, no fees, valid until 2026-10-01 at 00:00.",
)
BB = Blackboard(channels={"user": ChannelState(), "cp": ChannelState(lines=(REP,))})
NOW = datetime(2026, 9, 26, tzinfo=UTC)
TABLE_ROW = "term_months → recurring, months"  # one row of the slot table


def _slot(field: str, value: str, unit: str, role: str) -> dict[str, Any]:
    return {"field": field, "value": value, "unit": unit, "role": role}


PRICE = _slot("monthly_price", "7500", "usd_minor", "recurring") | {"utt_ref": "cp-3"}


@pytest.mark.parametrize(
    "slot",
    [
        _slot("term_months", "12", "months", "expiry"),  # ed5063 r1: wrong role
        _slot("expires", "false", "bool", "expiry"),  # ed5063 r2: never confirmable
        _slot("expires", "false", "iso", "expiry"),
        _slot("expires", "2026-10-01", "iso", "expiry"),  # no zone: no terms hash
        _slot("fees_none", "True", "bool", "one_time"),
        _slot("fees_none", "yes", "bool", "one_time"),
        _slot("monthly_price", "7500", "months", "recurring"),  # wrong unit
        _slot("price", "7500", "usd_minor", "recurring"),  # ed5063 seq 538
        _slot("fee:activation", "20.00", "usd_minor", "one_time"),  # #166 N1
        _slot("term_months", "12 months", "months", "recurring"),
        _slot("term_months", 12, "months", "recurring"),  # type: ignore[arg-type]
        _slot("expires", "2026-10-01T00:00:00-05:00", "iso", "expiry"),  # 25 chars
    ],
)
def test_a_slot_the_read_back_cannot_confirm_is_refused_with_the_table(
    slot: dict[str, Any],
) -> None:
    result = record_offer(BB, "o1", [PRICE, slot | {"utt_ref": "cp-3"}], 0, NOW)
    assert not result.ok and not result.effects  # whole: no partial record
    assert TABLE_ROW in result.text and "String should" not in result.text


@pytest.mark.parametrize(
    ("slots", "why"),
    [
        ([], "no slots"),
        ([PRICE, PRICE], "monthly_price repeats"),
        (
            [PRICE, _slot("fees_none", "true", "bool", "one_time"),
             _slot("fee:activation", "2000", "usd_minor", "one_time")],
            "fees_none=true with fee:activation",
        ),
        (
            [PRICE, _slot("changes_none", "true", "bool", "change"),
             _slot("applied_change:plan", "true", "bool", "change")],
            "changes_none=true with applied_change:plan",
        ),
    ],
)  # fmt: skip
def test_slots_that_contradict_each_other_are_refused(
    slots: list[dict[str, Any]], why: str
) -> None:  # #166 N2: no terms hash could ever bind them
    slots = [s | {"utt_ref": "cp-3"} for s in slots]
    result = record_offer(BB, "o1", slots, 0, NOW)
    assert not result.ok and not result.effects and why in result.text


def test_the_table_bounds_the_iso_form() -> None:  # #166 N1: -05:00 is 25 chars
    assert "≤ 24 chars, prefer …Z" in SYSTEM


def test_the_table_is_guards_role_table_and_is_in_slows_prompt() -> None:
    for row in (
        "monthly_price → recurring, usd_minor",
        "expires → expiry, iso",
        "fees_none → one_time, bool, true|false",
        "fee:<code> → one_time, usd_minor",
    ):
        assert row in SYSTEM, row


def test_a_valid_record_passes() -> None:
    slots = [
        PRICE,
        _slot("term_months", "12", "months", "recurring") | {"utt_ref": "cp-3"},
        _slot("fees_none", "true", "bool", "one_time") | {"utt_ref": "cp-3"},
        _slot("expires", "2026-10-01T00:00:00Z", "iso", "expiry") | {"utt_ref": "cp-3"},
    ]
    result = record_offer(BB, "o1", slots, 0, NOW)
    assert result.ok, result.text
    ((type_, payload),) = result.effects
    assert type_ == "offer.recorded" and payload["revision"] == 1


def test_the_fence_hint_names_either_lane() -> None:
    """S1-SYS-23: a fence is a new user message or a rep turn during a queued
    accept; the hint must not say it is only a user message."""
    hint = HINTS["fence_raised"]
    assert "user message" in hint and "rep turn" in hint and "wait" in hint


@pytest.mark.parametrize(
    "said", ["a monthly price of 75.00", "$75 a month", "75 dollars a month"]
)
def test_money_binds_to_the_rep_line_that_says_it(said: str) -> None:
    """Run 84f731 (seq 363): Slow cited cp-8, the line after the offer, so the
    refusal was right; it now says how to cite and express money. Citing the
    line that says it binds 7500 cents to "$75" in any spoken form (I4)."""
    offer = Line(utt_id="cp-7", speaker="partner", text=f"I can offer {said}.")
    after = Line(utt_id="cp-8", speaker="partner", text="That is the best I can do.")
    cp = ChannelState(lines=(offer, after))
    bb = Blackboard(channels={"user": ChannelState(), "cp": cp})
    price = _slot("monthly_price", "7500", "usd_minor", "recurring")
    wrong = record_offer(bb, "o1", [price | {"utt_ref": "cp-8"}], 0, NOW)
    assert not wrong.ok and "monthly_price=7500 is not in rep line cp-8" in wrong.text
    assert "cite the utt of the rep line that says it" in wrong.text
    assert "usd_minor in cents (75.00 → 7500)" in wrong.text
    ((_, denied),) = wrong.effects  # counted as declass, the violation unchanged
    assert denied["violations"] == ["monthly_price=7500 is not in rep line cp-8"]
    right = record_offer(bb, "o1", [price | {"utt_ref": "cp-7"}], 0, NOW)
    assert right.ok, right.text
