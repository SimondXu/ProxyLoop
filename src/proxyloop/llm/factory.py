"""``make_client(ref)``: the one place a ``ModelRef`` becomes an ``LLMClient``.

``src/`` builds only ``real_http`` adapters. ``recorded_replay`` and
``test_fake`` clients exist only under ``tests/`` and are injected there; the
``baseline`` FSM arrives with the MOD model registry (S1-MOD-01). Live mode
accepts ``real_http`` alone (I8).
"""

from __future__ import annotations

import httpx

from proxyloop.contract.llm import AdapterKind, LLMClient, ModelRef
from proxyloop.llm.http import Clock, RecordSink
from proxyloop.llm.relay import ChatClient
from proxyloop.llm.vllm import VLLMClient


class LiveModeError(ValueError):
    """Live mode was asked for an adapter that is not ``real_http``."""


def make_client(
    ref: ModelRef,
    *,
    live: bool,
    clock: Clock,
    on_retry: RecordSink | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> LLMClient:
    """``on_retry`` enables the one connection retry and receives the failed
    attempt's record; ``transport`` is a test seam (httpx.MockTransport)."""

    if ref.kind is not AdapterKind.REAL_HTTP:
        if live:
            raise LiveModeError(f"live mode accepts only real_http, not {ref.kind}")
        raise ValueError(f"src/ builds only real_http adapters, not {ref.kind}")
    cls = VLLMClient if ref.endpoint == "vllm" else ChatClient
    return cls(ref, clock, on_retry, transport)
