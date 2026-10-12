"""Claude over Anthropic's native ``/v1/messages`` (ADR-0027): Slow on
``claude-sonnet-5-5``, billed to the user's monthly API credit.

Tool calls only: one non-streamed response per call; ``stream_text`` is not
served. Leading system messages become the ``system`` field; a later one stays a
``system`` message. An assistant turn's tool calls become ``tool_use`` blocks and
each ``tool`` message a ``tool_result`` block of the following user turn. Thinking
blocks are never replayed: ``ChatMessage`` carries none, and Slow's context is
windowed, so a replayed block could not pass the history-editing check. Empty
turns and whitespace-only text are not sent; adjacent same-role turns merge.

Effort: ``none`` is ``thinking: between_tools`` (Sonnet 5.5's lowest setting);
``low``, ``medium`` and ``high`` are adaptive thinking at that effort; ``minimal``
has no counterpart and is refused. ``tool_choice`` and sampling pass through as
asked: Sonnet 5.5 answers a forced tool or a non-default temperature with a 400,
which is ``LLMUnavailable``, never a quietly relaxed request. No ``fallbacks``
parameter is ever sent (AGENTS rule 6).

Prompt caching: one breakpoint, at the end of the system prompt (tools and system
are the stable prefix). Slow's history cannot be cached: the newest message is
stubbed once it is history and the window slides, so a breakpoint on it was a
cache write every step and never a read (measured on run 4b9901, 2026-10-11).
``prompt_tokens`` is the whole input; ``cache_read_tokens`` and
``cache_write_tokens`` are its cached parts.
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
    Usage,
    tool_response_content,
)
from proxyloop.llm.http import Attempt, EndpointError, HTTPAdapter, Json

PATH = "/v1/messages"
VERSION = "2023-06-01"


class MessagesAttempt(Attempt):
    def body(self, chunk: Json) -> None:
        """The fields of a Messages API response."""

        self.request_id = self.request_id or chunk.get("id")
        self.echo = self.echo or chunk.get("model")
        usage: Json | None = chunk.get("usage")
        if usage:
            read = usage.get("cache_read_input_tokens") or 0
            write = usage.get("cache_creation_input_tokens") or 0
            self.usage = Usage(
                prompt_tokens=usage["input_tokens"] + read + write,
                completion_tokens=usage["output_tokens"],
                cache_read_tokens=read,
                cache_write_tokens=write,
            )
        if reason := chunk.get("stop_reason"):
            self.finish_reason = reason


def _messages(messages: tuple[ChatMessage, ...]) -> tuple[str, list[Json]]:
    """The ``system`` text and the Messages API turns, strictly alternating:
    adjacent same-role turns (tool results, then a note after a refusal) are
    merged into one turn of blocks, in order."""

    system: list[str] = []
    turns: list[Json] = []
    for m in messages:
        if m.cache_breakpoint:  # the request-level breakpoint covers Slow
            raise ValueError("cache_breakpoint is not supported on this endpoint")
        text: list[Json] = (
            [{"type": "text", "text": m.content}] if m.content.strip() else []
        )
        if m.role == "system" and not turns:
            system.append(m.content)
            continue
        if m.role == "assistant":
            role, blocks = (
                "assistant",
                text
                + [
                    {
                        "type": "tool_use",
                        "id": c.call_id,
                        "name": c.name,
                        "input": json.loads(c.arguments),
                    }
                    for c in m.tool_calls
                ],
            )
        elif m.role == "tool":
            result = {"type": "tool_result", "tool_use_id": m.tool_call_id}
            role, blocks = "user", [result | {"content": m.content}]
        elif m.role == "system":  # after the first turn: its own operator message
            if text:
                turns.append({"role": "system", "content": m.content})
            continue
        else:
            role, blocks = "user", text
        if not blocks:  # a turn that said nothing is not sent (a refusal)
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += blocks
        else:
            turns.append({"role": role, "content": blocks})
    return "\n\n".join(system), turns


def _tools(body: Json) -> str:
    """A whole response as the content ``response_sha`` hashes."""

    if not body.get("stop_reason"):
        raise EndpointError("response without a stop_reason")
    blocks: list[Json] = body["content"]
    text = "".join(b["text"] for b in blocks if b["type"] == "text")
    calls = tuple(
        ToolCall(
            call_id=b["id"],
            name=b["name"],
            arguments=json.dumps(b["input"], ensure_ascii=False),
        )
        for b in blocks
        if b["type"] == "tool_use"
    )
    return tool_response_content(text, calls)


class AnthropicClient(HTTPAdapter):
    ENDPOINTS = ("anthropic",)
    ATTEMPT = MessagesAttempt

    def _auth(self, api_key: str) -> dict[str, str]:
        return {"x-api-key": api_key, "anthropic-version": VERSION}

    def _effort(self, body: Json) -> None:
        effort = self.ref.reasoning_effort
        if effort is None:
            return
        if effort == "minimal":
            raise ValueError("the anthropic endpoint has no 'minimal' effort")
        if effort == "none":
            body["thinking"] = {"type": "between_tools"}
        else:
            body["thinking"] = {"type": "adaptive"}
            body["output_config"] = {"effort": effort}

    def stream_text(self, request: TextRequest) -> AsyncIterator[str | LLMCallRecord]:
        raise ValueError("the anthropic endpoint serves tool calls only (ADR-0027)")

    async def chat_tools(self, request: ToolRequest) -> ToolResponse:
        system, turns = _messages(request.messages)
        body: Json = {
            "model": self.ref.model_id,
            "max_tokens": request.max_tokens,
            "messages": turns,
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in request.tools
            ],
        }
        if system:  # the one breakpoint: the history after it changes every step
            body["system"] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        if request.tool_choice is not None:
            body["tool_choice"] = {"type": "tool", "name": request.tool_choice}
        if request.temperature is not None:
            body["temperature"] = request.temperature
        self._effort(body)
        *parts, record = [
            item async for item in self._call(request, PATH, body, _tools)
        ]
        assert isinstance(record, LLMCallRecord)
        content = json.loads("".join(str(p) for p in parts))
        calls = tuple(ToolCall.model_validate(c) for c in content["tool_calls"])
        return ToolResponse(text=content["text"], tool_calls=calls, record=record)
