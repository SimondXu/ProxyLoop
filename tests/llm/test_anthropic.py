"""The Anthropic Messages adapter (ADR-0027): request mapping, response folding,
loud failures and pricing, against httpx.MockTransport."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from tests.contract.llm_conformance import assert_tool_conformance
from tests.llm.wire import KEY, Recorder, counter_clock, set_env

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
)
from proxyloop.llm.anthropic import AnthropicClient
from proxyloop.llm.factory import make_client
from proxyloop.llm.spend import SpendLedger


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
    assert sent["system"] == "S"
    assert sent["messages"] == [
        {"role": "user", "content": "TASK head"},
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
    assert sent["cache_control"] == {"type": "ephemeral"}
    assert sent["thinking"] == {"type": "adaptive"}
    assert sent["output_config"] == {"effort": "medium"}
    assert response.text == "ok"
    assert [c.name for c in response.tool_calls] == ["act"]
    assert json.loads(response.tool_calls[0].arguments) == {"note": "é"}
    record = response.record
    assert record.usage and record.usage.prompt_tokens == 5000  # cache read + write
    assert record.usage.completion_tokens == 50
    assert record.finish_reason == "tool_use" and record.request_id == "msg_01"
    assert record.served_model_echo == "claude-sonnet-5-5"
    assert record.sampling_sent == {}


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


def test_minimal_effort_and_text_streams_are_refused(monkeypatch: Any) -> None:
    llm = client(monkeypatch, Recorder(), sonnet("minimal"))
    with pytest.raises(ValueError, match="minimal"):
        asyncio.run(llm.chat_tools(SLOW))
    text = TextRequest(
        call_id="t",
        role="slow",
        messages=SLOW.messages[:2],
        max_tokens=10,
        temperature=0,
    )
    with pytest.raises(ValueError, match="tool calls only"):
        llm.stream_text(text)


def test_sonnet_is_priced_at_the_upper_bound_rate(monkeypatch: Any) -> None:
    wire = Recorder(httpx.Response(200, json=body()))
    response = asyncio.run(client(monkeypatch, wire).chat_tools(SLOW))
    ledger = SpendLedger(projected_tokens=200_000, projected_calls=40, refs=[sonnet()])
    charge = ledger.price(response.record)
    assert charge.basis == "tokens"
    assert charge.micro_usd == 5000 * 2.50 + 50 * 10.00  # $2.50/M in, $10/M out
