"""SlowLoop: one step in flight, wakes coalesced; ``SlowView`` in ``cfg.slow_view``
(I5, ADR-0016): unread relays become notes on the last tool result and the step's
``slow.tool`` cites them; in ``transcript`` mode the ``[CONVERSATIONS]`` block of
both lanes as heard goes in the newest message only and is a one-line stub once
that turn is history, so each line is in a request once. The context is bounded
(ADR-0009): the task head and the last ``WINDOW`` answered turns; once turns fall
out, Slow's own latest summaries stand in for them."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING

from proxyloop.contract import llm
from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.llm import ChatMessage
from proxyloop.contract.views import SlowView, view_slow
from proxyloop.kernel.watchdog import Abort
from proxyloop.slow import asks, prompt, state, transcript
from proxyloop.slow.tools import FORMATS, SlowTools, case_ref

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

_NO_TOOL = {"name": "act", "args": None, "result_text": "no tool call", "ok": False}
MAX_STEPS = 120  # per session: the runaway guard (S1-SYS-29; was 40, PLAN §0.5a)
WINDOW = 6  # [E] answered turns kept in the context (ADR-0009)
CALL_S = 180.0  # provisional until S0-ROOT-12: one whole Slow call, relay included
Turn = tuple[ChatMessage, tuple[ChatMessage, ...]]  # Slow's answer, what answered it


class SlowLoop:
    def __init__(
        self, host: Kernel, client: llm.LLMClient, brief: str, keys: frozenset[str]
    ):
        self._host, self._client, self._brief = host, client, brief
        self._mode = host.cfg.slow_view
        reads = self._mode is SlowViewMode.TRANSCRIPT
        firm = host.task.counterparty.company  # R6: only as the brief names it
        firm = firm if firm.casefold() in brief.casefold() else ""
        case = case_ref(host.task.id)
        self.tools = SlowTools(host, keys, case, transcript=reads, company=firm)
        self._cursor = transcript.Cursor()
        self._kind: state.Kind = host.task.mode  # task data, not the view (V3)
        public = ", ".join(sorted(keys & FORMATS.keys())) or "none"  # 21988c
        self._head = (
            f"TASK: {brief}\nTASK KIND: {self._kind}\n"
            f"SHAREABLE FACT KEYS (record_fact uses exactly these "
            f"keys, whatever a relay calls them): {', '.join(sorted(keys))}; of "
            f"these, only {public} can go public from the user's words, the "
            "others stay private and share_fact cannot publish them\n"
            f"{prompt.PLAYBOOK[self._kind]}"
        )
        self._first = ""  # the head with the first step's notes
        self._turns: list[Turn] = []  # the last WINDOW answered turns
        self._dropped = 0  # answered turns that left the context
        self._said: ChatMessage | None = None  # the last answer, not yet answered
        self._results: list[tuple[str, str]] = []  # (tool call id, result text)
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

    def _context(self, text: str, stub: str, view: SlowView) -> list[ChatMessage]:
        """``text``: this step's notes; ``stub``: the same, as history keeps
        them (the block stubbed; equal in ``relay_only``)."""
        if self._said is None:  # the first step
            self._first = f"{self._head}\n\n{stub}"
            return [ChatMessage(role="user", content=f"{self._head}\n\n{text}")]
        self._turns.append((self._said, self._answer(stub)))
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
        newest = self._answer(text)  # the block only here (ADR-0016)
        turns[-len(newest) :] = newest
        return [ChatMessage(role="user", content=head), *turns]

    async def step(self, reasons: Sequence[str]) -> None:
        if self.steps >= MAX_STEPS:  # a loud end, never a fallback
            raise Abort("slow_step_cap", f"Slow reached {MAX_STEPS} steps")
        self.tools.readback()  # the status bar shows Guard's current statuses
        host, bb = self._host, self._host.bb
        view = view_slow(bb, self._mode, self._brief)
        new = [r for r in view.relays if r.msg_id not in self.tools.received]
        self.tools.received |= {r.msg_id for r in new}
        basis = {"basis_seq": bb.seq}
        wake = basis | {"wake_reasons": list(reasons)}
        started = host.emit("slow.step.started", "slow", wake, []).event_id
        wakes = f"[WAKE] {', '.join(reasons)}"
        now = host.bb.t_ms  # Guard's clock
        more = state.bar(bb, self._kind, self.tools)
        bar = prompt.status_bar(view, now, asks.intake(host), more)
        reads = self._mode is SlowViewMode.TRANSCRIPT
        relays = [prompt.note(r, quoted=reads) for r in new]
        text = stub = "\n".join([wakes, *relays, bar])
        if reads:
            block, self._cursor = transcript.render(view.transcripts, self._cursor)
            if self._cursor.omitted:  # counted as dropped (ADR-0016)
                host.counts["slow_transcript_omitted"] += self._cursor.omitted
            shown = f"[CONVERSATIONS shown at step {self.steps + 1}: "
            shown += f"+{self._cursor.new} lines]"
            text = "\n".join([wakes, block, *relays, bar])
            stub = "\n".join([wakes, shown, *relays, bar])
        context = self._context(text, stub, view)
        self.steps += 1
        request = llm.ToolRequest(
            call_id=f"slow:{self.steps}",
            role="slow",
            messages=(
                ChatMessage(role="system", content=prompt.system(self._mode)),
                *context,
            ),
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
            (c.call_id, self.tools.act(c, causes, basis=basis["basis_seq"]))
            for c in resp.tool_calls
        ]
        filtered = resp.record.finish_reason == "content_filter"  # S1-SYS-28
        if filtered:  # counted, never retried; any tool calls ran as usual
            host.counts["slow_content_filter"] += 1
        if not resp.tool_calls:
            none = dict(_NO_TOOL)
            if filtered:
                none["result_text"] = "no tool call (content_filter)"
            host.emit("slow.tool", "slow", none, causes)
        host.emit("slow.step.completed", "slow", basis, [started])
