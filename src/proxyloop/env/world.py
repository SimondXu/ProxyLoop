"""World model calls: the call policy (ADR-0005 D5-6) and the world's writer.

A world output failing its schema or check is regenerated at most twice, each
attempt its own call and counted in the result event's ``attempts``; then
``WorldError`` ends the episode, unless the caller names the spec'd fallback
(only the Mouth's ``fidelity_fallback``, ARCHITECTURE §10.1). Every attempt
has a wall-clock timeout (a ``WorldError``); the cancelled call's record still
reaches ``World.record``. ``LLMUnavailable`` always propagates (I8).

Every world ``llm.call`` event is written from one place: ``World.record``,
the ``on_record`` sink of the world's clients, which receives every record
(successes, failures, retries, cancellations). The world never writes a
returned record itself; it cites calls by ``call_id``.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from decimal import Decimal
from typing import Literal, Protocol

from proxyloop.contract import llm
from proxyloop.contract.llm import LLMCallRecord, LLMClient, TextRequest, ToolRequest

MAX_REGENERATIONS, TIMEOUT_S = 2, 20.0
MAX_TOKENS = 512  # bounds neither reasoning nor latency here (ADR-0005 Risks)


class WorldError(Exception):
    """The world failed: the episode ends with an error."""


class Invalid(ValueError):
    """A world output that fails its schema or its deterministic check."""


class WorldSink(Protocol):
    """The session's bus (world stream) and ``prompts.jsonl`` store."""

    def emit(
        self,
        type_: str,
        actor: str,
        payload: Mapping[str, object],
        causes: Sequence[str],
    ) -> str: ...  # the new event's event_id

    def store(self, kind: Literal["messages", "response"], content: str) -> None: ...


class World:
    """The world's writer: world events, and every world ``llm.call``."""

    def __init__(self, sink: WorldSink) -> None:
        self.sink = sink
        self._causes: dict[str, str] = {}  # call_id -> the event it answers
        self._calls: dict[str, list[str]] = {}  # call_id -> its llm.call events

    def record(self, record: LLMCallRecord) -> None:
        """The ``on_record`` sink of every world client."""

        cause = self._causes.get(record.call_id)
        if cause is None:
            raise WorldError(f"a record for unknown world call {record.call_id!r}")
        payload = record.model_dump(mode="json")
        ev = self.sink.emit("llm.call", f"world.{record.role}", payload, [cause])
        self._calls.setdefault(record.call_id, []).append(ev)

    def calls(self, call_ids: Sequence[str]) -> list[str]:
        """The ``llm.call`` events of these calls, retries included."""

        return [ev for c in call_ids for ev in self._calls.get(c, [])]

    def emit(
        self,
        type_: str,
        actor: str,
        payload: Mapping[str, object],
        causes: Sequence[str],
    ) -> str:
        return self.sink.emit(type_, actor, payload, causes)

    def _start(self, request: TextRequest | ToolRequest, cause: str) -> None:
        self._causes[request.call_id] = cause
        self.sink.store("messages", llm.request_content(request))

    async def tools(
        self, client: LLMClient, request: ToolRequest, cause: str
    ) -> tuple[llm.ToolCall, ...]:
        self._start(request, cause)
        resp = await client.chat_tools(request)
        self.sink.store(
            "response", llm.tool_response_content(resp.text, resp.tool_calls)
        )
        return resp.tool_calls

    async def text(self, client: LLMClient, request: TextRequest, cause: str) -> str:
        self._start(request, cause)
        parts: list[str] = []
        stream = client.stream_text(request)
        try:
            async for item in stream:
                if isinstance(item, str):
                    parts.append(item)
        finally:  # close the stream on a timeout too; store what was delivered
            close: Callable[[], Awaitable[object]] | None = getattr(
                stream, "aclose", None
            )
            if close is not None:
                await close()
            if parts:
                self.sink.store("response", "".join(parts))
        return "".join(parts)


async def bounded[R, T](
    attempt: Callable[[int], Awaitable[R]],
    check: Callable[[R], T],
    *,
    what: str,
    timeout_s: float,
    exhausted: Callable[[], T] | None = None,
) -> tuple[T, int, bool]:
    """Run ``attempt(n)`` until ``check`` passes: ``(value, attempts, valid)``."""

    last: Invalid | None = None
    for n in range(MAX_REGENERATIONS + 1):
        try:
            raw = await asyncio.wait_for(attempt(n), timeout_s)
        except TimeoutError as err:
            raise WorldError(f"{what}: no answer within {timeout_s} s") from err
        try:
            return check(raw), n + 1, True
        except Invalid as err:
            last = err
    if exhausted is None:
        raise WorldError(
            f"{what}: invalid after {MAX_REGENERATIONS} regenerations: {last}"
        )
    return exhausted(), MAX_REGENERATIONS + 1, False


def numbers(text: str) -> set[Decimal]:
    """The numbers written as digits in ``text`` (``1,000.50`` is 1000.50)."""

    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    return {Decimal(m) for m in re.findall(r"\d+(?:\.\d+)?", text)}
