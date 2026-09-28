"""SimRep: Ear -> policy -> Mouth, emitting the world events (§4.2, §10.1).

Per heard block (ADR-0021: every agent utterance heard while a rep turn was in
flight, in delivery order; one utterance when none queued): ``llm.call``s,
then per utterance a ``rep.ear`` [its ``utt.delivered``, the calls]; per
decision ``rep.policy`` [its utterance's ``rep.ear``], on a commit
``rep.commit_heard`` and ``ledger.write``, then ``llm.call``s and
``rep.mouth`` [``rep.policy``]. The policy steps every utterance's act, in
order, exactly as it would one turn at a time. The kernel emits the returned
lines as ``utt.final`` and a strike as ``chan.strike``.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass

from proxyloop.contract.llm import LLMClient
from proxyloop.env import world
from proxyloop.env.counterparty.ear import Ear, Heard
from proxyloop.env.counterparty.mouth import Mouth
from proxyloop.env.counterparty.policy import Decision, Policy
from proxyloop.env.tasks.schema import Task

# A decision, the heard text it answers, and (utt_id, its rep.ear) if heard.
Step = tuple[Decision, str, tuple[str, str] | None]


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
        self._heard: list[Heard] = []  # heard, not yet taken by a rep turn

    async def on_agent_utterance(
        self, utt_id: str, text_heard: str, event_id: str, t_ms: int
    ) -> RepTurn:
        """React to the agent's utterances as heard (their ``utt.delivered``):
        the turn takes every one heard so far as one block. A call whose
        utterance an earlier turn already took returns an empty turn."""

        self._heard.append(Heard(utt_id, text_heard, event_id, t_ms))
        async with self._turn:
            block, self._heard = self._heard, []
            if not block or self.policy.done:
                return RepTurn((), False, self.policy.done)
            acts = await self.ear.classify(block, self.policy.made())
            steps: list[Step] = [
                (d, h.text, (h.utt_id, ear_ev))
                for h, (act, ear_ev) in zip(block, acts, strict=True)
                for d in self.policy.step(act, h.utt_id, h.text, h.t_ms)
            ]  # step returns nothing once the call is over
            return await self._run(steps)

    async def tick(self, t_ms: int) -> RepTurn:
        if self._turn.locked():  # a rep turn is in flight: the floor is not free
            return RepTurn((), False, self.policy.done)
        async with self._turn:
            return await self._run([(d, "", None) for d in self.policy.tick(t_ms)])

    def floor(self, free: bool, t_ms: int) -> None:
        """Either party took or released the floor (the kernel's speech clock)."""

        self.policy.floor(free, t_ms)

    async def _run(self, steps: list[Step]) -> RepTurn:
        """Emit each decision; voice them in order, but a run of equal intents
        without a commit once, at its last (ADR-0021 D4)."""

        lines: list[tuple[str, str]] = []
        for i, (d, heard, ear) in enumerate(steps):
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
            again = i + 1 < len(steps) and steps[i + 1][0].intent == d.intent
            if d.intent.kind != "offer_expired" and (d.commit is not None or not again):
                lines.append(await self.mouth.say(d.intent, heard, ev))
        strike = any(d.strike for d, _, _ in steps)
        return RepTurn(tuple(lines), strike, self.policy.done)
