"""SlowLoop: one step in flight; wakes during a step coalesce into the next.
A step reads the relay-only ``SlowView`` (I5): unread relays become notes on the
last tool result, with the status bar. The fold keeps ``f2s_pending`` whole, so
the loop tracks what it has read (its ``slow.tool`` events cite them)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING

from proxyloop.contract import llm
from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.llm import ChatMessage
from proxyloop.contract.views import view_slow
from proxyloop.slow import prompt
from proxyloop.slow.tools import SlowTools

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

_NO_TOOL = {"name": "act", "args": None, "result_text": "no tool call", "ok": False}


class SlowLoop:
    def __init__(
        self, host: Kernel, client: llm.LLMClient, brief: str, keys: frozenset[str]
    ):
        self._host, self._client, self._brief = host, client, brief
        self.tools = SlowTools(host, keys)
        self._head = f"TASK: {brief}\nSHAREABLE FACT KEYS: {', '.join(sorted(keys))}"
        self._history: list[ChatMessage] = []
        self._results: list[tuple[str, str]] = []  # (tool call id, result text)
        self._read: set[str] = set()
        self._reasons: set[str] = set()
        self._wake, self._n = asyncio.Event(), 0

    def wake(self, reason: str) -> None:
        self._reasons.add(reason)
        self._wake.set()

    async def run(self) -> None:
        while not self.tools.finished:
            await self._wake.wait()
            self._wake.clear()
            reasons, self._reasons = sorted(self._reasons), set()
            await self.step(reasons)

    def _context(self, text: str) -> list[ChatMessage]:
        if not self._history:
            return [ChatMessage(role="user", content=f"{self._head}\n\n{text}")]
        if not self._results:  # the last answer called no tool
            return [ChatMessage(role="user", content=text)]
        *done, (last_id, last) = self._results
        tool = [ChatMessage(role="tool", content=r, tool_call_id=i) for i, r in done]
        last_text = f"{last}\n\n{text}"
        return [
            *tool,
            ChatMessage(role="tool", content=last_text, tool_call_id=last_id),
        ]

    async def step(self, reasons: Sequence[str]) -> None:
        host, bb = self._host, self._host.bb
        view = view_slow(bb, SlowViewMode.RELAY_ONLY, self._brief)
        new = [r for r in view.relays if r.msg_id not in self._read]
        self._read |= {r.msg_id for r in new}
        basis = {"basis_seq": bb.seq}
        wake = basis | {"wake_reasons": list(reasons)}
        started = host.emit("slow.step.started", "slow", wake, []).event_id
        notes = [*map(prompt.note, new), prompt.status_bar(view)]
        self._history += self._context("\n".join(notes))
        self._n += 1
        request = llm.ToolRequest(
            call_id=f"slow:{self._n}",
            role="slow",
            messages=(
                ChatMessage(role="system", content=prompt.SYSTEM),
                *self._history,
            ),
            tools=(prompt.ACT,),
            tool_choice=prompt.ACT.name,
            max_tokens=prompt.MAX_TOKENS,
        )
        host.expect(request.call_id, started)
        host.store("messages", llm.request_content(request))
        resp = await self._client.chat_tools(request)
        host.store("response", llm.tool_response_content(resp.text, resp.tool_calls))
        causes = [host.call_event(request.call_id), *(r.msg_id for r in new)]
        said = ChatMessage(
            role="assistant", content=resp.text, tool_calls=resp.tool_calls
        )
        self._history.append(said)
        self._results = [
            (c.call_id, self.tools.act(c, causes)) for c in resp.tool_calls
        ]
        if not resp.tool_calls:
            host.emit("slow.tool", "slow", _NO_TOOL, causes)
        host.emit("slow.step.completed", "slow", basis, [started])
