"""SimRep: Ear -> policy -> Mouth, emitting the world events (§4.2, §10.1).

Per heard utterance: ``llm.call``s and ``rep.ear`` [the ``utt.delivered``],
``rep.policy`` [``rep.ear``], on a commit ``rep.commit_heard`` and
``ledger.write``, then ``llm.call``s and ``rep.mouth`` [``rep.policy``]. The
kernel emits the returned lines as ``utt.final`` and a strike as ``chan.strike``.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass

from proxyloop.contract.llm import LLMClient
from proxyloop.env import world
from proxyloop.env.counterparty.ear import Ear
from proxyloop.env.counterparty.mouth import Mouth
from proxyloop.env.counterparty.policy import Decision, Policy
from proxyloop.env.tasks.schema import Task


@dataclass(frozen=True, slots=True)
class RepTurn:
    lines: tuple[tuple[str, str], ...]  # (text, its rep.mouth event_id)
    strike: bool
    ended: bool  # confirmed, transferred or hung up


class SimRep:
    """Calls are serialised; ``tick`` does nothing while a rep turn is in flight."""

    def __init__(
        self, task: Task, ear: LLMClient, mouth: LLMClient, writer: world.World
    ) -> None:
        cp = task.counterparty
        self.policy = Policy(cp, {k: task.profile.facts[k] for k in cp.identity})
        self.ear = Ear(ear, writer, cp.company, cp.identity)
        self.mouth = Mouth(mouth, writer, cp)
        self._world = writer
        self._turn = asyncio.Lock()

    async def on_agent_utterance(
        self, utt_id: str, text_heard: str, event_id: str, t_ms: int
    ) -> RepTurn:
        """React to one agent utterance as heard (its ``utt.delivered``)."""

        async with self._turn:
            if self.policy.done:
                return RepTurn((), False, True)
            made = self.policy.made()
            act, ear_ev = await self.ear.classify(utt_id, text_heard, event_id, made)
            decisions = self.policy.step(act, utt_id, text_heard, t_ms)
            return await self._run(decisions, text_heard, (utt_id, ear_ev))

    async def tick(self, t_ms: int) -> RepTurn:
        if self._turn.locked():  # a rep turn is in flight: the floor is not free
            return RepTurn((), False, self.policy.done)
        async with self._turn:
            return await self._run(self.policy.tick(t_ms), "", None)

    def floor(self, free: bool, t_ms: int) -> None:
        """Either party took or released the floor (the kernel's speech clock)."""

        self.policy.floor(free, t_ms)

    async def _run(
        self, decisions: list[Decision], heard: str, ear: tuple[str, str] | None
    ) -> RepTurn:
        lines: list[tuple[str, str]] = []
        for d in decisions:
            payload: dict[str, object] = {"from": d.from_, "to": d.to, "rung": d.rung}
            payload["intent"] = d.intent.model_dump(mode="json")
            reacted = ear is not None and d.intent.kind != "offer_expired"
            causes = [ear[1]] if ear is not None and reacted else []
            ev = self._world.emit("rep.policy", "world.policy", payload, causes)
            if d.commit is not None and ear is not None:
                heard_ev = self._world.emit(
                    "rep.commit_heard",
                    "world.policy",
                    {"utt_id": ear[0], "offer_ref": d.commit.offer_ref},
                    [ear[1], ev],
                )
                if (bound := d.commit.bound) is not None:
                    binding = asdict(bound) | {"terms": dict(bound.terms)}
                    write = {
                        "confirmation_id": d.commit.confirmation_id,
                        "binding": binding,
                    }
                    self._world.emit("ledger.write", "world.ledger", write, [heard_ev])
            if d.intent.kind != "offer_expired":
                lines.append(await self.mouth.say(d.intent, heard, ev))
        strike = any(d.strike for d in decisions)
        return RepTurn(tuple(lines), strike, self.policy.done)
