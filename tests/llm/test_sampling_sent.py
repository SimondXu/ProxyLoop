"""S1-CON-05 (ADR-0019): each call's record says which sampling reached the HTTP
body, and a chat model that ignores sampling (OpenRouter's cited list) gets none."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from tests.contract.llm_conformance import assert_text_conformance
from tests.contract.samples import QWEN, SONNET
from tests.llm.test_adapters import FAST, HOSTED, LUNA, TOOLS, client
from tests.llm.wire import (
    Recorder,
    chat_chunks,
    completion_chunks,
    sse,
    stream_response,
    tool_body,
)

from proxyloop.contract.llm import LLMCallRecord, LLMUnavailable

SAMPLING = ("temperature", "top_p", "seed")


def sent_sampling(wire: Recorder) -> dict[str, Any]:
    return {k: v for k, v in wire.body().items() if k in SAMPLING}


def test_vllm_records_the_sampling_it_sends(monkeypatch: Any) -> None:
    wire = Recorder(stream_response(sse(*completion_chunks(QWEN, ["Hi."]))))
    record = asyncio.run(assert_text_conformance(client(monkeypatch, QWEN, wire), FAST))
    assert sent_sampling(wire) == {"temperature": 0.3, "top_p": 1.0}
    assert record.sampling_sent == sent_sampling(wire)


def test_a_listed_model_gets_no_temperature_or_top_p(monkeypatch: Any) -> None:
    wire = Recorder(stream_response(sse(*chat_chunks(LUNA, ["Please hold."]))))
    request = HOSTED.model_copy(update={"seed": 7})
    record = asyncio.run(
        assert_text_conformance(client(monkeypatch, LUNA, wire), request)
    )
    assert sent_sampling(wire) == {"seed": 7}  # seed is not on the cited list
    assert record.sampling_sent == {"seed": 7}


def test_a_listed_model_records_provider_default(monkeypatch: Any) -> None:
    wire = Recorder(stream_response(sse(*chat_chunks(LUNA, ["Please hold."]))))
    record = asyncio.run(
        assert_text_conformance(client(monkeypatch, LUNA, wire), HOSTED)
    )
    assert sent_sampling(wire) == {}
    assert record.sampling_sent is None


def test_an_unlisted_model_is_unchanged_and_recorded(monkeypatch: Any) -> None:
    wire = Recorder(stream_response(sse(*chat_chunks(SONNET, ["Sure."]))))
    record = asyncio.run(
        assert_text_conformance(client(monkeypatch, SONNET, wire), HOSTED)
    )
    assert sent_sampling(wire) == {"temperature": 0.3, "top_p": 0.9}
    assert record.sampling_sent == {"temperature": 0.3, "top_p": 0.9}


@pytest.mark.parametrize(
    ("temperature", "expected"), [(None, None), (0.2, {"temperature": 0.2})]
)
def test_tool_calls_record_only_what_was_requested(
    monkeypatch: Any, temperature: float | None, expected: dict[str, float] | None
) -> None:
    wire = Recorder(httpx.Response(200, json=tool_body(SONNET, '{"act": "offer"}')))
    request = TOOLS.model_copy(update={"temperature": temperature})
    response = asyncio.run(client(monkeypatch, SONNET, wire).chat_tools(request))
    assert (sent_sampling(wire) or None) == expected
    assert response.record.sampling_sent == expected


def test_a_listed_model_tool_call_drops_temperature(monkeypatch: Any) -> None:
    wire = Recorder(httpx.Response(200, json=tool_body(LUNA, '{"act": "offer"}')))
    request = TOOLS.model_copy(update={"temperature": 0.2})
    response = asyncio.run(client(monkeypatch, LUNA, wire).chat_tools(request))
    assert sent_sampling(wire) == {}
    assert response.record.sampling_sent is None


def test_a_failed_attempt_records_what_it_sent(monkeypatch: Any) -> None:
    records: list[LLMCallRecord] = []
    wire = Recorder(httpx.Response(500, text="boom"))
    llm = client(monkeypatch, SONNET, wire, records)
    request = TOOLS.model_copy(update={"temperature": 0.2})
    with pytest.raises(LLMUnavailable) as caught:
        asyncio.run(llm.chat_tools(request))
    assert len(wire.requests) == 1  # no retry on an HTTP error
    assert (
        caught.value.record.sampling_sent == {"temperature": 0.2} == sent_sampling(wire)
    )
    assert records == [caught.value.record]
