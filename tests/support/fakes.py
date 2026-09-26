"""Scripted ``LLMClient`` fakes (``AdapterKind.test_fake``). Tests only (I8).

``ScriptedLLM`` answers each call with the next scripted response and yields
one conforming ``LLMCallRecord`` per call (``tests/contract/llm_conformance``).
``dead=True`` models a closed endpoint: ``LLMUnavailable``, nothing delivered.
``on_record`` (optional) receives every record, as a real adapter's sink does:
successes, the dead endpoint's failure, and a cancelled call (``error=
"cancelled"``). ``hang_s`` delays each answer, so a caller's timeout can
cancel it.
``recorded.py`` reuses it with ``recorded_replay`` refs.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Sequence

from tests.support.manual_clock import ManualClock

from proxyloop.contract.base import sha256_text
from proxyloop.contract.llm import (
    AdapterKind,
    LLMCallRecord,
    LLMUnavailable,
    ModelRef,
    TextRequest,
    ToolCall,
    ToolRequest,
    ToolResponse,
    Usage,
    request_content,
    tool_response_content,
)

CHUNK = 7  # characters per streamed delta: splits lines and sentences


def fake_ref(model_id: str = "fake-model") -> ModelRef:
    return ModelRef(kind=AdapterKind.TEST_FAKE, endpoint=None, model_id=model_id)


class ScriptedLLM:
    def __init__(
        self,
        ref: ModelRef,
        responses: Sequence[str],
        clock: ManualClock | None = None,
        dead: bool = False,
        on_record: Callable[[LLMCallRecord], None] | None = None,
        hang_s: float = 0,
    ) -> None:
        self._ref = ref
        self._responses = list(responses)
        self._clock = clock or ManualClock()
        self._dead = dead
        self._on_record = on_record
        self._hang_s = hang_s
        self.calls = 0

    @property
    def ref(self) -> ModelRef:
        return self._ref

    def _record(
        self,
        request: TextRequest | ToolRequest,
        response: str | None,
        start: int,
        error: str = "connection refused",
    ) -> LLMCallRecord:
        ok = response is not None
        record = LLMCallRecord(
            call_id=request.call_id,
            role=request.role,
            model_ref=self._ref,
            adapter_kind=self._ref.kind,
            requested_model=self._ref.model_id,
            served_model_echo=self._ref.model_id if ok else None,
            request_id=f"{self._ref.kind}-{self.calls}" if ok else None,
            prompt_sha=sha256_text(request_content(request)),
            response_sha=sha256_text(response) if ok else None,
            usage=Usage(prompt_tokens=1, completion_tokens=max(1, len(response)))
            if ok
            else None,
            t_start=start,
            t_first_token=start + 1 if ok and response else None,
            t_end=self._clock.monotonic_ms(),
            finish_reason="stop" if ok else None,
            attempt=0,
            error=None if ok else error,
        )
        if self._on_record is not None:
            self._on_record(record)
        return record

    async def _next(self, request: TextRequest | ToolRequest) -> tuple[str, int]:
        start = self._clock.monotonic_ms()
        if self._hang_s:
            try:
                await asyncio.sleep(self._hang_s)
            except asyncio.CancelledError:
                self._record(request, None, start, "cancelled")
                raise
        if self._dead:
            record = self._record(request, None, start)
            raise LLMUnavailable("endpoint is dead", record)
        if self.calls >= len(self._responses):
            raise AssertionError("the script has no response left")
        self.calls += 1
        self._clock.advance(1)
        return self._responses[self.calls - 1], start

    async def stream_text(
        self, request: TextRequest
    ) -> AsyncIterator[str | LLMCallRecord]:
        text, start = await self._next(request)
        sent = 0
        try:
            for sent in range(CHUNK, len(text) + CHUNK, CHUNK):
                yield text[sent - CHUNK : sent]
        except (asyncio.CancelledError, GeneratorExit):
            self._record(request, text[:sent] or None, start, "cancelled")
            raise
        yield self._record(request, text, start)

    async def chat_tools(self, request: ToolRequest) -> ToolResponse:
        """A scripted response is ``{"text": ..., "tool_calls": [...]}`` JSON."""

        raw, start = await self._next(request)
        body = json.loads(raw)
        calls = tuple(ToolCall.model_validate(c) for c in body["tool_calls"])
        content = tool_response_content(body["text"], calls)
        return ToolResponse(
            text=body["text"],
            tool_calls=calls,
            record=self._record(request, content, start),
        )
