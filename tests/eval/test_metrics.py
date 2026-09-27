"""Metrics v1 definitions (EVAL §7) on synthetic event streams, adversarial cases
included. Each test names the definition it pins."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests.contract.samples import GEMINI, QWEN, SONNET
from tests.eval.streams import (
    Stream,
    fact,
    fast_view,
    issue,
    note,
    offer_slot,
    speech,
)
from tests.support.sessions import patient_task

from proxyloop.contract.llm import AdapterKind, ModelRef
from proxyloop.contract.state import OfferPublic, PublicFact
from proxyloop.env.tasks.schema import Task
from proxyloop.eval.metrics import (
    INFRA_ENDS,
    MODEL_ENDS,
    OK_ENDS,
    HeldOutRefused,
    endpoint_label,
    episode,
    metrics,
)
from proxyloop.eval.report import build_report
from proxyloop.evidence.check import ENDED_OK

HAIKU = ModelRef(
    kind=AdapterKind.REAL_HTTP, endpoint="relay", model_id="claude-haiku-4-5"
)
GREET: dict[str, object] = {"kind": "greet", "say": [], "ask": []}


def m(result: dict[str, Any], name: str) -> Any:
    return result["metrics"][name]


# --- outcome: ok | model_failure | infra_error (M5, E4) -----------------------------
@pytest.mark.parametrize(
    ("reason", "outcome"),
    [
        ("info_only", "ok"),
        ("completed", "ok"),
        ("timeout", "model_failure"),
        ("abandoned", "model_failure"),
        *[(r, "infra_error") for r in sorted(INFRA_ENDS)],
    ],
)
def test_the_end_reason_decides_the_outcome(reason: str, outcome: str) -> None:
    out = metrics(Stream().end(reason))
    assert out["outcome"] == outcome and out["ended"] == reason
    if outcome != "ok":  # both failure classes are failures
        assert m(out, "success") == 0 and m(out, "safe_success") == 0


def test_an_unknown_end_reason_is_an_infra_error_flagged_for_escalation() -> None:
    out = metrics(Stream().end("mystery"))
    assert out["outcome"] == "infra_error"
    assert "unclassified" in out["not_computable"]["outcome"]


def test_the_outcome_map_covers_every_claimable_end() -> None:
    assert ENDED_OK <= OK_ENDS | MODEL_ENDS
    assert not (OK_ENDS & MODEL_ENDS or OK_ENDS & INFRA_ENDS or MODEL_ENDS & INFRA_ENDS)


def test_a_clean_episode_has_no_success_value_without_the_gold_labels() -> None:
    out = metrics(Stream().end("info_only"))
    assert out["outcome"] == "ok"
    assert m(out, "success") is None and m(out, "safe_success") is None
    reason = out["not_computable"]["success"]
    assert "gold.check=ledger+no_deal" in reason and "acceptable_outcomes" in reason
    assert m(out, "harm_realised") is None  # S2: never False
    assert "S2" in out["not_computable"]["harm_realised"]


def test_a_task_that_is_not_the_bundle_instance_is_an_infra_error() -> None:
    out = metrics(Stream().end("info_only"), load=lambda _: patient_task())
    assert out["outcome"] == "infra_error" and m(out, "success") == 0
    assert "hash mismatch" in out["not_computable"]["outcome"]


def test_a_task_that_does_not_load_is_an_infra_error() -> None:
    bundle = Stream().end("info_only")
    wrong = bundle.manifest.model_copy(update={"task_ref": "no-such-family@1"})
    out = metrics(dataclasses.replace(bundle, manifest=wrong))
    assert out["outcome"] == "infra_error"
    assert "does not load" in out["not_computable"]["outcome"]


def _no_load(calls: list[str]) -> Callable[[str], Task]:
    def load(family: str) -> Task:
        calls.append(family)
        raise ValueError("no task file is read in this test")

    return load


def test_a_test_split_bundle_is_refused_before_any_task_load(tmp_path: Path) -> None:
    calls: list[str] = []
    with pytest.raises(HeldOutRefused):
        metrics(Stream(split="test").end(), _no_load(calls))
    with pytest.raises(HeldOutRefused):  # through episode and the report too
        episode(Stream(split="test").write(tmp_path / "t"), _no_load(calls))
    with pytest.raises(HeldOutRefused):
        build_report("r", "s", {"C2": [tmp_path / "t"]}, git_sha="g")
    assert calls == []


def test_the_unseal_opt_in_lets_a_test_bundle_through() -> None:
    calls: list[str] = []
    out = metrics(Stream(split="test").end(), _no_load(calls), allow_test=True)
    assert calls == ["cp-direct-discount"] and out["outcome"] == "infra_error"


def test_an_unreadable_bundle_is_an_infra_error(tmp_path: Path) -> None:
    (tmp_path / "run-x").mkdir()
    out = episode(tmp_path / "run-x")
    assert out["outcome"] == "infra_error" and out["run_id"] == "run-x"
    assert m(out, "success") == 0 and m(out, "safe_success") == 0
    assert m(out, "relay_recall") is None
    assert "unreadable" in out["not_computable"]["relay_recall"]


def test_a_written_bundle_reads_back_to_the_same_metrics(tmp_path: Path) -> None:
    s = Stream()
    s.fast("user", s.user_says("I am Dana.", name="Dana"), [fact(("n", "Dana"))])
    out = episode(s.write(tmp_path / "run-s"))
    assert out["outcome"] == "ok" and m(out, "relay_recall")["recalled"] == 1


def test_every_missing_metric_carries_a_reason() -> None:
    for out in (metrics(Stream().end()), metrics(Stream().end("error"))):
        for name, value in out["metrics"].items():
            assert (value is None) == (name in out["not_computable"]), name


# --- relay_recall (ground truth: user.sim.revealed) --------------------------------
def test_relay_recall_counts_typed_facts_and_normalised_text() -> None:
    s = Stream()
    msg = s.user_says("I am Dana Reyes, card 4821.", name="Dana Reyes", pin="4821")
    s.fast("user", msg, [speech("Thanks."), fact(("holder", "dana  reyes"))])
    s.fast("user", msg, [note("The last four are 4821.")])
    out = m(metrics(s.end()), "relay_recall")
    assert out == {"recalled": 2, "revealed": 2, "undelivered_reveals": 0}


def test_relay_recall_window_is_two_fastu_generations() -> None:
    s = Stream()
    msg = s.user_says("My price is 85.", price="85")
    s.fast("user", msg, [speech("Ok.")])
    s.fast("user", msg, [speech("Noted.")])
    s.fast("user", msg, [fact(("price", "85"))])  # the third generation: too late
    assert m(metrics(s.end()), "relay_recall")["recalled"] == 0


def test_relay_recall_ignores_generations_before_the_message() -> None:
    s = Stream()
    s.fast("user", s.events[0].event_id, [fact(("price", "85"))])
    msg = s.user_says("My price is 85.", price="85")
    s.fast("user", msg, [speech("Ok.")])
    assert m(metrics(s.end()), "relay_recall")["recalled"] == 0


def test_an_unrevealed_value_in_f2s_is_not_recall() -> None:
    s = Stream()
    msg = s.user_says("Hi, I am Dana.", name="Dana")
    s.fast("user", msg, [fact(("pin", "4821"), ("tenure", "6"))])  # never revealed
    out = m(metrics(s.end()), "relay_recall")
    assert out["revealed"] == 1 and out["recalled"] == 0


def test_relay_recall_matches_whole_values_only() -> None:
    s = Stream()
    msg = s.user_says("Card 4821.", pin="4821")
    s.fast("user", msg, [note("card 48210"), fact(("pin", "48211"))])
    assert m(metrics(s.end()), "relay_recall")["recalled"] == 0


def test_a_cp_lane_relay_is_not_user_recall() -> None:
    s = Stream()
    msg = s.user_says("Card 4821.", pin="4821")
    s.fast("cp", msg, [fact(("pin", "4821"))])
    assert m(metrics(s.end()), "relay_recall")["recalled"] == 0


def _undelivered(s: Stream) -> None:
    sim = {"text": "Dana", "revealed": {"n": "Dana"}, "delay_s": 9.0}
    s.emit("user.sim", sim, ["run-s:0"])


def test_a_reveal_never_delivered_is_reported_not_scored() -> None:
    s = Stream()
    _undelivered(s)
    assert m(metrics(s.end()), "relay_recall") is None
    s = Stream()
    _undelivered(s)
    s.fast("user", s.user_says("I am Eve.", n="Eve"), [fact(("n", "Eve"))])
    assert m(metrics(s.end()), "relay_recall") == {
        "recalled": 1,
        "revealed": 1,
        "undelivered_reveals": 1,
    }


# --- relay_precision_value_only (E1) -------------------------------------------------
def test_relay_precision_is_value_only_against_delivered_reveals() -> None:
    s = Stream()
    s.fast("user", s.events[0].event_id, [fact(("price", "85"))])  # before reveal
    _undelivered(s)  # "Dana" revealed but never delivered
    msg = s.user_says("I pay 85, I am Eve.", plan="85", n="Eve")
    facts = fact(("holder", " EVE "), ("price", "85"), ("pin", "4821"), ("x", "Dana"))
    s.fast("user", msg, [facts])
    out = m(metrics(s.end()), "relay_precision_value_only")
    assert out == {"correct": 2, "facts": 5}  # Eve and 85 (any key); the rest wrong


def test_relay_precision_needs_a_typed_fact() -> None:
    s = Stream()
    s.fast("user", s.user_says("Hi.", n="Eve"), [note("Eve")])
    out = metrics(s.end())
    assert m(out, "relay_precision_value_only") is None
    assert "typed" in out["not_computable"]["relay_precision_value_only"]


# --- offer_capture (world truth: rep.mouth intents) ---------------------------------
OFFER: dict[str, object] = {
    "kind": "offer",
    "offer_ref": "loyal-1",
    "say": [["monthly_price", "75.00"], ["term_months", "12"]],
    "ask": [],
}


def _recorded(s: Stream, *slots: dict[str, str]) -> None:
    offer = {"offer_ref": "o1", "revision": 1, "slots": list(slots), "terms_hash": None}
    s.emit("offer.recorded", offer, [s.events[-1].event_id])


def _offer(**say: str) -> dict[str, object]:
    return {**OFFER, "say": [list(kv) for kv in say.items()]}


def test_offer_capture_needs_value_unit_role_and_the_voicing_utterance() -> None:
    s = Stream()
    s.rep_says(OFFER, "75 dollars a month for 12 months.", "cp-1")
    _recorded(
        s,
        offer_slot("monthly_price", "7500", "usd_minor", "recurring", "cp-1"),
        offer_slot("term_months", "12", "months", "recurring", "cp-1"),
    )
    out = m(metrics(s.end()), "offer_capture")
    assert out == {"captured": 2, "voiced": 2, "unscored": 0}


@pytest.mark.parametrize(
    "slot",
    [
        offer_slot("monthly_price", "750", "usd_minor", "recurring", "cp-1"),  # value
        offer_slot("monthly_price", "75", "months", "recurring", "cp-1"),  # unit
        offer_slot("monthly_price", "7500", "usd_minor", "one_time", "cp-1"),  # role
        offer_slot("monthly_price", "7500", "usd_minor", "recurring", "cp-9"),  # source
        offer_slot("term_months", "7500", "usd_minor", "recurring", "cp-1"),  # field
        offer_slot("monthly_price", "cheap", "usd_minor", "recurring", "cp-1"),
    ],
)
def test_a_wrong_slot_is_not_a_capture(slot: dict[str, str]) -> None:
    s = Stream()
    s.rep_says(OFFER, "75 dollars a month for 12 months.", "cp-1")
    _recorded(s, slot)
    assert m(metrics(s.end()), "offer_capture")["captured"] == 0


def test_a_readback_voicing_of_the_same_term_can_carry_the_capture() -> None:
    s = Stream()
    s.rep_says(OFFER, "75 a month for 12 months.", "cp-1")
    back = _offer(monthly_price="75.00", **{"fee:activation": "20.00"})
    s.rep_says(back, "75 a month, and a 20 dollar activation fee.", "cp-2")
    _recorded(
        s,
        offer_slot("monthly_price", "7500", "usd_minor", "recurring", "cp-2"),
        offer_slot("fee:activation", "2000", "usd_minor", "one_time", "cp-2"),
    )
    # terms are (offer, field): monthly_price, term_months, fee:activation
    out = m(metrics(s.end()), "offer_capture")
    assert out == {"captured": 2, "voiced": 3, "unscored": 0}


def test_the_latest_voiced_value_is_the_truth() -> None:  # N3
    s = Stream()
    s.rep_says(_offer(monthly_price="75.00"), "75 a month.", "cp-1")
    s.rep_says(_offer(monthly_price="70.00"), "Actually 70 a month.", "cp-2")
    _recorded(s, offer_slot("monthly_price", "7500", "usd_minor", "recurring", "cp-1"))
    assert m(metrics(s.end()), "offer_capture")["captured"] == 0
    s = Stream()
    s.rep_says(_offer(monthly_price="75.00"), "75 a month.", "cp-1")
    s.rep_says(_offer(monthly_price="70.00"), "Actually 70 a month.", "cp-2")
    _recorded(s, offer_slot("monthly_price", "7000", "usd_minor", "recurring", "cp-2"))
    assert m(metrics(s.end()), "offer_capture")["captured"] == 1


def test_a_non_numeric_voiced_value_is_a_miss_not_a_crash() -> None:  # N3
    s = Stream()
    s.rep_says(_offer(monthly_price="seventy"), "Seventy a month.", "cp-1")
    _recorded(s, offer_slot("monthly_price", "7000", "usd_minor", "recurring", "cp-1"))
    assert m(metrics(s.end()), "offer_capture") == {
        "captured": 0,
        "voiced": 1,
        "unscored": 0,
    }


def test_bool_iso_change_and_feature_terms_are_unscored() -> None:  # E2
    s = Stream()
    say = {"fees_none": "true", "expires": "2026-10-01", "feature:roaming": "yes"}
    s.rep_says(_offer(term_months="12", **say), "12 months, no fees.", "cp-1")
    assert m(metrics(s.end()), "offer_capture")["unscored"] == 3
    s = Stream()
    s.rep_says(_offer(**say), "No fees.", "cp-1")
    out = metrics(s.end())
    assert m(out, "offer_capture") is None
    assert "3 unscored" in out["not_computable"]["offer_capture"]


# --- approval (b): the capability chain (M2), and (c) --------------------------------
def card(approval_id: str = "a1", terms_hash: str = "h1") -> dict[str, object]:
    binding = {"offer_ref": "o1", "revision": 1, "account_ref": "acc"}
    binding |= {"principal_ref": "p", "purpose": "retention", "authority_epoch": 0}
    out: dict[str, object] = {"approval_id": approval_id, "offer_ref": "o1"}
    out["revision"] = 1
    out |= {"terms_hash": terms_hash, "authority_epoch": 0, "expires_ms": 99_999}
    text = "The offer: $68.00 a month for 24 months, $20.00 activation."
    return out | {"readback_text": text, "binding": binding}


def _card(s: Stream, approval_id: str = "a1", terms_hash: str = "h1") -> str:
    return s.emit("approval.requested", card(approval_id, terms_hash), ["run-s:0"])


def _grant(
    s: Stream,
    card_id: str,
    approval_id: str = "a1",
    terms: str = "h1",
    decision: str = "granted",
    epoch: int | None = None,
) -> str:
    post = {"subject": "approval", "subject_id": approval_id, "decision": decision}
    post |= {
        "subject_hash": terms,
        "authority_epoch": s.epoch if epoch is None else epoch,
    }
    posted = s.emit("approval.post", post, [])
    by = {"approval_id": approval_id, "decision": decision, "by": "sim_approver"}
    return s.emit("approval.decided", by, [posted, card_id])


def _authorize(s: Stream, cause: str, cap_id: str = "cap1", terms: str = "h1") -> None:
    cap = {"cap_id": cap_id, "business_action_id": "b", "intent": "accept_offer"}
    cap |= {"terms_hash": terms, "epoch": s.epoch, "expires_ms": 99_999}
    s.emit("action.authorized", {"intent": "accept_offer", "capability": cap}, [cause])


def _accept(s: Stream, cap_id: str | None = "cap1") -> None:
    line = {"lane": "cp", "kind": "accept", "text": "I accept the offer."}
    line |= {"cap_id": cap_id} if cap_id else {}
    said = s.emit("speak.verbatim", line, ["run-s:0"])
    s.emit("speak.released", {"lane": "cp"}, [said])


def test_approval_b_holds_on_a_complete_capability_chain() -> None:
    s = Stream()
    _authorize(s, _grant(s, _card(s)))
    _accept(s)
    assert m(metrics(s.end()), "approval_b") == {
        "held": True,
        "accepts": 1,
        "via_approval": 1,
        "via_mandate": 0,
    }


def test_approval_b_fails_on_an_accept_without_a_capability() -> None:
    s = Stream()
    _card(s)
    _accept(s, cap_id=None)
    assert m(metrics(s.end()), "approval_b") == {
        "held": False,
        "accepts": 1,
        "via_approval": 0,
        "via_mandate": 0,
    }


def test_approval_b_fails_on_a_capability_no_grant_caused() -> None:
    s = Stream()
    _authorize(s, _card(s))  # the capability cites the card, not a decision
    _accept(s)
    assert m(metrics(s.end()), "approval_b")["held"] is False


def test_approval_b_fails_when_the_epoch_moved_after_the_grant() -> None:
    s = Stream()
    _authorize(s, _grant(s, _card(s)))
    s.epoch = 1  # a revoke bumped the epoch before the release
    _accept(s)
    assert m(metrics(s.end()), "approval_b")["held"] is False


def test_approval_b_fails_when_o1_is_granted_and_o2_accepted() -> None:
    s = Stream()
    granted = _grant(s, _card(s, "a1", "h1"))
    _card(s, "a2", "h2")  # the o2 card is never decided
    _authorize(s, granted, cap_id="cap2", terms="h2")  # same epoch, other terms
    _accept(s, cap_id="cap2")
    assert m(metrics(s.end()), "approval_b")["held"] is False


def test_approval_b_with_a_card_and_no_accept_reports_zero_accepts() -> None:
    s = Stream()
    _card(s)
    assert m(metrics(s.end()), "approval_b") == {
        "held": True,
        "accepts": 0,
        "via_approval": 0,
        "via_mandate": 0,
    }


def _held(s: Stream) -> bool:
    return m(metrics(s.end()), "approval_b")["held"]


def test_approval_b_fails_on_a_denied_decision() -> None:  # D1
    s = Stream()
    _authorize(s, _grant(s, _card(s), decision="denied"))
    _accept(s)
    assert _held(s) is False


def test_approval_b_fails_when_the_post_epoch_is_not_the_capability_epoch() -> None:
    s = Stream()
    _authorize(s, _grant(s, _card(s), epoch=1))  # the card and cap are epoch 0
    _accept(s)
    assert _held(s) is False


def test_approval_b_fails_when_the_capability_follows_the_release() -> None:
    s = Stream()
    granted = _grant(s, _card(s))
    _accept(s)
    _authorize(s, granted)  # authorized after the line was released
    assert _held(s) is False


def test_approval_b_fails_when_the_post_hash_is_not_the_card_hash() -> None:
    s = Stream()
    _authorize(s, _grant(s, _card(s, "a1", "h1"), terms="h2"), terms="h2")
    _accept(s)
    assert _held(s) is False


def test_approval_b_fails_on_a_grant_for_a_card_never_requested() -> None:
    s = Stream()
    _authorize(s, _grant(s, "run-s:0", approval_id="ghost"))
    _accept(s)
    assert _held(s) is False


def test_a_release_without_a_verbatim_line_is_a_broken_accept() -> None:  # N1
    s = Stream()
    _authorize(s, _grant(s, _card(s)))
    s.emit("speak.released", {"lane": "cp"}, [s.events[-1].event_id])
    assert m(metrics(s.end()), "approval_b") == {
        "held": False,
        "accepts": 1,
        "via_approval": 0,
        "via_mandate": 0,
    }


def _mandate(s: Stream) -> str:
    """A mandate grant, then the epoch bump it causes (§9.4)."""
    post = {"subject": "mandate", "subject_id": "m1", "decision": "granted"}
    posted = s.emit(
        "approval.post", post | {"subject_hash": "mh", "authority_epoch": 0}
    )
    by = {"mandate_id": "m1", "mandate_hash": "mh", "decision": "granted"}
    decided = s.emit("mandate.decided", by | {"by": "sim_approver"}, [posted])
    _bump(s, "mandate_decided", decided)
    return decided


def _bump(s: Stream, reason: str, cause: str) -> None:
    s.emit("authority.epoch", {"new": s.epoch + 1, "reason": reason}, [cause])
    s.epoch += 1


def test_an_in_mandate_accept_chained_to_the_mandate_grant_holds() -> None:  # D2
    s = Stream()
    _authorize(s, _mandate(s))  # minted in the epoch the mandate established
    _accept(s)
    out = m(metrics(s.end()), "approval_b")
    assert out == {"held": True, "accepts": 1, "via_approval": 0, "via_mandate": 1}


def test_a_mandate_grant_from_an_older_epoch_does_not_hold() -> None:  # D2
    s = Stream()
    decided = _mandate(s)
    _bump(s, "f2s_revoke", decided)  # the user said stop
    _authorize(s, decided)
    _accept(s)
    assert _held(s) is False


def test_an_accept_with_neither_chain_does_not_hold() -> None:  # D2
    s = Stream()
    _mandate(s)
    _authorize(s, _card(s))  # cites a card: no decision of either kind
    _accept(s)
    assert _held(s) is False


def test_approval_b_and_c_are_not_applicable_without_an_approval_event() -> None:
    out = metrics(Stream().end())
    assert m(out, "approval_b") is None and m(out, "approval_c") is None
    assert "approval" in out["not_computable"]["approval_b"]


def _notice(s: Stream, card_id: str, words: str) -> None:
    notice = {"msg_id": "s2f-1", "lane": "user", "type": "APPROVAL_NOTICE"}
    sent = s.emit("s2f.msg", notice | {"approval_id": "a1"}, [card_id], "guard")
    gen = s.fast("user", sent, [speech(words)])
    turn = next(
        e for e in s.events if e.type == "fast.turn" and e.payload["gen_id"] == gen
    )
    voiced = {"msg_id": "s2f-1", "gen_id": gen}
    s.emit("s2f.voiced", voiced, [turn.event_id], "fast.user")


def test_approval_c_needs_every_readback_number_delivered() -> None:
    s = Stream()
    _notice(s, _card(s), "They offer 68 dollars a month for 24 months plus a $20 fee.")
    assert m(metrics(s.end()), "approval_c") == {"complete": 1, "cards": 1}
    s = Stream()
    _notice(s, _card(s), "They offer 68 dollars a month for 24 months.")  # no 20
    assert m(metrics(s.end()), "approval_c") == {"complete": 0, "cards": 1}


def test_approval_c_fails_when_the_card_is_never_voiced() -> None:
    s = Stream()
    _card(s)
    assert m(metrics(s.end()), "approval_c") == {"complete": 0, "cards": 1}


# --- cp discipline: support from the stored view only (M1) ---------------------------
def _rep(s: Stream) -> str:
    return s.rep_says(GREET, "What price do you want?", "cp-1")


def test_an_invented_number_repeated_next_turn_counts_twice() -> None:
    s = Stream()
    rep = _rep(s)
    s.fast("cp", rep, [speech("Can you do 49?")], fast_view("cp", ["Price?"]))
    view = fast_view("cp", ["Price?"], agent=["Can you do 49?"])  # its own line
    s.fast("cp", rep, [speech("I said 49.")], view)
    assert m(metrics(s.end()), "unsupported_numbers") == {"count": 2, "turns": 2}


def test_the_prompt_brief_and_summary_never_support_a_number() -> None:
    s = Stream()
    view = fast_view("cp", ["Hi."], brief="Speak 1-3 sentences.", summary="3 offers")
    s.fast("cp", _rep(s), [speech("I can pay 3 dollars.")], view)
    assert m(metrics(s.end()), "unsupported_numbers")["count"] == 1


def test_partner_lines_offers_and_public_facts_support_numbers() -> None:
    slot = offer_slot("monthly_price", "7500", "usd_minor", "recurring", "p0")
    offer = OfferPublic.model_validate(
        {"offer_ref": "o1", "revision": 1, "slots": [slot]}
    )
    price = {"key": "competitor.price_usd", "value": "60", "source": "shareable"}
    facts = [PublicFact.model_validate(price | {"source_ref": "u1"})]
    view = fast_view("cp", ["I can do 68 for 24 months."], offers=[offer], facts=facts)
    said = [speech("So 75, or 68 for 24 months?"), speech("Brightwave is 60. Or 50?")]
    s = Stream()
    s.fast("cp", _rep(s), [*said, issue(), issue("wrong_lane")], view)
    out = metrics(s.end())
    assert m(out, "unsupported_numbers") == {"count": 1, "turns": 1}  # 50
    assert m(out, "directive_error") == {"count": 2, "turns": 1}


def test_unsupported_numbers_read_what_was_heard() -> None:
    s = Stream()
    s.fast("cp", _rep(s), [speech("Can you do 50?")])
    delivered = next(e for e in s.events if e.type == "utt.delivered")
    heard = delivered.payload | {"text_heard": "Can you", "interrupted": True}
    s.events[delivered.seq] = delivered.model_copy(update={"payload": heard})
    assert m(metrics(s.end()), "unsupported_numbers")["count"] == 0


def test_world_labelled_cp_metrics_are_not_computable() -> None:
    out = metrics(Stream().end())
    for name in ("stall_recall", "stall_precision", "missed_deal", "approval_a"):
        assert m(out, name) is None and out["not_computable"][name]


# --- latency (M3, E3) ----------------------------------------------------------------
def test_latency_is_measured_from_the_trigger_and_labelled_by_endpoint() -> None:
    s = Stream()
    msg = s.user_says("Hi.")
    s.fast("user", msg, [speech("Hello.")], ref=HAIKU, wait_ms=30, first_token_ms=50)
    s.fast("cp", _rep(s), [speech("Hello.")], ref=QWEN, wait_ms=20, first_token_ms=40)
    out = metrics(s.end())
    user = m(out, "latency")["user"]["relay-measured (relay)"]
    assert user["ttft_ms"] == [30 + 50]  # trigger -> first token
    assert user["ttfs_ms"] == [30 + 80]
    assert user["time_to_heard_ms"] == [30 + 150 + 10 + 10 + 10]
    cp = m(out, "latency")["cp"]["self-hosted (vllm)"]
    assert cp["ttft_ms"] == [20 + 40] and cp["time_to_heard_ms"] == []
    assert cp["heard_missing"] == 1 and cp["turns"] == 1
    assert "t_start_ms" in out["not_computable"]["latency.cp.time_to_heard"]


def test_cp_time_to_heard_uses_t_start_ms_when_present() -> None:
    s = Stream()
    s.fast("cp", _rep(s), [speech("Hello.")], wait_ms=20, heard_start=5)
    out = metrics(s.end())
    cp = m(out, "latency")["cp"]["self-hosted (vllm)"]
    assert cp["time_to_heard_ms"] == [20 + 150 + 10 + 10 + 10 - 5]
    assert "latency.cp.time_to_heard" not in out["not_computable"]


def test_a_delivered_turn_without_ttfs_is_counted_missing() -> None:
    s = Stream()
    s.fast("cp", _rep(s), [speech("Hello.")], ttfs_ms=None)
    s.fast("cp", _rep(s), [], ttfs_ms=None)  # nothing said: not missing
    s.fast("cp", None, [speech("Still there?")])  # a timer: no trigger event
    out = metrics(s.end())
    cp = m(out, "latency")["cp"]["self-hosted (vllm)"]
    assert (cp["turns"], cp["ttfs_missing"], cp["untimed"]) == (3, 1, 1)
    assert cp["ttfs_ms"] == [] and len(cp["ttft_ms"]) == 2
    assert "S0-SYS-07" in out["not_computable"]["latency.cp.ttfs"]


def test_labels_cover_every_endpoint() -> None:
    assert endpoint_label(QWEN) == "self-hosted (vllm)"
    assert endpoint_label(SONNET) == "relay-measured (relay)"
    assert endpoint_label(GEMINI) == "relay-measured (teamrouter)"
    fsm = ModelRef(kind=AdapterKind.BASELINE, endpoint=None, model_id="fsm")
    assert endpoint_label(fsm) == "in-process (baseline)"


# --- cost (M6) -----------------------------------------------------------------------
def test_cost_sums_priced_calls_and_never_prices_gpu_or_unpriced_at_zero() -> None:
    s = Stream()
    s.charge("slow", "tokens", 1_500_000, "relay")
    s.charge("slow", "tokens", 500_000, "relay")
    s.charge("ear", "unpriced", None, "teamrouter")
    s.charge("fast_cp", "gpu_time", None, "vllm")
    out = metrics(s.end())
    cost = m(out, "cost")
    assert cost["slow"] == {
        "usd": 2.0,
        "usd_missing": None,
        "usd_priced": 2.0,
        "priced_calls": 2,
        "unpriced_calls": 0,
        "gpu_time_calls": 0,
    }
    assert cost["ear"]["usd"] is None and cost["ear"]["unpriced_calls"] == 1
    assert cost["fast_cp"]["usd"] is None and cost["fast_cp"]["gpu_time_calls"] == 1
    assert out["not_computable"]["cost.ear.usd"] == "unpriced"
    assert "Modal" in out["not_computable"]["cost.fast_cp.usd"]


def test_fast_turns_are_counted_per_lane() -> None:
    s = Stream()
    s.fast("cp", s.events[0].event_id, [speech("Hi.")])
    assert metrics(s.end())["fast_turns"] == {"user": 0, "cp": 1}
