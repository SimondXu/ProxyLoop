"""The LLM interface every adapter implements (ARCHITECTURE §2; ADR-0001, ADR-0004).

Adapters live in SYS (``proxyloop.llm``). A dead endpoint raises
``LLMUnavailable``: there is no fallback, and no retry on model output.
Structured output is a forced tool call; there is no JSON mode.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Literal, Protocol, Self

from pydantic import Field, model_validator

from proxyloop.contract.base import Frozen, canonical_json


class AdapterKind(StrEnum):
    REAL_HTTP = "real_http"
    RECORDED_REPLAY = "recorded_replay"
    TEST_FAKE = "test_fake"
    BASELINE = "baseline"


# Endpoints are named as data; SYS resolves URL and key from its environment.
Endpoint = Literal["relay", "teamrouter", "vllm"]
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high"]
LLMRole = Literal["fast_user", "fast_cp", "slow", "ear", "mouth", "simuser", "teacher"]


class ModelRef(Frozen):
    """One model, by exact id (never an alias)."""

    kind: AdapterKind
    endpoint: Endpoint | None  # None only for an in-process baseline
    model_id: str = Field(min_length=1)
    reasoning_effort: ReasoningEffort | None = None  # None: the provider default

    @model_validator(mode="after")
    def _endpoint(self) -> Self:
        if self.kind is AdapterKind.REAL_HTTP and self.endpoint is None:
            raise ValueError("a real_http model needs an endpoint")
        if self.kind is AdapterKind.BASELINE and self.endpoint is not None:
            raise ValueError("a baseline model runs in process, without an endpoint")
        return self


class ToolCall(Frozen):
    call_id: str
    name: str
    arguments: str  # the raw JSON text the model produced; validated by the caller


class ChatMessage(Frozen):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()  # assistant only
    tool_call_id: str | None = None  # tool only
    cache_breakpoint: bool = False  # Slow's one prompt-cache breakpoint (§8)


class ToolSpec(Frozen):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    description: str
    parameters: dict[str, object]  # JSON schema


class TextRequest(Frozen):
    """A streamed text call: a pre-rendered ``prompt`` (vLLM) or ``messages``."""

    call_id: str
    role: LLMRole
    prompt: str | None = None
    messages: tuple[ChatMessage, ...] = ()
    max_tokens: int = Field(gt=0)
    temperature: float = Field(ge=0)
    top_p: float = Field(default=1.0, gt=0, le=1)
    seed: int | None = None

    @model_validator(mode="after")
    def _one_input(self) -> Self:
        if (self.prompt is None) == (not self.messages):
            raise ValueError("give exactly one of prompt and messages")
        return self


class ToolRequest(Frozen):
    """A tool call. ``tool_choice`` names the one tool the model must call."""

    call_id: str
    role: LLMRole
    messages: tuple[ChatMessage, ...] = Field(min_length=1)
    tools: tuple[ToolSpec, ...] = Field(min_length=1)
    tool_choice: str | None = None  # None: the model may answer in text
    max_tokens: int = Field(gt=0)
    temperature: float | None = None

    @model_validator(mode="after")
    def _choice(self) -> Self:
        names = [tool.name for tool in self.tools]
        if len(set(names)) != len(names):
            raise ValueError("tool names must be unique")
        if self.tool_choice is not None and self.tool_choice not in names:
            raise ValueError("tool_choice must name one of the tools")
        return self


class Usage(Frozen):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    reasoning_tokens: int | None = None  # as the provider reports it


class LLMCallRecord(Frozen):
    """The ``llm.call`` payload. Times are ms on the session clock."""

    call_id: str
    role: LLMRole
    model_ref: ModelRef
    adapter_kind: AdapterKind
    requested_model: str
    served_model_echo: str | None
    request_id: str | None
    prompt_sha: str
    response_sha: str | None
    usage: Usage | None
    t_start: int
    t_first_token: int | None
    t_end: int
    finish_reason: str | None  # as the provider reports it; None on error
    attempt: Literal[0, 1]  # one record per HTTP attempt: a retry is a second
    error: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.requested_model != self.model_ref.model_id:
            raise ValueError("requested_model must be the ModelRef's model_id")
        if self.adapter_kind is not self.model_ref.kind:
            raise ValueError("adapter_kind must be the ModelRef's kind")
        first = self.t_first_token
        if not self.t_start <= (self.t_start if first is None else first) <= self.t_end:
            raise ValueError("need t_start <= t_first_token <= t_end")
        return self


class ToolResponse(Frozen):
    text: str
    tool_calls: tuple[ToolCall, ...]
    record: LLMCallRecord


class LLMUnavailable(Exception):
    """The endpoint is dead: the session aborts (no fallback, I8). The failed
    call's record always travels with it."""

    def __init__(self, message: str, record: LLMCallRecord) -> None:
        super().__init__(message)
        self.record = record


class LLMClient(Protocol):
    """One configured model. Every call yields exactly one ``LLMCallRecord``."""

    @property
    def ref(self) -> ModelRef: ...

    def stream_text(self, request: TextRequest) -> AsyncIterator[str | LLMCallRecord]:
        """Yield text deltas, then the call's record as the last item."""
        ...

    async def chat_tools(self, request: ToolRequest) -> ToolResponse: ...


def request_content(request: TextRequest | ToolRequest) -> str:
    """The prompt text that ``prompt_sha`` hashes and ``prompts.jsonl`` stores."""

    if isinstance(request, TextRequest) and request.prompt is not None:
        return request.prompt
    body: dict[str, object] = {
        "messages": [m.model_dump(mode="json") for m in request.messages]
    }
    if isinstance(request, ToolRequest):
        body["tools"] = [t.model_dump(mode="json") for t in request.tools]
        body["tool_choice"] = request.tool_choice
    return canonical_json(body)


def tool_response_content(text: str, tool_calls: tuple[ToolCall, ...]) -> str:
    """The response text that ``response_sha`` hashes for a tool call."""

    calls = [c.model_dump(mode="json") for c in tool_calls]
    return canonical_json({"text": text, "tool_calls": calls})
