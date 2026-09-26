"""The real_http adapters against the contract conformance kit and the retry rule."""

from __future__ import annotations

import asyncio
import socket
import time
from typing import Any

import httpx
import pytest
from tests.contract.llm_conformance import (
    assert_text_conformance,
    assert_tool_conformance,
    assert_unavailable,
    check_unavailable,
)
from tests.contract.samples import GEMINI, QWEN, SONNET
from tests.llm.wire import (
    KEY,
    BrokenStream,
    Recorder,
    chat_chunks,
    completion_chunks,
    counter_clock,
    set_env,
    sse,
    stream_response,
    tool_body,
)

from proxyloop.contract.base import sha256_text
from proxyloop.contract.llm import (
    AdapterKind,
    ChatMessage,
    LLMCallRecord,
    LLMClient,
    LLMUnavailable,
    ModelRef,
    TextRequest,
    ToolRequest,
    ToolSpec,
)
from proxyloop.llm.factory import LiveModeError, make_client
from proxyloop.llm.http import LLMConfigError
from proxyloop.llm.relay import ChatClient
from proxyloop.llm.vllm import VLLMClient

PROMPT = (
    "<|im_start|>system\nS<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
)
FAST = TextRequest(
    call_id="g1", role="fast_cp", prompt=PROMPT, max_tokens=160, temperature=0.3
)
HOSTED = TextRequest(
    call_id="g2",
    role="fast_user",
    messages=(
        ChatMessage(role="system", content="S"),
        ChatMessage(role="user", content="U"),
    ),
    max_tokens=160,
    temperature=0.3,
    top_p=0.9,
)
CLASSIFY = ToolSpec(
    name="classify",
    description="Classify the utterance.",
    parameters={"type": "object", "properties": {"act": {"type": "string"}}},
)
TOOLS = ToolRequest(
    call_id="s1",
    role="slow",
    messages=(ChatMessage(role="user", content="Rep: we can offer $10 off."),),
    tools=(CLASSIFY,),
    tool_choice="classify",
    max_tokens=256,
)


def client(
    monkeypatch: Any,
    ref: ModelRef,
    recorder: Recorder | None = None,
    retries: list[LLMCallRecord] | None = None,
) -> LLMClient:
    assert ref.endpoint is not None
    set_env(monkeypatch, ref.endpoint)
    return make_client(
        ref,
        live=True,
        clock=counter_clock(),
        on_retry=None if retries is None else retries.append,
        transport=recorder.transport() if recorder else None,
    )


async def drain(
    llm: LLMClient, request: TextRequest
) -> tuple[list[object], BaseException]:
    delivered: list[object] = []
    with pytest.raises(LLMUnavailable) as caught:
        async for item in llm.stream_text(request):
            delivered.append(item)
    return delivered, caught.value


def test_vllm_stream_conforms_and_sends_the_prompt(monkeypatch: Any) -> None:
    body = sse(*completion_chunks(QWEN, ["Hello", " there."]))
    wire = Recorder(stream_response(body))
    record = asyncio.run(assert_text_conformance(client(monkeypatch, QWEN, wire), FAST))
    sent = wire.body()
    assert wire.requests[0].url.path == "/v1/completions"
    assert wire.requests[0].headers["authorization"] == f"Bearer {KEY}"
    assert sent["prompt"] == PROMPT and sent["model"] == "Qwen3.5-9B"
    assert sent["stream_options"] == {"include_usage": True}
    assert (record.request_id, record.finish_reason, record.attempt) == (
        "cmpl-3f9c",
        "stop",
        0,
    )
    assert record.t_start < record.t_first_token < record.t_end  # type: ignore[operator]


def test_request_id_header_wins(monkeypatch: Any) -> None:
    body = sse(*completion_chunks(QWEN, ["Hi."]))
    wire = Recorder(stream_response(body, **{"x-request-id": "req_hdr"}))
    record = asyncio.run(assert_text_conformance(client(monkeypatch, QWEN, wire), FAST))
    assert record.request_id == "req_hdr"


