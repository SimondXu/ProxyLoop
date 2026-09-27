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
from proxyloop.env.user.simuser import SimReply, SimUser

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


def test_the_stop_fires_on_the_first_reply_after_the_card(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    responses = (_reply("Sure, go on."), _reply("Stop, don't accept anything."))
    user = SimUser(TASK, sink.llm(*responses, _reply("OK.")), sink.world, seed=7)
    before = _say(sink, user, "I asked about a better price.")
    assert before is not None and HINT not in _prompt(sink)
    assert user.approver is not None
    granted = user.approver.decide(_card(), _offer(7600, months=12))
    assert granted.post.decision == "granted"  # the principal approved the card
    stop = _say(sink, user, "Please approve 76 dollars a month for 12 months.")
    assert stop is not None and stop.text == "Stop, don't accept anything."
    assert f"Now, in this reply: {HINT}" in _prompt(sink)
    sims = sink.of("user.sim")
    assert "stop" not in sims[0].payload and sims[1].payload["stop"] == "stop"
    assert user.approver.decide(_card(), _offer(7300, months=12)).reasons == (
        "stopped",
    )
    _say(sink, user, "Understood, I stopped.")  # it fires once
    assert "stop" not in sink.of("user.sim")[2].payload


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
    responses = [_reply(f"r{n}") for n in range(3)]
    user = SimUser(
        _task(trigger="after_turn_k", k=2), sink.llm(*responses), sink.world, 7
    )
    for n in range(3):
        _say(sink, user, f"message {n}")
    assert ["stop" in s.payload for s in sink.of("user.sim")] == [False, True, False]


def test_after_offer_fires_when_the_agent_says_an_offer_price(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    responses = [_reply(f"r{n}") for n in range(2)]
    user = SimUser(_task(trigger="after_offer"), sink.llm(*responses), sink.world, 7)
    _say(sink, user, "Your bill is 95 dollars now.")  # not an offer price
    _say(sink, user, "They offer 76 dollars a month.")
    assert ["stop" in s.payload for s in sink.of("user.sim")] == [False, True]


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
