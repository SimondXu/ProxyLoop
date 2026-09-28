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
    assert "record them" not in offers, offers  # keep-1's slots note: none now


def test_a_no_stop_line_without_a_relayed_revoke(tmp_path: Path) -> None:
    """NEEDS_REPLAN from the card's expiry, no REVOKE relayed: no stop line
    (a stop relayed only as a NOTE has none either: the SYSTEM clause is
    Slow's only cue then, tests/concurrency/test_stop_ends.py)."""
    h = _card(tmp_path)
    stale = {"previous": "AWAITING_APPROVAL", "status": "NEEDS_REPLAN"}
    h.emit("status.changed", "guard", stale, [h.root.event_id])
    assert not state.stopped(h.bb, h.bus.events)
    assert "\nstop: " not in _bar(h)


def _revoked_early(h: Host) -> None:
    """FastU relays a revoke while the case is IN_CALL (any mind change about
    anything pending): the kernel bumps the epoch, and nothing stales."""
    said = h.emit("user.msg", "kernel", {"text": "Hold on, not that one."})
    relay = {"msg_id": f"r1:{len(h.bus.events)}", "lane": "user", "gen_id": "u"}
    relay |= {"utt_ref": said.event_id, "type": "REVOKE", "text": "hold on"}
    got = h.emit("f2s.msg", "fast.user", relay, [said.event_id])
    bump = {"new": h.bb.epoch + 1, "reason": "f2s_revoke"}
    h.emit("authority.epoch", "kernel", bump, [got.event_id])
    assert h.bb.public.status is CaseStatus.IN_CALL


def _read_back(tmp_path: Path) -> Host:
    """x-user-mind-change's walk to keep-2 read back (IN_CALL, no card)."""
    mandate, states = fw.WALKS["x-user-mind-change"]
    bounds = dict(mandate)
    h = fw._verified(tmp_path, bounds.pop("cap"), **bounds)  # pyright: ignore[reportPrivateUsage]
    for name, step, _ in states:
        if step is not None:
            step(h)
        if name == "keep-2 read back":
            return h
    raise AssertionError("the walk has no keep-2 read back state")


def test_a_an_early_revoke_then_a_new_card_expiring_shows_no_stop_line(
    tmp_path: Path,
) -> None:
    """rev-269 M1: relays are never drained; an early REVOKE, then a card in
    the new epoch that expires: the replan is the expiry's, no stop line."""
    h = _read_back(tmp_path)
    _revoked_early(h)
    fw.request("keep-2")(h)
    card = h.bb.private.pending_approval
    assert card is not None and card.authority_epoch == h.bb.epoch
    (asked,) = h.of("approval.requested")
    expired = {"previous": "AWAITING_APPROVAL", "status": "NEEDS_REPLAN"}
    h.emit("status.changed", "guard", expired, [asked.event_id])
    assert not state.stopped(h.bb, h.bus.events)
    assert "\nstop: " not in _bar(h)


def test_a_slows_own_revoke_staling_the_card_shows_no_stop_line(
    tmp_path: Path,
) -> None:
    """Only FastU's relayed stop (``f2s_revoke``) opens the stop line: a card
    Slow's own revoke staled (the SYSTEM clause's act, which finishes in the
    same act) replans without one, even after an earlier relayed REVOKE."""
    h = _read_back(tmp_path)
    _revoked_early(h)
    fw.request("keep-2")(h)
    (got,) = h.act({"tool": "revoke", "reason": "the user said stop"})
    assert got.startswith("revoke: revoked"), got
    (bump,) = [
        e for e in h.of("authority.epoch") if e.payload["reason"] == "slow_revoke"
    ]
    stale = {"previous": "AWAITING_APPROVAL", "status": "NEEDS_REPLAN"}
    h.emit("status.changed", "guard", stale, [bump.event_id])
    assert not state.stopped(h.bb, h.bus.events)
    assert "\nstop: " not in _bar(h)


def test_a_a_revoked_accept_after_an_early_revoke_shows_no_stop_line(
    tmp_path: Path,
) -> None:
    """rev-269 M1 and case (e): the replan is the revoked accept's
    (``accept_revoked``, caused by ``speak.revoked``), not a revoke's."""
    h = _read_back(tmp_path)
    _revoked_early(h)
    fw.request("keep-2")(h)
    fw.granted(h)
    fw.accept("keep-2")(h)
    assert h.bb.public.status is CaseStatus.COMMIT_AUTHORIZED
    (cap,) = h.bb.capabilities
    (minted,) = h.of("action.authorized")
    why = {"cap_id": cap, "reason": "fence"}
    revoked = h.emit("speak.revoked", "kernel", why, [minted.event_id])
    back = {"previous": "COMMIT_AUTHORIZED", "status": "NEEDS_REPLAN"}
    h.emit("status.changed", "guard", back, [revoked.event_id])
    assert not state.stopped(h.bb, h.bus.events)
    assert "\nstop: " not in _bar(h)


