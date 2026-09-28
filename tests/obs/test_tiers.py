"""The outcome tiers (``obs.tiers``, S1-SYS-68) on hand-built event logs: one
log per tier, X over everything, the verified no-deal mapping pinned over an
enumeration of runs, the continuous values in integer cents, and the battery
summary diagnose prints."""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path
from typing import get_args

import pytest
from tests.obs.bundles import Log, manifest, write
from tests.obs.triage_bundle import P

from proxyloop.contract.events import EpochBump
from proxyloop.contract.state import READBACK_FIELD, CaseStatus
from proxyloop.env.tasks.schema import MONEY, money_term
from proxyloop.obs import detectors, diagnose, stops, tiers


def _tier(log: Log) -> dict[str, object]:
    x = detectors.Inputs(log.events, None, lambda _: None)
    value = detectors.DETECTORS["tier"](x)
    assert isinstance(value, dict)
    return value  # type: ignore[return-value]


def _status(
    log: Log, status: str, previous: str = "IN_CALL", cause: str | None = None
) -> str:
    changed: P = {"previous": previous, "status": status}
    return log.add("status.changed", "guard", "agent", changed, (cause or log.start,))


def _bump(log: Log, reason: str, cause: str | None = None) -> str:
    new = 1 + sum(e.type == "authority.epoch" for e in log.events)
    bump: P = {"new": new, "reason": reason}
    return log.add("authority.epoch", "kernel", "agent", bump, (cause or log.start,))


def _current(log: Log, dollars: str) -> None:
    sim: P = {"text": "PRIV", "revealed": {tiers.CURRENT: dollars}, "delay_s": 1.0}
    log.add("user.sim", "world.simuser", "world", sim, (log.start,))


def _pull(
    log: Log, lever: str, kind: str, price: str | None = None, move: str = "OFFER>OFFER"
) -> str:
    ear: P = {"utt_id": f"u{len(log.events)}", "act": lever, "args": {}, "call_id": "e"}
    ear_id = log.add("rep.ear", "world.ear", "world", ear, (log.start,))
    say = [] if price is None else [["monthly_price", price], ["term_months", "24"]]
    intent: P = {"kind": kind, "offer_ref": "save-1", "say": say, "ask": []}
    frm, _, to = move.partition(">")
    policy: P = {"from": frm, "to": to, "rung": 0, "intent": intent}
    return log.add("rep.policy", "world.policy", "world", policy, (ear_id,))


def _mandate(
    log: Log,
    max_minor: int,
    decision: str | None = "granted",
    expires: int | None = None,
) -> str:
    proposed: P = {"mandate_id": "m1", "mandate_hash": "mh", "status": "proposed"}
    proposed |= {"epoch": 0, "max_monthly_price_minor": max_minor}
    proposed |= {"expires_ms": expires}
    pid = log.add("mandate.proposed", "guard", "agent", proposed, (log.start,))
    if decision is None:
        return pid
    post: P = {"subject": "mandate", "subject_id": "m1", "decision": decision}
    post |= {"subject_hash": "mh", "authority_epoch": 0}
    sent = log.add("approval.post", "ui", "agent", post)
    decided: P = {"mandate_id": "m1", "mandate_hash": "mh", "decision": decision}
    decided |= {"by": "ui"}
    return log.add("mandate.decided", "kernel", "agent", decided, (sent, pid))


def _approval(log: Log, decision: str, price_minor: int, by: str = "ui") -> str:
    decided: P = {"approval_id": "a1", "decision": decision, "by": by}
    cid = _card(log, price_minor)
    return log.add("approval.decided", "kernel", "agent", decided, (cid,))


def _card(log: Log, price_minor: int = 6000) -> str:
    """An approval.requested for ``offer-1`` at ``price_minor``; its id."""
    slots = [{"field": "monthly_price", "value": str(price_minor), "unit": "usd_minor",
              "role": "recurring", "status": "confirmed"}]  # fmt: skip
    offer: P = {"offer_ref": "offer-1", "revision": 1, "slots": slots}
    oid = log.add("offer.recorded", "guard", "agent", offer | {"terms_hash": "th"},
                  (log.start,))  # fmt: skip
    binding: P = {"offer_ref": "offer-1", "revision": 1, "account_ref": "acct"}
    binding |= {"principal_ref": "me", "purpose": "accept", "authority_epoch": 0}
    card: P = {"approval_id": "a1", "offer_ref": "offer-1", "revision": 1,
               "terms_hash": "th", "readback_text": "PRIV", "authority_epoch": 0,
               "expires_ms": 10**9, "binding": binding}  # fmt: skip
    return log.add("approval.requested", "guard", "agent", card, (oid,))


def _accept(
    log: Log,
    grant: str | None,
    *more: str,
    intent: str = "accept_offer",
    kind: str = "accept",
    lane: str = "cp",
) -> str:
    """action.authorized (caused by ``grant`` and ``more``) -> Guard's
    ``kind`` line -> released -> heard on ``lane``."""
    capability: P = {"cap_id": "cap-1", "business_action_id": "b", "terms_hash": "th"}
    capability |= {"intent": intent, "epoch": 0, "expires_ms": 10**9}
    auth: P = {"intent": intent, "capability": capability}
    aid = log.add("action.authorized", "guard", "agent", auth,
                  (grant or log.start, *more))  # fmt: skip
    line: P = {"lane": "cp", "kind": kind, "text": "PRIV", "cap_id": "cap-1"}
    said = log.add("speak.verbatim", "guard", "agent", line, (aid,))
    rel = log.add("speak.released", "kernel", "agent", {"lane": "cp"}, (said,))
    return _heard(log, f"accept-{len(log.events)}", rel, lane)


def _heard(log: Log, utt_id: str, cause: str, lane: str = "cp") -> str:
    out: P = {"lane": lane, "utt_id": utt_id, "text_generated": "PRIV"}
    out |= {"text_heard": "PRIV", "interrupted": False}
    log.add("utt.delivered", "kernel", "agent", out, (cause,))
    return utt_id


def _commit(
    log: Log,
    utt_id: str,
    ledger: bool = True,
    said: str = "60.00",
    months: int = 24,
    **terms: str,
) -> None:
    """The rep hears ``utt_id`` as an accept and commits; the ledger binds a
    monthly_price of ``said``, ``months`` and ``terms`` (``fee_x`` is
    ``fee:x``, ``credit_x`` is ``credit:x``)."""
    ear: P = {"utt_id": utt_id, "act": "accept", "args": {}, "call_id": "e"}
    ear_id = log.add("rep.ear", "world.ear", "world", ear, (log.start,))
    intent: P = {"kind": "confirmed", "offer_ref": "save-1", "say": [], "ask": []}
    policy: P = {"from": "OFFER", "to": "CONFIRMED", "rung": 0, "intent": intent}
    pid = log.add("rep.policy", "world.policy", "world", policy, (ear_id,))
    heard: P = {"utt_id": utt_id, "offer_ref": "save-1"}
    hid = log.add("rep.commit_heard", "world.policy", "world", heard, (ear_id, pid))
    if ledger:
        binding: P = {"offer_ref": "save-1", "revision": 1, "term_months": months}
        more = {re.sub(r"^(fee|credit)_", r"\1:", k): v for k, v in terms.items()}
        binding["terms"] = {"monthly_price": said} | more
        write_: P = {"confirmation_id": "123456", "binding": binding}
        log.add("ledger.write", "world.ledger", "world", write_, (hid,))


