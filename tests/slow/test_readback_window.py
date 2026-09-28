"""Slow's tools feed Guard every voiced read-back ask of an offer in this call
(ADR-0020): an ask never voiced, voiced by a speechless turn, for another
offer or from an earlier call never anchors, and statuses are recomputed on
every readback(), never copied."""

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


def _read_back_r2(h: Host, *before: dict[str, Any], voice: bool = True) -> None:
    """r1 (price, term) from cp-1, the asks in ``before`` (the newest guide
    voiced), the rep's full read-back (cp-2), then r2 recorded from it: the
    21988c shape."""
    h.rep("cp-1", PRICE_TERM)
    r1 = _slots("cp-1", ("monthly_price", "term_months"))
    h.act(RECORD | {"offer_slots": r1}, *before)
    if voice:
        h.voice()
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
    assert h.tools.asked == {("save-2", 1): ["s2f-1"]}  # r2 has no ask of its own
    assert _statuses(h) == {"confirmed"}


def test_n7_an_ask_for_another_offer_never_anchors(tmp_path: Path) -> None:
    h = Host(tmp_path)
    h.call()
    # the same price and term as save-2's, so W2' alone would not stop it
    h.rep("cp-0", "Or the same, $69 a month for 24 months, on another line.")
    other = [
        {"field": "monthly_price", "value": "6900", "utt_ref": "cp-0"},
        {"field": "term_months", "value": "24", "utt_ref": "cp-0"},
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
    h.voice()
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


HOLD: dict[str, Any] = {"tool": "guide_fast", "move": "ask_discount", "slots": []}


def test_n10_an_ask_never_voiced_never_anchors(tmp_path: Path) -> None:
    """#219 review D1: a newer guide in the same act superseded the ask
    (ADR-0013), so it was never spoken; the rep's unprompted statement of
    every term is no read-back."""
    h = Host(tmp_path)
    h.call()
    _opened(h)
    _read_back_r2(h, _ask("save-2"), HOLD)
    assert h.bb.public.guidance_cp[-1].move == "ask_discount"
    assert not [e for e in h.of("s2f.voiced") if "readback" in str(e.payload)]
    assert "confirmed" not in _statuses(h)


def test_n10_an_ask_voiced_by_a_speechless_turn_never_anchors(tmp_path: Path) -> None:
    """S1-SYS-21's rule: a voicing by a turn with no speech was never heard."""
    h = Host(tmp_path)
    h.call()
    _opened(h)
    h.rep("cp-1", PRICE_TERM)
    r1 = _slots("cp-1", ("monthly_price", "term_months"))
    h.act(RECORD | {"offer_slots": r1}, _ask("save-2"))
    h.voice(spoke=False)
    h.rep("cp-2", TERMS)
    h.act(RECORD | {"offer_slots": _slots("cp-2")})
    assert "confirmed" not in _statuses(h)


def _asked_r1(h: Host) -> None:
    """The call, r1 (price, term) from cp-1 and Slow's read-back ask for it."""
    h.call()
    _opened(h)
    h.rep("cp-1", PRICE_TERM)
    r1 = _slots("cp-1", ("monthly_price", "term_months"))
    h.act(RECORD | {"offer_slots": r1}, _ask("save-2"))


def test_the_window_opens_after_the_delivery_not_the_ask(tmp_path: Path) -> None:
    """The rep's full statement between the ask and its delivery is before
    the window; only a restatement after the whole delivery confirms."""
    h = Host(tmp_path)
    _asked_r1(h)
    h.rep("cp-2", TERMS)  # before the ask was spoken
    h.act(RECORD | {"offer_slots": _slots("cp-2")})
    h.voice()
    assert "confirmed" not in _statuses(h)
    h.rep("cp-3", TERMS)
    assert _statuses(h) == {"confirmed"}


def test_da_a_rep_line_between_voicing_and_delivery_never_anchors(
    tmp_path: Path,
) -> None:
    """#219 D-A (backlog): s2f.voiced comes with the fast.turn, before the
    sentence plays; a stale reply landing in between is no read-back."""
    h = Host(tmp_path)
    _asked_r1(h)
    gen = h.voice(deliver=False)
    h.rep("cp-2", TERMS)
    h.deliver(gen)
    h.act(RECORD | {"offer_slots": _slots("cp-2")})
    assert "confirmed" not in _statuses(h)


def test_da_a_barge_in_cut_never_anchors(tmp_path: Path) -> None:
    """#219 D-A: the rep barged in and the ask was cut, so it was never heard
    whole; the rep's statement answers nothing."""
    h = Host(tmp_path)
    _asked_r1(h)
    gen = h.voice(deliver=False)
    h.rep("cp-2", TERMS)
    h.deliver(gen, interrupted=True)
    h.act(RECORD | {"offer_slots": _slots("cp-2")})
    h.rep("cp-3", TERMS)
    assert "confirmed" not in _statuses(h)


def test_da_a_whole_delivery_then_the_answer_confirms(tmp_path: Path) -> None:
    h = Host(tmp_path)
    _asked_r1(h)
    gen = h.voice(deliver=False)
    assert "confirmed" not in _statuses(h)
    h.deliver(gen)
    h.rep("cp-2", TERMS)
    h.act(RECORD | {"offer_slots": _slots("cp-2")})
    assert _statuses(h) == {"confirmed"}


def test_db_an_unvoiced_ask_never_anchors_the_strict_rule(tmp_path: Path) -> None:
    """#219 D-B: the revision's own ask, superseded by a later guide in the same
    act (ADR-0013), was never spoken; the rep's restatement confirms nothing."""
    h = Host(tmp_path)
    h.call()
    _opened(h)
    h.rep("cp-1", TERMS)
    h.act(RECORD | {"offer_slots": _slots("cp-1")}, _ask("save-2"), HOLD)
    assert not h.of("s2f.voiced")
    h.rep("cp-2", TERMS)
    assert "confirmed" not in _statuses(h)
    h.voice()  # the hold, voiced and heard: still no read-back ask
    h.rep("cp-3", TERMS)
    assert "confirmed" not in _statuses(h)


def test_db_a_cut_ask_never_anchors_the_strict_rule(tmp_path: Path) -> None:
    """#219 D-B: the revision's own ask was cut mid-sentence by a barge-in, so
    it was never heard whole; the rep's restatement of every slot confirms
    nothing."""
    h = Host(tmp_path)
    h.call()
    _opened(h)
    h.rep("cp-1", TERMS)
    h.act(RECORD | {"offer_slots": _slots("cp-1")}, _ask("save-2"))
    h.deliver(h.voice(deliver=False), interrupted=True)
    h.rep("cp-2", TERMS)
    assert h.bb.public.offers["save-2"].revision == 1
    assert "confirmed" not in _statuses(h)


def test_db_the_strict_rule_opens_after_the_delivery(tmp_path: Path) -> None:
    h = Host(tmp_path)
    h.call()
    _opened(h)
    h.rep("cp-1", TERMS)
    h.act(RECORD | {"offer_slots": _slots("cp-1")}, _ask("save-2"))
    gen = h.voice(deliver=False)
    h.rep("cp-2", TERMS)  # said before the ask was heard
    assert "confirmed" not in _statuses(h)
    h.deliver(gen)
    assert "confirmed" not in _statuses(h)
    h.rep("cp-3", TERMS)
    assert _statuses(h) == {"confirmed"}


def test_n10_an_ask_voiced_by_a_cancelled_turn_never_anchors(tmp_path: Path) -> None:
    """S1-SYS-59's rule: a voicing turn later cancelled (any reason) was never
    heard, though it had speech."""
    h = Host(tmp_path)
    h.call()
    _opened(h)
    h.rep("cp-1", PRICE_TERM)
    r1 = _slots("cp-1", ("monthly_price", "term_months"))
    h.act(RECORD | {"offer_slots": r1}, _ask("save-2"))
    h.voice()
    cut = {"gen_id": h.of("fast.turn")[-1].payload["gen_id"], "reason": "verbatim"}
    h.emit("fast.cancelled", "fast.cp", cut, [h.of("fast.turn")[-1].event_id])
    h.rep("cp-2", TERMS)
    h.act(RECORD | {"offer_slots": _slots("cp-2")})
    assert "confirmed" not in _statuses(h)


def test_d5_an_ask_for_a_closed_offer_opens_no_window(tmp_path: Path) -> None:
    h = Host(tmp_path)
    h.call()
    h.rep("cp-1", TERMS)
    h.act(RECORD | {"offer_slots": _slots("cp-1")})
    h.act({"tool": "decline_offer", "offer_ref": "save-2", "reason": "too high"})
    assert h.bb.public.offers["save-2"].status != "open"
    h.act(_ask("save-2"))
    assert h.tools.readback_asks == {}


def test_n11_an_answer_that_changes_the_asked_revision(tmp_path: Path) -> None:
    """W2' (#219 D2): r1 at $68 from a line with no role cue; the answer to its
    ask says $60; r2 at $60 stays unconfirmed."""
    h = Host(tmp_path)
    h.call()
    h.rep("cp-1", "It is $68, on a 24-month term.")
    r1 = [
        {"field": "monthly_price", "value": "6800", "utt_ref": "cp-1"},
        {"field": "term_months", "value": "24", "utt_ref": "cp-1"},
    ]
    h.act(RECORD | {"offer_slots": r1}, _ask("save-2"))
    h.voice()
    h.rep("cp-2", TERMS.replace("$69", "$60"))
    r2 = [s | {"value": "6000"} if s["value"] == "6900" else s for s in SLOTS]
    (text,) = h.act(RECORD | {"offer_slots": [s | {"utt_ref": "cp-2"} for s in r2]})
    assert text == "record_offer: recorded save-2 r2", text
    assert "confirmed" not in _statuses(h)
