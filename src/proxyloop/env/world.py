"""World model calls: the model, the call policy (ADR-0005 D5-6), the sink.

A world output failing its schema or check is regenerated at most twice, each
attempt its own ``llm.call`` and counted in the result event's ``attempts``;
then ``WorldError`` ends the episode, unless the caller names the spec'd
fallback (only the Mouth's ``fidelity_fallback``, ARCHITECTURE §10.1). Every
attempt has a wall-clock timeout (a ``WorldError``). ``LLMUnavailable``
always propagates (I8). Nothing is coerced or defaulted.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from decimal import Decimal
from typing import Literal, Protocol

from proxyloop.contract import llm
from proxyloop.contract.llm import LLMCallRecord, LLMClient, TextRequest, ToolRequest

# ADR-0005 Decision 1.
WORLD_MODEL = llm.ModelRef(
    kind=llm.AdapterKind.REAL_HTTP,
    endpoint="teamrouter",
    model_id="gemini-3.8-flash",
    reasoning_effort="low",  # provisional: ADR-0005, root probe pending
)
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


def _log(
    sink: WorldSink,
    actor: str,
    request: TextRequest | ToolRequest,
    response: str | None,
    record: LLMCallRecord,
    causes: Sequence[str],
) -> str:
    sink.store("messages", llm.request_content(request))
    if response is not None:
        sink.store("response", response)
    return sink.emit("llm.call", actor, record.model_dump(mode="json"), causes)


async def tools_call(
    client: LLMClient, sink: WorldSink, actor: str, request: ToolRequest, cause: str
) -> tuple[tuple[llm.ToolCall, ...], str]:
    """One forced tool call, logged as its ``llm.call`` even when it fails."""

    try:
        resp = await client.chat_tools(request)
    except llm.LLMUnavailable as err:
        _log(sink, actor, request, None, err.record, [cause])
        raise
    content = llm.tool_response_content(resp.text, resp.tool_calls)
    return resp.tool_calls, _log(sink, actor, request, content, resp.record, [cause])


async def text_call(
    client: LLMClient, sink: WorldSink, actor: str, request: TextRequest, cause: str
) -> tuple[str, str]:
    """One streamed text call, logged as its ``llm.call`` even when it fails."""

    parts: list[str] = []
    record: LLMCallRecord | None = None
    try:
        async for item in client.stream_text(request):
            if isinstance(item, str):
                parts.append(item)
            else:
                record = item
    except llm.LLMUnavailable as err:
        _log(sink, actor, request, None, err.record, [cause])
        raise
    if record is None:
        raise WorldError(f"{request.call_id}: the adapter yielded no record")
    text = "".join(parts)
    return text, _log(sink, actor, request, text, record, [cause])


def numbers(text: str) -> set[Decimal]:
    """The numbers written as digits in ``text`` (``1,000.50`` is 1000.50)."""

    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    return {Decimal(m) for m in re.findall(r"\d+(?:\.\d+)?", text)}
