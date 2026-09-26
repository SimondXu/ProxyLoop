"""The real_http adapters against the contract conformance kit and the retry rule."""

from __future__ import annotations

import asyncio
import socket
import time
from collections.abc import AsyncGenerator
from typing import Any, cast

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
    records: list[LLMCallRecord] | None = None,
) -> LLMClient:
    assert ref.endpoint is not None
    set_env(monkeypatch, ref.endpoint)
    sink = [] if records is None else records
    return make_client(
        ref,
        live=True,
        clock=counter_clock(),
        on_record=sink.append,
        transport=recorder.transport() if recorder else None,
    )


async def drain(
    llm: LLMClient, request: TextRequest
) -> tuple[list[object], LLMUnavailable]:
    delivered: list[object] = []
    with pytest.raises(LLMUnavailable) as caught:
        async for item in llm.stream_text(request):
            delivered.append(item)
    return delivered, caught.value


def fails(monkeypatch: Any, ref: ModelRef, *responses: Any) -> list[LLMCallRecord]:
    """Run FAST (or TOOLS on a chat ref): it must raise LLMUnavailable with its
    record, which is also the sink's last record."""
    records: list[LLMCallRecord] = []
    llm = client(monkeypatch, ref, Recorder(*responses), records)

    async def run() -> LLMUnavailable:
        if ref.endpoint == "vllm":
            delivered, error = await drain(llm, FAST)
            if delivered:  # delivered text is hashed, never dropped
                text = "".join(str(d) for d in delivered)
                assert error.record.response_sha == sha256_text(text)
            else:
                check_unavailable(error, delivered)
            return error
        with pytest.raises(LLMUnavailable) as caught:
            await llm.chat_tools(TOOLS)
        return caught.value

    error = asyncio.run(run())
    assert error.record.error and error.record == records[-1]
    return records


def test_vllm_stream_conforms_and_sends_the_prompt(monkeypatch: Any) -> None:
    body = sse(*completion_chunks(QWEN, ["Hello", " there."]))
    wire = Recorder(stream_response(body))
    records: list[LLMCallRecord] = []
    llm = client(monkeypatch, QWEN, wire, records)
    record = asyncio.run(assert_text_conformance(llm, FAST))
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
    assert record.t_first_token is not None
    assert record.t_start < record.t_first_token < record.t_end
    assert records == [record]  # the sink sees every record


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
    body = tool_body(SONNET, raw)
    wire = Recorder(httpx.Response(200, json=body, headers={"request-id": "req_011"}))
    llm = client(monkeypatch, SONNET, wire)
    response = asyncio.run(assert_tool_conformance(llm, TOOLS))
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
    records: list[LLMCallRecord] = []
    llm = make_client(QWEN, live=True, clock=counter_clock(), on_record=records.append)
    start = time.monotonic()
    asyncio.run(assert_unavailable(llm, FAST))
    assert time.monotonic() - start < 5
    assert [r.attempt for r in records] == [0, 1]
    assert all(r.error and "127.0.0.1" not in r.error for r in records)


def test_one_retry_before_the_first_token_is_recorded(monkeypatch: Any) -> None:
    body = sse(*completion_chunks(QWEN, ["Hello."]))
    wire = Recorder(httpx.ConnectError("refused"), stream_response(body))
    records: list[LLMCallRecord] = []
    llm = client(monkeypatch, QWEN, wire, records)
    record = asyncio.run(assert_text_conformance(llm, FAST))
    assert record.attempt == 1 and len(wire.requests) == 2
    failed, succeeded = records
    assert succeeded == record
    assert failed.attempt == 0 and failed.response_sha is None
    assert failed.error is not None and "ConnectError" in failed.error


def test_second_connection_failure_raises(monkeypatch: Any) -> None:
    records = fails(
        monkeypatch, QWEN, httpx.ConnectError("refused"), httpx.ConnectTimeout("t/o")
    )
    assert [r.attempt for r in records] == [0, 1]


