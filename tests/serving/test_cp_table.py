"""The cp decision table's checks (ADR-0029): the classes profile_check leaves
unscored. Offline: no model call."""

from __future__ import annotations

from typing import Any

from tests.serving.test_profile_check import ARM, guided, on_hold
from tests.serving.test_teacher_select import TOK, cand, mk, user_view

from proxyloop.contract.messages import GuideMove
from proxyloop.contract.state import CaseStatus
from proxyloop.contract.views import FastView, Trigger
from scripts.mod import cp_table as ct

Json = dict[str, Any]


def checked(fv: FastView, raw: str) -> Json:
    v = mk(fv)
    return ct.check(cand(ARM, v, raw), v, TOK)


def done(fv: FastView, status: CaseStatus = CaseStatus.COMMITTED) -> FastView:
    return fv.model_copy(update={"status": status})


def test_a_standing_hold_is_repeated_when_the_rep_speaks() -> None:
    fv = on_hold(guided(GuideMove.ASK_DISCOUNT, "Are you still there?"), "decision")
    kept = checked(fv, "Still checking, thank you.\n@hold decision")
    assert (kept["rule"], kept["ok"]) == ("H4", True)
    assert checked(fv, "Still checking, thank you.")["ok"] is False  # ends the hold
    assert checked(fv, "Still checking.\n@hold offer")["ok"] is False  # other reason
    waited = fv.model_copy(update={"trigger": Trigger(kind="hold_wait", wait_s=20)})
    assert checked(waited, "Thanks for holding.\n@hold decision")["rule"] == "H4"


def test_new_guidance_that_is_not_a_hold_move_ends_the_hold() -> None:
    fv = on_hold(guided(GuideMove.ASK_FINAL_OFFER, trigger="guidance"), "decision")
    assert checked(fv, "Is this your best and final offer?")["ok"] is True
    late = checked(fv, "Is this your best and final offer?\n@hold decision")
    assert (late["rule"], late["ok"]) == ("H5", False)
    # A hold move on hold is H1, which profile_check scores.
    again = on_hold(guided(GuideMove.HOLD_FOR_FACT, trigger="guidance"), "decision")
    assert checked(again, "One moment.\n@hold fact_request")["rule"] is None


def test_after_a_commit_nothing_stalls() -> None:
    fv = done(guided(GuideMove.ASK_READBACK, "Your plan is updated."))
    clean = checked(fv, "Thank you very much.")
    assert (clean["rule"], clean["ok"], clean["s1_hits"]) == ("S1", True, [])
    assert checked(fv, "Thank you.\n@hold decision")["s1_hits"] == ["hold"]
    assert checked(fv, "Could you read that back to me?")["s1_hits"] == ["readback"]
    assert checked(fv, "I can't accept that myself.")["s1_hits"] == ["cant_accept"]
    # S1 overrides a standing hold, and covers the later statuses.
    held = done(on_hold(fv, "offer"), CaseStatus.VERIFIED_COMPLETE)
    assert checked(held, "Thanks.\n@hold offer")["s1_hits"] == ["hold"]
    assert checked(done(fv, CaseStatus.COMMIT_AUTHORIZED), "Thanks.")["rule"] is None


def test_stall_speech_and_a_hold_go_together() -> None:
    fv = guided(GuideMove.ASK_DISCOUNT, "Would you like to accept that?")
    both = checked(fv, "I need to check with my customer, please hold.\n@hold offer")
    assert both["incoherent"] is False
    assert checked(fv, "Please hold while I check with my customer.")["incoherent"]
    assert checked(fv, "Sure, sounds good.\n@hold offer")["incoherent"]
    assert checked(fv, "Could you lower the price?")["incoherent"] is False
    # The user lane has no hold: never scored.
    user = checked(user_view(lines=("hi",)), "One moment please.")
    assert (user["rule"], user["incoherent"]) == (None, False)


def test_tally_counts_each_rule_over_its_rows() -> None:
    fv = on_hold(guided(GuideMove.ASK_DISCOUNT, "Hello?"), "decision")
    rows = [
        checked(fv, "Still here.\n@hold decision"),
        checked(fv, "Still here."),
        checked(done(guided(GuideMove.ASK_DISCOUNT)), "Thanks.\n@hold offer"),
        checked(guided(GuideMove.ASK_DISCOUNT), "One moment please."),
    ]
    t = ct.tally(rows)
    assert t["H4"] == [1, 2] and t["H5"] == [0, 0] and t["S1"] == [0, 1]
    assert t["s1_hits"] == {"hold": 1, "readback": 0, "cant_accept": 0}
    # H7 is scored where no hold stands (H4 covers a standing one): rows 3 and 4.
    assert t["incoherent"] == [2, 2]
