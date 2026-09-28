"""S1-SYS-83 (success-path audit, root decision 2026-09-29): a stop ends
cleanly. F-i (a): after the user's stop, relayed as a revoke that staled the
pending card (NEEDS_REPLAN), the status bar's stop line is the one next step
(tell_user, then finish(escalate)) and the close line names no competing step;
Slow's prompt says the stop act (SYSTEM and the full playbook). F-i (b): a
card of an older authority epoch is shown stale, never pending. F-m: the close
line never says finish(no_deal) would verify while the rep's closing reply
states a money amount no recorded offer carries, as Slow's view holds that
reply (its line in ``transcript`` mode, the cp relays citing it in both).
The test plays the kernel (the kernel-level runs: tests/concurrency)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.slow import test_close_levers as cl
from tests.slow import test_family_walks as fw
from tests.slow.test_authority import Host

from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.state import Capability, CaseStatus
from proxyloop.contract.views import view_slow
from proxyloop.slow import prompt, state

R, T = SlowViewMode.RELAY_ONLY, SlowViewMode.TRANSCRIPT


def _bar(h: Host, mode: SlowViewMode = R) -> str:
    h.tools.readback()
    more = state.bar(h.bb, "full", h.tools)
    return prompt.status_bar(view_slow(h.bb, mode, "b"), h.now(), None, more)


def _line(h: Host, head: str, mode: SlowViewMode = R) -> str:
    (line,) = [x for x in _bar(h, mode).splitlines() if x.startswith(head)]
    return line


def _card(tmp_path: Path) -> Host:
    """x-user-mind-change's walk to its pending card (tests/slow/test_family_walks)."""
    mandate, states = fw.WALKS["x-user-mind-change"]
    bounds = dict(mandate)
    h = fw._verified(tmp_path, bounds.pop("cap"), **bounds)  # pyright: ignore[reportPrivateUsage]
    for name, step, _ in states:
        if step is not None:
            step(h)
        if name == "card pending":
            return h
    raise AssertionError("the walk has no card pending state")


# F-i (a): the stop line


@pytest.mark.parametrize("mode", [R, T])
def test_a_the_relayed_stop_makes_the_stop_act_the_one_step(
    tmp_path: Path, mode: SlowViewMode
) -> None:
    h = _card(tmp_path)
    fw.stop_relayed(h)
    assert h.bb.public.status is CaseStatus.NEEDS_REPLAN
    assert _line(h, "stop: ", mode) == state.STOP
    close = _line(h, "close: ", mode)
    assert close == (
        "close: final offer not asked; the user stopped the case (stop line): "
        "finish(no_deal) does not apply"
    )
    assert "blocked" not in close
    levers = _line(h, "levers: ", mode)
    assert levers.startswith(f"levers: {state.STOPPED}: ")
    assert fw.next_steps(h) == {"escalate"}


def test_a_the_stop_act_escalates_and_the_line_leaves(tmp_path: Path) -> None:
    h = _card(tmp_path)
    fw.stop_relayed(h)
    fw.escalated(h)
    bar = _bar(h)
    assert "\nstop: " not in bar and "\ncase: ESCALATED;" in bar


def test_a_an_offer_gets_no_step_after_the_stop(tmp_path: Path) -> None:
    """The stop state with a lever still free: no offer hint and no
    available lever competes with the stop act."""
    h = _card(tmp_path)
    fw.stop_relayed(h)
    more = state.bar(h.bb, "full", h.tools)
    free = state.Bar(
        more.close, (), more.readbacks, {}, more.slots, more.identify, True,
        more.discount, more.stop,
    )  # fmt: skip
    got = prompt.status_bar(view_slow(h.bb, R, "b"), h.now(), None, free)
    (levers,) = [x for x in got.splitlines() if x.startswith("levers: ")]
    assert levers.startswith(f"levers: {state.STOPPED}: cite_competitor")
    (offers,) = [x for x in got.splitlines() if x.startswith("offers: ")]
    assert "→" not in offers and "comes first" not in offers, offers


def test_a_no_stop_line_without_a_relayed_revoke(tmp_path: Path) -> None:
    """NEEDS_REPLAN from the card's expiry, no REVOKE relayed: no stop line
    (a stop relayed only as a NOTE has none either: the SYSTEM clause is
    Slow's only cue then, tests/concurrency/test_stop_ends.py)."""
    h = _card(tmp_path)
    stale = {"previous": "AWAITING_APPROVAL", "status": "NEEDS_REPLAN"}
    h.emit("status.changed", "guard", stale, [h.root.event_id])
    assert not state.stopped(h.bb)
    assert "\nstop: " not in _bar(h)


