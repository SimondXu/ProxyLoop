"""Self-test of the conformance kit's checks on plain values (no client)."""

from __future__ import annotations

import pytest
from tests.contract.llm_conformance import (
    check_text_items,
    check_tool_response,
    check_unavailable,
)
from tests.contract.samples import GEMINI, QWEN, call_record

from proxyloop.contract.base import sha256_text
from proxyloop.contract.llm import (
    ChatMessage,
    LLMCallRecord,
    LLMUnavailable,
    TextRequest,
    ToolCall,
    ToolRequest,
    ToolResponse,
    ToolSpec,
    request_content,
    tool_response_content,
)

REQUEST = TextRequest(
    call_id="k1", role="fast_cp", prompt="P", max_tokens=8, temperature=0.3
)
PROMPT_SHA = sha256_text(request_content(REQUEST))


def _record(response: str, **update: object) -> LLMCallRecord:
    base: dict[str, object] = {
        "prompt_sha": PROMPT_SHA,
        "response_sha": sha256_text(response),
    }
    return call_record(QWEN, **(base | update))


def test_well_formed_stream_passes() -> None:
    record = _record("Hello there.")
    assert check_text_items(QWEN, REQUEST, ["Hello", " there.", record]) == record


@pytest.mark.parametrize(
    ("items", "message"),
    [
        ([], "yielded nothing"),
        (["Hello there."], "last item must be the record"),
        ([_record("Hello there."), "Hello there."], "last item must be the record"),
        (["Hi", _record("Hi"), _record("Hi")], "only the last item"),
        (["Hello"], "last item"),
    ],
)
def test_malformed_streams_fail(items: list[str | LLMCallRecord], message: str) -> None:
    with pytest.raises(AssertionError, match=message):
        check_text_items(QWEN, REQUEST, items)


@pytest.mark.parametrize(
    "record",
    [
        _record("Hello there!"),  # response_sha of other text
        _record("Hello there.", prompt_sha="0" * 64),
        _record("Hello there.", call_id="k2"),
        _record("Hello there.", error="boom"),
        _record("Hello there.", usage=None),
        _record("Hello there.", served_model_echo=None),
        _record("Hello there.", t_first_token=None),
    ],
)
def test_inconsistent_records_fail(record: LLMCallRecord) -> None:
    with pytest.raises(AssertionError):
        check_text_items(QWEN, REQUEST, ["Hello there.", record])


def test_record_from_another_model_fails() -> None:
    with pytest.raises(AssertionError):
        check_text_items(GEMINI, REQUEST, ["Hello there.", _record("Hello there.")])


def test_tool_response_hashes_text_and_calls() -> None:
    tool = ToolSpec(name="classify", description="d", parameters={"type": "object"})
    request = ToolRequest(
        call_id="k1",
        role="fast_cp",
        messages=(ChatMessage(role="user", content="hi"),),
        tools=(tool,),
        tool_choice="classify",
        max_tokens=8,
    )
    calls = (ToolCall(call_id="t1", name="classify", arguments='{"act": "other"'),)
    content = tool_response_content("", calls)
    record = call_record(
        prompt_sha=sha256_text(request_content(request)),
        response_sha=sha256_text(content),
    )
    check_tool_response(
        QWEN, request, ToolResponse(text="", tool_calls=calls, record=record)
    )
    wrong = ToolResponse(text="x", tool_calls=calls, record=record)
    with pytest.raises(AssertionError):
        check_tool_response(QWEN, request, wrong)


def test_unavailable_checks() -> None:
    failed = call_record(response_sha=None, error="connect refused", t_first_token=None)
    check_unavailable(LLMUnavailable("dead", failed), [])
    check_unavailable(LLMUnavailable("dead"), [])
    with pytest.raises(AssertionError, match="no text"):
        check_unavailable(LLMUnavailable("dead"), ["partial"])
    with pytest.raises(AssertionError, match="names the error"):
        check_unavailable(LLMUnavailable("dead", call_record(response_sha=None)), [])