def test_a_no_stop_line_after_a_released_accept(tmp_path: Path) -> None:
    h = _card(tmp_path)
    fw.stop_relayed(h)
    assert state.stopped(h.bb, h.bus.events)
    cap = Capability(
        cap_id="cap-1", business_action_id="b", intent="accept_offer",
        terms_hash="t", epoch=1, expires_ms=1, consumed=True,
    )  # fmt: skip
    released = h.bb.model_copy(update={"capabilities": {"cap-1": cap}})
    assert not state.stopped(released, h.bus.events)


@pytest.mark.parametrize("mode", [R, T])
def test_a_the_prompt_says_the_stop_act(mode: SlowViewMode) -> None:
    flat = " ".join(prompt.system(mode).split())
    assert "or on the user's stop with a card pending or the case NEEDS_REPLAN" in flat
    assert (
        "The user's stop: when the user says stop or withdraws while a card is "
        "pending (AWAITING_APPROVAL) or the case is NEEDS_REPLAN, end the case in "
        "ONE act: revoke(reason) unless the case is already NEEDS_REPLAN, "
        "tell_user that nothing was accepted and the case is stopped, then "
        "finish(escalate, summary)."
    ) in flat
    other = (  # rev-269 M3: from IN_CALL no finish can pass: claim no stop
        "In any other state, revoke(reason) and tell_user that every grant is "
        "withdrawn and nothing will be accepted without the user's new approval; "
        "do not call finish."
    )
    assert other in flat
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
    assert close == (  # rev-269 M2: conditional, Guard's verdict kept
        "close: final offer asked; the rep's closing reply cp-10 states $69, which "
        "no recorded offer carries: if it is an offer the rep made, record_offer "
        "it first; otherwise tell_user the terms and the outcome before finish, "
        "and finish(no_deal) would verify"
    )
    h.act({"tool": "tell_user", "text": "No deal: the $78 offer was over your limit."})
    assert _line(h, "close: ", T).endswith(
        "record_offer it first; otherwise finish(no_deal) would verify"
    )


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


MENTIONS = {  # rev-269 M2, rev-269b N-1: amounts that may not be offers
    "competitor": ("That is the best offer I can provide; I cannot match "
                   "Brightwave's $60.", "$60"),
    "current": ("That is the best offer I can provide, or you stay at your "
                "current $85.", "$85"),
    "zero": ("That is the best offer I can provide, and the setup fee is $0.", None),
}  # fmt: skip
FACTS = (("competitor.price_usd", "60"), ("plan.current_price_usd", "85"))


def _facts(h: Host, msg: str, facts: tuple[tuple[str, str], ...]) -> None:
    """The user states ``facts`` in ``msg``; Slow records each from it."""
    told = h.emit("user.msg", "kernel", {"text": msg})
    for key, value in facts:
        call = {"tool": "record_fact", "key": key, "value": value}
        (got,) = h.act(call | {"utt_ref": told.event_id})
        assert got.startswith("record_fact: recorded"), got


def _noted(amount: str) -> str:
    return (
        f"close: final offer asked; the rep's closing reply cp-10 states {amount}, "
        "which no recorded offer carries: if it is an offer the rep made, "
        "record_offer it first; otherwise tell_user the terms and the outcome "
        "before finish, and finish(no_deal) would verify"
    )


@pytest.mark.parametrize("said", list(MENTIONS))
def test_m_a_fact_amount_gets_the_conditional_note_and_zero_none(
    tmp_path: Path, said: str
) -> None:
    """$0 is no offer: the plain verdict line. A current or a competitor's
    price the user stated (recorded facts) may still be an offer: the
    conditional note, with Guard's verdict kept (rev-269b N-1)."""
    text, amount = MENTIONS[said]
    h = _closed(tmp_path, text)
    _facts(h, "I pay $85 a month now; Brightwave offered me $60.", FACTS)
    plain = _line(h, "close: ", R)  # relay_only: no relay of cp-10
    assert plain.endswith("finish(no_deal) would verify"), plain
    assert "record_offer" not in plain, plain
    close = _line(h, "close: ", T)
    assert close == (plain if amount is None else _noted(amount)), close


def test_m_an_offer_at_the_users_limit_gets_the_note(tmp_path: Path) -> None:
    """rev-269b N-1: "$70 a month" with budget.max_monthly_usd=70 recorded
    (private) is an offer inside the mandate at its limit: not hidden."""
    h = _closed(tmp_path, "That is the best offer I can provide: $70 a month.")
    _facts(h, "I can pay at most $70 a month.", (("budget.max_monthly_usd", "70"),))
    assert h.bb.private.case_facts["budget.max_monthly_usd"].value == "70"
    assert _line(h, "close: ", T) == _noted("$70")


def test_m_is_for_full_cases_only(tmp_path: Path) -> None:
    """rev-269 M5b: an info_only close reports offers and records none after
    the fact; its line is Guard's verdict whatever the reply states."""
    h = _closed(tmp_path, UNRECORDED)
    more = state.bar(h.bb, "info_only", h.tools)
    bar = prompt.status_bar(view_slow(h.bb, T, "b"), h.now(), None, more)
    (close,) = [x for x in bar.splitlines() if x.startswith("close: ")]
    assert close.endswith("finish(info_only) allowed") and "$69" not in close, close
