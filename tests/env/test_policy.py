"""The rep's deterministic policy (ARCHITECTURE §10.1) on the S0 family."""

from __future__ import annotations

from typing import Any

import pytest

from proxyloop.env.counterparty.ear import EarAct
from proxyloop.env.counterparty.policy import Decision, Policy
from proxyloop.env.ledger import LedgerMode
from proxyloop.env.tasks.loader import load_task

TASK = load_task("cp-direct-discount")
CP = TASK.counterparty
NAME, LAST4 = "account.holder_name", "account.last4"


def _policy(**cp: Any) -> Policy:
    spec = CP.model_copy(update=cp)
    return Policy(spec, {k: TASK.profile.facts[k] for k in spec.identity})


def _say(p: Policy, act: str, t_ms: int = 0, heard: str = "", **args: Any) -> Decision:
    """``facts={key: value}`` for ``provide_fact``."""
    if "facts" in args:
        args["facts"] = tuple({"key": k, "value": v} for k, v in args["facts"].items())
    ear = EarAct.model_validate({"act": act, **args})
    return p.step(ear, f"u{t_ms}", heard, t_ms)[-1]


def _verified(t_ms: int = 0) -> Policy:
    p = _policy()
    _say(p, "other", t_ms)
    _say(p, "provide_fact", t_ms, facts={NAME: "dana REYES"})
    _say(p, "provide_fact", t_ms, facts={LAST4: "4 8 2 1"})
    assert p.state == "DISCOVER"
    return p


def test_identity_fails_on_a_wrong_value_and_passes_on_the_right_one() -> None:
    p = _policy()
    greet = _say(p, "smalltalk")
    assert (greet.from_, greet.to, greet.intent.kind) == ("GREET", "IDENTIFY", "greet")
    assert greet.intent.ask == (NAME, LAST4)
    wrong = _say(p, "provide_fact", facts={LAST4: "1111"})
    assert wrong.intent.kind == "ask_identity" and wrong.intent.ask == (NAME, LAST4)
    lever = _say(p, "ask_discount")  # no offer before identity
    assert lever.intent.kind == "ask_identity" and not p.offers
    _say(p, "provide_fact", facts={NAME: "Dana Reyes"})
    done = _say(p, "provide_fact", facts={LAST4: "4821"})
    assert (done.to, done.intent.kind) == ("DISCOVER", "how_can_help")
    assert p.strikes == 1  # the lever; a wrong value is no strike


def test_one_utterance_can_give_every_identity_fact() -> None:
    p = _policy()
    _say(p, "other")
    done = _say(p, "provide_fact", facts={NAME: "Dana Reyes", LAST4: "4821"})
    assert (done.to, done.intent.kind, p.strikes) == ("DISCOVER", "how_can_help", 0)


def test_identity_patience_abandons_after_the_last_strike() -> None:
    p = _policy()
    _say(p, "smalltalk")  # the greeting: no strike
    first, second = _say(p, "refuse_fact"), _say(p, "refuse_fact")
    assert [(d.to, d.intent.kind, d.strike) for d in (first, second)] == [
        ("IDENTIFY", "ask_identity", True)
    ] * 2
    last = _say(p, "refuse_fact")
    assert (last.from_, last.to, last.intent.kind, last.strike) == (
        "IDENTIFY",
        "ENDED",
        "hang_up",
        True,
    )
    assert p.done and p.strikes == CP.patience.strikes == 3


def test_smalltalk_then_the_right_facts_reaches_discover_with_one_strike() -> None:
    p = _policy()
    _say(p, "other")
    assert _say(p, "smalltalk").strike
    done = _say(p, "provide_fact", facts={NAME: "Dana Reyes", LAST4: "4821"})
    assert (done.to, done.strike, p.strikes) == ("DISCOVER", False, 1)


def test_each_distinct_lever_climbs_one_rung_up_to_the_final_offer() -> None:
    p = _verified()
    first = _say(p, "ask_discount")
    assert (first.to, first.intent.kind, first.rung) == ("OFFER", "offer", 0)
    assert dict(first.intent.say) == {"monthly_price": "75.00", "term_months": "12"}
    again = _say(p, "ask_discount")  # the same lever twice gives nothing
    assert (again.intent.kind, again.rung) == ("no_better", 0)
    final = _say(p, "cite_competitor", price_usd=60)
    assert (final.to, final.intent.kind, final.intent.offer_ref) == (
        "FINAL",
        "final_offer",
        "loyal-2",
    )
    assert _say(p, "tenure").intent.kind == "no_better"  # past the top rung


