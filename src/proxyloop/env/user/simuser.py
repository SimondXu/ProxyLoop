"""SimUser: the principal on the async user lane (ARCHITECTURE §10.2).

A forced ``reply`` call returns ``{text, revealed{key: value}}``; every
revealed key must be a profile fact and every value appear verbatim in
``text`` (the relay ground truth, EVAL §7), else the reply is regenerated
(ADR-0005 D5). The user answers questions but need not answer every status
message: ``{silent: true, revealed: {}}`` sends nothing (no ``user.sim``; its
``llm.call`` records stay). The opening is never silent. The delay is sampled
per reply from the task's range; the kernel delivers the reply ``delay_s``
after the agent's message, on the wall clock. There is no patience and no
strike.

A ``full`` task's principal also has an approval button, ``approver`` (see
``approver.py``). The task's ``stop`` fires once, in the reply to the first
agent message at which its trigger holds: the k-th agent message
(``after_turn_k``), one that says an offer's monthly price (``after_offer``),
or any message after the approver saw a card (``after_card``). That reply is
generated from ``text_hint``, cannot be silent, must reveal every changed fact
of a mind change, and its ``user.sim`` carries ``stop: stop|mind_change`` (the
world truth for EVAL §7). From then on the approver denies everything after a
stop, and uses the changed facts after a mind change.
"""

from __future__ import annotations

import random
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Self

from pydantic import ConfigDict, Field, ValidationError, model_validator

from proxyloop.contract.base import Frozen
from proxyloop.contract.llm import (
    ChatMessage,
    LLMClient,
    ToolCall,
    ToolRequest,
    ToolSpec,
)
from proxyloop.env import world
from proxyloop.env.tasks.schema import Stop, Task
from proxyloop.env.user.approver import Approver

TEMPERATURE = 0.7  # pinned: persona variety; the reveal check guards the facts
SYSTEM = """You are {persona}
You asked an assistant to do this for you: {goal}
Private facts about you (key: value):
{facts}
Reply to the assistant's latest chat message as yourself in one to three short \
sentences by calling `reply`. Always answer a question. A status update needs no \
answer: to stay silent, call `reply` with silent true, no text and nothing \
revealed. Share a fact only when asked or useful. When your text contains a fact, \
copy its value exactly and list it in `revealed` under its key. Never invent \
facts."""


class SimOut(Frozen):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    silent: bool = False
    text: str | None = Field(default=None, min_length=1)
    revealed: dict[str, str]

    @model_validator(mode="after")
    def _silent_or_text(self) -> Self:
        if self.silent != (self.text is None):
            raise ValueError("a reply has text exactly when it is not silent")
        if self.silent and self.revealed:
            raise ValueError("a silent turn reveals nothing")
        return self


@dataclass(frozen=True, slots=True)
class SimReply:
    text: str
    revealed: dict[str, str]
    delay_s: float
    event_id: str  # its user.sim event


def check_reply(
    calls: tuple[ToolCall, ...],
    facts: Mapping[str, str],
    opening: bool = False,
    stop: Collection[str] | None = None,  # a stop: the changed facts to reveal
) -> SimOut:
    if len(calls) != 1 or calls[0].name != "reply":
        raise world.Invalid("expected exactly one reply call")
    try:
        out = SimOut.model_validate_json(calls[0].arguments)
    except ValidationError as err:
        raise world.Invalid(f"schema: {err.errors()[0]['msg']}") from err
    if out.silent and opening:
        raise world.Invalid("the opening request cannot be silent")
    if out.silent and stop is not None:
        raise world.Invalid("the stop cannot be silent")
    if missing := sorted(set(stop or ()) - out.revealed.keys()):
        raise world.Invalid(f"the mind change does not reveal {missing}")
    if unknown := sorted(out.revealed.keys() - facts.keys()):
        raise world.Invalid(f"revealed unknown keys {unknown}")
    if wrong := sorted(k for k, v in out.revealed.items() if v != facts[k]):
        raise world.Invalid(f"revealed values that are not the profile's: {wrong}")
    text = out.text or ""
    if absent := sorted(k for k, v in out.revealed.items() if v not in text):
        raise world.Invalid(f"revealed values not in the text: {absent}")
    return out