@pytest.mark.parametrize("ref", [SONNET, GEMINI], ids=["relay", "teamrouter"])
def test_hosted_fast_stream_conforms(monkeypatch: Any, ref: ModelRef) -> None:
    wire = Recorder(stream_response(sse(*chat_chunks(ref, ["Sure", ", one moment."]))))
    record = asyncio.run(
        assert_text_conformance(client(monkeypatch, ref, wire), HOSTED)
    )
    sent = wire.body()
    assert wire.requests[0].url.path == "/v1/chat/completions"
    assert sent["messages"] == [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "U"},
    ]
    assert sent["top_p"] == 0.9 and "response_format" not in sent
    assert sent.get("reasoning_effort") == ref.reasoning_effort
    assert record.usage is not None and record.usage.reasoning_tokens == 4


def test_forced_tool_call_conforms_and_passes_arguments_through(
    monkeypatch: Any,
) -> None:
    raw = '{"act": "offer", "amount_usd": 60'  # malformed JSON: never repaired here
    wire = Recorder(
        httpx.Response(
            200, json=tool_body(SONNET, raw), headers={"request-id": "req_011"}
        )
    )
    response = asyncio.run(
        assert_tool_conformance(client(monkeypatch, SONNET, wire), TOOLS)
    )
    sent = wire.body()
    assert sent["tool_choice"] == {"type": "function", "function": {"name": "classify"}}
    assert sent["tools"][0]["function"]["name"] == "classify"
    assert "response_format" not in sent and "stream" not in sent
    assert response.tool_calls[0].arguments == raw
    assert response.record.request_id == "req_011"
    assert response.record.finish_reason == "tool_calls"


def test_dead_url_raises_within_5s(monkeypatch: Any) -> None:
    with socket.socket() as sock:  # a real closed port: connection refused
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    set_env(monkeypatch, "vllm", f"http://127.0.0.1:{port}")
    retries: list[LLMCallRecord] = []
    llm = make_client(QWEN, live=True, clock=counter_clock(), on_retry=retries.append)
    start = time.monotonic()
    asyncio.run(assert_unavailable(llm, FAST))
    assert time.monotonic() - start < 5
    assert [r.attempt for r in retries] == [0] and retries[0].error


def test_one_retry_before_the_first_token_is_recorded(monkeypatch: Any) -> None:
    body = sse(*completion_chunks(QWEN, ["Hello."]))
    wire = Recorder(httpx.ConnectError("refused"), stream_response(body))
    retries: list[LLMCallRecord] = []
    record = asyncio.run(
        assert_text_conformance(client(monkeypatch, QWEN, wire, retries), FAST)
    )
    assert record.attempt == 1 and len(wire.requests) == 2
    (failed,) = retries
    assert failed.attempt == 0 and failed.response_sha is None
    assert failed.error is not None and "ConnectError" in failed.error


def test_second_connection_failure_raises(monkeypatch: Any) -> None:
    wire = Recorder(httpx.ConnectError("refused"), httpx.ConnectTimeout("timeout"))
    retries: list[LLMCallRecord] = []
    delivered, error = asyncio.run(
        drain(client(monkeypatch, QWEN, wire, retries), FAST)
    )
    assert isinstance(error, LLMUnavailable)
    check_unavailable(error, delivered)
    assert error.record.attempt == 1 and len(retries) == 1


def test_no_retry_without_a_record_sink(monkeypatch: Any) -> None:
    wire = Recorder(httpx.ConnectError("refused"))
    delivered, error = asyncio.run(drain(client(monkeypatch, QWEN, wire), FAST))
    assert isinstance(error, LLMUnavailable) and not delivered
    assert error.record.attempt == 0 and len(wire.requests) == 1


def test_no_retry_after_the_first_token(monkeypatch: Any) -> None:
    first = sse(*completion_chunks(QWEN, ["Hello", "!"])[:1], done=False)
    wire = Recorder(httpx.Response(200, stream=BrokenStream(first)))
    retries: list[LLMCallRecord] = []
    delivered, error = asyncio.run(
        drain(client(monkeypatch, QWEN, wire, retries), FAST)
    )
    assert isinstance(error, LLMUnavailable)
    assert delivered == ["Hello"] and not retries and len(wire.requests) == 1
    assert error.record.error and "ReadError" in error.record.error
    assert error.record.response_sha == sha256_text("Hello")  # what was delivered