def test_a_hidden_term_is_said_only_on_a_read_back() -> None:
    p = _verified()
    offer = _say(p, "ask_discount")
    assert "fee:activation" not in dict(offer.intent.say)
    assert "fee:activation" not in p.made()["loyal-1"]
    back = _say(p, "ask_readback")
    assert back.intent.kind == "readback"
    assert dict(back.intent.say)["fee:activation"] == "20.00"


def test_an_offer_expires_after_its_ttl() -> None:
    p = _verified()
    _say(p, "ask_discount", 1_000)
    ttl_ms = int(CP.ladder[0].ttl_s * 1000)
    assert (
        p.step(EarAct(act="smalltalk"), "u8", "", ttl_ms)[-1].intent.kind == "clarify"
    )
    assert p.offers["loyal-1"].status == "open"
    expired = p.step(
        EarAct(act="accept", offer_ref="loyal-1"), "u9", "", 1_000 + ttl_ms
    )
    assert [d.intent.kind for d in expired] == ["offer_expired", "offer_unavailable"]
    assert expired[0].from_ == expired[0].to  # silent: no state change
    assert p.state != "CONFIRMED" and p.ledger.lookup("x") is None


def test_silence_counts_only_while_the_floor_is_free_then_hangs_up() -> None:
    p = _verified(0)
    silence = int(CP.patience.silence_s * 1000)
    assert p.tick(10 * silence) == []  # the rep's own answer holds the floor
    p.floor(True, 1_000)
    assert p.tick(1_000 + silence - 1) == []
    first = p.tick(1_000 + silence)
    assert [(d.intent.kind, d.strike) for d in first] == [("check_in", True)]
    assert p.tick(10 * silence) == []  # the check-in line holds the floor
    p.floor(True, 20_000)
    second = p.tick(20_000 + silence)
    assert second[-1].intent.kind == "check_in" and p.strikes == 2
    p.floor(False, 30_000)  # the agent speaks: no silence
    assert p.tick(30_000 + 10 * silence) == []
    p.floor(True, 100_000)
    last = p.tick(100_000 + silence)
    assert (last[-1].to, last[-1].intent.kind, p.done) == ("ENDED", "hang_up", True)
    assert p.tick(10**9) == [] and p.step(EarAct(act="accept"), "u", "", 10**9) == []


def test_a_hold_is_patient_until_hold_s() -> None:
    p = _verified(0)
    assert _say(p, "hold_request", 0).intent.kind == "ok_hold"
    p.floor(True, 0)
    silence, hold = CP.patience.silence_s * 1000, int(CP.patience.hold_s * 1000)
    assert p.tick(int(silence) + 1) == []  # a hold is not silence
    assert p.tick(hold)[-1].intent.kind == "check_in"


def _identifying() -> Policy:
    p = _policy()
    _say(p, "smalltalk")  # the greeting: GREET -> IDENTIFY, no strike
    assert p.state == "IDENTIFY"
    return p


def test_repeated_holds_in_identify_do_not_restart_the_hold_clock() -> None:
    """S1-SYS-20 (world semantics): an agent that keeps asking to hold while
    identifying gets the timer strikes of one hold, then the hang-up."""
    p, hold = _identifying(), int(CP.patience.hold_s * 1000)
    step, t, struck = hold - 1_000, 0, list[int]()
    while not p.done and t < 20 * hold:
        assert _say(p, "hold_request", t).intent.kind == "ok_hold"
        for tick in range(t + 1_000, t + step + 1, 1_000):
            if [d for d in p.tick(tick) if d.strike]:
                struck.append(tick)
        t += step
    assert struck[:2] == [hold, 2 * hold]  # as for a single hold
    assert (p.done, p.timer_strikes, p.identity_strikes) == (
        True,
        CP.patience.strikes,
        0,
    )


def test_a_provide_fact_restarts_the_hold_clock_in_identify() -> None:
    p, hold = _identifying(), int(CP.patience.hold_s * 1000)
    _say(p, "hold_request", 0)
    _say(p, "provide_fact", hold - 1_000, facts={NAME: "Dana Reyes"})
    assert p.state == "IDENTIFY" and p.tick(hold) == []
    _say(p, "hold_request", hold)
    assert p.tick(2 * hold - 1) == []
    assert p.tick(2 * hold)[-1].intent.kind == "check_in"
    assert p.timer_strikes == 1