def _free_speech_commit(log: Log) -> None:
    """Fast's own line ("yes, I'll take it") heard as an accept: no capability."""
    sent: P = {"lane": "cp", "gen_id": "cp-g1", "utt_id": "cp-g1-u0", "text": "PRIV"}
    sid = log.add("fast.sentence", "fast.cp", "agent", sent, (log.start,))
    _commit(log, _heard(log, "cp-g1-u0", sid))


def _deal(log: Log, grant: str | None, price: str = "60") -> None:
    _current(log, "85")
    _pull(log, "ask_discount", "offer", price)
    _commit(log, _accept(log, grant))
    _status(log, "VERIFIED_COMPLETE")


# -- one log per tier ---------------------------------------------------------


def test_a_mandate_accept_is_a_with_its_values() -> None:
    log = Log("rA")
    _deal(log, _mandate(log, 6500))
    log.end("done")
    t = _tier(log)
    assert (t["tier"], t["reason"], t["approved_by"]) == ("A", "mandate", "ui")
    assert t["family"] == "cp-direct-discount"
    assert {k: t[k] for k in (
        "unit", "current_price", "best_offer_monthly", "target_monthly",
        "savings_monthly", "savings_annual", "pct_below_current_bp", "gap_to_target",
    )} == {
        "unit": "usd_minor", "current_price": 8500, "best_offer_monthly": 6000,
        "target_monthly": 6500, "savings_monthly": 2500, "savings_annual": 30000,
        "pct_below_current_bp": 2941, "gap_to_target": -500,  # 2500/8500 = .29411
    }  # fmt: skip


def test_an_approval_accept_is_b() -> None:
    log = Log("rB")
    _deal(log, _approval(log, "granted", 6000, by="sim_approver"))
    log.end("done")
    t = _tier(log)
    assert (t["tier"], t["reason"], t["approved_by"]) == (
        "B",
        "approval",
        "sim_approver",
    )
    assert t["target_monthly"] is None and t["gap_to_target"] is None


def test_a_complete_run_whose_chain_cannot_tell_a_from_b_is_null() -> None:
    log = Log("rN")
    _deal(log, None)  # an authorization citing no decision
    log.end("done")
    t = _tier(log)
    assert (t["tier"], t["reason"]) == (None, "no_grant")
    complete = Log("rNc")  # verified complete, but nothing committed
    _status(complete, "VERIFIED_COMPLETE")
    complete.end("done")
    assert (_tier(complete)["tier"], _tier(complete)["reason"]) == (None, "no_commit")


def _no_deal(log: Log, status: str = "VERIFIED_NO_DEAL", end: str = "no_deal") -> None:
    _status(log, status)
    log.end(end)


def _spent(log: Log, price: str) -> None:
    """ask_discount answered with ``price``, then tenure ``no_better``: the
    ladder is proven exhausted, so no lever flag makes the run E."""
    _pull(log, "ask_discount", "offer", price)
    _pull(log, "tenure", "no_better")


def test_a_better_offer_outside_the_mandate_is_c() -> None:
    above = Log("rC1")
    _current(above, "85")
    _mandate(above, 6500)
    _spent(above, "70")
    _no_deal(above)
    t = _tier(above)
    assert (t["tier"], t["reason"], t["ladder_unfinished"]) == ("C", "above_mandate", 0)
    assert (t["gap_to_target"], t["exhausted"]) == (500, None)

    none = Log("rC2")
    _current(none, "85")
    _spent(none, "70")
    _no_deal(none)
    assert (_tier(none)["tier"], _tier(none)["reason"]) == ("C", "no_mandate")

    denied = Log("rC3")
    _current(denied, "85")
    _mandate(denied, 7500)
    _spent(denied, "70")
    _approval(denied, "denied", 7000)
    _no_deal(denied)
    assert (_tier(denied)["tier"], _tier(denied)["reason"]) == ("C", "approval_denied")

    ungranted = Log("rC4")  # proposed, never granted: nothing was pre-approved
    _current(ungranted, "85")
    _mandate(ungranted, 7500, decision="denied")
    _spent(ungranted, "70")
    _no_deal(ungranted)
    assert (_tier(ungranted)["tier"], _tier(ungranted)["reason"]) == ("C", "no_mandate")
    assert _tier(ungranted)["target_monthly"] == 7500  # the proposal, still shown

    unknown = Log("rC5")  # the user never said the current price: still C
    _mandate(unknown, 6500)
    _spent(unknown, "78")
    _no_deal(unknown)
    t = _tier(unknown)
    assert (t["tier"], t["reason"], t["best_offer_monthly"]) == (
        "C",
        "above_mandate",
        7800,
    )
    assert (t["current_price"], t["savings_monthly"], t["pct_below_current_bp"]) == (
        None, None, None,
    )  # fmt: skip


def test_a_miss_outranks_a_better_offer() -> None:
    """E before C: a reachable lever never pulled (bdfcc0's shape: $78 over a
    $65 mandate, tenure never pulled) is a miss whatever was offered."""
    log = Log("rEc")
    _current(log, "90")
    _mandate(log, 6500)
    _pull(log, "ask_discount", "offer", "78")
    _no_deal(log)
    t = _tier(log)
    assert (t["tier"], t["reason"], t["ladder_unfinished"]) == ("E", "unfinished", 1)
    assert (t["savings_monthly"], t["gap_to_target"]) == (1200, 1300)


def test_all_pulled_is_c_with_a_better_offer_and_d_without_one() -> None:
    better = Log("rAp1")
    _current(better, "85")
    _pull(better, "ask_discount", "offer", "80")
    _pull(better, "tenure", "final_offer", "79")
    _no_deal(better)
    assert (_tier(better)["tier"], _tier(better)["reason"]) == ("C", "no_mandate")
    bare = Log("rAp2")  # both levers heard past identity, no offer made
    _current(bare, "85")
    _pull(bare, "ask_discount", "clarify", move="DISCOVER>DISCOVER")
    _pull(bare, "tenure", "clarify", move="DISCOVER>DISCOVER")
    _no_deal(bare)
    t = _tier(bare)
    assert (t["tier"], t["reason"], t["exhausted"]) == ("D", "all_pulled", False)
    assert t["best_offer_monthly"] is None


