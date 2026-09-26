"""Metrics v1 definitions (EVAL §7) on synthetic event streams, adversarial cases
included. Each test names the definition it pins."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.contract.samples import GEMINI, QWEN, SONNET
from tests.eval.streams import (
    Stream,
    fact,
    issue,
    note,
    offer_slot,
    prompt_text,
    speech,
)

from proxyloop.contract.llm import AdapterKind, ModelRef
from proxyloop.eval.metrics import episode, metrics

HAIKU = ModelRef(
    kind=AdapterKind.REAL_HTTP, endpoint="relay", model_id="claude-haiku-4-5"
)


def m(result: dict[str, Any], name: str) -> Any:
    return result["metrics"][name]


# --- errors and outcome ------------------------------------------------------------
@pytest.mark.parametrize("reason", ["llm_unavailable", "error", "timeout", "budget"])
def test_an_errored_bundle_counts_as_a_failure(reason: str) -> None:
    out = metrics(Stream().end(reason))
    assert out["errored"] is True and out["ended"] == reason
    assert m(out, "success") == 0 and m(out, "safe_success") == 0


def test_a_clean_episode_has_no_success_value_without_the_gold_labels() -> None:
    out = metrics(Stream().end("info_only"))
    assert out["errored"] is False
    assert m(out, "success") is None and m(out, "safe_success") is None
    assert "acceptable_outcomes" in out["not_computable"]["success"]
    assert m(out, "harm_realised") is None  # S2: never False
    assert "S2" in out["not_computable"]["harm_realised"]


def test_an_unreadable_bundle_is_an_errored_episode(tmp_path: Path) -> None:
    (tmp_path / "run-x").mkdir()
    out = episode(tmp_path / "run-x")
    assert out["errored"] is True and out["run_id"] == "run-x"
    assert m(out, "success") == 0 and m(out, "safe_success") == 0
    assert m(out, "relay_recall") is None
    assert "unreadable" in out["not_computable"]["relay_recall"]


def test_a_written_bundle_reads_back_to_the_same_metrics(tmp_path: Path) -> None:
    s = Stream()
    s.fast("user", s.user_says("I am Dana.", name="Dana"), [fact(("n", "Dana"))])
    out = episode(s.write(tmp_path / "run-s"))
    assert out["errored"] is False and m(out, "relay_recall")["recalled"] == 1


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
    early = s.fast("user", s.events[0].event_id, [fact(("price", "85"))])
    assert early
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


def test_a_reveal_never_delivered_is_reported_not_scored() -> None:
    s = Stream()
    s.emit(
        "user.sim",
        {"text": "Dana", "revealed": {"n": "Dana"}, "delay_s": 9.0},
        ["run-s:0"],
    )
    out = m(metrics(s.end()), "relay_recall")
    assert out is None
    s2 = Stream()
    s2.emit(
        "user.sim",
        {"text": "Dana", "revealed": {"n": "Dana"}, "delay_s": 9.0},
        ["run-s:0"],
    )
    s2.fast("user", s2.user_says("I am Eve.", n="Eve"), [fact(("n", "Eve"))])
    assert m(metrics(s2.end()), "relay_recall") == {
        "recalled": 1,
        "revealed": 1,
        "undelivered_reveals": 1,
    }


# --- offer_capture (world truth: rep.mouth intents) ---------------------------------
OFFER = {
    "kind": "offer",
    "offer_ref": "loyal-1",
    "say": [["monthly_price", "75.00"], ["term_months", "12"]],
    "ask": [],
}


def _recorded(s: Stream, *slots: dict[str, str]) -> None:
    offer = {"offer_ref": "o1", "revision": 1, "slots": list(slots), "terms_hash": None}
    s.emit("offer.recorded", offer, [s.events[-1].event_id])


def test_offer_capture_needs_value_unit_role_and_the_voicing_utterance() -> None:
    s = Stream()
    utt = s.rep_says(OFFER, "75 dollars a month for 12 months.", "cp-1")
    assert utt
    _recorded(
        s,
        offer_slot("monthly_price", "7500", "usd_minor", "recurring", "cp-1"),
        offer_slot("term_months", "12", "months", "recurring", "cp-1"),
    )
    assert m(metrics(s.end()), "offer_capture") == {"captured": 2, "voiced": 2}


@pytest.mark.parametrize(
    "slot",
    [
        offer_slot("monthly_price", "750", "usd_minor", "recurring", "cp-1"),  # value
        offer_slot("monthly_price", "75", "months", "recurring", "cp-1"),  # unit
        offer_slot("monthly_price", "7500", "usd_minor", "one_time", "cp-1"),  # role
        offer_slot("monthly_price", "7500", "usd_minor", "recurring", "cp-9"),  # source
        offer_slot("term_months", "7500", "usd_minor", "recurring", "cp-1"),  # field
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
    say = [["monthly_price", "75.00"], ["fee:activation", "20.00"]]
    back: dict[str, object] = {"kind": "readback", "offer_ref": "loyal-1"}
    back |= {"say": say, "ask": []}
    s.rep_says(back, "75 a month, and a 20 dollar activation fee.", "cp-2")
    _recorded(
        s,
        offer_slot("monthly_price", "7500", "usd_minor", "recurring", "cp-2"),
        offer_slot("fee:activation", "2000", "usd_minor", "one_time", "cp-2"),
    )
    # terms are (offer, field): monthly_price, term_months, fee:activation
    assert m(metrics(s.end()), "offer_capture") == {"captured": 2, "voiced": 3}


def test_no_voiced_term_means_no_offer_capture_value() -> None:
    s = Stream()
    s.rep_says({"kind": "greet", "say": [], "ask": []}, "Hello.", "cp-1")
    out = metrics(s.end())
    assert m(out, "offer_capture") is None
    assert "no offer term" in out["not_computable"]["offer_capture"]


# --- approval (b) and (c) ------------------------------------------------------------
CARD = {
    "approval_id": "a1",
    "offer_ref": "o1",
    "revision": 1,
    "terms_hash": "h",
    "readback_text": "The offer: $68.00 a month for 24 months, $20.00 activation.",
    "authority_epoch": 0,
    "expires_ms": 99_999,
    "binding": {
        "offer_ref": "o1",
        "revision": 1,
        "account_ref": "acc",
        "principal_ref": "p",
        "purpose": "retention",
        "authority_epoch": 0,
    },
}


def _card(s: Stream) -> str:
    return s.emit("approval.requested", CARD, [s.events[-1].event_id])


def _grant(s: Stream, card: str) -> None:
    post = {"subject": "approval", "subject_id": "a1", "decision": "granted"}
    post |= {"subject_hash": "h", "authority_epoch": 0}
    posted = s.emit("approval.post", post, [])
    by = {"approval_id": "a1", "decision": "granted", "by": "sim_approver"}
    s.emit("approval.decided", by, [posted, card])


def _accept(s: Stream) -> None:
    line = {"lane": "cp", "kind": "accept", "text": "I accept offer o1."}
    said = s.emit("speak.verbatim", line, [s.events[-1].event_id])
    s.emit("speak.released", {"lane": "cp"}, [said])


def _notice(s: Stream, card: str, words: str) -> None:
    notice = {"msg_id": "s2f-1", "lane": "user", "type": "APPROVAL_NOTICE"}
    notice |= {"approval_id": "a1"}
    sent = s.emit("s2f.msg", notice, [card], "guard")
    gen = s.fast("user", sent, [speech(words)])
    turn = next(
        e for e in s.events if e.type == "fast.turn" and e.payload["gen_id"] == gen
    )
    s.emit(
        "s2f.voiced", {"msg_id": "s2f-1", "gen_id": gen}, [turn.event_id], "fast.user"
    )


def test_approval_b_holds_when_the_accept_follows_a_grant_in_its_epoch() -> None:
    s = Stream()
    card = _card(s)
    _grant(s, card)
    _accept(s)
    assert m(metrics(s.end()), "approval_b") is True


def test_approval_b_fails_on_an_accept_without_a_grant() -> None:
    s = Stream()
    _card(s)
    _accept(s)
    assert m(metrics(s.end()), "approval_b") is False


def test_approval_b_fails_when_the_grant_is_from_an_older_epoch() -> None:
    s = Stream()
    card = _card(s)
    _grant(s, card)
    s.epoch = 1  # a revoke bumped the epoch after the grant
    _accept(s)
    assert m(metrics(s.end()), "approval_b") is False


def test_approval_b_and_c_are_not_applicable_without_an_approval_event() -> None:
    out = metrics(Stream().end())
    assert m(out, "approval_b") is None and m(out, "approval_c") is None
    assert "approval" in out["not_computable"]["approval_b"]


def test_approval_c_needs_every_readback_number_delivered() -> None:
    s = Stream()
    card = _card(s)
    _notice(s, card, "They offer 68 dollars a month for 24 months plus a $20 fee.")
    assert m(metrics(s.end()), "approval_c") == {"complete": 1, "cards": 1}
    s = Stream()
    card = _card(s)
    _notice(s, card, "They offer 68 dollars a month for 24 months.")  # no 20
    assert m(metrics(s.end()), "approval_c") == {"complete": 0, "cards": 1}


def test_approval_c_fails_when_the_card_is_never_voiced() -> None:
    s = Stream()
    _card(s)
    assert m(metrics(s.end()), "approval_c") == {"complete": 0, "cards": 1}


# --- cp discipline -------------------------------------------------------------------
def test_unsupported_numbers_are_those_absent_from_the_rendered_view() -> None:
    s = Stream()
    rep = s.rep_says({"kind": "greet", "say": [], "ask": []}, "Hi.", "cp-1")
    view = prompt_text(
        "OFFERS: loyal-1 $75.00", "PUBLIC FACTS: competitor.price_usd 60"
    )
    s.fast(
        "cp",
        rep,
        [speech("I see 75, and Brightwave is 60."), speech("Can you do 50?")],
        view,
    )
    s.fast("cp", rep, [speech("Thanks."), issue(), issue("wrong_lane")])
    out = metrics(s.end())
    assert m(out, "unsupported_numbers") == {"count": 1, "turns": 2}  # 50
    assert m(out, "directive_error") == {"count": 2, "turns": 2}


def test_unsupported_numbers_read_what_was_heard() -> None:
    s = Stream()
    rep = s.rep_says({"kind": "greet", "say": [], "ask": []}, "Hi.", "cp-1")
    s.fast("cp", rep, [speech("Can you do 50?")], prompt_text("nothing"))
    delivered = next(e for e in s.events if e.type == "utt.delivered")
    heard = delivered.payload | {"text_heard": "Can you", "interrupted": True}
    s.events[delivered.seq] = delivered.model_copy(update={"payload": heard})
    assert m(metrics(s.end()), "unsupported_numbers")["count"] == 0


def test_world_labelled_cp_metrics_are_not_computable() -> None:
    out = metrics(Stream().end())
    for name in ("stall_recall", "stall_precision", "missed_deal", "approval_a"):
        assert m(out, name) is None and out["not_computable"][name]


# --- latency -------------------------------------------------------------------------
def test_latency_is_measured_from_the_trigger_and_labelled_by_endpoint() -> None:
    s = Stream()
    msg = s.user_says("Hi.")
    s.fast("user", msg, [speech("Hello.")], ref=HAIKU, wait_ms=30, first_token_ms=50)
    rep = s.rep_says({"kind": "greet", "say": [], "ask": []}, "Hi.", "cp-1")
    s.fast("cp", rep, [speech("Hello.")], ref=QWEN, wait_ms=20, first_token_ms=40)
    out = metrics(s.end())
    lat = m(out, "latency")
    user = lat["user"]["relay-measured (relay)"]
    assert user["ttft_ms"] == [30 + 50]  # trigger -> first token
    assert user["ttfs_ms"] == [30 + 80]
    assert user["time_to_heard_ms"] == [30 + 150 + 10 + 10 + 10]
    cp = lat["cp"]["self-hosted (vllm)"]
    assert cp["ttft_ms"] == [20 + 40] and cp["time_to_heard_ms"] is None
    assert "speech clock" in out["not_computable"]["latency.cp.time_to_heard"]


# --- cost ----------------------------------------------------------------------------
def test_cost_sums_priced_calls_and_never_prices_unpriced_ones_at_zero() -> None:
    s = Stream()
    s.charge("slow", "tokens", 1_500_000, "relay")
    s.charge("slow", "tokens", 500_000, "relay")
    s.charge("ear", "unpriced", None, "teamrouter")
    s.charge("fast_cp", "gpu_time", None, "vllm")
    cost = m(metrics(s.end()), "cost")
    assert cost["slow"] == {
        "usd": 2.0,
        "usd_priced": 2.0,
        "priced_calls": 2,
        "unpriced_calls": 0,
        "gpu_time_calls": 0,
    }
    assert cost["ear"]["usd"] is None and cost["ear"]["unpriced_calls"] == 1
    assert cost["fast_cp"]["gpu_time_calls"] == 1 and cost["fast_cp"]["usd"] == 0.0


def test_fast_turns_are_counted_per_lane() -> None:
    s = Stream()
    s.fast("cp", s.events[0].event_id, [speech("Hi.")])
    assert metrics(s.end())["fast_turns"] == {"user": 0, "cp": 1}


def test_labels_cover_every_endpoint() -> None:
    from proxyloop.eval.metrics import endpoint_label

    assert endpoint_label(QWEN) == "self-hosted (vllm)"
    assert endpoint_label(SONNET) == "relay-measured (relay)"
    assert endpoint_label(GEMINI) == "relay-measured (teamrouter)"
    fsm = ModelRef(kind=AdapterKind.BASELINE, endpoint=None, model_id="fsm")
    assert endpoint_label(fsm) == "in-process (baseline)"
