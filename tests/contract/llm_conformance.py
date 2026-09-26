"""Conformance kit for ``contract.llm.LLMClient`` adapters.

S0-SYS-04 (vLLM, relay, TeamRouter) and S1-MOD-01 (FSM, teacher-repair) run
these against their adapters, e.g. over recorded fixtures from
``tests/support/recorded.py``::

    record = await assert_text_conformance(client, request)
    await assert_unavailable(client, request)  # with the endpoint dead

The ``check_*`` functions are pure; the ``assert_*`` drivers call the client.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from proxyloop.contract.base import sha256_text
from proxyloop.contract.llm import (
    AdapterKind,
    LLMCallRecord,
    LLMClient,
    LLMUnavailable,
    ModelRef,
    TextRequest,
    ToolRequest,
    ToolResponse,
    request_content,
    tool_response_content,
)


def check_record(
    ref: ModelRef,
    request: TextRequest | ToolRequest,
    record: LLMCallRecord,
    response: str,
) -> None:
    """One successful call's record against its request, client and response."""

    assert (record.call_id, record.role) == (request.call_id, request.role)
    assert record.model_ref == ref and record.adapter_kind is ref.kind
    assert record.prompt_sha == sha256_text(request_content(request))
    assert record.error is None, record.error
    assert record.response_sha == sha256_text(response)
    if response and isinstance(request, TextRequest):
        assert record.t_first_token is not None
    if ref.kind is AdapterKind.REAL_HTTP:  # ARCHITECTURE §14
        assert record.request_id, "real_http calls record a request id"
        assert record.usage is not None and record.usage.completion_tokens > 0, (
            "real_http calls report completion tokens"
        )
        assert record.served_model_echo, "real_http calls record the echoed model"


def check_text_items(
    ref: ModelRef, request: TextRequest, items: Sequence[str | LLMCallRecord]
) -> LLMCallRecord:
    """``stream_text`` output: text deltas, then exactly one record, last."""

    assert items, "stream_text yielded nothing"
    *deltas, record = items
    assert isinstance(record, LLMCallRecord), "the last item must be the record"
    text: list[str] = []
    for delta in deltas:
        assert isinstance(delta, str), "only the last item may be a record"
        text.append(delta)
    check_record(ref, request, record, "".join(text))
    return record


def check_tool_response(
    ref: ModelRef, request: ToolRequest, response: ToolResponse
) -> None:
    """``chat_tools`` output; tool names and arguments pass through unrepaired."""

    content = tool_response_content(response.text, response.tool_calls)
    check_record(ref, request, response.record, content)


async def assert_text_conformance(
    client: LLMClient, request: TextRequest
) -> LLMCallRecord:
    items = [item async for item in client.stream_text(request)]
    return check_text_items(client.ref, request, items)


async def assert_tool_conformance(
    client: LLMClient, request: ToolRequest
) -> ToolResponse:
    response = await client.chat_tools(request)
    check_tool_response(client.ref, request, response)
    return response


def check_unavailable(error: LLMUnavailable, delivered: Sequence[object]) -> None:
    """A dead endpoint raises ``LLMUnavailable`` and delivers no text."""

    assert not delivered, "no text may be delivered from a dead endpoint"
    assert error.record.error, "the failed call's record names the error"
    assert error.record.response_sha is None


async def assert_unavailable(client: LLMClient, request: TextRequest) -> None:
    delivered: list[object] = []
    with pytest.raises(LLMUnavailable) as caught:
        async for item in client.stream_text(request):
            delivered.append(item)
    check_unavailable(caught.value, delivered)
