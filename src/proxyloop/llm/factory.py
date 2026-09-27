"""``make_client(ref)``: the one place a ``ModelRef`` becomes an ``LLMClient``.

``src/`` builds only ``real_http`` adapters. ``recorded_replay`` and
``test_fake`` clients exist only under ``tests/`` and are injected there. A
``baseline`` ref is the in-process FSM Fast, condition F (``models.fsm``, §0.2),
built only outside live mode. Live mode accepts ``real_http`` alone (I8).

``base_url`` points one client at another server root, for the dead-endpoint
smoke only (a real, unreachable address for one role, ``--fast-cp-base-url``).
The endpoint's variables are still read; its key is never sent there.
"""

from __future__ import annotations

import httpx

from proxyloop.contract.llm import AdapterKind, LLMClient, ModelRef
from proxyloop.llm.http import Clock, RecordSink
from proxyloop.llm.relay import ChatClient
from proxyloop.llm.vllm import VLLMClient
from proxyloop.models.fsm import FsmTalker


class LiveModeError(ValueError):
    """Live mode was asked for an adapter that is not ``real_http``."""


class Redirect(httpx.AsyncBaseTransport):
    """Sends every request to ``base_url``'s scheme, host and port (the path
    stays the endpoint's), without the ``Authorization`` header."""

    def __init__(
        self, base_url: str, inner: httpx.AsyncBaseTransport | None = None
    ) -> None:
        url = httpx.URL(base_url)
        if not url.host or url.path not in ("", "/") or url.query:
            raise ValueError("base_url must be a server root, scheme://host[:port]")
        self._url, self._inner = url, inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        to = self._url
        request.url = request.url.copy_with(
            scheme=to.scheme, host=to.host, port=to.port
        )
        request.headers["Host"] = request.url.netloc.decode("ascii")
        request.headers.pop("Authorization", None)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def make_client(
    ref: ModelRef,
    *,
    live: bool,
    clock: Clock,
    on_record: RecordSink,
    transport: httpx.AsyncBaseTransport | None = None,
    base_url: str | None = None,
) -> LLMClient:
    """``on_record`` receives every record the client produces (``llm.http``);
    ``transport`` is a test seam (httpx.MockTransport); ``base_url``: see above."""

    if ref.kind is AdapterKind.BASELINE and not live:
        return FsmTalker(ref, clock, on_record)
    if ref.kind is not AdapterKind.REAL_HTTP:
        if live:
            raise LiveModeError(f"live mode accepts only real_http, not {ref.kind}")
        raise ValueError(f"src/ builds only real_http and baseline, not {ref.kind}")
    if base_url is not None:
        transport = Redirect(base_url, transport)
    cls = VLLMClient if ref.endpoint == "vllm" else ChatClient
    return cls(ref, clock, on_record, transport)