@pytest.mark.parametrize(
    ("response", "detail"),
    [
        (httpx.Response(503, text="model_not_found"), "HTTP 503"),
        (stream_response(sse({"error": {"message": "overloaded"}})), "stream error"),
        (
            stream_response(sse(*completion_chunks(QWEN, ["Hi", "!"])[:1], done=False)),
            "without finishing",
        ),
    ],
)
def test_endpoint_failures_raise_without_retry(
    monkeypatch: Any, response: httpx.Response, detail: str
) -> None:
    wire = Recorder(response)
    retries: list[LLMCallRecord] = []
    _, error = asyncio.run(drain(client(monkeypatch, QWEN, wire, retries), FAST))
    assert isinstance(error, LLMUnavailable)
    assert error.record.error and detail in error.record.error
    assert not retries and len(wire.requests) == 1


def test_malformed_tool_envelope_raises(monkeypatch: Any) -> None:
    wire = Recorder(
        httpx.Response(200, json={"id": "msg_02", "model": "claude-sonnet-5"})
    )
    with pytest.raises(LLMUnavailable) as caught:
        asyncio.run(client(monkeypatch, SONNET, wire).chat_tools(TOOLS))
    assert caught.value.record.error and caught.value.record.response_sha is None


def test_errors_never_carry_the_key_or_host(monkeypatch: Any) -> None:
    echo = f"bad key {KEY} for https://vllm.test/v1"
    wire = Recorder(httpx.Response(401, text=echo))
    _, error = asyncio.run(drain(client(monkeypatch, QWEN, wire), FAST))
    for text in (str(error), error.record.model_dump_json()):  # type: ignore[union-attr]
        assert KEY not in text and "vllm.test" not in text


def test_env_errors_name_the_variable_not_the_value(monkeypatch: Any) -> None:
    monkeypatch.delenv("PL_RELAY_BASE_URL", raising=False)
    monkeypatch.setenv("PL_RELAY_API_KEY", KEY)
    with pytest.raises(LLMConfigError, match="PL_RELAY_BASE_URL is not set"):
        make_client(SONNET, live=True, clock=counter_clock())
    monkeypatch.setenv("PL_RELAY_BASE_URL", "https://relay.test/v1")
    with pytest.raises(LLMConfigError, match="without /v1") as caught:
        make_client(SONNET, live=True, clock=counter_clock())
    assert "relay.test" not in str(caught.value)


@pytest.mark.parametrize(
    "kind", [AdapterKind.RECORDED_REPLAY, AdapterKind.TEST_FAKE, AdapterKind.BASELINE]
)
def test_live_mode_rejects_non_real_http(kind: AdapterKind) -> None:
    endpoint = None if kind is AdapterKind.BASELINE else "vllm"
    ref = ModelRef(kind=kind, endpoint=endpoint, model_id="Qwen3.5-9B")
    with pytest.raises(LiveModeError):
        make_client(ref, live=True, clock=counter_clock())
    with pytest.raises(ValueError, match="only real_http"):
        make_client(ref, live=False, clock=counter_clock())


def test_factory_picks_the_adapter_by_endpoint(monkeypatch: Any) -> None:
    assert isinstance(client(monkeypatch, QWEN), VLLMClient)
    assert isinstance(client(monkeypatch, SONNET), ChatClient)
    assert isinstance(client(monkeypatch, GEMINI), ChatClient)


def test_wrong_input_shapes_are_refused(monkeypatch: Any) -> None:
    fast, hosted = client(monkeypatch, QWEN), client(monkeypatch, SONNET)
    with pytest.raises(ValueError, match="pre-rendered prompt"):
        fast.stream_text(HOSTED)
    with pytest.raises(ValueError, match="messages"):
        hosted.stream_text(FAST)
    with pytest.raises(TypeError):
        asyncio.run(fast.chat_tools(TOOLS))
    cached = TOOLS.model_copy(
        update={
            "messages": (ChatMessage(role="user", content="x", cache_breakpoint=True),)
        }
    )
    with pytest.raises(ValueError, match="cache_breakpoint"):
        asyncio.run(hosted.chat_tools(cached))
