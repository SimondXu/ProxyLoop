"""The outcome tiers (``obs.tiers``, S1-SYS-68) on hand-built event logs: one
log per tier, X over everything, the verified no-deal mapping pinned over an
enumeration of runs, the continuous values in integer cents, and the battery
summary diagnose prints."""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import pytest
from tests.obs.bundles import Log, manifest, write
from tests.obs.triage_bundle import P

from proxyloop.contract.state import READBACK_FIELD, CaseStatus
from proxyloop.env.tasks.schema import MONEY, money_term
from proxyloop.obs import detectors, diagnose, tiers


def _tier(log: Log) -> dict[str, object]:
    x = detectors.Inputs(log.events, None, lambda _: None)
    value = detectors.DETECTORS["tier"](x)
    assert isinstance(value, dict)
    return value  # type: ignore[return-value]


def _status(log: Log, status: str) -> None:
    changed: P = {"previous": "IN_CALL", "status": status}
    log.add("status.changed", "guard", "agent", changed, (log.start,))


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


def _mandate(log: Log, max_minor: int, decision: str | None = "granted") -> str:
    proposed: P = {"mandate_id": "m1", "mandate_hash": "mh", "status": "proposed"}
    proposed |= {"epoch": 0, "max_monthly_price_minor": max_minor}
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
    cid = log.add("approval.requested", "guard", "agent", card, (oid,))
    decided: P = {"approval_id": "a1", "decision": decision, "by": by}
    return log.add("approval.decided", "kernel", "agent", decided, (cid,))


def _accept(log: Log, grant: str | None, cap: str = "cap-1") -> str:
    """action.authorized (caused by ``grant``) -> the accept line -> heard."""
    capability: P = {"cap_id": cap, "business_action_id": "b", "terms_hash": "th"}
    capability |= {"intent": "accept_offer", "epoch": 0, "expires_ms": 10**9}
    auth: P = {"intent": "accept_offer", "capability": capability}
    aid = log.add("action.authorized", "guard", "agent", auth,
                  (grant or log.start,))  # fmt: skip
    line: P = {"lane": "cp", "kind": "accept", "text": "PRIV", "cap_id": cap}
    said = log.add("speak.verbatim", "guard", "agent", line, (aid,))
    rel = log.add("speak.released", "kernel", "agent", {"lane": "cp", "cap_id": cap},
                  (said,))  # fmt: skip
    return _heard(log, f"accept-{len(log.events)}", rel)


def _heard(log: Log, utt_id: str, cause: str) -> str:
    out: P = {"lane": "cp", "utt_id": utt_id, "text_generated": "PRIV"}
    out |= {"text_heard": "PRIV", "interrupted": False}
    log.add("utt.delivered", "kernel", "agent", out, (cause,))
    return utt_id


def _commit(log: Log, utt_id: str, ledger: bool = True) -> None:
    ear: P = {"utt_id": utt_id, "act": "accept", "args": {}, "call_id": "e"}
    ear_id = log.add("rep.ear", "world.ear", "world", ear, (log.start,))
    intent: P = {"kind": "confirmed", "offer_ref": "save-1", "say": [], "ask": []}
    policy: P = {"from": "OFFER", "to": "CONFIRMED", "rung": 0, "intent": intent}
    pid = log.add("rep.policy", "world.policy", "world", policy, (ear_id,))
    heard: P = {"utt_id": utt_id, "offer_ref": "save-1"}
    hid = log.add("rep.commit_heard", "world.policy", "world", heard, (ear_id, pid))
    if ledger:
        write_: P = {"confirmation_id": "123456", "binding": {}}
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


def test_an_escalated_run_is_s() -> None:
    log = Log("rS")
    _status(log, "ESCALATED")
    log.end("escalated")
    assert (_tier(log)["tier"], _tier(log)["reason"]) == ("S", "escalated")


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


# -- totality -----------------------------------------------------------------

_LADDERS = ("none", "no_ladder", "unfinished", "exhausted", "all_pulled", "committed")
_PRICES = ("worse", "better_no_mandate", "within", "above", "no_current")
_ENDS = ("done", "no_deal", "info_only", "timeout", "world_error", "llm_unavailable",
         "abandoned")  # fmt: skip
_STATUSES = (None, *CaseStatus)


def _enumerated(status: CaseStatus | None, end: str, ladder: str, price: str) -> Log:
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
    for status, end, ladder, price in itertools.product(
        _STATUSES, _ENDS, _LADDERS, _PRICES
    ):
        t = _tier(_enumerated(status, end, ladder, price))
        tier, reason, case = t["tier"], t["reason"], (status, end, ladder, price)
        seen.add(tier)
        assert tier in allowed and isinstance(reason, str) and reason, case
        s = None if status is None else status.value
        if s == "VERIFIED_COMPLETE":
            want = ("A", "mandate") if ladder == "committed" else (None, "no_commit")
            assert (tier, reason) == want, case
        elif s == "ESCALATED":
            assert (tier, reason) == ("S", "escalated"), case
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


def _row(task_ref: str, tier: str | None, kind: str | None = None) -> dict[str, object]:
    t: dict[str, object] = {"tier": tier, "family": task_ref.partition("@")[0]}
    t |= {"task_kind": kind, "declass_denied": 1 if tier == "A" else 0}
    return {"task_ref": task_ref, "detectors": {"tier": t}}


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
    block = out[out.index(f"== tiers ({tiers.NOTE})") :]
    assert block[1:] == [
        "  cp-direct-discount A=1 F=1 | ab=yes",
        "  ab_every_family=yes declass_denied=0",
    ]
    assert diagnose.main(["--root", str(tmp_path), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert sorted(r["run_id"] for r in doc["runs"]) == ["rA", "rF"]
    assert doc["tiers"]["ab_per_family"] == {"cp-direct-discount": True}
