"""What the HTTP adapters share: env resolution, one call attempt, the retry rule.

Every endpoint reads exactly two variables at client construction,
``PL_<ENDPOINT>_BASE_URL`` (the server root, without ``/v1``) and
``PL_<ENDPOINT>_API_KEY``. Neither value is ever logged or recorded.

Records: every record an adapter produces goes to the ``on_record`` sink given at
construction (required, so none is ever lost): each failed attempt, each success,
and a cancelled or abandoned stream (``error="cancelled"``, the delivered text
hashed). The success record is also yielded or returned, per the contract.

Retry rule (AGENTS rules 6 and 12): at most one retry, only for a connection
failure before the first token. Everything else raises ``LLMUnavailable`` at once,
with its record; a malformed body is such a failure, never a raw exception.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from proxyloop.contract.base import sha256_text
from proxyloop.contract.llm import (
    Endpoint,
    LLMCallRecord,
    LLMUnavailable,
    ModelRef,
    TextRequest,
    ToolRequest,
    Usage,
    request_content,
)

Clock = Callable[[], int]  # ms on the session clock
RecordSink = Callable[[LLMCallRecord], None]
Json = dict[str, Any]
# A dead endpoint fails within 2 x the connect timeout (< 5 s, the acceptance bound).
TIMEOUT = httpx.Timeout(120.0, connect=2.0, pool=2.0)
CONNECTION_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)
# Everything an endpoint can do wrong; LookupError covers KeyError and IndexError.
FAILURES = (httpx.HTTPError, ValueError, LookupError, TypeError, AttributeError)
ATTEMPTS: tuple[Literal[0, 1], ...] = (0, 1)


class EndpointError(ValueError):
    """The endpoint answered, but not with a usable response."""


class LLMConfigError(RuntimeError):
    """A missing or malformed endpoint variable; names the variable, never its value."""


@dataclass(frozen=True)
class EndpointEnv:
    base_url: str = field(repr=False)
    api_key: str = field(repr=False)

    @classmethod
    def load(cls, endpoint: Endpoint) -> EndpointEnv:
        values: list[str] = []
        for suffix in ("BASE_URL", "API_KEY"):
            name = f"PL_{endpoint.upper()}_{suffix}"
            value = os.environ.get(name, "").strip()
            if not value:
                raise LLMConfigError(f"{name} is not set")
            values.append(value)
        base = values[0].rstrip("/")
        if base.endswith("/v1"):
            raise LLMConfigError(
                f"PL_{endpoint.upper()}_BASE_URL must be the server root, without /v1"
            )
        return cls(base, values[1])

    def redact(self, text: str) -> str:
        host = httpx.URL(self.base_url).host
        for secret in (self.api_key, self.base_url, host):
            if secret:
                text = text.replace(secret, "<redacted>")
        return text

    def client(self, transport: httpx.AsyncBaseTransport | None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=TIMEOUT,
            transport=transport,
        )


@dataclass
class Attempt:
    """One HTTP attempt, folded into its ``LLMCallRecord``."""

    ref: ModelRef
    request: TextRequest | ToolRequest
    attempt: Literal[0, 1]
    t_start: int
    t_first_token: int | None = None
    request_id: str | None = None
    echo: str | None = None
    usage: Usage | None = None
    finish_reason: str | None = None
    saw_done: bool = False  # the SSE "[DONE]" line

    def headers(self, resp: httpx.Response) -> None:
        self.request_id = resp.headers.get("x-request-id") or resp.headers.get(
            "request-id"
        )

    def body(self, chunk: Json) -> None:
        """The fields every OpenAI-compatible body or stream chunk may carry."""

        self.request_id = self.request_id or chunk.get("id")
        model = chunk.get("model")
        if self.echo and model and model != self.echo:
            raise EndpointError(f"echoed model changed mid-stream: {model!r}")
        self.echo = self.echo or model
        usage: Json | None = chunk.get("usage")
        if usage:
            details: Json = usage.get("completion_tokens_details") or {}
            self.usage = Usage(
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                reasoning_tokens=details.get("reasoning_tokens"),
            )
        choices: list[Json] = chunk.get("choices") or []
        for choice in choices:
            if reason := choice.get("finish_reason"):
                self.finish_reason = reason

    def complete(self) -> bool:
        """A stream finished: ``[DONE]``, or a finish reason and the usage chunk."""

        return self.saw_done or (self.finish_reason is not None and bool(self.usage))

    def record(
        self, t_end: int, response: str | None, error: str | None = None
    ) -> LLMCallRecord:
        return LLMCallRecord(
            call_id=self.request.call_id,
            role=self.request.role,
            model_ref=self.ref,
            adapter_kind=self.ref.kind,
            requested_model=self.ref.model_id,
            served_model_echo=self.echo,
            request_id=self.request_id,
            prompt_sha=sha256_text(request_content(self.request)),
            response_sha=None if response is None else sha256_text(response),
            usage=self.usage,
            t_start=self.t_start,
            t_first_token=self.t_first_token,
            t_end=t_end,
            finish_reason=None if error else self.finish_reason,
            attempt=self.attempt,
            error=error,
        )


class HTTPAdapter:
    """Base of the real_http adapters: owns the client, the clock and the retry."""

    ENDPOINTS: tuple[Endpoint, ...] = ()

    def __init__(
        self,
        ref: ModelRef,
        clock: Clock,
        on_record: RecordSink,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if ref.endpoint not in self.ENDPOINTS:
            raise ValueError(f"{type(self).__name__} serves {self.ENDPOINTS}")
        self._ref, self._clock, self._on_record = ref, clock, on_record
        self._env = EndpointEnv.load(ref.endpoint)
        self._http = self._env.client(transport)

    @property
    def ref(self) -> ModelRef:
        return self._ref

    async def aclose(self) -> None:
        await self._http.aclose()

    def _emit(self, attempt: Attempt, text: str, error: str | None) -> LLMCallRecord:
        """Close the attempt's record and hand it to the sink; a failure hashes
        only text actually delivered."""
        response = text if error is None else (text or None)
        record = attempt.record(self._clock(), response, error)
        self._on_record(record)
        return record

    async def _call(
        self,
        request: TextRequest | ToolRequest,
        path: str,
        body: Json,
        parse: Callable[[Json], str | None],
    ) -> AsyncIterator[str | LLMCallRecord]:
        """POST one call: yield its text (stream deltas, or a whole body's content
        from ``parse``), then its record."""

        streaming = bool(body.get("stream"))
        for n in ATTEMPTS:
            attempt = Attempt(self._ref, request, n, self._clock())
            text: list[str] = []
            try:
                async with self._http.stream("POST", path, json=body) as resp:
                    attempt.headers(resp)
                    if resp.status_code != 200:
                        detail = (await resp.aread()).decode(errors="replace")[:300]
                        raise EndpointError(f"HTTP {resp.status_code}: {detail}")
                    async with aclosing(_chunks(resp, attempt, streaming)) as chunks:
                        async for chunk in chunks:
                            attempt.body(chunk)
                            if delta := parse(chunk):
                                if attempt.t_first_token is None:
                                    attempt.t_first_token = self._clock()
                                text.append(delta)
                                yield delta
                if streaming and not attempt.complete():
                    raise EndpointError("stream ended without finishing")
            except FAILURES as exc:
                error = self._env.redact(f"{type(exc).__name__}: {exc}")[:500]
                record = self._emit(attempt, "".join(text), error)
                retry = attempt.t_first_token is None and n == 0
                if retry and isinstance(exc, CONNECTION_ERRORS):
                    continue
                message = f"{self._ref.model_id} unavailable: {error}"
                raise LLMUnavailable(message, record) from exc
            except (asyncio.CancelledError, GeneratorExit):
                self._emit(attempt, "".join(text), "cancelled")
                raise
            yield self._emit(attempt, "".join(text), None)
            return


async def _chunks(
    resp: httpx.Response, attempt: Attempt, streaming: bool
) -> AsyncGenerator[Json]:
    """The JSON chunks of an SSE stream, or the one body of a plain response."""

    if not streaming:
        yield json.loads(await resp.aread())
        return
    async for line in resp.aiter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            attempt.saw_done = True
            continue
        chunk: Json = json.loads(data)
        if "error" in chunk:
            raise EndpointError(f"stream error: {chunk['error']}")
        yield chunk
