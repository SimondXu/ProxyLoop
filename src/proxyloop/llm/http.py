"""What the HTTP adapters share: env resolution, one call attempt, the retry rule.

Every endpoint reads exactly two variables at client construction,
``PL_<ENDPOINT>_BASE_URL`` (the server root, without ``/v1``) and
``PL_<ENDPOINT>_API_KEY``. Neither value is ever logged or recorded.

Retry rule (AGENTS rules 6 and 12): at most one retry, only for a connection
failure (nothing was sent back, so no token exists), and only when the caller
gave ``on_retry``, which receives the failed attempt's record. Without it no
retry happens, so no record is ever dropped. Everything else raises
``LLMUnavailable`` at once.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Callable
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
ATTEMPTS: tuple[Literal[0, 1], ...] = (0, 1)


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
    done: bool = False

    def headers(self, resp: httpx.Response) -> None:
        self.request_id = resp.headers.get("x-request-id") or resp.headers.get(
            "request-id"
        )

    def body(self, chunk: Json) -> None:
        """The fields every OpenAI-compatible body or stream chunk may carry."""

        self.request_id = self.request_id or chunk.get("id")
        self.echo = self.echo or chunk.get("model")
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
                self.done = True

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
        on_retry: RecordSink | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if ref.endpoint not in self.ENDPOINTS:
            raise ValueError(f"{type(self).__name__} serves {self.ENDPOINTS}")
        self._ref, self._clock, self._on_retry = ref, clock, on_retry
        self._env = EndpointEnv.load(ref.endpoint)
        self._http = self._env.client(transport)

    @property
    def ref(self) -> ModelRef:
        return self._ref

    async def aclose(self) -> None:
        await self._http.aclose()

    def _fail(
        self, attempt: Attempt, text: str, exc: Exception | str
    ) -> LLMUnavailable:
        detail = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
        error = self._env.redact(detail)[:500]
        # Delivered text stays hashed, so a partial response keeps its provenance.
        record = attempt.record(self._clock(), text or None, error)
        return LLMUnavailable(f"{self._ref.model_id} unavailable: {error}", record)

    def _retry(self, attempt: Attempt, exc: Exception) -> bool:
        if not (
            attempt.attempt == 0
            and self._on_retry
            and isinstance(exc, CONNECTION_ERRORS)
        ):
            return False
        self._on_retry(self._fail(attempt, "", exc).record)
        return True

    async def _stream(
        self,
        request: TextRequest,
        path: str,
        body: Json,
        text_of: Callable[[Json], str | None],
    ) -> AsyncIterator[str | LLMCallRecord]:
        """POST a streamed call; yield text deltas, then the record."""

        for n in ATTEMPTS:
            attempt = Attempt(self._ref, request, n, self._clock())
            text: list[str] = []
            try:
                async with self._http.stream("POST", path, json=body) as resp:
                    attempt.headers(resp)
                    if resp.status_code != 200:
                        detail = (await resp.aread()).decode(errors="replace")[:300]
                        raise self._fail(
                            attempt, "", f"HTTP {resp.status_code}: {detail}"
                        )
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            attempt.done = True
                            continue
                        chunk: Json = json.loads(data)
                        if "error" in chunk:
                            raise self._fail(
                                attempt,
                                "".join(text),
                                f"stream error: {chunk['error']}",
                            )
                        attempt.body(chunk)
                        if delta := text_of(chunk):
                            if attempt.t_first_token is None:
                                attempt.t_first_token = self._clock()
                            text.append(delta)
                            yield delta
            except LLMUnavailable:
                raise
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                if self._retry(attempt, exc):
                    continue
                raise self._fail(attempt, "".join(text), exc) from exc
            if not attempt.done:
                raise self._fail(
                    attempt, "".join(text), "stream ended without finishing"
                )
            yield attempt.record(self._clock(), "".join(text))
            return

    async def _post(
        self, request: ToolRequest, path: str, body: Json
    ) -> tuple[Attempt, Json]:
        """POST a non-streamed call; return the attempt and the response body."""

        for n in ATTEMPTS:
            attempt = Attempt(self._ref, request, n, self._clock())
            try:
                resp = await self._http.post(path, json=body)
                attempt.headers(resp)
                if resp.status_code != 200:
                    detail = f"HTTP {resp.status_code}: {resp.text[:300]}"
                    raise self._fail(attempt, "", detail)
                data: Json = resp.json()
                attempt.body(data)
                return attempt, data
            except LLMUnavailable:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                if self._retry(attempt, exc):
                    continue
                raise self._fail(attempt, "", exc) from exc
        raise AssertionError("unreachable: the second attempt returns or raises")