class SimUser:
    def __init__(
        self, task: Task, client: LLMClient, writer: world.World, seed: int
    ) -> None:
        self._client, self._world = client, writer
        self.approver = Approver(task, seed) if task.principal is not None else None
        self._facts = self.approver.facts if self.approver else dict(task.profile.facts)
        self._delay = task.user.reply_delay_s.range
        self._task, self._persona = task, task.profile.persona.strip()
        self._stop, self._fired, self._turns = task.stop, False, 0
        ladder = [o.all_terms for o in task.counterparty.ladder]
        self._prices = {
            Decimal(t["monthly_price"]) for t in ladder if "monthly_price" in t
        }
        revealed: dict[str, object] = {"type": "object", "additionalProperties": False}
        revealed["properties"] = {k: {"type": "string"} for k in sorted(self._facts)}
        silent = {"type": "boolean", "description": "true: send nothing this time"}
        props = {"text": {"type": "string"}, "revealed": revealed, "silent": silent}
        schema: dict[str, object] = {
            "type": "object",
            "properties": props,
            "required": ["revealed"],
        }
        self._tool = ToolSpec(
            name="reply", description="Your message.", parameters=schema
        )
        self._rng = random.Random(seed)
        self._chat: list[str] = []
        self.timeout_s = world.TIMEOUT_S

    async def on_agent_message(self, text: str | None, cause: str) -> SimReply | None:
        """Reply to the agent's message (``cause``); ``None`` opens the case.
        ``None`` back: the user stays silent."""

        if text is not None:
            self._chat.append(f"Assistant: {text}")
            self._turns += 1
        stop = self._stop if text is not None and self._due(text) else None
        now = ""
        if stop is not None:
            self._fired = True
            if self.approver is not None:
                self.approver.stop(stop.change)
            now = f"\n\nNow, in this reply: {stop.text_hint.strip()}"
            if stop.change:
                said = "; ".join(f"{k}: {v}" for k, v in sorted(stop.change.items()))
                now += f" Say your changed facts exactly: {said}."
        chat = "\n".join(self._chat) or "(empty: write your opening request)"
        facts = "\n".join(f"{k}: {v}" for k, v in sorted(self._facts.items()))
        goal = self._task.goal(self._facts).strip()
        system = SYSTEM.format(persona=self._persona, goal=goal, facts=facts)
        messages = (
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=f"Chat so far:\n{chat}{now}"),
        )
        reveal = None if stop is None else tuple(stop.change or ())
        call_ids = [f"simuser:{cause}:{n}" for n in range(world.MAX_REGENERATIONS + 1)]

        async def attempt(n: int) -> tuple[ToolCall, ...]:
            request = ToolRequest(
                call_id=call_ids[n],
                role="simuser",
                messages=messages,
                tools=(self._tool,),
                tool_choice="reply",
                max_tokens=world.MAX_TOKENS,
                temperature=TEMPERATURE,
            )
            return await self._world.tools(self._client, request, cause)

        out, attempts, _ = await world.bounded(
            attempt,
            lambda calls: check_reply(calls, self._facts, text is None, reveal),
            what="simuser",
            timeout_s=self.timeout_s,
        )
        if out.text is None:  # silent: its llm.call records are the only trace
            return None
        self._chat.append(f"You: {out.text}")
        delay = round(self._rng.uniform(*self._delay), 3)
        payload = {"text": out.text, "revealed": out.revealed, "delay_s": delay}
        payload["attempts"] = attempts
        if stop is not None:
            payload["stop"] = "stop" if stop.change is None else "mind_change"
        causes = [cause, *self._world.calls(call_ids[:attempts])]
        ev = self._world.emit("user.sim", "world.simuser", payload, causes)
        return SimReply(out.text, out.revealed, delay, ev)

    def _due(self, text: str) -> bool:
        stop: Stop | None = self._stop
        if stop is None or self._fired:
            return False
        if stop.trigger == "after_turn_k":
            return self._turns >= (stop.k or 0)
        if stop.trigger == "after_offer":
            return bool(world.numbers(text) & self._prices)
        return self.approver is not None and self.approver.cards_seen > 0