def test_a_no_stop_line_after_a_released_accept(tmp_path: Path) -> None:
    h = _card(tmp_path)
    fw.stop_relayed(h)
    assert state.stopped(h.bb)
    cap = Capability(
        cap_id="cap-1", business_action_id="b", intent="accept_offer",
        terms_hash="t", epoch=1, expires_ms=1, consumed=True,
    )  # fmt: skip
    released = h.bb.model_copy(update={"capabilities": {"cap-1": cap}})
    assert not state.stopped(released)


@pytest.mark.parametrize("mode", [R, T])
def test_a_the_prompt_says_the_stop_act(mode: SlowViewMode) -> None:
    flat = " ".join(prompt.system(mode).split())
    assert "or on the user's stop (below)" in flat
    assert (
        "The user's stop: when the user says stop or withdraws, end the case in "
        "ONE act: revoke(reason) unless the case is already NEEDS_REPLAN, "
        "tell_user that nothing was accepted and the case is stopped, then "
        "finish(escalate, summary)."
    ) in flat
    full = prompt.PLAYBOOK["full"]
    assert "the user's stop comes first: while the stop line shows, its act is " in full
    assert "stop line" not in prompt.PLAYBOOK["info_only"]


# F-i (b): a stale card


def test_b_a_card_of_an_older_epoch_is_stale_not_pending(tmp_path: Path) -> None:
    h = _card(tmp_path)
    card = h.bb.private.pending_approval
    assert card is not None
    pending = _line(h, "approvals: ")
    assert pending.startswith(f"approvals: {card.approval_id} for keep-2 r2 pending")
    fw.stop_relayed(h)
    assert h.bb.private.pending_approval == card  # the fold keeps it
    assert _line(h, "approvals: ") == (
        f"approvals: {card.approval_id} for keep-2 r2 stale (authority changed; "
        "it cannot be granted)"
    )


# F-m: an amount the closing reply states that no recorded offer carries

UNRECORDED = "That is the best offer I can provide: our best and final is $69 a month."
RESTATES = "That is the best offer I can provide: $78.00 a month is final."


def _closed(tmp_path: Path, reply: str) -> Host:
    """offer-1 ($78) declined, the final offer asked and heard, and the rep's
    closing reply ``reply`` (cp-10): finish(no_deal) would verify."""
    h = cl._offered(tmp_path)  # pyright: ignore[reportPrivateUsage]
    h.act(cl.DECLINE)
    h.act(cl.FINAL)
    h.voice()
    h.rep("cp-10", reply)
    c = cl._close(h)  # pyright: ignore[reportPrivateUsage]
    assert (c.reply, c.reasons) == ("cp-10", ())  # Guard's verdict: it verifies
    return h


def test_m_an_unrecorded_amount_in_the_heard_reply_blocks_would_verify(
    tmp_path: Path,
) -> None:
    h = _closed(tmp_path, UNRECORDED)
    close = _line(h, "close: ", T)
    assert close == (
        "close: final offer asked; the rep's closing reply cp-10 states $69, which "
        "no recorded offer carries: record_offer it first; finish(no_deal) not "
        "before that"
    )
    assert "would verify" not in close


def test_m_relay_only_sees_the_amount_only_as_relayed(tmp_path: Path) -> None:
    """``relay_only`` holds no transcript: the line reads the cp relays that
    cite the closing reply, and without one it is Guard's verdict unchanged."""
    h = _closed(tmp_path, UNRECORDED)
    assert _line(h, "close: ", R).endswith("finish(no_deal) would verify")
    (said,) = [e for e in h.of("utt.final") if e.payload["utt_id"] == "cp-10"]
    h.relay(said, "rep: best and final is $69 a month")
    for mode in (R, T):
        close = _line(h, "close: ", mode)
        assert "states $69, which no recorded offer carries" in close, close


def test_m_a_reply_restating_a_recorded_amount_still_verifies(tmp_path: Path) -> None:
    h = _closed(tmp_path, RESTATES)
    for mode in (R, T):
        close = _line(h, "close: ", mode)
        assert close.endswith("finish(no_deal) would verify"), close


def test_m_unrecorded_reads_money_only() -> None:
    assert state.unrecorded((), ["a 24-month term, 12 months"]) == ()
    assert state.unrecorded((), ["$69.50 or 70 dollars"]) == ("$69.50", "$70")
