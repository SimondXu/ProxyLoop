"""Slow's tools feed Guard every read-back ask of an offer in this call
(ADR-0020): an ask for another offer or from an earlier call never anchors,
and statuses are recomputed on every readback(), never copied."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from tests.slow.test_authority import SLOTS, TERMS, Host

RECORD = {"tool": "record_offer", "offer_ref": "save-2"}
PRICE_TERM = "I can offer a monthly price of $69 with a term of 24 months."


def _ask(ref: str) -> dict[str, Any]:
    return {"tool": "guide_fast", "move": "ask_readback", "slots": [f"offer:{ref}"]}


def _slots(utt: str, fields: tuple[str, ...] = ()) -> list[dict[str, str]]:
    return [s | {"utt_ref": utt} for s in SLOTS if not fields or s["field"] in fields]


def _statuses(h: Host, ref: str = "save-2") -> set[str]:
    h.tools.readback()
    return {s.status for s in h.bb.public.offers[ref].slots}


def _opened(h: Host, call: int = 1) -> None:
    said = {"lane": "cp", "call": call, "reason": "ready"}
    h.emit("chan.opened", "kernel", said, [h.root.event_id])


def _read_back_r2(h: Host, *before: dict[str, Any]) -> None:
    """r1 (price, term) from cp-1, the asks in ``before``, the rep's full
    read-back (cp-2), then r2 recorded from it: the 21988c shape."""
    h.rep("cp-1", PRICE_TERM)
    r1 = _slots("cp-1", ("monthly_price", "term_months"))
    h.act(RECORD | {"offer_slots": r1}, *before)
    h.rep("cp-2", TERMS)
    (r2,) = h.act(RECORD | {"offer_slots": _slots("cp-2")})
    assert r2 == "record_offer: recorded save-2 r2", r2


def test_one_ask_confirms_the_revision_recorded_from_its_answer(
    tmp_path: Path,
) -> None:
    h = Host(tmp_path)
    h.call()
    _opened(h)
    _read_back_r2(h, _ask("save-2"))
    assert h.tools.asked == {("save-2", 1): 1}  # r2 has no ask of its own
    assert _statuses(h) == {"confirmed"}


def test_n7_an_ask_for_another_offer_never_anchors(tmp_path: Path) -> None:
    h = Host(tmp_path)
    h.call()
    h.rep("cp-0", "Or $55 a month for 12 months.")
    other = [
        {"field": "monthly_price", "value": "5500", "utt_ref": "cp-0"},
        {"field": "term_months", "value": "12", "utt_ref": "cp-0"},
    ]
    record = {"tool": "record_offer", "offer_ref": "save-3", "offer_slots": other}
    _read_back_r2(h, record, _ask("save-3"))
    assert "confirmed" not in _statuses(h)


def test_n7_an_ask_from_an_earlier_call_never_anchors(tmp_path: Path) -> None:
    h = Host(tmp_path)
    h.call()
    _opened(h)
    h.rep("cp-1", PRICE_TERM)
    r1 = _slots("cp-1", ("monthly_price", "term_months"))
    h.act(RECORD | {"offer_slots": r1}, _ask("save-2"))
    h.emit("chan.closed", "kernel", {"lane": "cp"}, [h.root.event_id])
    _opened(h, 2)  # a second call: its transcript runs on
    h.rep("cp-2", TERMS)
    h.act(RECORD | {"offer_slots": _slots("cp-2")})
    assert "confirmed" not in _statuses(h)


def test_n9_a_later_contradiction_reverts_a_confirmed_status(tmp_path: Path) -> None:
    h = Host(tmp_path)
    h.call()
    _read_back_r2(h, _ask("save-2"))
    assert _statuses(h) == {"confirmed"}
    assert h.bb.public.offers["save-2"].terms_hash is not None
    h.rep("cp-3", "Sorry, I misspoke: it is $75 a month.")
    assert "confirmed" not in _statuses(h)  # recomputed, not carried over
    (last,) = h.of("readback.updated")[-1:]
    statuses = cast(dict[str, str], last.payload["slot_statuses"])
    assert "confirmed" not in statuses.values()