def test_a_wrong_fact_between_holds_does_not_restart_the_hold_clock() -> None:
    """#157 review nit 3: only a newly verified key restarts IDENTIFY's hold
    clock; a junk provide_fact (asked again, not struck) between holds does not."""
    p, hold = _identifying(), int(CP.patience.hold_s * 1000)
    step, t, struck = hold - 1_000, 0, list[int]()
    while not p.done and t < 20 * hold:
        assert _say(p, "hold_request", t).intent.kind == "ok_hold"
        for tick in range(t + 1_000, t + step, 1_000):
            if [d for d in p.tick(tick) if d.strike]:
                struck.append(tick)
        if not p.done:  # then a junk fact, just before the next hold
            wrong = _say(p, "provide_fact", t + step - 500, facts={LAST4: "1111"})
            assert wrong.intent.kind == "ask_identity" and not wrong.strike
        t += step
    assert struck[:2] == [hold, 2 * hold]
    assert (p.done, p.timer_strikes, p.identity_strikes) == (
        True,
        CP.patience.strikes,
        0,
    )


def test_the_identify_hold_clock_runs_across_other_acts_counters_apart() -> None:
    """#157 review nit 2, kept by design: IDENTIFY's hold clock runs from the
    first hold since the last verified fact, even across a heard act that
    ended the hold; that act strikes identity patience, the hold strikes the
    timer, and neither counter adds to the other."""
    p, hold = _identifying(), int(CP.patience.hold_s * 1000)
    _say(p, "hold_request", 0)
    assert _say(p, "smalltalk", hold - 2_000).strike  # identity strike 1
    _say(p, "hold_request", hold - 1_000)  # resumes the clock started at 0
    (checked,) = p.tick(hold)
    assert (checked.intent.kind, checked.strike) == ("check_in", True)
    assert (p.identity_strikes, p.timer_strikes) == (1, 1)


def test_a_single_hold_then_the_facts_behave_as_before() -> None:
    p, hold = _identifying(), int(CP.patience.hold_s * 1000)
    assert _say(p, "hold_request", 0).intent.kind == "ok_hold"
    assert p.tick(hold - 1) == []
    done = _say(p, "provide_fact", hold - 1, facts={NAME: "Dana Reyes", LAST4: "4821"})
    assert (done.to, done.intent.kind, p.strikes) == ("DISCOVER", "how_can_help", 0)
    _say(p, "hold_request", hold)  # S1-SYS-28: a repeat resumes this clock
    _say(p, "hold_request", 2 * hold - 1_000)
    assert p.tick(2 * hold - 1) == []
    assert p.tick(2 * hold)[-1].intent.kind == "check_in"


def test_repeated_holds_outside_identify_do_not_restart_the_hold_clock() -> None:
    """S1-SYS-28 (world semantics, run f3a106): FastC re-asking to hold every
    few seconds kept the call alive for 400 s. In every state a repeated hold
    request resumes the clock of the first hold since the last progress."""
    p, hold = _verified(0), int(CP.patience.hold_s * 1000)
    step, t, struck = hold - 1_000, 0, list[int]()
    while not p.done and t < 20 * hold:
        assert p.state == "DISCOVER"
        assert _say(p, "hold_request", t).intent.kind == "ok_hold"
        for tick in range(t + 1_000, t + step + 1, 1_000):
            if [d for d in p.tick(tick) if d.strike]:
                struck.append(tick)
        t += step
    assert struck[:2] == [hold, 2 * hold]  # as for a single hold
    assert (p.done, p.timer_strikes) == (True, CP.patience.strikes)


def test_any_other_utterance_outside_identify_restarts_the_hold_clock() -> None:
    """Progress outside IDENTIFY is any heard act but a hold request."""
    p, hold = _verified(0), int(CP.patience.hold_s * 1000)
    _say(p, "hold_request", 0)
    _say(p, "smalltalk", hold - 2_000)
    _say(p, "hold_request", hold - 1_000)
    assert p.tick(2 * hold - 1_001) == []
    assert p.tick(2 * hold - 1_000)[-1].intent.kind == "check_in"


def test_accept_by_name_commits_and_binds_every_term_hidden_included() -> None:
    p = _verified()
    _say(p, "ask_discount")
    d = _say(p, "accept", heard="We accept the $75 offer.", offer_ref="loyal-1")
    assert (d.to, d.intent.kind) == ("CONFIRMED", "confirmed")
    assert d.commit is not None and d.commit.bound is not None
    bound = d.commit.bound
    assert (bound.offer_ref, bound.term_months) == ("loyal-1", 12)
    assert dict(bound.terms) == {"monthly_price": "75.00", "fee:activation": "20.00"}
    assert p.ledger.lookup(d.commit.confirmation_id) == bound
    assert dict(d.intent.say) == {"confirmation": d.commit.confirmation_id}