def test_no_retry_after_the_first_token(monkeypatch: Any) -> None:
    """Even a connection-class error is not retried once a token was delivered."""
    first = sse(*completion_chunks(QWEN, ["Hello", "!"])[:1], done=False)
    stream = BrokenStream(first, httpx.ConnectError("reset"))
    wire = Recorder(httpx.Response(200, stream=stream))
    records: list[LLMCallRecord] = []
    delivered, error = asyncio.run(
        drain(client(monkeypatch, QWEN, wire, records), FAST)
    )
    assert delivered == ["Hello"] and records == [error.record]
    assert len(wire.requests) == 1
    assert error.record.error and "ConnectError" in error.record.error
    assert error.record.response_sha == sha256_text("Hello")  # what was delivered


FINISHED_NO_USAGE = completion_chunks(QWEN, ["Hi."])[:1]


@pytest.mark.parametrize(
    ("response", "detail"),
    [
        (httpx.Response(503, text="model_not_found"), "HTTP 503"),
        (stream_response(sse({"error": {"message": "overloaded"}})), "stream error"),
        (
            stream_response(sse(*completion_chunks(QWEN, ["Hi", "!"])[:1], done=False)),
            "without finishing",
        ),
        (stream_response(sse(*FINISHED_NO_USAGE, done=False)), "without finishing"),
    ],
    ids=["http-503", "error-chunk", "no-finish", "finish-without-usage-or-done"],
)
def test_endpoint_failures_raise_without_retry(
    monkeypatch: Any, response: httpx.Response, detail: str
) -> None:
    (record,) = fails(monkeypatch, QWEN, response)
    assert record.error and detail in record.error


def test_finish_and_usage_without_done_succeed(monkeypatch: Any) -> None:
    body = sse(*completion_chunks(QWEN, ["Hi."]), done=False)
    llm = client(monkeypatch, QWEN, Recorder(stream_response(body)))
    asyncio.run(assert_text_conformance(llm, FAST))


def test_echoed_model_change_mid_stream_is_an_error(monkeypatch: Any) -> None:
    chunks = completion_chunks(QWEN, ["Hello", " there."])
    chunks[1]["model"] = "Qwen3.5-9B-live"
    (record,) = fails(monkeypatch, QWEN, stream_response(sse(*chunks)))
    assert record.error and "echoed model changed" in record.error


def _stream(*lines: str) -> httpx.Response:
    return stream_response("".join(f"data: {x}\n\n" for x in lines).encode())


def _tool(message: object, **update: object) -> httpx.Response:
    body: dict[str, Any] = {**tool_body(SONNET, "{}"), **update}
    if message is not None:
        body["choices"][0]["message"] = message
    return httpx.Response(200, json=body)


@pytest.mark.parametrize(
    ("ref", "response"),
    [
        (QWEN, _stream('{"id": "c1", "choices": [{"text": "Hi"')),  # not JSON
        (QWEN, _stream("[1, 2]")),  # a list, not an object
        (QWEN, _stream('{"id": "c1", "choices": "oops"}')),  # choices not a list
        (QWEN, _stream('{"id": "c1", "choices": [], "usage": {"prompt_tokens": 1}}')),
        (
            QWEN,
            _stream(
                '{"choices": [], "usage": {"prompt_tokens": -1, '
                '"completion_tokens": 1}}'
            ),
        ),
        (SONNET, httpx.Response(200, text="<html>bad gateway</html>")),
        (SONNET, _tool(None, choices=[])),
        (SONNET, _tool({"tool_calls": [{"id": "t1", "function": {"name": "x"}}]})),
        (
            SONNET,
            _tool(
                {
                    "tool_calls": [
                        {
                            "id": "t1",
                            "function": {"name": "classify", "arguments": None},
                        }
                    ]
                }
            ),
        ),
        (SONNET, _tool("not an object")),
    ],
    ids=[
        "sse-not-json",
        "sse-list",
        "sse-choices-str",
        "sse-usage-missing-key",
        "sse-usage-negative",
        "tool-not-json",
        "tool-no-choices",
        "tool-call-no-arguments",
        "tool-call-null-arguments",
        "tool-message-str",
    ],
)
def test_malformed_bodies_raise_llm_unavailable_with_a_record(
    monkeypatch: Any, ref: ModelRef, response: httpx.Response
) -> None:
    (record,) = fails(monkeypatch, ref, response)
    assert record.attempt == 0 and record.response_sha is None


