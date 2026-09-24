"""One typed OpenAI-compatible Chat Completions adapter for Runtime."""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, cast
from urllib.parse import urlparse

from proxyloop_agent_core import FastAdapterResult, ModelCallUsage, ModelIdentity
from proxyloop_contracts import FastModelView, SlowWorkRequest, SlowWorkResult
from pydantic import ValidationError

from .errors import ModelFailureKind, OpenAICompatibleAdapterError
from .outputs import (
    FastModelOutput,
    SlowModelOutput,
    compile_fast_output,
    compile_slow_output,
)

_DATED_SNAPSHOT_SUFFIX = re.compile(r"\d{4}-\d{2}-\d{2}|\d{8}")

# Bump when the adapter's request shaping or the system prompts in
# ``_messages`` change; both are recorded on every ModelTrace.
ADAPTER_VERSION = "openai-compatible-adapter-v1"
PROMPT_VERSION = "openai-compatible-chat-v1"


class _Completions(Protocol):
    def parse(self, **kwargs: object) -> object: ...


class _Client(Protocol):
    chat: Any


class OpenAICompatibleAdapter:
    """Proposal-only adapter using one Chat Completions Structured Outputs call."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str,
        timeout: float = 30.0,
        max_completion_tokens: int = 1_024,
        client: object | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        if not model or not base_url or not api_key:
            raise ValueError("model, base_url, and api_key are required")
        if (
            type(timeout) not in {int, float}
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be positive")
        if type(max_completion_tokens) is not int or max_completion_tokens < 1:
            raise ValueError("max_completion_tokens must be positive")
        self.model = model
        self.base_url = base_url
        self.timeout = float(timeout)
        self.max_completion_tokens = max_completion_tokens
        # The host only: a base URL may carry credentials in its userinfo.
        self.model_identity = ModelIdentity(
            provider=urlparse(base_url).hostname or "openai_compatible",
            model=model,
            model_version=model,
            adapter_version=ADAPTER_VERSION,
            prompt_version=PROMPT_VERSION,
        )
        self._monotonic = monotonic or time.perf_counter
        self._client = client if client is not None else self._build_client(api_key)

    def decide(self, view: FastModelView) -> FastAdapterResult:
        return self.decide_with_usage(view)[0]

    def reason(self, request: SlowWorkRequest) -> SlowWorkResult:
        return self.reason_with_usage(request)[0]

    def decide_with_usage(
        self, view: FastModelView
    ) -> tuple[FastAdapterResult, ModelCallUsage]:
        if not isinstance(view, FastModelView):
            raise TypeError("Fast adapter accepts only FastModelView")
        response, usage = self._request(view, FastModelOutput)
        try:
            output = _parsed_output(response, FastModelOutput)
            decision = compile_fast_output(view, output)
        except OpenAICompatibleAdapterError:
            raise
        except Exception as exc:
            raise OpenAICompatibleAdapterError(ModelFailureKind.INVALID_OUTPUT) from exc
        return FastAdapterResult(pins=view.pins, decision=decision), usage

    def reason_with_usage(
        self, request: SlowWorkRequest
    ) -> tuple[SlowWorkResult, ModelCallUsage]:
        if not isinstance(request, SlowWorkRequest):
            raise TypeError("Slow adapter accepts only SlowWorkRequest")
        response, usage = self._request(request, SlowModelOutput)
        try:
            output = _parsed_output(response, SlowModelOutput)
            result = compile_slow_output(request, output)
            if result.pins != request.pins or (
                result.planning_basis != request.planning_basis
            ):
                raise OpenAICompatibleAdapterError(ModelFailureKind.STALE_PINS)
            if result.request_id != request.request_id or (
                result.case_id != request.case_id
            ):
                raise OpenAICompatibleAdapterError(ModelFailureKind.STALE_PINS)
        except OpenAICompatibleAdapterError:
            raise
        except Exception as exc:
            raise OpenAICompatibleAdapterError(ModelFailureKind.INVALID_OUTPUT) from exc
        return result, usage

    def _build_client(self, api_key: str) -> object:
        try:
            from openai import OpenAI

            return OpenAI(
                api_key=api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=0,
            )
        except Exception as exc:
            raise OpenAICompatibleAdapterError(ModelFailureKind.CONFIGURATION) from exc

    def _request(
        self, input_value: object, output_model: type[Any]
    ) -> tuple[object, ModelCallUsage]:
        messages = _messages(input_value)
        try:
            completions: _Completions = cast(Any, self._client).chat.completions
            started = self._monotonic()
            response = completions.parse(
                model=self.model,
                messages=messages,
                max_completion_tokens=self.max_completion_tokens,
                response_format=output_model,
            )
            elapsed = self._monotonic() - started
        except ValidationError as exc:
            # ``parse`` validates the returned content against the schema
            # client-side; a mismatch is the model's output, not the transport.
            raise OpenAICompatibleAdapterError(ModelFailureKind.INVALID_OUTPUT) from exc
        except Exception as exc:
            kind = (
                ModelFailureKind.TIMEOUT
                if "timeout" in type(exc).__name__.lower()
                else ModelFailureKind.TRANSPORT
            )
            raise OpenAICompatibleAdapterError(kind) from exc
        _validate_response_model(response, self.model)
        usage = _field(response, "usage")
        return response, ModelCallUsage(
            input_tokens=_token_count(_field(usage, "prompt_tokens")),
            output_tokens=_token_count(_field(usage, "completion_tokens")),
            latency_ms=max(0, round(elapsed * 1000)),
        )


def _token_count(value: object) -> int:
    """A reported count, or zero when the response carries none."""

    return value if type(value) is int and value >= 0 else 0


def _messages(input_value: object) -> list[dict[str, str]]:
    if isinstance(input_value, FastModelView):
        system = (
            "Return one strict semantic Fast proposal. Infrastructure IDs, "
            "timestamps, and pins are compiled outside the model. Set "
            "action_intent to null. Propose only; do not authorize or execute."
        )
        payload = {"typed_fast_view": input_value.model_dump(mode="json")}
    elif isinstance(input_value, SlowWorkRequest):
        system = (
            "Return one strict semantic Slow strategy and optional next capability. "
            "IDs, timestamps, pins, and inert proposals are compiled outside the "
            "model. Propose only; do not authorize or execute."
        )
        payload = {"typed_slow_request": input_value.model_dump(mode="json")}
    else:
        raise TypeError("unsupported model input")
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        },
    ]


def _validate_response_model(response: object, requested_model: str) -> None:
    response_model = _field(response, "model")
    if not isinstance(response_model, str) or not response_model:
        raise OpenAICompatibleAdapterError(ModelFailureKind.MODEL_METADATA)
    # An alias such as ``gpt-4o`` may be served by its dated snapshot
    # ``gpt-4o-2024-08-06`` (or ``-YYYYMMDD``, e.g. ``-20240806``); any other
    # suffix (``gpt-4o-mini``, ``-latest``) is a different model.
    if not (
        response_model == requested_model
        or (
            response_model.startswith(f"{requested_model}-")
            and _DATED_SNAPSHOT_SUFFIX.fullmatch(
                response_model[len(requested_model) + 1 :]
            )
            is not None
        )
    ):
        raise OpenAICompatibleAdapterError(ModelFailureKind.MODEL_METADATA)


def _parsed_output(response: object, output_model: type[Any]) -> Any:
    choices = _field(response, "choices")
    first = choices[0] if isinstance(choices, Sequence) and choices else None
    message = _field(first, "message")
    if _field(message, "refusal"):
        raise OpenAICompatibleAdapterError(ModelFailureKind.INVALID_OUTPUT)
    parsed = _field(message, "parsed")
    if not isinstance(parsed, output_model):
        raise OpenAICompatibleAdapterError(ModelFailureKind.INVALID_OUTPUT)
    return parsed


def _field(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


__all__ = ["OpenAICompatibleAdapter"]