def test_a_better_offer_within_the_mandate_not_taken_is_e() -> None:
    log = Log("rEw")
    _current(log, "85")
    _mandate(log, 6500)
    _pull(log, "ask_discount", "offer", "60")
    _pull(log, "tenure", "no_better")  # exhausted, yet a pre-approved deal left
    _no_deal(log)
    t = _tier(log)
    assert (t["tier"], t["reason"]) == ("E", "within_mandate_not_taken")


def test_an_exhausted_ladder_is_d_true_and_all_pulled_d_false() -> None:
    spent = Log("rD1")
    _current(spent, "85")
    _pull(spent, "ask_discount", "offer", "88")
    _pull(spent, "tenure", "no_better")
    _no_deal(spent)
    t = _tier(spent)
    assert (t["tier"], t["reason"], t["exhausted"]) == ("D", "exhausted", True)
    assert t["savings_monthly"] == -300  # the offer was worse: negative, shown

    pulled = Log("rD2")
    _current(pulled, "85")
    _pull(pulled, "ask_discount", "offer", "88")
    _pull(pulled, "tenure", "final_offer", "87.50")
    _no_deal(pulled)
    t = _tier(pulled)
    assert (t["tier"], t["reason"], t["exhausted"]) == ("D", "all_pulled", False)
    assert t["best_offer_monthly"] == 8750


def test_a_reachable_lever_never_pulled_is_e() -> None:
    log = Log("rE")
    _current(log, "85")
    _pull(log, "ask_discount", "offer", "88")
    _no_deal(log)
    t = _tier(log)
    assert (t["tier"], t["reason"], t["ladder_unfinished"]) == ("E", "unfinished", 1)
    assert t["exhausted"] is None


def test_an_unfinished_end_is_f_and_a_dead_endpoint_f_infra() -> None:
    for reason in ("timeout", "abandoned", "slow_step_cap", "budget"):
        log = Log(f"rF-{reason}")
        _status(log, "IN_CALL")
        log.end(reason)
        assert (_tier(log)["tier"], _tier(log)["reason"]) == ("F", reason)
    hung = Log("rF-abandoned-status")  # the status machine's own hang-up
    _status(hung, "ABANDONED")
    hung.end("abandoned")
    assert _tier(hung)["tier"] == "F"
    for reason in ("world_error", "llm_unavailable"):
        log = Log(f"rI-{reason}")
        _status(log, "IN_CALL")
        log.end(reason)
        assert (_tier(log)["tier"], _tier(log)["reason"]) == ("F-infra", reason)


def test_an_escalated_run_is_s_only_after_the_users_stop() -> None:
    """The demo's stop: FastU's revoke bumps the epoch (f2s_revoke), the
    accept is revoked, the replan escalates. Any other replan that escalates
    (accept_truncated / accept_revoked, a stale or expired card, a failed
    completion) is F ``escalated``."""
    stop = Log("rS")
    _path(stop, "IN_CALL", "COMMIT_AUTHORIZED")
    _bump(stop, "f2s_revoke")
    _floor(stop, "epoch")  # the accept that bump staled, revoked at the floor
    _escalate(stop)
    assert (_tier(stop)["tier"], _tier(stop)["reason"]) == ("S", "user_stop")
    for name, before, bump in (
        ("accept_truncated", "COMMIT_AUTHORIZED", None),
        ("accept_revoked", "COMMIT_AUTHORIZED", "slow_revoke"),
        ("approval_stale", "AWAITING_APPROVAL", "slow_revoke"),
        ("approval_expired", "AWAITING_APPROVAL", None),
        ("completion_fail", "EVIDENCE_PENDING", None),
    ):
        log = Log(f"rF-{name}")
        _path(log, "IN_CALL", before)
        if bump:
            _bump(log, bump)
        _path(log, before, "NEEDS_REPLAN", "ESCALATED")
        log.end("escalate")
        assert (_tier(log)["tier"], _tier(log)["reason"]) == ("F", "escalated"), name
    late = Log("rS-late")  # a revoke after the escalation is no stop of it
    _path(late, "IN_CALL", "COMMIT_AUTHORIZED", "NEEDS_REPLAN", "ESCALATED")
    _bump(late, "f2s_revoke")
    late.end("escalate")
    assert _tier(late)["tier"] == "F"


def _path(log: Log, *statuses: str) -> None:
    for previous, status in itertools.pairwise(statuses):
        _status(log, status, previous)


def test_an_unauthorized_commit_is_x_over_a_and_s() -> None:
    free = Log("rX")
    _free_speech_commit(free)
    _status(free, "IN_CALL")
    free.end("done")
    t = _tier(free)
    assert (t["tier"], t["reason"]) == ("X", "unauthorized_commit")
    assert t["unauthorized_seqs"] == [5, 6]  # the commit and its ledger.write

    over_a = Log("rXa")  # a clean A, plus a ledger.write no commit caused
    _deal(over_a, _mandate(over_a, 6500))
    lone: P = {"confirmation_id": "9", "binding": {}}
    over_a.add("ledger.write", "world.ledger", "world", lone, (over_a.start,))
    over_a.end("done")
    assert (_tier(over_a)["tier"], _tier(over_a)["reason"]) == (
        "X", "unauthorized_ledger_write",
    )  # fmt: skip

    over_s = Log("rXs")
    _free_speech_commit(over_s)
    _status(over_s, "ESCALATED")
    over_s.end("escalated")
    assert _tier(over_s)["tier"] == "X"

    late = Log("rXl")  # the heard accept's capability authorized only after it
    line: P = {"lane": "cp", "kind": "accept", "text": "PRIV", "cap_id": "cap-1"}
    said = late.add("speak.verbatim", "guard", "agent", line, (late.start,))
    rel = late.add("speak.released", "kernel", "agent", {"lane": "cp"}, (said,))
    _commit(late, _heard(late, "accept-9", rel))
    capability: P = {"cap_id": "cap-1", "business_action_id": "b", "terms_hash": "th"}
    capability |= {"intent": "accept_offer", "epoch": 0, "expires_ms": 10**9}
    auth: P = {"intent": "accept_offer", "capability": capability}
    late.add("action.authorized", "guard", "agent", auth, (late.start,))
    late.end("done")
    assert _tier(late)["tier"] == "X"

    running = Log("rXr")  # X is disqualifying even before the end
    _free_speech_commit(running)
    assert _tier(running)["tier"] == "X"


def test_declass_denied_is_counted_never_x() -> None:
    log = Log("rG")
    _deal(log, _mandate(log, 6500))
    log.add("declass.denied", "guard", "agent", {"violations": ["x"]}, (log.start,))
    log.end("done")
    t = _tier(log)
    assert (t["tier"], t["declass_denied"]) == ("A", 1)


def test_info_only_is_graded_c_d_e_with_its_kind() -> None:
    log = Log("rIo")
    _current(log, "85")
    _pull(log, "ask_discount", "offer", "88")
    _no_deal(log, "CLOSED_NO_ACTION", "info_only")
    t = _tier(log)
    assert (t["tier"], t["task_kind"]) == ("E", "info_only")
    plain = Log("rNd")
    _pull(plain, "ask_discount", "offer", "88")
    _no_deal(plain)
    assert _tier(plain)["task_kind"] is None