def _stalled() -> httpx.Response:
    first = sse(*completion_chunks(QWEN, ["Hello", "!"])[:1], done=False)
    return httpx.Response(200, stream=BrokenStream(first, None))


def _cancelled(records: list[LLMCallRecord]) -> LLMCallRecord:
    (record,) = records
    assert record.error == "cancelled" and record.finish_reason is None
    assert record.response_sha == sha256_text("Hello")  # the delivered text
    assert record.t_first_token is not None and record.t_end > record.t_first_token
    return record


def test_break_after_the_first_token_leaves_a_record(monkeypatch: Any) -> None:
    records: list[LLMCallRecord] = []
    llm = client(monkeypatch, QWEN, Recorder(_stalled()), records)

    async def run() -> None:
        async for _ in llm.stream_text(FAST):
            break

    asyncio.run(run())  # the loop finalises the abandoned generator
    _cancelled(records)


def test_wait_for_timeout_leaves_a_record(monkeypatch: Any) -> None:
    records: list[LLMCallRecord] = []
    llm = client(monkeypatch, QWEN, Recorder(_stalled()), records)

    async def consume() -> None:
        async for _ in llm.stream_text(FAST):
            pass

    async def run() -> None:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(consume(), timeout=0.05)

    asyncio.run(run())
    _cancelled(records)


def test_aclose_leaves_a_record(monkeypatch: Any) -> None:
    records: list[LLMCallRecord] = []
    llm = client(monkeypatch, QWEN, Recorder(_stalled()), records)

    async def run() -> None:
        stream = cast(AsyncGenerator[object], llm.stream_text(FAST))
        assert await anext(stream) == "Hello"
        await stream.aclose()
        _cancelled(records)  # at once, not at loop shutdown

    asyncio.run(run())


def test_errors_never_carry_the_key_or_host(monkeypatch: Any) -> None:
    echo = f"bad key {KEY} for https://vllm.test/v1"
    records = fails(monkeypatch, QWEN, httpx.Response(401, text=echo))
    for text in (records[0].model_dump_json(),):
        assert KEY not in text and "vllm.test" not in text


def test_env_errors_name_the_variable_not_the_value(monkeypatch: Any) -> None:
    monkeypatch.delenv("PL_RELAY_BASE_URL", raising=False)
    monkeypatch.setenv("PL_RELAY_API_KEY", KEY)
    with pytest.raises(LLMConfigError, match="PL_RELAY_BASE_URL is not set"):
        make_client(SONNET, live=True, clock=counter_clock(), on_record=print)
    monkeypatch.setenv("PL_RELAY_BASE_URL", "https://relay.test/v1")
    with pytest.raises(LLMConfigError, match="without /v1") as caught:
        make_client(SONNET, live=True, clock=counter_clock(), on_record=print)
    assert "relay.test" not in str(caught.value)


@pytest.mark.parametrize(
    "kind", [AdapterKind.RECORDED_REPLAY, AdapterKind.TEST_FAKE, AdapterKind.BASELINE]
)
def test_live_mode_rejects_non_real_http(kind: AdapterKind) -> None:
    endpoint = None if kind is AdapterKind.BASELINE else "vllm"
    ref = ModelRef(kind=kind, endpoint=endpoint, model_id="Qwen3.5-9B")
    with pytest.raises(LiveModeError):
        make_client(ref, live=True, clock=counter_clock(), on_record=print)
    with pytest.raises(ValueError, match="only real_http"):
        make_client(ref, live=False, clock=counter_clock(), on_record=print)


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
    message = ChatMessage(role="user", content="x", cache_breakpoint=True)
    cached = TOOLS.model_copy(update={"messages": (message,)})
    with pytest.raises(ValueError, match="cache_breakpoint"):
        asyncio.run(hosted.chat_tools(cached))
