"""SlowLoop: one step in flight, wakes coalesced; relay-only ``SlowView`` (I5): unread
relays become notes on the last tool result and the step's ``slow.tool`` cites them.
The context is bounded (ADR-0009): the task head and the last ``WINDOW`` answered
turns; once turns fall out, Slow's own latest summaries stand in for them."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING

from proxyloop.contract import llm
from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.llm import ChatMessage
from proxyloop.contract.views import SlowView, view_slow
from proxyloop.kernel.watchdog import Abort
from proxyloop.slow import prompt
from proxyloop.slow.tools import SlowTools, case_ref

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

_NO_TOOL = {"name": "act", "args": None, "result_text": "no tool call", "ok": False}
MAX_STEPS = 40  # per session: the S0 runaway guard (PLAN §0.5a, 2026-09-26)
WINDOW = 6  # [E] answered turns kept in the context (ADR-0009)
CALL_S = 180.0  # provisional until S0-ROOT-12: one whole Slow call, relay included
Turn = tuple[ChatMessage, tuple[ChatMessage, ...]]  # Slow's answer, what answered it


class SlowLoop:
    def __init__(
        self, host: Kernel, client: llm.LLMClient, brief: str, keys: frozenset[str]
    ):
        self._host, self._client, self._brief = host, client, brief
        self.tools = SlowTools(host, keys, case_ref(host.task.id))
        self._keys = keys
        self._head = (
            f"TASK: {brief}\nSHAREABLE FACT KEYS (record_fact uses exactly these "
            f"keys, whatever a relay calls them): {', '.join(sorted(keys))}"
        )
        self._first = ""  # the head with the first step's notes
        self._turns: list[Turn] = []  # the last WINDOW answered turns
        self._dropped = 0  # answered turns that left the context
        self._said: ChatMessage | None = None  # the last answer, not yet answered
        self._results: list[tuple[str, str]] = []  # (tool call id, result text)
        self._read: set[str] = set()
        self._reasons: set[str] = set()
        self._wake, self.steps = asyncio.Event(), 0

    def wake(self, reason: str) -> None:
        self._reasons.add(reason)
        self._wake.set()

    async def run(self) -> None:
        while not self.tools.finished:
            await self._wake.wait()
            self._wake.clear()
            reasons, self._reasons = sorted(self._reasons), set()
            await self.step(reasons)

    def _answer(self, text: str) -> tuple[ChatMessage, ...]:  # to the last answer
        if not self._results:  # it called no tool
            return (ChatMessage(role="user", content=text),)
        *done, (last_id, last) = self._results
        tool = [ChatMessage(role="tool", content=r, tool_call_id=i) for i, r in done]
        last_text = f"{last}\n\n{text}"
        return (
            *tool,
            ChatMessage(role="tool", content=last_text, tool_call_id=last_id),
        )

    def _context(self, text: str, view: SlowView) -> list[ChatMessage]:
        if self._said is None:  # the first step
            self._first = f"{self._head}\n\n{text}"
            return [ChatMessage(role="user", content=self._first)]
        self._turns.append((self._said, self._answer(text)))
        if len(self._turns) > WINDOW:  # every tool call leaves with its result
            del self._turns[0]
            self._dropped += 1
        head = self._first
        if self._dropped:  # Slow's own digests stand in for what left (ADR-0009)
            head = (
                f"{self._head}\n\n[EARLIER] {self._dropped} earlier turns left this "
                "context; your latest summaries stand for them.\n"
                f"PRIVATE SUMMARY: {view.private_summary or 'none'}\n"
                f"PUBLIC SUMMARY: {view.public_summary or 'none'}"
            )
        turns = [m for said, answer in self._turns for m in (said, *answer)]
        return [ChatMessage(role="user", content=head), *turns]

    async def step(self, reasons: Sequence[str]) -> None:
        if self.steps >= MAX_STEPS:  # a loud end, never a fallback
            raise Abort("slow_step_cap", f"Slow reached {MAX_STEPS} steps")
        self.tools.readback()  # the status bar shows Guard's current statuses
        host, bb = self._host, self._host.bb
        view = view_slow(bb, SlowViewMode.RELAY_ONLY, self._brief)
        new = [r for r in view.relays if r.msg_id not in self._read]
        self._read |= {r.msg_id for r in new}
        basis = {"basis_seq": bb.seq}
        wake = basis | {"wake_reasons": list(reasons)}
        started = host.emit("slow.step.started", "slow", wake, []).event_id
        wakes = f"[WAKE] {', '.join(reasons)}"
        bar = prompt.status_bar(view, self._keys, host.now())
        notes = [wakes, *map(prompt.note, new), bar]
        context = self._context("\n".join(notes), view)
        self.steps += 1
        request = llm.ToolRequest(
            call_id=f"slow:{self.steps}",
            role="slow",
            messages=(ChatMessage(role="system", content=prompt.SYSTEM), *context),
            tools=(prompt.ACT,),
            tool_choice=prompt.ACT.name,
            max_tokens=prompt.MAX_TOKENS,
        )
        host.expect(request.call_id, started)
        host.store("messages", llm.request_content(request))
        deadline = asyncio.timeout(CALL_S)
        try:
            async with deadline:
                resp = await self._client.chat_tools(request)
        except TimeoutError as err:
            if not deadline.expired():
                raise
            took = f"{request.call_id} took over {CALL_S:g} s"
            raise Abort("slow_timeout", took) from err
        host.store("response", llm.tool_response_content(resp.text, resp.tool_calls))
        causes = [host.call_event(request.call_id), *(r.msg_id for r in new)]
        self._said = ChatMessage(
            role="assistant", content=resp.text, tool_calls=resp.tool_calls
        )
        self._results = [
            (c.call_id, self.tools.act(c, causes)) for c in resp.tool_calls
        ]
        if not resp.tool_calls:
            host.emit("slow.tool", "slow", _NO_TOOL, causes)
        host.emit("slow.step.completed", "slow", basis, [started])
