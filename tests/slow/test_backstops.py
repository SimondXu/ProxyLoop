"""S1-SYS-94 (run 8433bd): Slow backstops. (1) An amount a rep line states
that no recorded offer carries is named on the offers line, and the close
line then never says "would verify"; (2) record_fact citing a utt_ref that
names no line is refused. The test plays the kernel (rule 12: generic words)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from tests.slow import test_discount_first as first
from tests.slow.test_authority import Host

from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.views import view_slow
from proxyloop.slow import prompt, state

R, T = SlowViewMode.RELAY_ONLY, SlowViewMode.TRANSCRIPT
FINAL = {"tool": "guide_fast", "move": "ask_final_offer"}
OFFERED = "I can offer a monthly price of 78.00 with a term of 24 months."
CLOSING = "I'm afraid that is the best offer I can provide."
NOTE = (
    "cp-2 states $78.00, which no recorded offer carries: record_offer it if it "
    "is an offer, else record_fact it citing that line"
)


def _bar(h: Host, mode: SlowViewMode = T) -> list[str]:
    h.tools.readback()
    more = state.bar(h.bb, "full", h.tools)
    return prompt.status_bar(view_slow(h.bb, mode, "b"), h.now(), None, more).split(
        "\n"
    )


def _line(h: Host, head: str, mode: SlowViewMode = T) -> str:
    (line,) = [x for x in _bar(h, mode) if x.startswith(head)]
    return line


def _stated(tmp_path: Path) -> Host:
    """Verified, the discount asked and heard, and the rep states an offer
    (cp-2) that Slow never records."""
    h = first._verified(tmp_path, 6500, max_term_months=24)  # pyright: ignore[reportPrivateUsage]
    h.act(first.DISCOUNT)
    h.voice()
    h.rep("cp-2", OFFERED)
    return h


def _closed(h: Host, reply: str = CLOSING) -> None:
    """The final offer asked, heard, and the rep's closing reply."""
    h.act(FINAL)
    h.voice()
    h.rep(f"cp-{len(h.bb.channels['cp'].lines) + 1}", reply)
    c = state.close(h.bb, "full", h.tools.asked_final, h.tools.told_at)
    assert c.reply is not None and c.reasons == (), c  # Guard: it verifies


# (a) an unrecorded offer line: named on the offers line; no "would verify"


def test_a_an_unrecorded_offer_line_is_named_and_blocks_would_verify(
    tmp_path: Path,
) -> None:
    h = _stated(tmp_path)
    assert _line(h, "offers: ") == f"offers: none recorded; {NOTE}"
    _closed(h)
    close = _line(h, "close: ")
    assert "would verify" not in close, close
    assert close.endswith(
        "finish(no_deal) not yet: missing a record of cp-2's $78.00 (offers line)"
    ), close


def test_a_relay_only_sees_the_amount_only_as_relayed(tmp_path: Path) -> None:
    h = _stated(tmp_path)
    assert _line(h, "offers: ", R) == "offers: none"
    (said,) = [e for e in h.of("utt.final") if e.payload["utt_id"] == "cp-2"]
    h.relay(said, "rep offers 78.00 a month for 24 months")
    assert _line(h, "offers: ", R) == f"offers: none recorded; {NOTE}"
    _closed(h)
    assert "would verify" not in _line(h, "close: ", R)


def test_a_recording_the_offer_clears_the_note(tmp_path: Path) -> None:
    h = _stated(tmp_path)
    slots = [
        {"field": "monthly_price", "value": "7800", "utt_ref": "cp-2"},
        {"field": "term_months", "value": "24", "utt_ref": "cp-2"},
    ]
    (got,) = h.act({"tool": "record_offer", "offer_ref": "o-1", "offer_slots": slots})
    assert got.startswith("record_offer: recorded o-1 r1"), got
    assert "which no recorded offer carries" not in _line(h, "offers: ")


def test_a_the_stop_line_hides_the_note(tmp_path: Path) -> None:
    """While the user's stop is the one step, the note names no step."""
    h = _stated(tmp_path)
    stopped = replace(state.bar(h.bb, "full", h.tools), stop=True)
    view = view_slow(h.bb, T, "b")
    lines = prompt.status_bar(view, h.now(), None, stopped).splitlines()
    assert "offers: none" in lines, lines


# (b) no false positives


def test_b_an_amount_an_earlier_revision_carried_is_not_flagged(
    tmp_path: Path,
) -> None:
    """cp-2's $78 was recorded as o-1 r1; cp-3 revised it to $75 (o-1 r2)."""
    h = _stated(tmp_path)
    slots = [
        {"field": "monthly_price", "value": "7800", "utt_ref": "cp-2"},
        {"field": "term_months", "value": "24", "utt_ref": "cp-2"},
    ]
    h.act({"tool": "record_offer", "offer_ref": "o-1", "offer_slots": slots})
    h.rep("cp-3", "Sorry, I misspoke: it is $75 a month for 24 months.")
    slots[0] |= {"value": "7500", "utt_ref": "cp-3"}
    slots[1] |= {"utt_ref": "cp-3"}
    (got,) = h.act({"tool": "record_offer", "offer_ref": "o-1", "offer_slots": slots})
    assert got.startswith("record_offer: recorded o-1 r2"), got
    assert "which no recorded offer carries" not in _line(h, "offers: ")


