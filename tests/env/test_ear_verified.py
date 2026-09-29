"""The Ear hears a lever after verification (S1-SYS-95). The request says
whether the caller is verified, and only that line and the precedence sentence
differ; SimRep derives the flag from the policy state at the start of each
block; and the policy answers scripted Ear acts (the lever the Ear heard) as
the ladder says."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.env.bus_sink import BusSink
from tests.env.test_backlog import (
    DISCOUNT,
    ID,
    NAME,
    NAME_ONLY,
    Line,
    Play,
    _intents,  # pyright: ignore[reportPrivateUsage]
)
from tests.support.fakes import ScriptedLLM, fake_ref

from proxyloop.env.counterparty import ear
from proxyloop.env.counterparty.ear import Ear, Heard
from proxyloop.env.tasks.loader import load_task

CP = load_task("cp-direct-discount").counterparty
NAMED_ASK: Line = (  # a discount ask that names the account holder
    "I'm calling to see whether there's a way to lower Dana Reyes's monthly price.",
    {"act": "ask_discount"},
)
TENURE: Line = (
    "I've been with you eight years, so can you lower my price?",
    {"act": "tenure"},
)
NAMED_FACT: Line = (  # before verification a name-bearing line is identity
    "I'm calling to lower Dana Reyes's price.",
    {"act": "provide_fact", "facts": [{"key": NAME, "value": "Dana Reyes"}]},
)


def _request(tmp_path: Path, verified: bool) -> tuple[str, str]:
    sink = BusSink(tmp_path)
    client = ScriptedLLM(fake_ref(), [])
    block = [Heard("u1", "Can you lower the price?", "e1", 0)]
    request = Ear(client, sink.world, CP.company, CP.identity).request(
        block, {}, (), 0, verified=verified
    )
    return request.messages[0].content, request.messages[1].content


def test_a_the_request_differs_only_by_the_verified_line_and_the_order(
    tmp_path: Path,
) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (sys_no, user_no), (sys_yes, user_yes) = (
        _request(tmp_path / "a", False),
        _request(tmp_path / "b", True),
    )
    assert ear.ORDER_UNVERIFIED in sys_no and ear.ORDER_VERIFIED in sys_yes
    assert sys_no.replace(ear.ORDER_UNVERIFIED, "@") == sys_yes.replace(
        ear.ORDER_VERIFIED, "@"
    )
    assert ear.CALLER_NOT_VERIFIED in user_no and ear.CALLER_VERIFIED in user_yes
    assert user_no.replace(ear.CALLER_NOT_VERIFIED, "@") == user_yes.replace(
        ear.CALLER_VERIFIED, "@"
    )


def test_a_after_verification_the_levers_rank_before_provide_fact() -> None:
    order = ear.ORDER_VERIFIED
    ranked = [
        "ask_readback",
        "cite_competitor",
        "cancel_intent",
        "tenure",
        "ask_discount",
        "provide_fact",
    ]
    assert [order.index(a) for a in ranked] == sorted(order.index(a) for a in ranked)
    assert "tenure (only if the utterance says how long" in order
    assert order.startswith("accept (only of an offer you made), decline, ask_readback")
    unverified = ear.ORDER_UNVERIFIED  # unchanged: the codebook v1 order
    assert unverified.index("provide_fact") < unverified.index("ask_discount")


def _flags(play: Play) -> list[bool]:
    return [
        ear.CALLER_VERIFIED in r.messages[-1].content
        and ear.CALLER_NOT_VERIFIED not in r.messages[-1].content
        for r in play.ear.requests
    ]


def _play(tmp_path: Path, lines: list[Line]) -> Play:
    play = Play(tmp_path, lines, len(lines))
    play.run()
    return play


def test_b_simrep_says_verified_only_once_the_policy_left_identify(
    tmp_path: Path,
) -> None:
    play = _play(tmp_path, [NAME_ONLY, ID, NAMED_ASK])
    # the name alone leaves last4 missing: still identifying at turn 2 and 3
    assert _flags(play) == [False, False, True]
    assert play.rep.policy.state == "OFFER"


def test_b_before_verification_a_name_bearing_line_is_still_identity(
    tmp_path: Path,
) -> None:
    play = _play(tmp_path, [NAMED_FACT])
    assert _flags(play) == [False]
    assert _intents(play, "rep.policy") == ["ask_identity"]  # not the offer path


def test_b_after_verification_the_named_discount_ask_is_the_offer_path(
    tmp_path: Path,
) -> None:
    play = _play(tmp_path, [ID, NAMED_ASK])
    assert _flags(play) == [False, True]
    assert _intents(play, "rep.policy") == ["how_can_help", "offer"]


def test_b_tenure_line_after_a_discount_ask_unlocks_the_next_rung(
    tmp_path: Path,
) -> None:
    play = _play(tmp_path, [ID, DISCOUNT, TENURE])
    kinds = _intents(play, "rep.policy")
    assert kinds == ["how_can_help", "offer", "final_offer"]
    assert [e.payload["rung"] for e in play.of("rep.policy")][-1] == 1


def test_b_tenure_first_is_the_first_offer_like_any_lever(tmp_path: Path) -> None:
    play = _play(tmp_path, [ID, TENURE])
    payloads: list[dict[str, Any]] = [e.payload for e in play.of("rep.policy")]
    assert payloads[-1]["intent"]["kind"] == "offer" and payloads[-1]["rung"] == 0
