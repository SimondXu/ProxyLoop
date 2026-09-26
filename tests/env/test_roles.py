"""Ear, Mouth, SimRep and SimUser on scripted fakes, writing through the real Bus."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from tests.env.bus_sink import BusSink
from tests.support.fakes import ScriptedLLM, fake_ref

from proxyloop.contract.events import Event, check_causes
from proxyloop.contract.llm import LLMCallRecord, LLMUnavailable
from proxyloop.env import world
from proxyloop.env.counterparty.ear import Ear
from proxyloop.env.counterparty.mouth import Mouth, template
from proxyloop.env.counterparty.policy import PublicIntent
from proxyloop.env.counterparty.simrep import RepTurn, SimRep
from proxyloop.env.tasks.loader import load_task
from proxyloop.env.user.simuser import SimUser

TASK = load_task("cp-direct-discount")
CP = TASK.counterparty
OFFERS = {"loyal-1": dict(CP.ladder[0].terms)}


def _tool(name: str, **args: Any) -> str:
    call = {"call_id": "t", "name": name, "arguments": json.dumps(args)}
    return json.dumps({"text": "", "tool_calls": [call]})


def _ear(sink: BusSink, *responses: str) -> Ear:
    return Ear(ScriptedLLM(fake_ref(), responses), sink, CP.company, CP.identity)


def _world_ok(sink: BusSink) -> list[Event]:
    """Every world event is on the world stream from a world actor, and the log's
    causes hold; every llm.call's prompt and response are stored by sha."""

    events = sink.bus.events
    check_causes(events)
    world_events = [e for e in events if e.stream == "world"]
    assert all(e.actor.startswith("world.") for e in world_events)
    for e in sink.of("llm.call"):
        record = LLMCallRecord.model_validate(e.payload)
        assert sink.prompts[record.prompt_sha][0] == "messages"
        if record.response_sha is not None:
            assert sink.prompts[record.response_sha][0] == "response"
    return world_events


def test_the_ear_classifies_and_cites_the_heard_line_and_its_call(
    tmp_path: Path,
) -> None:
    sink = BusSink(tmp_path)
    heard = sink.heard("Is that really the best you can do?")
    ear = _ear(sink, _tool("classify", act="ask_discount"))
    text = str(heard.payload["text_heard"])
    act, ev = asyncio.run(ear.classify("u1", text, heard.event_id, {}))
    assert act.act == "ask_discount"
    (call,) = sink.of("llm.call")
    (rep_ear,) = sink.of("rep.ear")
    assert rep_ear.event_id == ev and call.actor == "world.ear"
    assert call.cause_ids == (heard.event_id,)
    assert rep_ear.cause_ids == (heard.event_id, call.event_id)
    assert rep_ear.payload["attempts"] == 1
    assert rep_ear.payload["call_id"] == call.payload["call_id"]
    _world_ok(sink)


@pytest.mark.parametrize(
    ("bad", "why"),
    [
        (_tool("classify", act="haggle"), "schema"),
        (_tool("classify", act="cite_competitor", price_usd=55), "number not said"),
        (_tool("classify", act="accept", offer_ref="loyal-9"), "never offered"),
        (_tool("reply", text="x", revealed={}), "wrong tool"),
    ],
)
def test_an_invalid_ear_output_is_regenerated_and_counted(
    tmp_path: Path, bad: str, why: str
) -> None:
    sink = BusSink(tmp_path)
    text = "Brightwave offers 60 dollars a month."
    heard = sink.heard(text)
    good = _tool("classify", act="cite_competitor", price_usd=60)
    act, _ = asyncio.run(
        _ear(sink, bad, good).classify("u1", text, heard.event_id, OFFERS)
    )
    assert act.price_usd == 60, why
    calls, (rep_ear,) = sink.of("llm.call"), sink.of("rep.ear")
    assert len(calls) == 2 and rep_ear.payload["attempts"] == 2
    assert rep_ear.cause_ids == (heard.event_id, *(c.event_id for c in calls))
    assert rep_ear.payload["call_id"] == calls[1].payload["call_id"]
    _world_ok(sink)


