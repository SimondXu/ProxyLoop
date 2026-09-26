"""The test fakes conform to the LLM interface, dead endpoint included."""

from __future__ import annotations

import asyncio
import json

from tests.contract.llm_conformance import (
    assert_text_conformance,
    assert_tool_conformance,
    assert_unavailable,
)
from tests.support.fakes import ScriptedLLM, fake_ref
from tests.support.manual_clock import ManualClock

from proxyloop.contract.llm import ChatMessage, TextRequest, ToolRequest, ToolSpec

TEXT = TextRequest(
    call_id="c1", role="fast_user", prompt="Say hi.", max_tokens=8, temperature=0
)


def test_text_and_tool_calls_conform() -> None:
    tool = {"call_id": "t1", "name": "wait", "arguments": "{}"}
    scripted = ScriptedLLM(
        fake_ref(),
        [
            "Hello there, how can I help today?",
            json.dumps({"text": "", "tool_calls": [tool]}),
        ],
    )
    request = ToolRequest(
        call_id="c2",
        role="slow",
        messages=(ChatMessage(role="user", content="Plan."),),
        tools=(ToolSpec(name="wait", description="Wait.", parameters={}),),
        tool_choice="wait",
        max_tokens=64,
    )
    record = asyncio.run(assert_text_conformance(scripted, TEXT))
    response = asyncio.run(assert_tool_conformance(scripted, request))
    assert record.adapter_kind == "test_fake" and response.tool_calls[0].name == "wait"


def test_a_dead_fake_raises_llm_unavailable_and_delivers_nothing() -> None:
    asyncio.run(assert_unavailable(ScriptedLLM(fake_ref(), [], dead=True), TEXT))


def test_the_manual_clock_moves_only_forward() -> None:
    clock = ManualClock()
    clock.advance(1500)
    assert clock.monotonic_ms() == 1500 and clock.wall().second == 1
