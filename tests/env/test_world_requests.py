"""Byte identity of the world's requests (S1-SYS-70): what the Ear, the Mouth
and the SimUser send, per attempt, for recorded shapes. ``world_requests.json``
holds each request as it was sent before the builders were extracted; a case
fails if the sent request drifts by one byte, or if the builder (``Ear.request``,
``Mouth.request``, ``SimUser.request``) called alone does not return it."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from tests.env.bus_sink import BusSink
from tests.support.fakes import ScriptedLLM, fake_ref

from proxyloop.contract.base import canonical_json
from proxyloop.contract.llm import (
    LLMCallRecord,
    TextRequest,
    ToolRequest,
    ToolResponse,
)
from proxyloop.env.counterparty.ear import Ear, Heard
from proxyloop.env.counterparty.mouth import Mouth
from proxyloop.env.counterparty.policy import PublicIntent
from proxyloop.env.tasks.loader import load_task
from proxyloop.env.tasks.schema import Task
from proxyloop.env.user.simuser import SimUser

SNAPSHOT = Path(__file__).with_name("world_requests.json")
CP = load_task("cp-direct-discount").counterparty
USER = load_task("x-user-mind-change")  # a principal; a plain stop after the card
OFFERS = {
    "loyal-1": {"monthly_price": "75.00", "term_months": "12"},
    "loyal-2": {"monthly_price": "70.00", "term_months": "24"},
}
Request = TextRequest | ToolRequest


class Capturing(ScriptedLLM):
    """A scripted client that keeps every request it is sent."""

    def __init__(self, sink: BusSink, *responses: str) -> None:
        super().__init__(fake_ref(), responses, on_record=sink.world.record)
        self.sent: list[Request] = []

    async def chat_tools(self, request: ToolRequest) -> ToolResponse:
        self.sent.append(request)
        return await super().chat_tools(request)

    def stream_text(self, request: TextRequest) -> AsyncIterator[str | LLMCallRecord]:
        self.sent.append(request)
        return super().stream_text(request)


def _tool(name: str, **args: Any) -> str:
    call = {"call_id": "t", "name": name, "arguments": json.dumps(args)}
    return json.dumps({"text": "", "tool_calls": [call]})


def _dump(request: Request) -> str:
    return canonical_json(request.model_dump(mode="json"))


# -- the Ear ------------------------------------------------------------------


def _ear_one(sink: BusSink, client: Capturing, verified: bool = False) -> None:
    heard = sink.heard("Is that really the best you can do?")
    block = [Heard("u1", str(heard.payload["text_heard"]), heard.event_id, 0)]
    ear = Ear(client, sink.world, CP.company, CP.identity)
    asyncio.run(ear.classify(block, {}, (), verified=verified))


def _ear_one_verified(sink: BusSink, client: Capturing) -> None:
    _ear_one(sink, client, verified=True)  # S1-SYS-95: after identity


EAR_THREE = (
    "Hi, I am calling for my client.",
    "Their name is Dana Reyes.\nThe last four are 4821.",
    "Can you do better than that?",
)


def _ear_three(sink: BusSink, client: Capturing) -> None:
    block: list[Heard] = []
    for n, text in enumerate(EAR_THREE, 1):
        ev = sink.heard(text)
        block.append(Heard(f"u{n}", text, ev.event_id, n))
    ear = Ear(client, sink.world, CP.company, CP.identity)
    asyncio.run(ear.classify(block, OFFERS, {"loyal-2"}))


EAR_THREE_ACTS = [{"act": "smalltalk"}, {"act": "other"}, {"act": "ask_discount"}]

# -- the Mouth ----------------------------------------------------------------

INTENTS = {
    "greet": PublicIntent(kind="greet", ask=("account.last4",)),
    "offer": PublicIntent(
        kind="offer", offer_ref="loyal-1", say=tuple(OFFERS["loyal-1"].items())
    ),
    "readback": PublicIntent(
        kind="readback",
        offer_ref="loyal-1",
        say=(
            *OFFERS["loyal-1"].items(),
            ("fees_none", "true"),
            ("expires", "none"),
        ),
    ),
    "confirmed": PublicIntent(kind="confirmed", say=(("confirmation", "048213"),)),
    "hang_up": PublicIntent(kind="hang_up"),
}
MOUTH_HEARD = {
    "greet": "",
    "offer": "Can you do better?",
    "readback": "Can you repeat the terms?",
    "confirmed": "Yes, we accept.",
    "hang_up": "",
}
MOUTH_LINES = {
    "greet": ["Thanks for calling. What are the last four digits?"],
    "offer": [
        "I can do 70 a month.",  # a number it was not given: regenerated
        "I can offer 75.00 a month for 12 months.",
    ],
    "readback": ["That is 75.00 a month for 12 months, no fees and no expiry."],
    "confirmed": ["Done, your confirmation number is 048213."],
    "hang_up": ["I cannot hear you, goodbye."],
}


def _mouth(kind: str) -> Callable[[BusSink, Capturing], None]:
    def run(sink: BusSink, client: Capturing) -> None:
        cause = sink.heard(MOUTH_HEARD[kind] or "(silence)").event_id
        mouth = Mouth(client, sink.world, CP)
        asyncio.run(mouth.say(INTENTS[kind], MOUTH_HEARD[kind], cause))

    return run


# -- the SimUser --------------------------------------------------------------

CHANGE = {"budget.max_monthly_usd": "74"}


def _mind_change_task() -> Task:
    data = USER.model_dump(mode="json")
    data["stop"] |= {"trigger": "after_turn_k", "k": 2, "change": CHANGE}
    data["gold"]["check"] = "ledger"
    return Task.model_validate(data)


def _simuser_chat(sink: BusSink, client: Capturing) -> None:
    """The opening, then a reply regenerated once (an unknown key)."""
    user = SimUser(USER, client, sink.world, seed=7)
    asyncio.run(user.on_agent_message(None, sink.heard("(open)", "user").event_id))
    cause = sink.heard("What is the account name?", "user").event_id
    asyncio.run(user.on_agent_message("What is the account name?", cause))


def _simuser_stop(sink: BusSink, client: Capturing) -> None:
    user = SimUser(USER, client, sink.world, seed=7)
    asyncio.run(user.on_agent_message(None, sink.heard("(open)", "user").event_id))
    asyncio.run(user.on_trigger("after_card", sink.heard("(card)").event_id))


def _simuser_mind_change(sink: BusSink, client: Capturing) -> None:
    """Turn 1 plain, turn 2 the mind change, turn 3 after it (changed facts)."""
    user = SimUser(_mind_change_task(), client, sink.world, seed=7)
    for text in SIM_AGENT:
        cause = sink.heard(text, "user").event_id
        asyncio.run(user.on_agent_message(text, cause))


SIM_AGENT = ("I am on it.", "They offered 76.", "Noted, I will ask for 74.")
SIM_REPLIES = {
    "simuser_chat": [
        _tool("reply", text="Please lower my TV bill.", revealed={}),
        _tool("reply", text="It is 1234.", revealed={"account.pin": "1234"}),
        _tool(
            "reply",
            text="It is under Elena Ruiz.",
            revealed={"account.holder_name": "Elena Ruiz"},
        ),
    ],
    "simuser_stop": [
        _tool("reply", text="Please lower my TV bill.", revealed={}),
        _tool("reply", text="Stop, keep my current plan.", revealed={}),
    ],
    "simuser_mind_change": [
        _tool("reply", silent=True, revealed={}),
        _tool("reply", text="Actually, up to 74 a month is fine.", revealed=CHANGE),
        _tool("reply", text="Thanks.", revealed={}),
    ],
}

CASES: dict[str, tuple[Callable[[BusSink, Capturing], None], list[str]]] = {
    "ear_one": (_ear_one, [_tool("classify", acts=[{"act": "ask_discount"}])]),
    "ear_one_verified": (
        _ear_one_verified,
        [_tool("classify", acts=[{"act": "ask_discount"}])],
    ),
    "ear_three_regenerated": (
        _ear_three,
        [
            _tool("classify", acts=EAR_THREE_ACTS[:2]),  # two acts for three
            _tool("classify", acts=EAR_THREE_ACTS),
        ],
    ),
    **{f"mouth_{k}": (_mouth(k), MOUTH_LINES[k]) for k in INTENTS},
    "simuser_chat": (_simuser_chat, SIM_REPLIES["simuser_chat"]),
    "simuser_stop": (_simuser_stop, SIM_REPLIES["simuser_stop"]),
    "simuser_mind_change": (_simuser_mind_change, SIM_REPLIES["simuser_mind_change"]),
}


def sent(case: str, tmp_path: Path) -> list[str]:
    """Every request ``case`` sends, in order, as canonical JSON."""

    run, responses = CASES[case]
    sink = BusSink(tmp_path)
    client = Capturing(sink, *responses)
    run(sink, client)
    assert client.calls == len(responses)  # every scripted response was used
    return [_dump(r) for r in client.sent]


def _snapshot() -> dict[str, list[str]]:
    """The recorded requests, each in canonical JSON (the file is indented)."""

    data: dict[str, list[object]] = json.loads(SNAPSHOT.read_text())
    return {case: [canonical_json(r) for r in reqs] for case, reqs in data.items()}


def test_the_snapshot_covers_every_case() -> None:
    assert sorted(_snapshot()) == sorted(CASES)


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_world_sends_the_recorded_request(case: str, tmp_path: Path) -> None:
    assert sent(case, tmp_path) == _snapshot()[case]


# -- the builders, called alone -----------------------------------------------

Build = Callable[[BusSink, Capturing, str, int], Request]


def _ear(
    texts: tuple[str, ...],
    offers: dict[str, dict[str, str]],
    open_: set[str],
    verified: bool = False,
) -> Build:
    def build(sink: BusSink, client: Capturing, cause: str, n: int) -> Request:
        block = [Heard(f"u{i}", t, cause, i) for i, t in enumerate(texts, 1)]
        return Ear(client, sink.world, CP.company, CP.identity).request(
            block, offers, open_, n, verified=verified
        )

    return build


def _mouth_built(kind: str) -> Build:
    def build(sink: BusSink, client: Capturing, cause: str, n: int) -> Request:
        mouth = Mouth(client, sink.world, CP)
        return mouth.request(INTENTS[kind], MOUTH_HEARD[kind], cause, n)

    return build


def _user(
    task: Task, chat: list[str], changed: bool = False, stop: bool = False
) -> Build:
    facts = dict(task.profile.facts) | (CHANGE if changed else {})

    def build(sink: BusSink, client: Capturing, cause: str, n: int) -> Request:
        user = SimUser(task, client, sink.world, seed=7)
        return user.request(chat, facts, task.stop if stop else None, cause, n)

    return build


OPENED = ["You: Please lower my TV bill."]
MIND = _mind_change_task()
TURNS = [f"Assistant: {t}" for t in SIM_AGENT]
REPLIED = [*TURNS[:2], "You: Actually, up to 74 a month is fine.", TURNS[2]]
BUILDS: dict[str, list[Build]] = {
    "ear_one": [_ear(("Is that really the best you can do?",), {}, set())],
    "ear_one_verified": [
        _ear(("Is that really the best you can do?",), {}, set(), True)
    ],
    "ear_three_regenerated": [_ear(EAR_THREE, OFFERS, {"loyal-2"})] * 2,
    **{f"mouth_{k}": [_mouth_built(k)] * len(MOUTH_LINES[k]) for k in INTENTS},
    "simuser_chat": [
        _user(USER, []),
        *[_user(USER, [*OPENED, "Assistant: What is the account name?"])] * 2,
    ],
    "simuser_stop": [_user(USER, []), _user(USER, OPENED, stop=True)],
    "simuser_mind_change": [
        _user(MIND, TURNS[:1]),
        _user(MIND, TURNS[:2], changed=True, stop=True),
        _user(MIND, REPLIED, changed=True),
    ],
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_builder_alone_returns_the_recorded_request(
    case: str, tmp_path: Path
) -> None:
    """``request(...)`` is the sent request, byte for byte, and pure: it sends
    nothing, emits nothing and stores nothing."""

    recorded = _snapshot()[case]
    assert len(BUILDS[case]) == len(recorded)
    sink = BusSink(tmp_path)
    client = Capturing(sink)
    before = tuple(sink.bus.events)
    for build, want in zip(BUILDS[case], recorded, strict=True):
        call_id: str = json.loads(want)["call_id"]
        role, rest = call_id.split(":", 1)
        cause, n = rest.rsplit(":", 1)
        request = build(sink, client, cause, int(n))
        assert request.role == role
        assert _dump(request) == want
        assert _dump(build(sink, client, cause, int(n))) == want  # deterministic
    assert client.sent == [] and client.calls == 0
    assert sink.bus.events == before and sink.prompts == {}
