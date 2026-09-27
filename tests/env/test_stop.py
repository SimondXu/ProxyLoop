"""SimUser's unscripted stop and mind change (EVAL §2, ARCHITECTURE §10.2)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests.env.bus_sink import BusSink
from tests.env.cards import card as _card
from tests.env.cards import offer as _offer

from proxyloop.env.tasks.loader import load_task
from proxyloop.env.tasks.schema import Task
from proxyloop.env.user.simuser import SimReply, SimUser, says_stop

TASK = load_task("x-user-mind-change")  # a stop after the card
HINT = TASK.stop.text_hint.strip() if TASK.stop else ""


def _reply(
    text: str | None = None,
    revealed: dict[str, str] | None = None,
    silent: bool = False,
) -> str:
    args: dict[str, Any] = {"revealed": revealed or {}}
    args |= {"silent": True} if silent else {"text": text}
    call = {"call_id": "t", "name": "reply", "arguments": json.dumps(args)}
    return json.dumps({"text": "", "tool_calls": [call]})


def _task(**stop: Any) -> Task:
    data = TASK.model_dump(mode="json")
    data["stop"] |= stop
    if stop.get("change"):
        data["gold"]["check"] = "ledger"
    return Task.model_validate(data)


def _say(sink: BusSink, user: SimUser, text: str) -> SimReply | None:
    cause = sink.heard(text, lane="user").event_id
    return asyncio.run(user.on_agent_message(text, cause))


def _prompt(sink: BusSink) -> str:
    return [c for kind, c in sink.prompts.values() if kind == "messages"][-1]


def _trigger(sink: BusSink, user: SimUser, trigger: Any) -> SimReply | None:
    cause = sink.heard("(a world event)", lane="cp").event_id
    return asyncio.run(user.on_trigger(trigger, cause))


def test_the_card_stops_the_user_unprompted_and_no_card_is_granted_after(
    tmp_path: Path,
) -> None:
    """(i): the agent never writes to the user after the card."""
    sink = BusSink(tmp_path)
    stop_line = "Stop, don't accept anything."
    user = SimUser(TASK, sink.llm(_reply(stop_line), _reply("OK.")), sink.world, 7)
    assert user.approver is not None
    card = user.approver.decide(_card(), _offer(7600, months=12))  # as issued
    assert card.post.decision == "granted"  # decided before the stop
    assert asyncio.run(user.on_trigger("after_offer", "x")) is None  # not its trigger
    stop = _trigger(sink, user, "after_card")
    assert stop is not None and stop.text == stop_line
    assert f"Now, in this reply: {HINT}" in _prompt(sink)
    (sim,) = sink.of("user.sim")
    assert sim.payload["stop"] == "stop" and 2 <= stop.delay_s <= 20
    assert _trigger(sink, user, "after_card") is None  # it fires once
    _say(sink, user, "Understood.")
    assert "stop" not in sink.of("user.sim")[1].payload


def test_a_card_issued_after_the_stop_trigger_is_denied(tmp_path: Path) -> None:
    """(ii)"""
    sink = BusSink(tmp_path)
    user = SimUser(TASK, sink.llm(_reply("Please stop.")), sink.world, 7)
    _trigger(sink, user, "after_card")
    assert user.approver is not None
    later = user.approver.decide(_card(), _offer(7300, months=12))
    assert later.post.decision == "denied" and later.reasons == ("stopped",)


def test_a_stop_without_a_stop_cue_is_regenerated(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    good = "Please stop, don't accept anything."
    user = SimUser(
        TASK, sink.llm(_reply("Sure, go ahead."), _reply(good)), sink.world, 7
    )
    out = _trigger(sink, user, "after_card")
    assert out is not None and out.text == good
    assert sink.of("user.sim")[0].payload["attempts"] == 2


def test_a_silent_stop_is_regenerated(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    responses = (_reply(silent=True), _reply("Stop."))
    user = SimUser(
        _task(trigger="after_turn_k", k=1), sink.llm(*responses), sink.world, 7
    )
    out = _say(sink, user, "Update: the rep is checking.")
    assert out is not None and out.text == "Stop."
    assert sink.of("user.sim")[0].payload["attempts"] == 2


def test_after_turn_k_fires_on_the_kth_agent_message(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    responses = [_reply("r0"), _reply("Wait, stop."), _reply("r2")]
    user = SimUser(
        _task(trigger="after_turn_k", k=2), sink.llm(*responses), sink.world, 7
    )
    for n in range(3):
        _say(sink, user, f"message {n}")
    assert ["stop" in s.payload for s in sink.of("user.sim")] == [False, True, False]


def test_after_offer_stops_unprompted_when_the_rep_offers(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    user = SimUser(
        _task(trigger="after_offer"), sink.llm(_reply("Stop.")), sink.world, 7
    )
    assert _trigger(sink, user, "after_card") is None
    out = _trigger(sink, user, "after_offer")
    assert out is not None and sink.of("user.sim")[0].payload["stop"] == "stop"


def test_a_mind_change_must_reveal_the_changed_fact(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    change = {"budget.max_monthly_usd": "74"}
    task = _task(trigger="after_turn_k", k=1, change=change)
    vague = _reply("Actually I'd pay a bit more.")
    old = _reply("I'll pay 70.", {"budget.max_monthly_usd": "70"})
    good = _reply("Actually, up to 74 a month is fine.", change)
    user = SimUser(task, sink.llm(vague, old, good), sink.world, seed=7)
    out = _say(sink, user, "They offered 76.")
    assert out is not None and out.revealed == change
    (sim,) = sink.of("user.sim")
    assert sim.payload["stop"] == "mind_change" and sim.payload["attempts"] == 3
    assert "budget.max_monthly_usd: 74" in _prompt(sink)  # its facts changed
    assert user.approver is not None
    assert user.approver.decide(_card(), _offer(7300, months=12)).reasons == ()
    assert user.approver.decide(_card(), _offer(7600, months=12)).reasons == (
        "monthly_price_over",
    )


Edit = Callable[[dict[str, Any]], object]
BROKEN: list[tuple[Edit, str]] = [
    (lambda d: d["stop"].update(trigger="after_turn_k"), "stop.k"),
    (lambda d: d["stop"].update(k=2), "stop.k"),
    (lambda d: d.update(stop=None), "no_commit_after_stop"),
    (lambda d: d["stop"].update(change={"pin": "1"}), "unknown profile facts"),
    (lambda d: d.update(principal=None), "full mode"),
    (lambda d: d["profile"]["facts"].update({"budget.max_fees_usd": "x"}), "limit"),
]


@pytest.mark.parametrize(("edit", "match"), BROKEN)
def test_the_schema_ties_stop_gold_and_principal(edit: Edit, match: str) -> None:
    data = TASK.model_dump(mode="json")
    edit(data)
    with pytest.raises(ValueError, match=match):
        Task.model_validate(data)


@pytest.mark.parametrize(
    ("text", "stop"),
    [
        ("Wait, what's the fee?", False),
        ("Sure, go ahead, don't worry about it.", False),
        ("Great, don't forget to ask about fees.", False),
        ("Please don't stop, keep going!", False),
        ("No need to stop yet.", False),
        ("Actually, let's not do this.", True),
        ("Forget it, I'll keep my plan.", True),
        ("Please stop, don't accept anything.", True),
        ("Don\N{RIGHT SINGLE QUOTATION MARK}t go ahead with it.", True),
    ],
)
def test_a_stop_cue_is_a_phrase_and_not_negated(text: str, stop: bool) -> None:
    assert says_stop(text) is stop