@pytest.mark.parametrize(
    ("heard", "args"),
    [
        ("Okay, we'll take it.", {}),
        ("We'll take the $70 one.", {"offer_ref": "loyal-1", "price_usd": 70}),
        ("Yes, sounds good, go ahead.", {"offer_ref": "loyal-1"}),  # ref not said
    ],
)
def test_an_ambiguous_accept_reads_back_before_committing(
    heard: str, args: dict[str, Any]
) -> None:
    p = _verified()
    _say(p, "ask_discount")
    ask = _say(p, "accept", heard=heard, **args)
    assert (ask.to, ask.intent.kind, ask.commit) == ("CONFIRM", "confirm_accept", None)
    assert dict(ask.intent.say)["fee:activation"] == "20.00"
    done = _say(p, "accept")  # "yes": the pending offer
    assert done.to == "CONFIRMED" and done.commit is not None
    assert done.commit.offer_ref == "loyal-1"


def test_a_decline_during_confirmation_returns_to_the_offer() -> None:
    p = _verified()
    _say(p, "ask_discount")
    _say(p, "accept")
    d = _say(p, "decline")
    assert (d.from_, d.to, d.intent.kind) == ("CONFIRM", "OFFER", "ack_decline")


def test_the_ledger_modes_bind_misquoted_or_nothing() -> None:
    for mode, months in ((LedgerMode.MISQUOTE, 24), (LedgerMode.ABSENT, None)):
        p = _policy(ledger=mode)
        steps: tuple[tuple[str, dict[str, Any]], ...] = (
            ("other", {}),
            ("provide_fact", {"facts": {NAME: "Dana Reyes"}}),
            ("provide_fact", {"facts": {LAST4: "4821"}}),
            ("ask_discount", {}),
        )
        for act, args in steps:
            _say(p, act, 0, **args)
        d = _say(p, "accept", heard="We accept loyal-1.", offer_ref="loyal-1")
        assert d.commit is not None
        bound = d.commit.bound
        assert (bound.term_months if bound else None) == months


def test_ask_supervisor_transfers_and_ends_the_rep_side() -> None:
    p = _verified()
    d = _say(p, "ask_supervisor")
    assert (d.to, d.intent.kind, p.done) == ("TRANSFER", "transfer", True)
    assert p.step(EarAct(act="ask_discount"), "u", "", 1) == []


def _silence(p: Policy, t_ms: int) -> Decision:
    """The floor goes free at ``t_ms`` and stays free past ``silence_s``."""
    p.floor(True, t_ms)
    (d,) = p.tick(t_ms + int(CP.patience.silence_s * 1000))
    assert d.strike
    return d


@pytest.mark.parametrize(
    "strikes",
    [
        ("silence", "refuse_fact", "refuse_fact"),  # gate smoke runs 1 and 2
        ("silence", "silence", "refuse_fact"),  # gate smoke run 3
        ("silence", "silence", "refuse_fact", "refuse_fact"),  # mixed 2 + 2
    ],
)
def test_timer_and_identity_strikes_never_add_up(strikes: tuple[str, ...]) -> None:
    p = _policy()
    _say(p, "other")  # the greeting: IDENTIFY
    for i, kind in enumerate(strikes):
        t_ms = (i + 1) * 100_000
        d = _silence(p, t_ms) if kind == "silence" else _say(p, kind, t_ms)
        assert d.strike and d.intent.kind != "hang_up" and not p.done
    done = _say(p, "provide_fact", 10**6, facts={NAME: "Dana Reyes", LAST4: "4821"})
    assert (done.to, done.intent.kind, p.done) == ("DISCOVER", "how_can_help", False)
    assert p.strikes == len(strikes)  # the total, as many as chan.strike events


def test_three_refusals_still_hang_up_after_a_silence() -> None:
    p = _policy()
    _say(p, "other")
    _silence(p, 0)
    kinds = [_say(p, "refuse_fact", t).intent.kind for t in (1, 2, 3)]
    assert kinds == ["ask_identity", "ask_identity", "hang_up"]
    assert (p.state, p.identity_strikes, p.timer_strikes) == ("ENDED", 3, 1)


def test_three_silences_hang_up_after_identity_strikes() -> None:
    p = _policy()
    _say(p, "other")
    _say(p, "refuse_fact", 1)
    _say(p, "refuse_fact", 2)
    kinds = [_silence(p, t).intent.kind for t in (100_000, 200_000, 300_000)]
    assert kinds == ["check_in", "check_in", "hang_up"]
    assert (p.state, p.identity_strikes, p.timer_strikes) == ("ENDED", 2, 3)
