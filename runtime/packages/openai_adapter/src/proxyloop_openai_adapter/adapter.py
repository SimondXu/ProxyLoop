"""One typed OpenAI-compatible Chat Completions adapter for Runtime."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

from proxyloop_agent_core import FastAdapterResult
from proxyloop_contracts import FastModelView, SlowWorkRequest, SlowWorkResult

from .errors import ModelFailureKind, OpenAICompatibleAdapterError
from .outputs import (
    FastModelOutput,
    SlowModelOutput,
    compile_fast_output,
    compile_slow_output,
)


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
        self._client = client if client is not None else self._build_client(api_key)

    def decide(self, view: FastModelView) -> FastAdapterResult:
        if not isinstance(view, FastModelView):
            raise TypeError("Fast adapter accepts only FastModelView")
        response = self._request(view, FastModelOutput)
        try:
            output = _parsed_output(response, FastModelOutput)
            decision = compile_fast_output(view, output)
        except OpenAICompatibleAdapterError:
            raise
        except Exception as exc:
            raise OpenAICompatibleAdapterError(ModelFailureKind.INVALID_OUTPUT) from exc
        return FastAdapterResult(pins=view.pins, decision=decision)

    def reason(self, request: SlowWorkRequest) -> SlowWorkResult:
        if not isinstance(request, SlowWorkRequest):
            raise TypeError("Slow adapter accepts only SlowWorkRequest")
        response = self._request(request, SlowModelOutput)
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
        return result

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

    def _request(self, input_value: object, output_model: type[Any]) -> object:
        messages = _messages(input_value)
        try:
            completions: _Completions = cast(Any, self._client).chat.completions
            response = completions.parse(
                model=self.model,
                messages=messages,
                max_completion_tokens=self.max_completion_tokens,
                response_format=output_model,
            )
        except Exception as exc:
            kind = (
                ModelFailureKind.TIMEOUT
                if "timeout" in type(exc).__name__.lower()
                else ModelFailureKind.TRANSPORT
            )
            raise OpenAICompatibleAdapterError(kind) from exc
        _validate_response_model(response, self.model)
        return response


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
    if not (
        response_model == requested_model
        or response_model.startswith(f"{requested_model}-")
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