def test_three_invalid_ear_outputs_end_the_episode(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    heard = sink.heard("hello")
    ear = _ear(sink, *[_tool("classify", act="haggle")] * 3)
    with pytest.raises(world.WorldError):
        asyncio.run(ear.classify("u1", "hello", heard.event_id, {}))
    assert len(sink.of("llm.call")) == 3 and sink.of("rep.ear") == []


def _mouth(sink: BusSink, *lines: str) -> Mouth:
    return Mouth(ScriptedLLM(fake_ref(), lines), sink, CP)


OFFER = PublicIntent(
    kind="offer",
    offer_ref="loyal-1",
    say=(("monthly_price", "75.00"), ("term_months", "12")),
)


def test_the_mouth_voices_the_values(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    cause = sink.heard("ok").event_id
    line = "I can do $75 a month on a 12-month plan."
    text, ev = asyncio.run(_mouth(sink, line).say(OFFER, "ok", cause))
    (rep_mouth,) = sink.of("rep.mouth")
    assert text == line and rep_mouth.event_id == ev
    assert (rep_mouth.payload["fidelity_ok"], rep_mouth.payload["attempts"]) == (
        True,
        1,
    )
    assert rep_mouth.cause_ids == (cause, sink.of("llm.call")[0].event_id)
    _world_ok(sink)


def test_the_mouth_falls_back_to_the_flagged_template(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    cause = sink.heard("ok").event_id
    wrong = ["$70 a month.", "seventy-five a month", "$75 for 12 or $65 for 24."]
    text, _ = asyncio.run(_mouth(sink, *wrong).say(OFFER, "ok", cause))
    (rep_mouth,) = sink.of("rep.mouth")
    assert text == template(OFFER, CP.company)
    assert (rep_mouth.payload["fidelity_ok"], rep_mouth.payload["attempts"]) == (
        False,
        3,
    )
    assert len(sink.of("llm.call")) == 3


def test_simrep_commits_heard_and_binds_the_ledger(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    ear = [
        _tool("classify", act="other"),
        _tool(
            "classify",
            act="provide_fact",
            key="account.holder_name",
            value="Dana Reyes",
        ),
        _tool("classify", act="provide_fact", key="account.last4", value="4821"),
        _tool("classify", act="ask_discount"),
        _tool("classify", act="accept", offer_ref="loyal-1"),
    ]
    mouth = [
        "Northwind Mobile here, can I get the account holder name and last 4 digits?",
        "And the last 4 digits?",
        "Thanks, how can I help?",
        "I can offer $75.00 a month for 12 months.",
        *["All done, thank you."] * 3,  # no confirmation number: the fallback
    ]
    rep = SimRep(
        TASK, ScriptedLLM(fake_ref(), ear), ScriptedLLM(fake_ref(), mouth), sink
    )
    said = [
        "Hi, I am an AI assistant calling for Dana.",
        "The account holder is Dana Reyes.",
        "The last four are 4821.",
        "Can you lower the price?",
        "We accept loyal-1.",
    ]
    turns: list[RepTurn] = []
    for i, text in enumerate(said):
        heard = sink.heard(text)
        utt_id = str(heard.payload["utt_id"])
        turn = rep.on_agent_utterance(utt_id, text, heard.event_id, i * 1000)
        turns.append(asyncio.run(turn))
    assert [len(t.lines) for t in turns] == [1, 1, 1, 1, 1]
    assert [t.ended for t in turns] == [False] * 4 + [True]
    (commit,) = sink.of("rep.commit_heard")
    (write,) = sink.of("ledger.write")
    rep_ear = sink.of("rep.ear")[-1]
    policy = sink.of("rep.policy")[-1]
    assert commit.cause_ids == (rep_ear.event_id, policy.event_id)
    assert commit.payload == {
        "utt_id": rep_ear.payload["utt_id"],
        "offer_ref": "loyal-1",
    }
    confirmation = str(write.payload["confirmation_id"])
    assert confirmation in turns[-1].lines[0][0]  # the template voices it
    assert write.cause_ids == (commit.event_id,) and write.actor == "world.ledger"
    binding = write.payload["binding"]
    assert binding == {
        "offer_ref": "loyal-1",
        "revision": 1,
        "term_months": 12,
        "terms": {"fee:activation": "20.00", "monthly_price": "75.00"},
    }
    assert (
        policy.cause_ids == (rep_ear.event_id,) and policy.payload["to"] == "CONFIRMED"
    )
    _world_ok(sink)


def test_a_dead_ear_aborts_with_its_failed_call_logged(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    heard = sink.heard("hello")
    dead = ScriptedLLM(fake_ref(), [], dead=True)
    rep = SimRep(TASK, dead, ScriptedLLM(fake_ref(), []), sink)
    with pytest.raises(LLMUnavailable):
        asyncio.run(rep.on_agent_utterance("u1", "hello", heard.event_id, 0))
    (call,) = sink.of("llm.call")
    assert call.payload["error"] and call.payload["response_sha"] is None
    assert sink.of("rep.ear") == [] and sink.of("rep.policy") == []


def test_a_silence_strike_is_an_uncaused_policy_event_and_a_check_in(
    tmp_path: Path,
) -> None:
    sink = BusSink(tmp_path)
    mouth = ScriptedLLM(fake_ref(), ["Hello, are you still there?"])
    rep = SimRep(TASK, ScriptedLLM(fake_ref(), []), mouth, sink)
    assert asyncio.run(rep.tick(1_000)) == RepTurn((), False, False)
    turn = asyncio.run(rep.tick(int(CP.patience.silence_s * 1000)))
    assert turn.strike and turn.lines[0][0] == "Hello, are you still there?"
    (policy,) = sink.of("rep.policy")
    assert policy.cause_ids == () and policy.payload["intent"] == {
        "kind": "check_in",
        "offer_ref": None,
        "say": [],
        "ask": [],
    }
    assert sink.of("rep.mouth")[0].cause_ids[0] == policy.event_id
    _world_ok(sink)


def _user(sink: BusSink, *responses: str) -> SimUser:
    return SimUser(TASK, ScriptedLLM(fake_ref(), responses), sink, seed=7)


def test_the_simuser_opens_and_reveals_verbatim(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    cause = sink.heard("How can I help?", lane="user").event_id
    reply = _tool(
        "reply",
        text="It's under Dana Reyes, card ending 4821.",
        revealed={"account.holder_name": "Dana Reyes", "account.last4": "4821"},
    )
    out = asyncio.run(_user(sink, reply).on_agent_message("How can I help?", cause))
    assert out.revealed == {
        "account.holder_name": "Dana Reyes",
        "account.last4": "4821",
    }
    lo, hi = TASK.user.reply_delay_s.range
    assert lo <= out.delay_s <= hi
    (sim,) = sink.of("user.sim")
    assert sim.event_id == out.event_id and sim.actor == "world.simuser"
    assert sim.payload["attempts"] == 1 and sim.payload["delay_s"] == out.delay_s
    assert sim.cause_ids == (cause, sink.of("llm.call")[0].event_id)
    _world_ok(sink)


@pytest.mark.parametrize(
    "bad",
    [
        {"text": "My last four are 4 8 2 1.", "revealed": {"account.last4": "4821"}},
        {"text": "My PIN is 1234.", "revealed": {"account.pin": "1234"}},
        {"text": "", "revealed": {}},
    ],
)
def test_a_simuser_reveal_not_in_the_text_is_regenerated(
    tmp_path: Path, bad: dict[str, Any]
) -> None:
    sink = BusSink(tmp_path)
    cause = sink.heard("Your last four?", lane="user").event_id
    good = _tool("reply", text="It's 4821.", revealed={"account.last4": "4821"})
    user = _user(sink, _tool("reply", **bad), good)
    out = asyncio.run(user.on_agent_message(None, cause))
    assert out.text == "It's 4821."
    (sim,) = sink.of("user.sim")
    assert sim.payload["attempts"] == 2 and len(sink.of("llm.call")) == 2


def test_the_reply_delay_is_seeded(tmp_path: Path) -> None:
    delays: list[float] = []
    for run in ("a", "b"):
        (tmp_path / run).mkdir()
        sink = BusSink(tmp_path / run)
        cause = sink.heard("hi", lane="user").event_id
        reply = _tool("reply", text="Hi.", revealed={})
        delays.append(
            asyncio.run(_user(sink, reply).on_agent_message("hi", cause)).delay_s
        )
    assert delays[0] == delays[1]
