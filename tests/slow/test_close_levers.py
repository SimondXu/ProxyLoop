"""ADR-0018 V3-V5 (S1-SYS-46): the status bar's ``close:`` line and the case
kind's playbook (F10), the read-back ask count and stop rule (F11), and the
``levers:`` line (F12). Rep lines are verbatim from runs e6ada1 and 527345;
fixtures assert refusal and status classes, and that each dry run agrees with
the tool it previews. The test plays the kernel."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from tests.slow.test_authority import Host
from tests.support.fakes import RepeatingLLM
from tests.support.manual_clock import ManualClock
from tests.support.sessions import fake

from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.views import view_slow
from proxyloop.slow import prompt, state
from proxyloop.slow.loop import SlowLoop

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

OFFER = "I can offer a monthly price of 78.00 with a term of 24 months."  # cp-8
RESTATED = (  # e6ada1 cp-13: no closing cue
    "The monthly price is 78.00 for a term of 24 months. There are no fees, no "
    "other changes, and no expiry."
)
BEST_RATE = "I'm afraid that really is the best rate I can offer for the account."
BEST = (
    "I'm afraid that is the best offer I can provide. I cannot go any lower than that."
)
CORRECT = "That is correct, that is the best offer I can provide."  # e6ada1 cp-17
SLOTS = [
    {"field": "monthly_price", "value": "7800", "utt_ref": "cp-8"},
    {"field": "term_months", "value": "24", "utt_ref": "cp-8"},
]
RECORD = {"tool": "record_offer", "offer_ref": "offer-1", "offer_slots": SLOTS}
READBACK = {"tool": "guide_fast", "move": "ask_readback", "slots": ["offer:offer-1"]}
FINAL = {"tool": "guide_fast", "move": "ask_final_offer"}
DECLINE = {"tool": "decline_offer", "offer_ref": "offer-1", "reason": "over limit"}
NO_DEAL = {"tool": "finish", "outcome": "no_deal", "summary": "no deal"}


def _close(h: Host, kind: state.Kind = "full") -> state.Close:
    return state.close(h.bb, kind, h.tools.asked_final, h.tools.told_at)


def _offered(tmp_path: Path) -> Host:
    h = Host(tmp_path)
    h.call()
    h.rep("cp-8", OFFER)
    assert h.act(RECORD, READBACK)[-1].endswith("read-back asked for offer-1 r1")
    return h


def _agrees(h: Host) -> state.Close:
    """The close line's dry run, then the real finish(no_deal): the same verdict."""
    c = _close(h)
    (got,) = h.act(NO_DEAL)
    assert got.startswith("finish: verified no deal" if not c.reasons else "finish: no")
    for reason in c.reasons:
        assert reason in got
    return c


def test_f10_e6ada1_restated_terms_after_the_last_ask_block_no_deal(
    tmp_path: Path,
) -> None:
    """e6ada1 seq 488: after ask_final_offer the rep only restated the terms, so
    finish(no_deal) was refused no_closing_reply; the close line says so first.
    cp-17's closing reply unblocks it."""
    h = _offered(tmp_path)
    h.rep("cp-9", BEST_RATE)
    c = _close(h)  # a closing cue, but the final offer was never asked (M1)
    assert (c.asked, c.reply) == (False, None) and "tell_user" not in c.line()
    assert set(c.reasons) == {"offer_open:offer-1", "final_offer_not_asked"}
    h.act(FINAL)
    h.rep("cp-13", RESTATED)
    c = _close(h)
    assert (c.asked, c.reply) == (True, None)
    assert set(c.reasons) == {"offer_open:offer-1", "no_closing_reply"}
    h.act(DECLINE)
    assert _agrees(h).reasons == ("no_closing_reply",)
    h.rep("cp-17", CORRECT)
    c = _agrees(h)
    assert (c.reply, c.reasons) == ("cp-17", ())
    assert h.ended == ["no_deal"]


def test_f10_527345_a_closing_reply_and_a_declined_offer_verify(
    tmp_path: Path,
) -> None:
    """527345 seq 334-355: the rep's reply to ask_final_offer closes; with the
    offer declined, finish(no_deal) would verify (VERIFIED_NO_DEAL)."""
    h = _offered(tmp_path)
    h.rep("cp-9", "I understand, but that is the best rate I can offer.")
    h.act(FINAL)
    h.rep("cp-10", BEST)
    c = _close(h)
    assert (c.asked, c.reply, c.reasons) == (True, "cp-10", ("offer_open:offer-1",))
    assert c.line().startswith("close: final offer asked; the rep's closing reply ")
    h.act(DECLINE)
    assert _agrees(h).reasons == ()
    assert h.ended == ["no_deal"]


