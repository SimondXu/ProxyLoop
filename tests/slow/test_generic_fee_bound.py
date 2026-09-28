"""S1-SYS-87 D3 bound (L-CORE option A): a fee the rep names only by generic
words can never be recorded, so the read-back "asked k times" stop rule counts a
revision's required fields that are not recorded (Guard's
``missing_required``) as omitted in each read-back window that got a reply;
after ``STOP_AFTER`` such windows the stuck clause is the one next step, and
it says "not recorded", never "not stated" (I11: the rep may have stated the
fee without naming it; rev-274 D4). A fee stated and recorded in the first
window is a new revision: that window is never held against it
(cp-hidden-fee-readback's success path)."""

from __future__ import annotations

from pathlib import Path

from tests.slow import test_discount_first as first
from tests.slow import test_family_walks as fw
from tests.slow.test_authority import Host

from proxyloop.slow import state

_bar, _verified = first._bar, first._verified  # pyright: ignore[reportPrivateUsage]

GENERIC = (  # the read-back names the fee only by generic words
    "It is $55 a month on a 12-month term, an upfront fee of $99, no other "
    "changes, and the offer does not expire."
)
STUCK = "omitted from 2 read-backs: fee:*|fees_none → not recorded: if a reply "
STOP = (
    "otherwise stop asking, report them to the user as not recorded (for a fee "
    "the rep stated without naming it: its amount, as an unnamed fee), then "
    "decline_offer and guide_fast(ask_final_offer)"
)


def _hidden(tmp_path: Path) -> Host:
    """cp-hidden-fee-readback: promo-1 recorded with price and term only
    (inside the $65/12/$0 mandate), its read-back asked."""
    h = _verified(tmp_path, 6500, max_term_months=12, max_one_time_fees_minor=0)
    fw.SENT(h)
    fw.offer("promo-1", 55, 12, None, False)(h)
    fw.ask_readback("promo-1")(h)
    return h


def _rep(h: Host, text: str) -> str:
    h.voice()
    utt = f"cp-{len(h.bb.channels['cp'].lines) + 1}"
    h.rep(utt, text)
    return utt


def _record(h: Host, fields: dict[str, str], utt: str) -> str:
    slots = [{"field": f, "value": v, "utt_ref": utt} for f, v in fields.items()]
    (got,) = h.act(
        {"tool": "record_offer", "offer_ref": "promo-1", "offer_slots": slots}
    )
    return got


def _promo(h: Host) -> str:
    return fw._entry(h, "promo-1")  # pyright: ignore[reportPrivateUsage]


def test_the_generic_fee_loop_ends_in_the_stuck_clause(tmp_path: Path) -> None:
    h = _hidden(tmp_path)
    utt = _rep(h, GENERIC)
    fields = fw._fields(55, 12, ("upfront", 99))  # pyright: ignore[reportPrivateUsage]
    got = _record(h, fields, utt)
    assert "fee:upfront: 'upfront' is a generic word" in got, got
    assert got.endswith(
        "fee:upfront: if the rep named this fee by no specific word, record_offer "
        'the other slots, then guide_fast(ask_readback, ["offer:promo-1"]) once '
        "more; a fee must be named by the rep to be recorded"
    ), got
    # the refusal's step: record the other slots, ask the read-back once more
    rest = {f: v for f, v in fields.items() if not f.startswith("fee:")}
    assert _record(h, rest, utt).startswith("record_offer: recorded promo-1 r2")
    fw.ask_readback("promo-1")(h)
    _rep(h, GENERIC)
    assert STUCK not in _promo(h), _promo(h)  # one window: ask once more
    assert fw.next_steps(h) == {"promo-1"}, _bar(h)
    fw.ask_readback("promo-1")(h)
    _rep(h, GENERIC)
    entry = _promo(h)
    assert STUCK in entry and STOP in entry, entry
    assert "not stated" not in entry, entry  # the rep stated $99 (I11)
    # rev-274 D3: the inside offer's step defers to the stuck clause: one step
    assert "inside the granted mandate → read-back stuck (see note)" in entry
    assert fw.next_steps(h) == {"ask_final_offer"}, _bar(h)
    r = state.bar(h.bb, "full", h.tools).readbacks[("promo-1", 2)]
    assert r.asked == 2 and r.stuck == ("fee:*|fees_none",), r


def test_a_fee_stated_in_the_first_read_back_is_recorded_and_the_walk_goes_on(
    tmp_path: Path,
) -> None:
    """Root's addendum: the first read-back states the named fee; before Slow
    records it, that window is not held against promo-1 r1 (no stuck clause:
    record it is the step); Slow records r2 with the fee, and the walk goes
    on unchanged (mention_tenure next)."""
    h = _hidden(tmp_path)
    fee = ("installation", 99)
    utt = _rep(h, fw._said(55, 12, fee))  # pyright: ignore[reportPrivateUsage]
    before = _promo(h)
    assert "stuck" not in before and "stop asking" not in before, before
    assert "record them from the rep line that states them" in before, before
    assert state.bar(h.bb, "full", h.tools).readbacks[("promo-1", 1)].stuck == ()
    fields = fw._fields(55, 12, fee)  # pyright: ignore[reportPrivateUsage]
    assert _record(h, fields, utt).startswith("record_offer: recorded promo-1 r2")
    slots = {s.field: s.value for s in h.bb.public.offers["promo-1"].slots}
    assert slots["fee:installation"] == "9900"
    assert "stuck" not in _promo(h) and "stop asking" not in _bar(h), _bar(h)
    assert fw.next_steps(h) == {"mention_tenure"}, _bar(h)


def test_a_partial_revision_read_back_whole_is_not_stuck(tmp_path: Path) -> None:
    """A partial revision whose read-back states every term, and whose next
    revision Slow records from it, is never made stuck."""
    h = _hidden(tmp_path)
    utt = _rep(h, fw._said(55, 12, None))  # pyright: ignore[reportPrivateUsage]
    assert state.bar(h.bb, "full", h.tools).readbacks[("promo-1", 1)].stuck == ()
    fields = fw._fields(55, 12, None)  # pyright: ignore[reportPrivateUsage]
    assert _record(h, fields, utt).startswith("record_offer: recorded promo-1 r2")
    fw.ask_readback("promo-1")(h)
    fw.read_back("promo-1", 55, 12)(h)
    fw.ask_readback("promo-1")(h)
    fw.read_back("promo-1", 55, 12)(h)
    r = state.bar(h.bb, "full", h.tools).readbacks[("promo-1", 2)]
    assert r.asked == 2 and r.stuck == (), r
    assert "stuck" not in _promo(h) and "stop asking" not in _promo(h), _promo(h)


def test_a_recorded_slot_omitted_twice_is_still_not_stated(tmp_path: Path) -> None:
    """rev-274 D4: only a field never recorded reads "not recorded"; a
    recorded slot two read-backs omitted keeps "not stated", and a revision
    with both names each."""
    h = _hidden(tmp_path)
    for _ in range(2):
        _rep(h, "Yes, it is $55 a month.")  # the term omitted, fees unrecorded
        fw.ask_readback("promo-1")(h)
    entry = _promo(h)
    unrec = "applied_change:*|changes_none, expires, fee:*|fees_none"
    both = (
        f"omitted from 2 read-backs: {unrec}, term_months → term_months not "
        f"stated as recorded, {unrec} not recorded: if a reply states them, "
        "record_offer a new revision citing that line; otherwise stop asking, "
        f"report them to the user: term_months as not stated, {unrec} as not "
        "recorded (for a fee"
    )
    assert both in entry, entry
