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
    ],
)
def test_a_slot_the_read_back_cannot_confirm_is_refused_with_the_table(
    slot: dict[str, Any],
) -> None:
    result = record_offer(BB, "o1", [PRICE, slot | {"utt_ref": "cp-3"}], 0, NOW)
    assert not result.ok and not result.effects  # whole: no partial record
    assert TABLE_ROW in result.text and "String should match" not in result.text


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