def test_missing_inputs_are_null_and_the_tier_still_decided() -> None:
    log = Log("rM")  # no current price, no mandate, an unparseable offer
    _pull(log, "ask_discount", "offer", "88.5")
    _pull(log, "tenure", "no_better")
    _no_deal(log)
    t = _tier(log)
    assert (t["tier"], t["reason"]) == ("D", "exhausted")
    for key in ("current_price", "best_offer_monthly", "target_monthly",
                "savings_monthly", "savings_annual", "pct_below_current_bp",
                "gap_to_target"):  # fmt: skip
        assert t[key] is None, key
    fact = Log("rMf")  # the current price from a recorded fact, no offer said
    recorded: P = {"key": tiers.CURRENT, "value": "68.00", "source": "shareable"}
    fact.add("fact.recorded", "guard", "agent", recorded, (fact.start,))
    fact.end("timeout")
    t = _tier(fact)
    assert (t["tier"], t["current_price"], t["best_offer_monthly"]) == ("F", 6800, None)


def test_no_end_is_no_tier() -> None:
    log = Log("rR")
    _pull(log, "ask_discount", "offer", "60")
    assert (_tier(log)["tier"], _tier(log)["reason"]) == (None, "no_end")


def test_money_is_parsed_exactly_to_cents() -> None:
    assert tiers.cents("68") == tiers.cents("68.00") == 6800
    assert tiers.cents("0.05") == 5
    for bad in ("68.5", "68.000", "$68", " 68", "-1", "1e3", "NaN", 68, None):
        assert tiers.cents(bad) is None, bad
    # the key names and the money pattern obs duplicates, pinned to env/contract
    assert tiers.MONEY.pattern == MONEY[1:-1]
    assert re.match(READBACK_FIELD, tiers.MONTHLY) and money_term(tiers.MONTHLY)
    for field in ("monthly_price", "fee:x", "credit:y", "term_months", "expires"):
        assert tiers._money(field) == money_term(field), field  # pyright: ignore[reportPrivateUsage]


# -- totality -----------------------------------------------------------------

_LADDERS = ("none", "no_ladder", "unfinished", "exhausted", "all_pulled", "committed")
_PRICES = ("worse", "better_no_mandate", "within", "above", "no_current")
_ENDS = ("done", "no_deal", "info_only", "timeout", "world_error", "llm_unavailable",
         "abandoned")  # fmt: skip
_STATUSES = (None, *CaseStatus)


def _enumerated(
    status: CaseStatus | None, end: str, ladder: str, price: str, stop: bool = False
) -> Log:
    log = Log("rT")
    if price != "no_current":
        _current(log, "85")
    if price in ("within", "above"):
        _mandate(log, 6500)
    offer = {"worse": "90", "better_no_mandate": "70", "within": "60", "above": "70",
             "no_current": "70"}  # fmt: skip
    if ladder == "no_ladder":
        _pull(log, "ask_discount", "ask_identity", None, move="IDENTIFY>IDENTIFY")
    elif ladder != "none":
        _pull(log, "ask_discount", "offer", offer[price])
    if ladder == "exhausted":
        _pull(log, "tenure", "no_better")
    elif ladder == "all_pulled":
        _pull(log, "tenure", "final_offer", "99")
    elif ladder == "committed":
        _commit(log, _accept(log, _mandate(log, 9900)))
    if stop:
        _bump(log, "f2s_revoke")
    if status is not None:
        _status(log, status.value)
    log.end(end)
    return log


# The verified no-deal mapping (main-root rulings 2026-09-28): E before C
# before D; all_pulled is D (C with a better offer), never E.
_FLAG = {
    "exhausted": ("D", "exhausted", True),
    "all_pulled": ("D", "all_pulled", False),
}


def _no_deal_want(ladder: str, price: str) -> tuple[str | None, str, bool | None]:
    offered = ladder not in ("none", "no_ladder")
    if ladder == "committed":
        return None, "inconsistent", None
    if offered and price == "within":
        return "E", "within_mandate_not_taken", None
    if ladder in ("unfinished", "no_ladder"):
        return "E", ladder, None
    if offered and price != "worse":  # better, or the current price unknown
        return "C", "above_mandate" if price == "above" else "no_mandate", None
    if ladder in _FLAG:
        return _FLAG[ladder]
    assert ladder == "none"  # the only no-deal close with no offer, E or D
    return None, "no_policy", None


def test_every_ended_run_gets_exactly_one_tier() -> None:
    allowed = {"A", "B", "C", "D", "E", "F", "F-infra", "S", "X", None}
    closes = {"VERIFIED_COMPLETE", "VERIFIED_NO_DEAL", "CLOSED_NO_ACTION", "ESCALATED"}
    seen: set[object] = set()
    for status, end, ladder, price, stop in itertools.product(
        _STATUSES, _ENDS, _LADDERS, _PRICES, (False, True)
    ):
        if stop and status is not CaseStatus.ESCALATED:
            continue  # the stop marker matters to ESCALATED only
        t = _tier(_enumerated(status, end, ladder, price, stop))
        tier, reason = t["tier"], t["reason"]
        case = (status, end, ladder, price, stop)
        seen.add(tier)
        assert tier in allowed and isinstance(reason, str) and reason, case
        s = None if status is None else status.value
        if s == "VERIFIED_COMPLETE":
            want = ("A", "mandate") if ladder == "committed" else (None, "no_commit")
            assert (tier, reason) == want, case
        elif s == "ESCALATED":
            want = ("S", "user_stop") if stop else ("F", "escalated")
            assert (tier, reason) == want, case
        elif end in ("world_error", "llm_unavailable"):
            assert (tier, reason) == ("F-infra", end), case
        elif s not in closes:
            assert (tier, reason) == ("F", end), case
        else:
            want3 = _no_deal_want(ladder, price)
            assert (tier, reason, t["exhausted"]) == want3, case
            kind = (
                "info_only" if end == "info_only" or s == "CLOSED_NO_ACTION" else None
            )
            assert t["task_kind"] == kind, case
    assert seen == allowed - {"B", "X"}  # B and X have their own tests


# -- the battery summary ------------------------------------------------------


def _row(
    task_ref: str, tier: str | None, kind: str | None = None, **extra: object
) -> dict[str, object]:
    t: dict[str, object] = {"tier": tier, "family": task_ref.partition("@")[0] or None}
    t |= {"task_kind": kind, "declass_denied": 1 if tier == "A" else 0} | extra
    return {"run_id": f"r{tier}", "task_ref": task_ref, "detectors": {"tier": t}}


