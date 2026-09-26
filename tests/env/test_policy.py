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
    ear = EarAct.model_validate({"act": act, **args})
    return p.step(ear, f"u{t_ms}", heard, t_ms)[-1]


def _verified(t_ms: int = 0) -> Policy:
    p = _policy()
    _say(p, "other", t_ms)
    _say(p, "provide_fact", t_ms, key=NAME, value="dana REYES")
    _say(p, "provide_fact", t_ms, key=LAST4, value="4 8 2 1")
    assert p.state == "DISCOVER"
    return p


def test_identity_fails_on_a_wrong_value_and_passes_on_the_right_one() -> None:
    p = _policy()
    greet = _say(p, "smalltalk")
    assert (greet.from_, greet.to, greet.intent.kind) == ("GREET", "IDENTIFY", "greet")
    assert greet.intent.ask == (NAME, LAST4)
    wrong = _say(p, "provide_fact", key=LAST4, value="1111")
    assert wrong.intent.kind == "ask_identity" and wrong.intent.ask == (NAME, LAST4)
    lever = _say(p, "ask_discount")  # no offer before identity
    assert lever.intent.kind == "ask_identity" and not p.offers
    _say(p, "provide_fact", key=NAME, value="Dana Reyes")
    done = _say(p, "provide_fact", key=LAST4, value="4821")
    assert (done.to, done.intent.kind) == ("DISCOVER", "how_can_help")


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
        for act, args in (
            ("other", {}),
            ("provide_fact", {"key": NAME, "value": "Dana Reyes"}),
            ("provide_fact", {"key": LAST4, "value": "4821"}),
            ("ask_discount", {}),
        ):
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
