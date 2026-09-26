"""OpenAI-compatible wire fixtures for the adapter tests (httpx.MockTransport).

Shapes follow the vLLM 0.29 ``/v1/completions`` stream and the relay's
``/v1/chat/completions`` responses as recorded in ADR-0001/ADR-0002 probes.
Transport-level test doubles only: the adapters under test are the real ones.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx

from proxyloop.contract.llm import ModelRef

Json = dict[str, Any]
Handler = Callable[[httpx.Request], httpx.Response]
KEY = "sk-test-secret-0123456789"
HOSTS = {"vllm": "vllm.test", "relay": "relay.test", "teamrouter": "tr.test"}


def set_env(monkeypatch: Any, endpoint: str, base: str | None = None) -> None:
    prefix = f"PL_{endpoint.upper()}_"
    monkeypatch.setenv(prefix + "BASE_URL", base or f"https://{HOSTS[endpoint]}")
    monkeypatch.setenv(prefix + "API_KEY", KEY)


def counter_clock() -> Callable[[], int]:
    ticks = itertools.count(1000, 10)
    return lambda: next(ticks)


def sse(*chunks: Json, done: bool = True) -> bytes:
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks]
    return "".join([*lines, "data: [DONE]\n\n" if done else ""]).encode()


def completion_chunks(ref: ModelRef, texts: list[str]) -> list[Json]:
    rid, model = "cmpl-3f9c", ref.model_id
    out: list[Json] = [
        {"id": rid, "model": model, "choices": [{"index": 0, "text": t}]} for t in texts
    ]
    out[-1]["choices"][0]["finish_reason"] = "stop"
    usage = {"prompt_tokens": 12, "completion_tokens": len(texts)}
    return [*out, {"id": rid, "model": model, "choices": [], "usage": usage}]


def chat_chunks(ref: ModelRef, texts: list[str]) -> list[Json]:
    rid, model = "chatcmpl-77a1", ref.model_id
    out: list[Json] = [
        {"id": rid, "model": model, "choices": [{"index": 0, "delta": {"content": t}}]}
        for t in texts
    ]
    out[-1]["choices"][0]["finish_reason"] = "stop"
    usage = {
        "prompt_tokens": 40,
        "completion_tokens": 9,
        "completion_tokens_details": {"reasoning_tokens": 4},
    }
    return [*out, {"id": rid, "model": model, "choices": [], "usage": usage}]


def tool_body(ref: ModelRef, arguments: str) -> Json:
    call = {
        "id": "toolu_01",
        "type": "function",
        "function": {"name": "classify", "arguments": arguments},
    }
    message = {"role": "assistant", "content": None, "tool_calls": [call]}
    return {
        "id": "msg_01",
        "model": ref.model_id,
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 310, "completion_tokens": 25},
    }


def stream_response(body: bytes, **headers: str) -> httpx.Response:
    return httpx.Response(
        200, content=body, headers={"content-type": "text/event-stream", **headers}
    )


class BrokenStream(httpx.AsyncByteStream):
    """Delivers ``first``, then fails with ``error`` (or stalls, if ``None``)."""

    def __init__(self, first: bytes, error: Exception | None) -> None:
        self.first, self.error = first, error

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.first
        if self.error is None:
            await asyncio.Event().wait()  # never set: a stalled endpoint
        raise self.error or AssertionError("unreachable")


class Recorder:
    """A MockTransport handler that replays ``responses`` in order and keeps
    every request it saw; an exception in ``responses`` is raised instead."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def body(self, index: int = 0) -> Json:
        data: Json = json.loads(self.requests[index].content)
        return data
