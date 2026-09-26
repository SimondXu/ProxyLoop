"""Hosted models over OpenAI-compatible ``/v1/chat/completions`` (ADR-0001, ADR-0005).

One class for both chat endpoints, ``relay`` (Slow, teacher, hosted Fast) and
``teamrouter`` (the world). Text streams; a tool call is one non-streamed
response. Structured output is a forced tool call: ``response_format`` is never
sent. Tool names and arguments pass through unrepaired; the caller validates.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from proxyloop.contract.llm import (
    ChatMessage,
    LLMCallRecord,
    TextRequest,
    ToolCall,
    ToolRequest,
    ToolResponse,
    tool_response_content,
)
from proxyloop.llm.http import HTTPAdapter, Json

PATH = "/v1/chat/completions"


def _message(m: ChatMessage) -> Json:
    if m.cache_breakpoint:  # no relay probe covers prompt caching yet
        raise ValueError("cache_breakpoint is not supported until llm-smoke probes it")
    out: Json = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["tool_calls"] = [
            {
                "id": c.call_id,
                "type": "function",
                "function": {"name": c.name, "arguments": c.arguments},
            }
            for c in m.tool_calls
        ]
    if m.tool_call_id is not None:
        out["tool_call_id"] = m.tool_call_id
    return out


def _delta_text(chunk: Json) -> str | None:
    choices: list[Json] = chunk.get("choices") or []
    deltas: list[Json] = [c.get("delta") or {} for c in choices]
    return "".join(d.get("content") or "" for d in deltas) or None


def _tools(body: Json) -> str:
    """A whole tool-call response as the content ``response_sha`` hashes."""

    message: Json = body["choices"][0]["message"]
    raw: list[Json] = message.get("tool_calls") or []
    calls = tuple(
        ToolCall(
            call_id=c["id"],
            name=c["function"]["name"],
            arguments=c["function"]["arguments"],
        )
        for c in raw
    )
    return tool_response_content(message.get("content") or "", calls)


class ChatClient(HTTPAdapter):
    ENDPOINTS = ("relay", "teamrouter")

    def _body(self, messages: tuple[ChatMessage, ...], max_tokens: int) -> Json:
        body: Json = {
            "model": self.ref.model_id,
            "messages": [_message(m) for m in messages],
            "max_tokens": max_tokens,
        }
        if self.ref.reasoning_effort is not None:
            body["reasoning_effort"] = self.ref.reasoning_effort
        return body

    def stream_text(self, request: TextRequest) -> AsyncIterator[str | LLMCallRecord]:
        if not request.messages:
            raise ValueError("a chat endpoint takes messages, not a prompt")
        body = self._body(request.messages, request.max_tokens)
        body |= {"temperature": request.temperature, "stream": True}
        body["stream_options"] = {"include_usage": True}
        if request.top_p != 1.0:
            body["top_p"] = request.top_p
        if request.seed is not None:
            body["seed"] = request.seed
        return self._call(request, PATH, body, _delta_text)

    async def chat_tools(self, request: ToolRequest) -> ToolResponse:
        body = self._body(request.messages, request.max_tokens)
        body["tools"] = [
            {"type": "function", "function": t.model_dump(mode="json")}
            for t in request.tools
        ]
        if request.tool_choice is not None:
            body["tool_choice"] = {
                "type": "function",
                "function": {"name": request.tool_choice},
            }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        *parts, record = [
            item async for item in self._call(request, PATH, body, _tools)
        ]
        assert isinstance(record, LLMCallRecord)
        content = json.loads("".join(str(p) for p in parts))
        calls = tuple(ToolCall.model_validate(c) for c in content["tool_calls"])
        return ToolResponse(text=content["text"], tool_calls=calls, record=record)
