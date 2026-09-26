"""SimUser: the principal on the async user lane (ARCHITECTURE §10.2).

A forced ``reply`` call returns ``{text, revealed{key: value}}``; every
revealed key must be a profile fact and every value appear verbatim in
``text`` (the relay ground truth, EVAL §7), else the reply is regenerated
(ADR-0005 D5). The delay is sampled per reply from the task's range; the
kernel delivers the reply ``delay_s`` after the agent's message, on the wall
clock. There is no patience and no strike.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import Field, ValidationError

from proxyloop.contract.base import Frozen
from proxyloop.contract.llm import (
    ChatMessage,
    LLMClient,
    ToolCall,
    ToolRequest,
    ToolSpec,
)
from proxyloop.env import world
from proxyloop.env.tasks.schema import Task

SYSTEM = """You are {persona}
You asked an assistant to do this for you: {goal}
Private facts about you (key: value):
{facts}
Answer the assistant's latest chat message as yourself in one to three short \
sentences by calling `reply`. Share a fact only when asked or useful. When your \
text contains a fact, copy its value exactly and list it in `revealed` under its \
key. Never invent facts."""


class SimOut(Frozen):
    text: str = Field(min_length=1)
    revealed: dict[str, str]


@dataclass(frozen=True, slots=True)
class SimReply:
    text: str
    revealed: dict[str, str]
    delay_s: float
    event_id: str  # its user.sim event


def check_reply(calls: tuple[ToolCall, ...], facts: Mapping[str, str]) -> SimOut:
    if len(calls) != 1 or calls[0].name != "reply":
        raise world.Invalid("expected exactly one reply call")
    try:
        out = SimOut.model_validate_json(calls[0].arguments)
    except ValidationError as err:
        raise world.Invalid(f"schema: {err.errors()[0]['msg']}") from err
    if unknown := sorted(out.revealed.keys() - facts.keys()):
        raise world.Invalid(f"revealed unknown keys {unknown}")
    if absent := sorted(
        k for k, v in out.revealed.items() if not v or v not in out.text
    ):
        raise world.Invalid(f"revealed values not in the text: {absent}")
    return out


class SimUser:
    def __init__(
        self, task: Task, client: LLMClient, sink: world.WorldSink, seed: int
    ) -> None:
        self._client, self._sink = client, sink
        self._facts, self._delay = task.profile.facts, task.user.reply_delay_s.range
        facts = "\n".join(f"{k}: {v}" for k, v in sorted(self._facts.items()))
        goal, persona = task.user_goal.strip(), task.profile.persona.strip()
        self._system = SYSTEM.format(persona=persona, goal=goal, facts=facts)
        revealed: dict[str, object] = {"type": "object", "additionalProperties": False}
        revealed["properties"] = {k: {"type": "string"} for k in sorted(self._facts)}
        props = {"text": {"type": "string"}, "revealed": revealed}
        schema: dict[str, object] = {
            "type": "object",
            "properties": props,
            "required": ["text", "revealed"],
        }
        self._tool = ToolSpec(
            name="reply", description="Your message.", parameters=schema
        )
        self._rng = random.Random(seed)
        self._chat: list[str] = []
        self.timeout_s = world.TIMEOUT_S

    async def on_agent_message(self, text: str | None, cause: str) -> SimReply:
        """Reply to the agent's message (``cause``); ``None`` opens the case."""

        if text is not None:
            self._chat.append(f"Assistant: {text}")
        chat = "\n".join(self._chat) or "(empty: write your opening request)"
        messages = (
            ChatMessage(role="system", content=self._system),
            ChatMessage(role="user", content=f"Chat so far:\n{chat}"),
        )
        evs: list[str] = []

        async def attempt(n: int) -> tuple[ToolCall, ...]:
            request = ToolRequest(
                call_id=f"simuser:{cause}:{n}",
                role="simuser",
                messages=messages,
                tools=(self._tool,),
                tool_choice="reply",
                max_tokens=world.MAX_TOKENS,
            )
            calls, ev = await world.tools_call(
                self._client, self._sink, "world.simuser", request, cause
            )
            evs.append(ev)
            return calls

        out, attempts, _ = await world.bounded(
            attempt,
            lambda calls: check_reply(calls, self._facts),
            what="simuser",
            timeout_s=self.timeout_s,
        )
        self._chat.append(f"You: {out.text}")
        delay = round(self._rng.uniform(*self._delay), 3)
        payload = {"text": out.text, "revealed": out.revealed, "delay_s": delay}
        payload["attempts"] = attempts
        ev = self._sink.emit("user.sim", "world.simuser", payload, [cause, *evs])
        return SimReply(out.text, out.revealed, delay, ev)