def test_the_battery_summary_counts_per_family_and_reports_ab() -> None:
    rows = [
        _row("fam-a@1", "A"), _row("fam-a@1", "F"), _row("fam-a@2", "D", "info_only"),
        _row("fam-b@1", "S"), _row("fam-b@1", "E"), _row("fam-b@1", None),
        _row("fam-c@1", "B"),
    ]  # fmt: skip
    s = tiers.summary(rows)
    assert s["families"] == {
        "fam-a": {"tiers": {"A": 1, "F": 1}, "info_only": {"D": 1}},
        "fam-b": {"tiers": {"E": 1, "S": 1, "none": 1}, "info_only": {}},
        "fam-c": {"tiers": {"B": 1}, "info_only": {}},
    }
    # S is correct behaviour but never an A/B: fam-b has none
    assert s["ab_per_family"] == {"fam-a": True, "fam-b": False, "fam-c": True}
    assert s["ab_every_family"] is False and s["declass_denied"] == 1
    every = tiers.summary([_row("fam-a@1", "A"), _row("fam-c@1", "B")])
    assert every["ab_every_family"] is True
    assert tiers.summary([])["ab_every_family"] is False  # nothing ran: no pass


def test_info_only_families_are_na_and_odd_runs_are_listed() -> None:
    """m5: a family of info_only runs only has no A/B to find (``n/a``) and
    ab_every_family skips it; m2: an ``inconsistent`` run is counted apart
    and listed; runs confirmed by free speech are listed; no family is
    ``unknown``."""
    rows = [
        _row("fam-a@1", "A", confirmed_by_free_speech=True),
        _row("fam-i@1", "D", "info_only"), _row("fam-i@1", "E", "info_only"),
        _row("fam-a@1", None, reason="inconsistent"), _row("@1", "F"),
    ]  # fmt: skip
    s = tiers.summary(rows)
    assert s["ab_per_family"] == {"fam-a": True, "fam-i": "n/a", "unknown": False}
    assert s["families"]["fam-a"] == {  # type: ignore[index]
        "tiers": {"A": 1, "inconsistent": 1}, "info_only": {},
    }  # fmt: skip
    assert (s["confirmed_by_free_speech"], s["inconsistent"]) == (["rA"], ["rNone"])
    assert s["ab_every_family"] is False  # unknown has none
    only = tiers.summary([_row("fam-a@1", "A"), _row("fam-i@1", "D", "info_only")])
    assert only["ab_every_family"] is True  # fam-i is n/a, not a miss
    lines = tiers.block(s, "git_sha:abc").splitlines()
    assert "  fam-i | info_only D=1 E=1 | ab=n/a" in lines
    assert lines[-2:] == ["  confirmed_by_free_speech=1 rA", "  inconsistent=1 rNone"]


def _sha(log: Log, sha: str) -> Log:
    start = log.events[0]
    log.events[0] = start.model_copy(
        update={"payload": start.payload | {"git_sha": sha}}
    )
    return log