def test_f10_info_only_finish_is_allowed_only_in_the_call(tmp_path: Path) -> None:
    h = Host(tmp_path)
    assert _close(h, "info_only").reasons == ("case_is:INTAKE",)
    (got,) = h.act({"tool": "finish", "outcome": "info_only", "summary": "s"})
    assert got.startswith("finish: finish(info_only) is not possible")
    h.call()
    h.rep("cp-1", BEST)  # mid-negotiation, before any ask (M1): no reply
    c = _close(h, "info_only")
    assert (c.reply, c.reasons) == (None, ()) and "tell_user" not in c.line()
    h.act(FINAL)
    h.rep("cp-2", BEST)
    c = _close(h, "info_only")
    assert (c.outcome, c.reply, c.reasons) == ("info_only", "cp-2", ())
    assert c.line().endswith("finish(info_only) allowed")


def _head(kind: state.Kind) -> str:
    mode = SlowViewMode.TRANSCRIPT
    host = SimpleNamespace(cfg=SimpleNamespace(slow_view=mode))
    host.task = SimpleNamespace(id="case-1", mode=kind)
    client = RepeatingLLM(fake("slow"), ["unused"], ManualClock())
    keys = frozenset({"competitor.price_usd", "tenure_years"})
    loop = SlowLoop(cast("Kernel", host), client, "brief", keys)
    return cast(str, cast(Any, loop)._head)


@pytest.mark.parametrize("kind", ["info_only", "full"])
def test_f10_the_head_carries_the_task_kind_and_its_own_playbook_only(
    kind: state.Kind,
) -> None:
    head = _head(kind)
    other = "full" if kind == "info_only" else "info_only"
    assert f"\nTASK KIND: {kind}\n" in head
    assert prompt.PLAYBOOK[kind] in head and prompt.PLAYBOOK[other] not in head
    # 21988c: share_fact on competitor keys; the head names what can go public
    assert "only tenure_years can go public" in head


REP_NO_EXPIRY = "It is $69 a month on a 24-month term, no fees, no other changes."
ASK = {"tool": "guide_fast", "move": "ask_readback", "slots": ["offer:save-2"]}


def _bar(h: Host, kind: state.Kind = "full") -> state.Bar:
    h.tools.readback()
    return state.bar(h.bb, kind, h.tools)


def test_f11_asks_are_counted_per_revision_and_two_stuck_read_backs_stop(
    tmp_path: Path,
) -> None:
    """f828f1: the rep restated the terms without the expiry after every ask.
    After two read-backs leaving ``expires`` unconfirmed, the bar says stop."""
    from tests.slow.test_authority import SLOTS as FULL
    from tests.slow.test_authority import TERMS

    h = Host(tmp_path)
    h.call()
    h.rep("cp-1", TERMS)
    record = {"tool": "record_offer", "offer_ref": "save-2", "offer_slots": FULL}
    h.act(record, ASK)
    h.rep("cp-2", REP_NO_EXPIRY)
    o = h.bb.public.offers["save-2"]
    b = _bar(h)
    assert state.unconfirmed(h.bb.public.offers["save-2"]) == {"expires"}
    assert b.readbacks[("save-2", 1)] == state.Readback(1, (), False)
    assert b.offer_note(o) == "read-back asked 1×"  # noqa: RUF001
    h.act(ASK)
    got = _bar(h).readbacks[("save-2", 1)]  # the rep has not replied yet
    assert got == state.Readback(2, (), False)
    h.rep("cp-3", REP_NO_EXPIRY)
    b = _bar(h)
    o = h.bb.public.offers["save-2"]
    assert b.readbacks[("save-2", 1)] == state.Readback(2, ("expires",), False)
    note = b.offer_note(o)
    assert "stop asking" in note and "decline_offer" in note
    assert "decline_offer" not in _bar(h, "info_only").offer_note(o)
    view = view_slow(h.bb, SlowViewMode.RELAY_ONLY, "b")
    bar = prompt.status_bar(view, h.bb.t_ms, None, b).splitlines()
    assert [x for x in bar if x.startswith("[STATUS]")] == ["[STATUS]"]
    assert [x.partition(":")[0] for x in bar[-2:]] == ["close", "levers"]
    assert note in bar[2]  # on the offers line
    lower = [
        x | {"value": "6500"} if x["field"] == "monthly_price" else x for x in FULL
    ]
    h.rep("cp-4", TERMS.replace("$69", "$65"))
    lower = [x | {"utt_ref": "cp-4"} for x in lower]
    (r2,) = h.act({**record, "offer_slots": lower})  # a new revision starts at 0
    assert r2.startswith("record_offer: recorded save-2 r2"), r2
    assert ("save-2", 2) not in _bar(h).readbacks
    assert _bar(h).offer_note(h.bb.public.offers["save-2"]) == ""


def _denied(h: Host) -> list[str]:
    return [str(e.payload["reason"]) for e in h.of("action.denied")]