@pytest.mark.parametrize(
    "said",
    [
        "Your account ending 4821 is on a 24-month term.",  # no money
        "The setup fee is $0 on this plan.",  # $0 is no offer
    ],
)
def test_b_a_non_price_number_follows_todays_rules(tmp_path: Path, said: str) -> None:
    h = first._verified(tmp_path, 6500, max_term_months=24)  # pyright: ignore[reportPrivateUsage]
    h.rep("cp-2", said)
    assert _line(h, "offers: ") == "offers: none"


def test_b_an_amount_a_recorded_fact_carries_is_not_flagged(tmp_path: Path) -> None:
    """The rep repeats the current price the user stated (a recorded fact);
    the rep's own mention can be recorded as a fact citing its line too."""
    h = first._verified(tmp_path, 6500, max_term_months=24)  # pyright: ignore[reportPrivateUsage]
    told = h.emit("user.msg", "kernel", {"text": "I pay $90 a month now."})
    fact = {"tool": "record_fact", "key": "plan.current_price_usd", "value": "90"}
    h.act(fact | {"utt_ref": told.event_id})
    h.rep("cp-2", "I see you pay $90.00 a month today.")
    assert _line(h, "offers: ") == "offers: none"
    h.rep("cp-3", "Our standard rate is $95.00 a month.")
    assert "cp-3 states $95.00" in _line(h, "offers: ")
    rate = {"tool": "record_fact", "key": "plan.standard_price_usd", "value": "95.00"}
    (got,) = h.act(rate | {"utt_ref": "cp-3"})
    assert got == "record_fact: recorded public", got
    assert _line(h, "offers: ") == "offers: none"


def test_b_the_closing_reply_keeps_its_own_note(tmp_path: Path) -> None:
    """The closing reply's amounts keep the F-m wording (rev-269 M2): only
    earlier rep lines move the close line off "would verify"."""
    h = first._verified(tmp_path, 6500, max_term_months=24)  # pyright: ignore[reportPrivateUsage]
    _closed(h, "That is the best offer I can provide: our best and final is $69.")
    assert _line(h, "offers: ") == "offers: none"
    assert _line(h, "close: ").endswith("and finish(no_deal) would verify")


# (c) record_fact citing no line is refused


def test_c_a_fabricated_utt_ref_is_refused_and_records_nothing(
    tmp_path: Path,
) -> None:
    h = Host(tmp_path)
    before = len(h.of("fact.recorded"))
    for ref in ("20260929T094406Z-c9bb59:1", None, "cp-9"):
        call = {"tool": "record_fact", "key": "tenure_years", "value": "5"}
        (got,) = h.act(call | ({"utt_ref": ref} if ref else {}))
        assert got.startswith("record_fact: utt_ref "), got
        assert "names no rep line, user message or user relay" in got, got
    assert len(h.of("fact.recorded")) == before
    tools = [e for e in h.of("slow.tool") if e.payload["name"] == "record_fact"]
    assert [e.payload["ok"] for e in tools] == [False] * 3


def test_c_a_user_message_ref_still_records(tmp_path: Path) -> None:
    h = Host(tmp_path)
    told = h.emit("user.msg", "kernel", {"text": "I've been with you for 5 years."})
    call = {"tool": "record_fact", "key": "tenure_years", "value": "5"}
    (got,) = h.act(call | {"utt_ref": told.event_id})
    assert got.startswith("record_fact: recorded "), got
    (rec,) = h.of("fact.recorded")
    assert rec.payload["source_ref"] == told.event_id


def test_c_a_rep_line_ref_still_records(tmp_path: Path) -> None:
    h = Host(tmp_path)
    h.call()
    h.rep("cp-1", "Your plan is $90.00 a month.")
    call = {"tool": "record_fact", "key": "plan.current_price_usd", "value": "90.00"}
    (got,) = h.act(call | {"utt_ref": "cp-1"})
    assert got == "record_fact: recorded public", got


def test_c_a_public_key_hides_its_stale_private_duplicate(tmp_path: Path) -> None:
    h = Host(tmp_path)
    wrong = h.emit("user.msg", "kernel", {"text": "It is for my neighbour."})
    name = {"tool": "record_fact", "key": "account.holder_name"}
    h.act(name | {"value": "Cynthia Robinson", "utt_ref": wrong.event_id})
    told = h.emit("user.msg", "kernel", {"text": "The name is Dana Reyes."})
    h.act(name | {"value": "Dana Reyes", "utt_ref": told.event_id})
    facts = _line(h, "facts: ")
    assert facts == 'facts: account.holder_name="Dana Reyes" [public]', facts