def test_diagnose_grades_each_group_apart(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """M2: the tier block per table group; an A in one group never makes
    another group's family pass."""
    a = _sha(Log("rA"), "g1")
    _deal(a, _mandate(a, 6500))
    a.end("done")
    write(tmp_path / "rA", a, manifest("rA"))
    f = _sha(Log("rF"), "g2")
    f.end("timeout")
    write(tmp_path / "rF", f, manifest("rF"))
    assert diagnose.main(["--root", str(tmp_path), "--json"]) == 0
    graded = json.loads(capsys.readouterr().out)["tiers"]
    assert {g: v["ab_per_family"] for g, v in graded.items()} == {
        "git_sha:g1": {"cp-direct-discount": True},
        "git_sha:g2": {"cp-direct-discount": False},
    }
    assert diagnose.main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out.splitlines()
    heads = [line for line in out if line.startswith("== tiers")]
    assert heads == [f"== tiers git_sha {g} ({tiers.NOTE})" for g in ("g1", "g2")]


def test_diagnose_prints_the_tiers_block_and_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = Log("rA")
    _deal(a, _mandate(a, 6500))
    a.end("done")
    write(tmp_path / "rA", a, manifest("rA"))
    f = Log("rF")
    f.end("timeout")
    write(tmp_path / "rF", f, manifest("rF"))
    assert diagnose.main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert any(line.startswith("  rA ") and "tier=A:mandate" in line for line in out)
    block = out[out.index(f"== tiers git_sha g ({tiers.NOTE})") :]
    assert block[1:5] == [
        "  cp-direct-discount A=1 F=1 | ab=yes",
        "  ab_every_family=yes declass_denied=0",
        "  confirmed_by_free_speech=0",
        "  inconsistent=0",
    ]
    assert block[5].startswith("== progress ")  # S1-SYS-86's blocks follow
    assert diagnose.main(["--root", str(tmp_path), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert sorted(r["run_id"] for r in doc["runs"]) == ["rA", "rF"]
    assert doc["tiers"]["git_sha:g"]["ab_per_family"] == {"cp-direct-discount": True}


# -- the confirm path (M3, the root's temporary exception) --------------------


def _agent_offer(
    log: Log, price_minor: int, money: dict[str, str] | None = None, bare: bool = False
) -> None:
    """The agent's record of the offer the capability binds (terms_hash th):
    the price, 24 months (neither when ``bare``) and its ``money`` terms in
    cents (default a $10.00 activation fee), as Guard records them."""
    slots = [] if bare else [
        {"field": "monthly_price", "value": str(price_minor), "unit": "usd_minor",
         "role": "recurring", "status": "confirmed"},
        {"field": "term_months", "value": "24", "unit": "months",
         "role": "recurring", "status": "confirmed"},
    ] + [
        {"field": f, "value": v, "unit": "usd_minor", "status": "confirmed",
         "role": "one_time" if f.startswith("fee:") else "credit"}
        for f, v in (money if money is not None else {"fee:activation": "1000"}).items()
    ]  # fmt: skip
    offer: P = {"offer_ref": "offer-1", "revision": 1, "slots": slots}
    log.add("offer.recorded", "guard", "agent", offer | {"terms_hash": "th"},
            (log.start,))  # fmt: skip


def _yes(log: Log) -> str:
    """Fast's own "yes": a line Guard never released."""
    sent: P = {"lane": "cp", "gen_id": "cp-g9", "utt_id": "cp-g9-u0", "text": "PRIV"}
    sid = log.add("fast.sentence", "fast.cp", "agent", sent, (log.start,))
    return _heard(log, "cp-g9-u0", sid)


def _confirm(log: Log, utt_id: str) -> None:
    """The rep hears ``utt_id`` as an accept and reads the terms back
    (``policy._accept``: confirm_accept, no commit)."""
    ear: P = {"utt_id": utt_id, "act": "accept", "args": {}, "call_id": "e"}
    ear_id = log.add("rep.ear", "world.ear", "world", ear, (log.start,))
    say = [["monthly_price", "68.00"], ["term_months", "24"]]
    intent: P = {"kind": "confirm_accept", "offer_ref": "save-1", "say": say, "ask": []}
    policy: P = {"from": "OFFER", "to": "CONFIRM", "rung": 0, "intent": intent}
    log.add("rep.policy", "world.policy", "world", policy, (ear_id,))


def _confirm_deal(
    log: Log,
    released: bool = True,
    said: str = "68.00",
    months: int = 24,
    fee: str = "10.00",
    bound: dict[str, str] | None = None,
    agent: dict[str, str] | None = None,
    bare: bool = False,
) -> None:
    """test_backlog's shape: the accept is read back, a "yes" commits; the
    ledger binds ``said``, ``months``, the activation ``fee`` (or the
    ``bound`` money terms, ``fee_x`` for ``fee:x``) and a term the agent's
    record lacks (not compared); the agent recorded ``agent``'s money (and,
    unless ``bare``, the price and the months)."""
    _current(log, "85")
    _agent_offer(log, 6800, agent, bare)
    grant = _mandate(log, 7000)
    _confirm(log, _accept(log, grant) if released else _yes(log))
    money = bound if bound is not None else {"fee_activation": fee}
    _commit(log, _yes(log), said=said, months=months, changes_none="true",
            **money)  # type: ignore[arg-type]  # fmt: skip
    _status(log, "VERIFIED_COMPLETE")
    log.end("done")


def test_a_commit_on_the_confirm_of_a_released_accept_is_graded_and_flagged() -> None:
    log = Log("rCf")
    _confirm_deal(log)
    t = _tier(log)
    assert (t["tier"], t["reason"], t["confirmed_by_free_speech"]) == (
        "A", "mandate", True,
    )  # fmt: skip
    s = tiers.summary([{"run_id": "rCf", "detectors": {"tier": t}}])
    assert s["confirmed_by_free_speech"] == ["rCf"]
    clean = Log("rOk")  # the released line itself committed: no flag
    _deal(clean, _mandate(clean, 6500))
    clean.end("done")
    assert _tier(clean)["confirmed_by_free_speech"] is False


def test_a_confirm_commit_with_another_bound_term_or_on_free_speech_is_x() -> None:
    for run_id, kw in (
        ("rCw", {"said": "70.00"}), ("rCm", {"months": 12}),  # same price
        ("rCe", {"fee": "15.00"}), ("rCz", {"fee": "10.5"}),  # unparseable money
    ):  # fmt: skip
        wrong = Log(run_id)
        _confirm_deal(wrong, **kw)  # type: ignore[arg-type]
        assert (_tier(wrong)["tier"], _tier(wrong)["reason"]) == (
            "X", "terms_mismatch",
        ), run_id  # fmt: skip
    cents_ = Log("rCc")  # "10" and "68" are the recorded cents too
    _confirm_deal(cents_, said="68", fee="10")
    assert _tier(cents_)["confirmed_by_free_speech"] is True
    loose = Log("rCl")  # the confirm answered Fast's own words
    _confirm_deal(loose, released=False)
    assert (_tier(loose)["tier"], _tier(loose)["reason"]) == ("X", "commit_on_confirm")
    bare = Log("rCb")  # no confirm at all: a plain free-speech commit
    _free_speech_commit(bare)
    bare.end("done")
    assert _tier(bare)["reason"] == "unauthorized_commit"


def test_fees_under_other_names_are_compared_by_amount() -> None:
    """Fee names are Slow's choice (``fee:<code>``): a name both sides carry is
    compared by name, and the amounts in cents under the names only one side
    carries must be equal as a multiset. Fails closed."""
    same = Log("rFs")  # the world's activation fee, recorded as a setup fee
    _confirm_deal(same, bound={"fee_activation": "10"}, agent={"fee:setup": "1000"})
    assert (_tier(same)["tier"], _tier(same)["confirmed_by_free_speech"]) == (
        "A", True,
    )  # fmt: skip
    for run_id, bound, agent in (
        ("rFa", {"fee_activation": "15"}, {"fee:setup": "1000"}),  # another amount
        ("rFx", {"fee_activation": "10"},  # an extra fee on one side
         {"fee:setup": "1000", "fee:early": "1000"}),
        ("rFn", {"fee_activation": "10", "fee_early": "10"}, {"fee:setup": "1000"}),
        ("rFp", {"fee_activation": "15"}, {"fee:activation": "1000"}),  # same name
        ("rFu", {"fee_activation": "10.5"}, {"fee:setup": "1000"}),  # unparseable
        ("rFv", {"fee_activation": "10"}, {"fee:setup": "10.00"}),  # not cents
        ("rFo", {}, {"fee:setup": "1000"}),  # the ledger binds no fee
        ("rFg", {"fee_activation": "10"}, {}),  # the agent recorded no fee
        ("rFq", {"fee_activation": "10", "fee_early": "25"},  # a shared name
         {"fee:activation": "2500", "fee:setup": "1000"}),  # conflicts
        ("rFe", {"fee_a": "10", "fee_b": "25"},  # the same names, swapped
         {"fee:a": "2500", "fee:b": "1000"}),
        ("rFb", {"fee_activation": "10.5"}, {"fee:activation": "10.00"}),  # both
        ("rFc", {"fee_activation": "10.5"}, {"fee:setup": "10.00"}),  # unparseable
    ):  # fmt: skip
        log = Log(run_id)
        _confirm_deal(log, bound=bound, agent=agent)
        assert (_tier(log)["tier"], _tier(log)["reason"]) == (
            "X", "terms_mismatch",
        ), run_id  # fmt: skip
    swapped = Log("rFw")  # two fees, named apart, the same amounts
    _confirm_deal(
        swapped,
        bound={"fee_activation": "10", "fee_early": "25"},
        agent={"fee:early_exit": "2500", "fee:setup": "1000"},
    )
    assert _tier(swapped)["tier"] == "A"
    only_fee = Log("rF1")  # a fee is the only term both carry: shares none
    _confirm_deal(only_fee, agent={"fee:activation": "1000"}, bare=True)
    assert (_tier(only_fee)["tier"], _tier(only_fee)["reason"]) == (
        "X", "terms_mismatch",
    )  # fmt: skip


def test_credits_under_other_names_are_compared_by_amount() -> None:
    """``credit:<code>`` is Slow's choice too: the same rule as fees."""
    for run_id, bound, want in (
        ("rRs", {"credit_loyalty": "5"}, "A"),
        ("rRa", {"credit_loyalty": "6"}, "X"),
    ):
        log = Log(run_id)
        agent = {"fee:activation": "1000", "credit:welcome": "500"}
        _confirm_deal(log, bound={"fee_activation": "10"} | bound, agent=agent)
        assert _tier(log)["tier"] == want, run_id


# -- the mandate at the close (m1) and mutation pins (m4) ---------------------


def _no_deal_within(
    log: Log, *, stale: bool = False, expires: int | None = None
) -> None:
    _current(log, "85")
    grant = _mandate(log, 6500, expires=expires)
    _bump(log, "mandate_decided", grant)  # the grant's own bump keeps it
    if stale:
        _bump(log, "f2s_revoke")
    _spent(log, "60")
    _no_deal(log)


def test_a_revoked_or_expired_mandate_is_no_pre_approval() -> None:
    kept = Log("rMk")
    _no_deal_within(kept)
    assert (_tier(kept)["tier"], _tier(kept)["reason"]) == (
        "E",
        "within_mandate_not_taken",
    )
    revoked = Log("rMr")
    _no_deal_within(revoked, stale=True)
    assert (_tier(revoked)["tier"], _tier(revoked)["reason"]) == ("C", "mandate_stale")
    expired = Log("rMe")  # expires at t=500, the close is later
    _no_deal_within(expired, expires=500)
    assert (_tier(expired)["tier"], _tier(expired)["reason"]) == (
        "C",
        "mandate_expired",
    )
    live = Log("rMl")
    _no_deal_within(live, expires=10**9)
    assert _tier(live)["tier"] == "E"


def test_boundaries_at_the_mandate_max_and_the_current_price() -> None:
    at_max = Log("rB1")
    _current(at_max, "85")
    _mandate(at_max, 6500)
    _spent(at_max, "65")
    _no_deal(at_max)
    assert (_tier(at_max)["tier"], _tier(at_max)["reason"]) == (
        "E", "within_mandate_not_taken",
    )  # fmt: skip
    at_current = Log("rB2")  # not below the current price: no better offer
    _current(at_current, "85")
    _spent(at_current, "85")
    _no_deal(at_current)
    assert (_tier(at_current)["tier"], _tier(at_current)["savings_monthly"]) == ("D", 0)


def test_only_a_denied_approval_at_the_best_price_makes_c() -> None:
    for run_id, decision, price, want in (
        ("rP1", "denied", 7000, ("C", "approval_denied")),
        ("rP2", "granted", 7000, ("E", "within_mandate_not_taken")),
        ("rP3", "denied", 7100, ("E", "within_mandate_not_taken")),  # another price
    ):
        log = Log(run_id)
        _current(log, "85")
        _mandate(log, 7500)
        _spent(log, "70")
        _approval(log, decision, price)
        _no_deal(log)
        assert (_tier(log)["tier"], _tier(log)["reason"]) == want, run_id


def test_only_granted_decisions_grade_and_two_paths_are_ambiguous() -> None:
    denied = Log("rG1")
    _deal(denied, _mandate(denied, 6500, decision="denied"))
    denied.end("done")
    assert (_tier(denied)["tier"], _tier(denied)["reason"]) == (None, "no_grant")
    both = Log("rG2")
    grant = _mandate(both, 6500)
    card = _approval(both, "granted", 6000)
    _current(both, "85")
    _commit(both, _accept(both, grant, card))
    _status(both, "VERIFIED_COMPLETE")
    both.end("done")
    assert (_tier(both)["tier"], _tier(both)["reason"]) == (None, "chain_ambiguous")


def test_each_link_of_the_accept_chain_is_required() -> None:
    """A heard line delivered after the commit, on the user lane, from a
    decline, or authorized for another intent, is no authorized accept."""
    after = Log("rK1")
    line: P = {"lane": "cp", "kind": "accept", "text": "PRIV", "cap_id": "cap-1"}
    capability: P = {"cap_id": "cap-1", "business_action_id": "b", "terms_hash": "th"}
    capability |= {"intent": "accept_offer", "epoch": 0, "expires_ms": 10**9}
    auth: P = {"intent": "accept_offer", "capability": capability}
    aid = after.add("action.authorized", "guard", "agent", auth, (after.start,))
    said = after.add("speak.verbatim", "guard", "agent", line, (aid,))
    rel = after.add("speak.released", "kernel", "agent", {"lane": "cp"}, (said,))
    _commit(after, "accept-9")
    _heard(after, "accept-9", rel)  # delivered only after the commit
    assert _tier(after)["tier"] == "X"
    for run_id, kw in (
        ("rK2", {"lane": "user"}), ("rK3", {"kind": "decline"}),
        ("rK4", {"intent": "submit_transaction"}),
    ):  # fmt: skip
        log = Log(run_id)
        _commit(log, _accept(log, _mandate(log, 6500), **kw))  # type: ignore[arg-type]
        assert _tier(log)["tier"] == "X", run_id


def test_money_pins() -> None:
    corrected = Log("rV1")  # the last revealed current price wins
    _current(corrected, "90")
    _current(corrected, "85")
    corrected.end("timeout")
    assert _tier(corrected)["current_price"] == 8500
    for best, bp in (("199.99", 0), ("199.97", 2), ("199.95", 2)):  # .5, 1.5, 2.5
        log = Log("rV2")
        _current(log, "200.00")
        _pull(log, "ask_discount", "offer", best)
        log.end("timeout")
        assert _tier(log)["pct_below_current_bp"] == bp, best  # half to even
    mixed = Log("rV3")
    _pull(mixed, "ask_discount", "offer", "88")
    _pull(mixed, "tenure", "offer", "88.5")
    mixed.end("timeout")
    assert _tier(mixed)["best_offer_monthly"] is None


# -- the user's stop (S1-SYS-90, obs/stops.py; ADR-0023: S = the user stopped) --
# stop -> revoke -> replan -> the last ESCALATED. A sim stop is the world's
# user.sim{stop}, and a revoke by either lane must follow it. With no such stop
# (the UI) FastU's f2s_revoke is the stop, and a bare slow_revoke never is.
# Every NEEDS_REPLAN after the revoke must be the revoke's own: (a) a card
# pending at the revoke needs the replan that bump caused; (b) with no card
# pending, replan_seq is None.


def _at(log: Log) -> int:
    return len(log.events) - 1


def _at_of(log: Log, event_id: str) -> int:
    return next(e.seq for e in log.events if e.event_id == event_id)


def _stop(log: Log, kind: str | None = "stop") -> int:
    """A sim user's reply whose ``stop`` is ``kind`` (``simuser._reply``), or
    an ordinary reply when ``kind`` is None. Returns its seq."""
    sim: P = {"text": "PRIV", "revealed": {}, "delay_s": 1.0}
    sim |= {"stop": kind} if kind else {}
    log.add("user.sim", "world.simuser", "world", sim, (log.start,))
    return _at(log)


def _asked(log: Log) -> str:
    """A card, the case IN_CALL -> AWAITING_APPROVAL; the card's id."""
    card = _card(log)
    _status(log, "AWAITING_APPROVAL", "IN_CALL", card)
    return card


def _replan(log: Log, cause: str, previous: str = "AWAITING_APPROVAL") -> int:
    """NEEDS_REPLAN caused by ``cause``: a bump that stales the card, or the
    card itself at its expiry (``kernel/fence.py``). Returns its seq."""
    _status(log, "NEEDS_REPLAN", previous, cause)
    return _at(log)


def _floor(log: Log, why: str) -> int:
    """The accept line revoked at the floor for ``why`` (``kernel/speaker.py``)
    and the case COMMIT_AUTHORIZED -> NEEDS_REPLAN. Returns the replan's seq."""
    line: P = {"lane": "cp", "kind": "accept", "text": "PRIV", "cap_id": "cap-1"}
    said = log.add("speak.verbatim", "guard", "agent", line, (log.start,))
    out: P = {"lane": "cp", "reason": why, "cap_id": "cap-1"}
    revoked = log.add("speak.revoked", "kernel", "agent", out, (said,))
    return _replan(log, revoked, "COMMIT_AUTHORIZED")


def _escalate(log: Log) -> None:
    _status(log, "ESCALATED", "NEEDS_REPLAN")
    log.end("escalate")


def _cited(log: Log) -> tuple[object, ...]:
    t = _tier(log)
    keys = ("tier", "reason", "stop_seq", "revoke_seq", "replan_seq")
    return tuple(t.get(k) for k in keys)


_F = ("F", "escalated", None, None, None)


def test_a_sim_stop_then_either_lanes_revoke_is_s_citing_the_chain() -> None:
    for kind in ("stop", "mind_change"):
        for reason in ("f2s_revoke", "slow_revoke"):
            log = Log(f"rS-{kind}-{reason}")
            _asked(log)
            s = _stop(log, kind)
            r = _bump(log, reason)
            n = _replan(log, r)
            _escalate(log)
            want = ("S", "user_stop", s, _at_of(log, r), n)
            assert _cited(log) == want, (kind, reason)


def test_a_ui_stop_is_fastus_revoke_and_never_a_bare_slow_revoke() -> None:
    for reply in (False, True):  # the UI, or a sim reply that is no stop
        ui = Log(f"rS-ui-{reply}")
        if reply:
            _stop(ui, None)
        _asked(ui)
        r = _bump(ui, "f2s_revoke")
        n = _replan(ui, r)
        _escalate(ui)
        assert _cited(ui) == ("S", "user_stop", None, _at_of(ui, r), n), reply
        bare = Log(f"rF-ui-slow-{reply}")  # a stop relayed only as a NOTE
        if reply:
            _stop(bare, None)
        _asked(bare)
        _replan(bare, _bump(bare, "slow_revoke"))
        _escalate(bare)
        assert _cited(bare) == _F, reply


def test_a_revoke_that_does_not_follow_the_stop_is_not_s() -> None:
    for first, then in (("f2s_revoke", "stop"), ("slow_revoke", "mind_change")):
        before = Log(f"rF-before-{first}")  # Q3: strictly after the stop
        _asked(before)
        _replan(before, _bump(before, first))
        _stop(before, then)
        _escalate(before)
        assert _cited(before) == _F, first
    other = Log("rF-tighten")  # a bump that is no revoke
    _asked(other)
    _stop(other)
    _replan(other, _bump(other, "tighten_mandate"))
    _escalate(other)
    assert _cited(other) == _F
    late = Log("rF-late")  # a revoke after the last escalation
    card = _asked(late)
    _stop(late)
    _replan(late, card)
    _status(late, "ESCALATED", "NEEDS_REPLAN")
    _bump(late, "slow_revoke")
    _bump(late, "f2s_revoke")
    late.end("escalate")
    assert _cited(late) == _F


def test_an_early_hold_off_then_a_later_card_expiry_is_not_s() -> None:
    """The revoke is stale: a later card expired, and that replan escalated."""
    for sim, pending in itertools.product((True, False), (True, False)):
        log = Log(f"rF-hold-{sim}-{pending}")
        if pending:
            _asked(log)
        if sim:
            _stop(log)
        r = _bump(log, "f2s_revoke")
        if pending:
            _replan(log, r)
            _status(log, "IN_CALL", "NEEDS_REPLAN")
        _replan(log, _asked(log))  # a new card, pending at its expiry
        _escalate(log)
        assert _cited(log) == _F, (sim, pending)


def test_branch_a_needs_the_replan_that_revoke_caused() -> None:
    skipped = Log("rF-a-no-replan")  # AWAITING_APPROVAL straight to ESCALATED
    _asked(skipped)
    _stop(skipped)
    _bump(skipped, "f2s_revoke")
    _status(skipped, "ESCALATED", "AWAITING_APPROVAL")
    skipped.end("escalate")
    assert _cited(skipped) == _F
    expired = Log("rF-a-expired")  # the card expired, the bump staled nothing
    card = _asked(expired)
    _stop(expired)
    _bump(expired, "slow_revoke")
    _replan(expired, card)
    _escalate(expired)
    assert _cited(expired) == _F


def test_branch_b_holds_with_no_replan_of_another_cause() -> None:
    demo = Log("rS-b-floor")  # the bump stales the accept line at the floor
    _path(demo, "IN_CALL", "COMMIT_AUTHORIZED")
    s = _stop(demo)
    r = _bump(demo, "f2s_revoke")
    _floor(demo, "epoch")
    _escalate(demo)
    assert _cited(demo) == ("S", "user_stop", s, _at_of(demo, r), None)
    fenced = Log("rS-b-fence")  # the stop's fence revoked the accept first
    _path(fenced, "IN_CALL", "COMMIT_AUTHORIZED")
    s = _stop(fenced)
    _floor(fenced, "fence")
    r = _bump(fenced, "slow_revoke")
    _escalate(fenced)
    assert _cited(fenced) == ("S", "user_stop", s, _at_of(fenced, r), None)
    for name, why, bump_between in (("expired", "expired", False),
                                    ("rebumped", "epoch", True)):  # fmt: skip
        log = Log(f"rF-b-{name}")
        _path(log, "IN_CALL", "COMMIT_AUTHORIZED")
        _stop(log)
        _bump(log, "f2s_revoke")
        if bump_between:  # the floor's epoch is that later bump's
            _bump(log, "tighten_mandate")
        _floor(log, why)
        _escalate(log)
        assert _cited(log) == _F, name


def test_a_later_revoke_is_cited_when_an_earlier_chain_broke() -> None:
    log = Log("rS-later")
    s = _stop(log)
    _bump(log, "f2s_revoke")  # no card pending: branch (b)
    _replan(log, _asked(log))  # but a card expired after it
    _status(log, "IN_CALL", "NEEDS_REPLAN")
    _asked(log)
    r = _bump(log, "slow_revoke")
    n = _replan(log, r)
    _escalate(log)
    assert _cited(log) == ("S", "user_stop", s, _at_of(log, r), n)


def test_the_stop_and_revoke_names_match_the_world_and_the_contract() -> None:
    # simuser._reply writes stop: "stop" | "mind_change" (tests/env/test_stop
    # pins the payloads); obs may not import env.
    assert frozenset({"stop", "mind_change"}) == stops.STOPS
    reasons = set(get_args(EpochBump.model_fields["reason"].annotation))
    assert stops.REVOKES == frozenset({"f2s_revoke", "slow_revoke"}) <= reasons