def test_f12_levers_lists_only_what_guide_fast_would_refuse(tmp_path: Path) -> None:
    """0a921a/f828f1/84f731: cite_competitor without a shared quote, mention_tenure
    citing a private tenure, an unauthorised cancel_lever. Each class on the
    line is the one the real guide_fast refusal carries."""
    h = Host(tmp_path)
    h.call()
    got = dict(state.unavailable(h.bb))
    assert got == {
        "cite_competitor": "competitor_quote_not_shareable",
        "cancel_lever": "cancel_lever_not_authorized",
    }
    said = h.emit("user.msg", "kernel", {"text": "I've been with you for 6 years."})
    fact = {"key": "tenure_years", "value": "6", "utt_ref": said.event_id}
    h.act({"tool": "record_fact", **fact})  # not a shareable key here: private
    got = dict(state.unavailable(h.bb))
    assert got["mention_tenure"] == "guide_slot_not_public"
    tries = [
        {"tool": "guide_fast", "move": m, "slots": s}
        for m, s in (
            ("cite_competitor", ["fact:competitor.price_usd"]),
            ("mention_tenure", ["fact:tenure_years"]),
            ("cancel_lever", []),
        )
    ]
    h.act(*tries)
    assert _denied(h) == [got[str(t["move"])] for t in tries]
    line = state.levers_line(state.unavailable(h.bb))
    assert line.startswith("levers: ") and "ask_discount" not in line
    grant = {"key": "authorization.cancel_lever", "value": "granted"}
    grant |= {"source_ref": said.event_id, "source": "shareable"}
    h.emit("fact.recorded", "guard", grant | {"scope": "public"}, [said.event_id])
    assert "cancel_lever" not in dict(state.unavailable(h.bb))


def test_f12_no_unavailable_lever_says_so() -> None:
    assert state.levers_line(()) == "levers: all available"


TELL = {"tool": "tell_user", "text": "Their best is $78 a month; no deal."}
BYE = "Understood, have a good day."  # 21988c cp-25: the closing reply


def test_f10_21988c_the_user_is_told_after_the_closing_reply_before_finish(
    tmp_path: Path,
) -> None:
    """21988c (user.told_terms failed): Slow told the user at 267 s, before
    the rep's closing reply (cp-25 at 402 s), then finished. The close line
    keeps telling the user pending until a tell_user after that reply."""
    h = _offered(tmp_path)
    h.act(FINAL)
    h.rep("cp-16", BEST)
    h.act(TELL, DECLINE)  # told before the closing reply that counts
    h.rep("cp-25", BYE)
    c = _close(h)
    assert (c.reply, c.reasons, c.told) == ("cp-25", (), False)
    assert "tell_user" in c.line()
    h.act(TELL)
    c = _close(h)
    assert (c.reply, c.reasons, c.told) == ("cp-25", (), True)
    assert "tell_user" not in c.line()
    info = state.close(h.bb, "info_only", h.tools.asked_final, h.tools.told_at)
    assert info.told


HOW = "Sorry about that. How can I help with the account?"  # 21988c cp-15
UNDERSTAND = "I completely understand."  # 21988c cp-17


def _asked_twice(tmp_path: Path, first: str, second: str) -> Host:
    from tests.slow.test_authority import SLOTS as FULL
    from tests.slow.test_authority import TERMS

    h = Host(tmp_path)
    h.call()
    h.rep("cp-1", TERMS)
    record = {"tool": "record_offer", "offer_ref": "save-2", "offer_slots": FULL}
    h.act(record, ASK)
    h.rep("cp-2", first)
    h.act(ASK)
    h.rep("cp-3", second)
    return h


def test_f11_21988c_no_read_back_reply_is_not_a_stop(tmp_path: Path) -> None:
    """21988c r3 (D2): after both asks the rep restated nothing, so no slot
    was omitted from a read-back: no stop and no decline; the bar says the
    rep has not read the offer back."""
    h = _asked_twice(tmp_path, HOW, UNDERSTAND)
    o = h.bb.public.offers["save-2"]
    b = _bar(h)
    assert b.readbacks[("save-2", 1)] == state.Readback(2, (), True)
    note = b.offer_note(o)
    assert "not read the offer back" in note
    assert "decline" not in note and "not stated" not in note


def test_f11_one_omitting_reply_and_one_non_reply_do_not_stop_yet(
    tmp_path: Path,
) -> None:
    h = _asked_twice(tmp_path, REP_NO_EXPIRY, UNDERSTAND)
    b = _bar(h)
    assert b.readbacks[("save-2", 1)] == state.Readback(2, (), True)
    assert "decline" not in b.offer_note(h.bb.public.offers["save-2"])


DATED = (  # the rep reads back an expiry Slow recorded as none (M2)
    "It is $69 a month on a 24-month term, no fees, no other changes, "
    "and the offer expires on June 30, 2026."
)


def test_f11_a_slot_read_back_with_another_value_suggests_a_re_record(
    tmp_path: Path,
) -> None:
    h = _asked_twice(tmp_path, DATED, DATED)
    b = _bar(h)
    assert b.readbacks[("save-2", 1)] == state.Readback(2, ("expires",), False)
    assert "record_offer a new revision" in b.offer_note(h.bb.public.offers["save-2"])


def test_a_refused_tell_user_does_not_count_as_told(tmp_path: Path) -> None:
    h = Host(tmp_path)
    h.call()
    (got,) = h.act({"tool": "tell_user", "text": ""})
    assert "invalid arguments" in got and h.tools.told_at is None
