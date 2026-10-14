"""S1-SYS-113 (ADR-0033): Slow's close line agrees with Guard on filler after
the closing reply (247b62), a COMMITTED case escalates when the rep refuses the
voiced accept (b48f0f, 0a6cf0, 08f079), and a revision needs no ``expires``
slot. The test plays the kernel and world sides (tests/slow/test_authority)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.slow.test_authority import BOUND, CHECK, DONE, KEYS, Host
from tests.slow.test_authority import _accepted as accepted  # pyright: ignore
from tests.slow.test_authority import _committed as committed  # pyright: ignore
from tests.slow.test_authority import _granted as granted  # pyright: ignore
from tests.slow.test_authority import _heard as heard  # pyright: ignore
from tests.slow.test_close_levers import BEST, FINAL, NO_REPLY, TELL
from tests.slow.test_close_levers import _agrees as agrees  # pyright: ignore
from tests.slow.test_close_levers import _close as close_of  # pyright: ignore
from tests.slow.test_close_levers import _declined as declined  # pyright: ignore
from tests.slow.test_close_levers import _refused as refused  # pyright: ignore

from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.state import CaseStatus
from proxyloop.contract.views import view_slow
from proxyloop.guard.readback import readback_status
from proxyloop.slow import prompt, state

FILLER = (  # verbatim from 247b62
    "No problem at all! How can I help with the account today?",
    "Sorry about that! How can I help with the account today?",
    "I completely understand.",
    "I'm sorry, but that offer is no longer available.",
)
REOPEN = (
    "Actually I can do $70",
    "How about 70 a month?",
    "Actually, I can waive the activation fee.",
    "Let me check with my supervisor.",
)


def _closed(tmp_path: Path) -> Host:
    """offer-1 declined, the final offer asked and heard, the rep closing."""
    h = declined(tmp_path)
    h.act(FINAL)
    h.voice()
    h.rep("cp-10", BEST)
    return h


@pytest.mark.parametrize("filler", FILLER)
def test_filler_after_the_closing_reply_still_verifies(
    tmp_path: Path, filler: str
) -> None:
    h = _closed(tmp_path)
    h.rep("cp-11", filler)
    h.rep("cp-12", filler)
    c = agrees(h)  # the close line's dry run is the real finish's verdict
    assert (c.reply, c.reasons) == ("cp-10", ()) and h.ended == ["no_deal"]
    assert h.bb.public.status is CaseStatus.VERIFIED_NO_DEAL


@pytest.mark.parametrize("later", REOPEN)
def test_a_line_that_reopens_blocks_both(tmp_path: Path, later: str) -> None:
    h = _closed(tmp_path)
    h.rep("cp-11", later)
    assert close_of(h).reply is None
    refused(h, NO_REPLY)
    h.rep("cp-12", FILLER[0])  # filler does not close it again
    refused(h, NO_REPLY)
    h.rep("cp-13", BEST)  # a new closing line does
    c = agrees(h)
    assert (c.reply, c.reasons) == ("cp-13", ()) and h.ended == ["no_deal"]


def test_filler_alone_is_no_closing_reply(tmp_path: Path) -> None:
    h = declined(tmp_path)
    h.act(FINAL)
    h.voice()
    h.rep("cp-10", FILLER[0])
    refused(h, NO_REPLY)


def test_the_user_told_after_the_closing_reply_counts_before_filler(
    tmp_path: Path,
) -> None:
    h = _closed(tmp_path)
    h.act(TELL)  # after the closing reply, before the filler
    h.rep("cp-11", FILLER[0])
    c = close_of(h)
    assert (c.reply, c.reasons, c.told) == ("cp-10", (), True)
    assert "tell_user" not in c.line()


REFUSED = "I'm sorry, but that offer is no longer available."  # 0a6cf0


def _refused_accept(tmp_path: Path) -> Host:
    """The accept released and heard (COMMITTED); the rep refuses it, and
    no ledger entry or confirmation follows."""
    h = accepted(tmp_path)
    (line,) = [e for e in h.of("speak.verbatim") if e.payload["kind"] == "accept"]
    released = h.emit(
        "speak.released", "kernel", {"lane": "cp", "cap_id": line.payload["cap_id"]},
        [line.event_id],
    )  # fmt: skip
    said = {"lane": "cp", "utt_id": "a-1", "text_generated": line.payload["text"]}
    said |= {"text_heard": line.payload["text"], "interrupted": False}
    h.delivered = h.emit("utt.delivered", "kernel", said, [released.event_id])
    committed(h)
    h.rep("cp-3", REFUSED)
    assert h.bb.public.status is CaseStatus.COMMITTED
    return h


def test_a_refused_accept_escalates_from_committed(tmp_path: Path) -> None:
    h = _refused_accept(tmp_path)
    c = close_of(h)
    line = c.line()
    assert line.startswith("close: ") and "COMMITTED" in line
    assert "tell_user that the accept was said but not confirmed" in line
    assert "finish(escalate" in line and "check_account" in line
    view = view_slow(h.bb, SlowViewMode.TRANSCRIPT, "b")
    bar = prompt.status_bar(view, h.bb.t_ms, None, state.bar(h.bb, "full", h.tools))
    assert line in bar
    early, again = h.act(DONE, {"tool": "accept_offer", "offer_ref": "save-2"})
    assert "needs EVIDENCE_PENDING; the case is COMMITTED" in early
    assert again.startswith("accept_offer: denied") and not h.ended
    (no_deal,) = h.act({"tool": "finish", "outcome": "no_deal", "summary": "x"})
    assert "needs IN_CALL" in no_deal
    (done,) = h.act({"tool": "finish", "outcome": "escalate", "summary": "x"})
    assert done == "finish: case closed" and h.ended == ["escalate"]
    assert h.bb.public.status is CaseStatus.ESCALATED
    assert len(h.of("action.authorized")) == 1  # nothing granted again


def test_the_prompt_names_the_committed_exit() -> None:
    for mode in SlowViewMode:
        assert "accept was said but not confirmed" in prompt.system(mode)


def test_a_confirmed_accept_still_reaches_evidence_not_escalation(
    tmp_path: Path,
) -> None:
    h = accepted(tmp_path)
    heard(h, {"terms": BOUND})
    account, done = h.act(CHECK, DONE)
    assert "binds the accepted terms" in account
    assert done == "finish: verified complete"


TERMS = "It is $69 a month on a 24-month term, no fees, and no other changes."
UNDATED = [  # no expires slot (ADR-0031: open for the call)
    {"field": "monthly_price", "value": "6900", "utt_ref": "cp-1"},
    {"field": "term_months", "value": "24", "utt_ref": "cp-1"},
    {"field": "fees_none", "value": "true", "utt_ref": "cp-1"},
    {"field": "changes_none", "value": "true", "utt_ref": "cp-1"},
]
ASK = {"tool": "guide_fast", "move": "ask_readback", "slots": ["offer:save-2"]}


def test_an_undated_offer_confirms_and_completes(tmp_path: Path) -> None:
    """expires is not required: the bar lists no missing slot, the read-back
    confirms it, it is accepted, and the ledger's ``expires: none`` binds it."""
    h = Host(tmp_path)
    assert "competitor.price_usd" in KEYS
    h.call()
    h.rep("cp-1", TERMS)
    record = {"tool": "record_offer", "offer_ref": "save-2", "offer_slots": UNDATED}
    h.act(record, ASK)
    view = view_slow(h.bb, SlowViewMode.TRANSCRIPT, "b")
    assert "not recorded" not in prompt.status_bar(view, h.bb.t_ms)
    h.voice()
    h.rep("cp-2", TERMS)
    h.tools.readback()
    o = h.bb.public.offers["save-2"]
    assert readback_status(o) == "confirmed" and o.terms_hash
    granted(h)
    h.act({"tool": "accept_offer", "offer_ref": "save-2"})
    assert h.bb.public.status is CaseStatus.COMMIT_AUTHORIZED
    heard(h, {"terms": BOUND})  # BOUND carries expires: none
    account, done = h.act(CHECK, DONE)
    assert "binds the accepted terms" in account
    assert done == "finish: verified complete"


def test_the_bar_lists_required_slots_without_expires(tmp_path: Path) -> None:
    h = Host(tmp_path)
    h.call()
    h.rep("cp-1", TERMS)
    two = UNDATED[:2]
    h.act({"tool": "record_offer", "offer_ref": "save-2", "offer_slots": two})
    view = view_slow(h.bb, SlowViewMode.TRANSCRIPT, "b")
    bar = prompt.status_bar(view, h.bb.t_ms)
    assert (
        "required slots not recorded: fee:*|fees_none, applied_change:*|changes_none;"
        in bar
    )
    assert "expires" not in bar
