"""The Anthropic Messages adapter (ADR-0027): request mapping, response folding,
loud failures and pricing, against httpx.MockTransport."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from tests.contract.llm_conformance import (
    assert_tool_conformance,
    check_text_items,
)
from tests.llm.wire import KEY, Recorder, counter_clock, set_env, sse, stream_response

from proxyloop.contract.llm import (
    AdapterKind,
    ChatMessage,
    LLMCallRecord,
    LLMClient,
    LLMUnavailable,
    ModelRef,
    ReasoningEffort,
    TextRequest,
    ToolCall,
    ToolRequest,
    ToolSpec,
    Usage,
)
from proxyloop.llm.anthropic import AnthropicClient
from proxyloop.llm.factory import make_client
from proxyloop.llm.spend import ANTHROPIC_RATES, SpendLedger


def sonnet(effort: ReasoningEffort | None = "medium") -> ModelRef:
    return ModelRef(
        kind=AdapterKind.REAL_HTTP,
        endpoint="anthropic",
        model_id="claude-sonnet-5-5",
        reasoning_effort=effort,
    )


ACT = ToolSpec(
    name="act",
    description="Your summaries and actions for this turn.",
    parameters={"type": "object", "properties": {"note": {"type": "string"}}},
)
PRIOR = (
    ToolCall(call_id="toolu_a", name="act", arguments='{"note": "one"}'),
    ToolCall(call_id="toolu_b", name="act", arguments='{"note": "two"}'),
)
SLOW = ToolRequest(  # the shape SlowLoop sends: no tool_choice, tool results in history
    call_id="slow:2",
    role="slow",
    messages=(
        ChatMessage(role="system", content="S"),
        ChatMessage(role="user", content="TASK head"),
        ChatMessage(role="assistant", content="", tool_calls=PRIOR),
        ChatMessage(role="tool", content="r1", tool_call_id="toolu_a"),
        ChatMessage(role="tool", content="r2\n\n[WAKE] rep", tool_call_id="toolu_b"),
    ),
    tools=(ACT,),
    max_tokens=8192,
)
FORCED = SLOW.model_copy(update={"tool_choice": "act"})


def body(**over: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": "msg_01",
        "type": "message",
        "model": "claude-sonnet-5-5",
        "content": [
            {"type": "thinking", "thinking": ""},
            {"type": "text", "text": "ok"},
            {
                "type": "tool_use",
                "id": "toolu_c",
                "name": "act",
                "input": {"note": "é"},
            },
        ],
        "stop_reason": "tool_use",
        "usage": {
            "input_tokens": 100,
            "cache_read_input_tokens": 4000,
            "cache_creation_input_tokens": 900,
            "output_tokens": 50,
        },
    }
    return out | over


def client(
    monkeypatch: Any,
    wire: Recorder,
    ref: ModelRef | None = None,
    records: list[LLMCallRecord] | None = None,
) -> LLMClient:
    set_env(monkeypatch, "anthropic")
    sink = [] if records is None else records
    return make_client(
        ref or sonnet(),
        live=True,
        clock=counter_clock(),
        on_record=sink.append,
        transport=wire.transport(),
    )


def test_slow_request_maps_to_messages_and_the_response_folds_back(
    monkeypatch: Any,
) -> None:
    wire = Recorder(httpx.Response(200, json=body()))
    llm = client(monkeypatch, wire)
    assert isinstance(llm, AnthropicClient)
    response = asyncio.run(assert_tool_conformance(llm, SLOW))
    sent, headers = wire.body(), wire.requests[0].headers
    assert wire.requests[0].url.path == "/v1/messages"
    assert headers["x-api-key"] == KEY and headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in headers
    assert sent["system"] == [  # the one breakpoint: the stable prefix ends here
        {"type": "text", "text": "S", "cache_control": {"type": "ephemeral"}}
    ]
    assert sent["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "TASK head"}]},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_a",
                    "name": "act",
                    "input": {"note": "one"},
                },
                {
                    "type": "tool_use",
                    "id": "toolu_b",
                    "name": "act",
                    "input": {"note": "two"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_a", "content": "r1"},
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_b",
                    "content": "r2\n\n[WAKE] rep",
                },
            ],
        },
    ]
    assert sent["tools"] == [
        {"name": "act", "description": ACT.description, "input_schema": ACT.parameters}
    ]
    assert "tool_choice" not in sent and "temperature" not in sent
    assert "fallbacks" not in sent and "stream" not in sent
    assert "cache_control" not in sent  # a breakpoint on the history never hits
    assert sent["thinking"] == {"type": "adaptive"}
    assert sent["output_config"] == {"effort": "medium"}
    assert response.text == "ok"
    assert [c.name for c in response.tool_calls] == ["act"]
    assert json.loads(response.tool_calls[0].arguments) == {"note": "é"}
    record = response.record
    assert record.usage and record.usage.prompt_tokens == 5000  # cache read + write
    assert record.usage.completion_tokens == 50
    assert (record.usage.cache_read_tokens, record.usage.cache_write_tokens) == (
        4000,
        900,
    )
    assert record.finish_reason == "tool_use" and record.request_id == "msg_01"
    assert record.served_model_echo == "claude-sonnet-5-5"
    assert record.sampling_sent == {}


def roles(sent: dict[str, Any]) -> list[str]:
    return [t["role"] for t in sent["messages"]]


def test_two_tool_rounds_alternate_and_a_refusal_turn_is_not_sent(
    monkeypatch: Any,
) -> None:
    """Review of #305: a second tool round opens its own user turn; a refusal
    (no text, no calls) is not sent, so the note after it joins the previous
    user turn; whitespace-only text is not sent."""
    one = ToolCall(call_id="toolu_1", name="act", arguments="{}")
    two = ToolCall(call_id="toolu_2", name="act", arguments="{}")
    history = (
        ChatMessage(role="system", content="S"),
        ChatMessage(role="user", content="TASK head"),
        ChatMessage(role="assistant", content="  ", tool_calls=(one,)),
        ChatMessage(role="tool", content="r1", tool_call_id="toolu_1"),
        ChatMessage(role="assistant", content="", tool_calls=(two,)),
        ChatMessage(role="tool", content="r2", tool_call_id="toolu_2"),
        ChatMessage(role="assistant", content=""),  # a refusal step
        ChatMessage(role="user", content="[WAKE] rep"),
    )
    wire = Recorder(httpx.Response(200, json=body()))
    request = SLOW.model_copy(update={"messages": history})
    asyncio.run(client(monkeypatch, wire).chat_tools(request))
    sent = wire.body()
    assert roles(sent) == ["user", "assistant", "user", "assistant", "user"]
    first_call, first_result = sent["messages"][1], sent["messages"][2]
    assert first_call["content"] == [
        {"type": "tool_use", "id": "toolu_1", "name": "act", "input": {}}
    ]  # whitespace-only text is not sent
    assert [b["tool_use_id"] for b in first_result["content"]] == ["toolu_1"]
    assert sent["messages"][-1]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_2", "content": "r2"},
        {"type": "text", "text": "[WAKE] rep"},
    ]


def test_a_forced_tool_passes_through_and_its_400_is_unavailable(
    monkeypatch: Any,
) -> None:
    refused = {"type": "error", "error": {"type": "invalid_request_error"}}
    wire = Recorder(httpx.Response(400, json=refused))
    records: list[LLMCallRecord] = []
    llm = client(monkeypatch, wire, records=records)
    with pytest.raises(LLMUnavailable) as caught:
        asyncio.run(llm.chat_tools(FORCED))
    assert wire.body()["tool_choice"] == {"type": "tool", "name": "act"}
    assert len(wire.requests) == 1  # a 400 is never retried
    assert caught.value.record == records[-1] and "HTTP 400" in (
        records[-1].error or ""
    )
    assert KEY not in (records[-1].error or "")


def test_a_response_without_a_stop_reason_is_unavailable(monkeypatch: Any) -> None:
    wire = Recorder(httpx.Response(200, json=body(stop_reason=None)))
    with pytest.raises(LLMUnavailable):
        asyncio.run(client(monkeypatch, wire).chat_tools(SLOW))


@pytest.mark.parametrize(
    ("effort", "thinking", "output_config"),
    [
        ("none", {"type": "between_tools"}, None),
        ("low", {"type": "adaptive"}, {"effort": "low"}),
        (None, None, None),
    ],
)
def test_effort_maps_to_thinking(
    monkeypatch: Any,
    effort: ReasoningEffort | None,
    thinking: object,
    output_config: object,
) -> None:
    wire = Recorder(httpx.Response(200, json=body()))
    asyncio.run(client(monkeypatch, wire, sonnet(effort)).chat_tools(SLOW))
    sent = wire.body()
    assert sent.get("thinking") == thinking
    assert sent.get("output_config") == output_config


def test_minimal_effort_and_a_prompt_are_refused(monkeypatch: Any) -> None:
    llm = client(monkeypatch, Recorder(), sonnet("minimal"))
    with pytest.raises(ValueError, match="minimal"):
        asyncio.run(llm.chat_tools(SLOW))
    prompt = TextRequest(
        call_id="t", role="fast_cp", prompt="P", max_tokens=10, temperature=0
    )
    with pytest.raises(ValueError, match="not a prompt"):
        llm.stream_text(prompt)


def test_an_unlisted_model_has_no_thinking_off(monkeypatch: Any) -> None:
    ref = sonnet("none").model_copy(update={"model_id": "claude-opus-5-5"})
    with pytest.raises(ValueError, match="no thinking-off"):
        asyncio.run(client(monkeypatch, Recorder(), ref).chat_tools(SLOW))


def haiku(effort: ReasoningEffort | None) -> ModelRef:
    return sonnet(effort).model_copy(update={"model_id": "claude-haiku-5-5"})


FAST = TextRequest(  # the probe's Fast request: the kernel's sampling, 16384 guard
    call_id="fast_cp:7",
    role="fast_cp",
    messages=(
        ChatMessage(role="system", content="F"),
        ChatMessage(role="user", content="rep: $78 a month"),
    ),
    max_tokens=16384,
    temperature=0.3,
    top_p=0.9,
    seed=11,
)


def events(*texts: str) -> list[dict[str, Any]]:
    usage = {"input_tokens": 120, "cache_read_input_tokens": 0, "output_tokens": 1}
    start = {"id": "msg_02", "model": "claude-haiku-5-5", "usage": usage}
    think = {"type": "thinking_delta", "thinking": "hm"}
    return [
        {"type": "message_start", "message": start},
        {"type": "ping"},
        {"type": "content_block_delta", "index": 0, "delta": think},
        *(
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": t},
            }
            for t in texts
        ),
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 30},
        },
        {"type": "message_stop"},
    ]


@pytest.mark.parametrize(
    ("effort", "thinking", "output_config"),
    [
        ("none", {"type": "disabled"}, None),
        ("medium", {"type": "adaptive"}, {"effort": "medium"}),
    ],
)
def test_a_haiku_text_stream_speaks_the_text_deltas_only(
    monkeypatch: Any,
    effort: ReasoningEffort,
    thinking: object,
    output_config: object,
) -> None:
    wire = Recorder(
        stream_response(sse(*events("Could you ", "read that back?"), done=False))
    )
    llm = client(monkeypatch, wire, haiku(effort))

    async def stream() -> list[str | LLMCallRecord]:
        return [item async for item in llm.stream_text(FAST)]

    items = asyncio.run(stream())
    record = check_text_items(llm.ref, FAST, items)
    sent = wire.body()
    assert sent["stream"] is True and sent["system"] == "F"
    assert sent["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "rep: $78 a month"}]}
    ]
    assert sent.get("thinking") == thinking
    assert sent.get("output_config") == output_config
    assert not {"temperature", "top_p", "seed"} & sent.keys()  # Haiku: defaults only
    assert (
        "".join(i for i in items if isinstance(i, str)) == "Could you read that back?"
    )
    assert record.usage == Usage(
        prompt_tokens=120,
        completion_tokens=30,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    assert record.finish_reason == "end_turn" and record.request_id == "msg_02"
    assert record.served_model_echo == "claude-haiku-5-5"
    assert record.sampling_sent == {}


def test_a_stream_without_a_stop_reason_is_unavailable(monkeypatch: Any) -> None:
    cut = [e for e in events("Could") if e["type"] != "message_delta"]
    wire = Recorder(stream_response(sse(*cut, done=False)))
    llm = client(monkeypatch, wire, haiku("none"))

    async def drain() -> None:
        async for _ in llm.stream_text(FAST):
            pass

    with pytest.raises(LLMUnavailable):
        asyncio.run(drain())


def test_sonnet_is_priced_from_the_cache_split(monkeypatch: Any) -> None:
    wire = Recorder(httpx.Response(200, json=body()))
    response = asyncio.run(client(monkeypatch, wire).chat_tools(SLOW))
    ledger = SpendLedger(projected_tokens=200_000, projected_calls=40, refs=[sonnet()])
    charge = ledger.price(response.record)
    assert charge.basis == "tokens"
    # 100 plain x $2 + 4000 read x $0.20 + 900 write x $2.50 + 50 out x $10
    assert charge.micro_usd == 100 * 2.00 + 4000 * 0.20 + 900 * 2.50 + 50 * 10.00


def test_without_a_cache_split_input_is_priced_at_the_upper_bound() -> None:
    rate = ANTHROPIC_RATES["claude-sonnet-5-5"]
    plain = Usage(prompt_tokens=1000, completion_tokens=10)
    assert rate.micro_usd(plain) == 1000 * 2.50 + 10 * 10.00
    with pytest.raises(ValueError, match="part of prompt_tokens"):
        Usage(
            prompt_tokens=10,
            completion_tokens=0,
            cache_read_tokens=8,
            cache_write_tokens=8,
        )
