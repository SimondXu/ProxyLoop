"""Hosted Terra adapter for the Phase 03A1-B evaluation.

The adapter is intentionally small and strict.  It accepts only the canonical
Fast/Slow views, sends an OpenAI-compatible Chat Completions structured-output
request, validates the returned canonical contract without repair or retry,
and exposes the last call record for the evaluator.  It has no policy,
approval, execution, or completion authority.

The OpenAI SDK is imported only when a real client is needed. Tests can inject
a fake ``chat.completions.parse`` client and therefore never need credentials
or network access.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Literal, cast

from proxyloop_agent_core import FastAdapterResult
from proxyloop_contracts import (
    FastModelView,
    SlowWorkRequest,
    SlowWorkResult,
)
from pydantic import BaseModel, ConfigDict

from .fast_output import FastModelOutput, compile_fast_output
from .slow_output import SlowModelOutput, compile_slow_output

# The user-approved Phase 03A1 reference is one exact Terra family through the
# frozen compatibility endpoint.  A returned snapshot suffix is accepted and
# recorded; a remapped model family is rejected.
FRONTIER_MODEL = "gpt-5.6-terra"
FRONTIER_BASE_URL = "https://29qg.com/v1"
FRONTIER_PROVIDER = "29qg-openai-compatible"
FRONTIER_RUNTIME = "openai-compatible-chat-completions"
FRONTIER_API_KEY_ENV = "PROXYLOOP_FRONTIER_API_KEY"

# The proxy does not return a billed-cost field.  Keep the already reviewed
# Sol-equivalent tariff as a conservative quota-accounting ceiling; actual
# usage is multiplied by this frozen rate and reported as conservative cost.
INPUT_PRICE_USD_PER_MILLION = 4.0
OUTPUT_PRICE_USD_PER_MILLION = 20.0

# These are evaluator-only names that must never cross the typed prompt seam.
# Canonical model fields remain the only source of prompt content.
FORBIDDEN_PROMPT_KEYS = frozenset(
    {
        "manifest",
        "private",
        "evaluator",
        "oracle",
        "gold",
        "family_id",
        "entity_cluster",
        "configuration_id",
        "provider_configuration_id",
        "provider_configuration_version",
        "split",
        "provider_split",
        "safety_only",
        "private_policy",
        "reference_action",
        "expected_action",
        "expected_outcome",
        "gold_label",
        "reward",
        "evaluator_criteria",
        "verifier_criteria",
        "oracle_action",
        "oracle_reason_codes",
        "scenario_label",
        "chain_of_thought",
        "kv_cache",
        "raw_prompt",
        "free_form_memory",
    }
)


class FrontierCallStatus(StrEnum):
    SUCCEEDED = "succeeded"
    NOT_RUN_MISSING_CREDENTIALS = "not_run_missing_credentials"
    NOT_RUN_MODEL_UNAVAILABLE = "not_run_model_unavailable"
    NOT_RUN_BUDGET_EXCEEDED = "not_run_budget_exceeded"
    FAILED_INVALID_RESPONSE = "failed_invalid_response"
    FAILED_PROVIDER_CALL = "failed_provider_call"


class FrontierAdapterError(RuntimeError):
    """Typed adapter failure that the evaluator records as a model failure."""

    def __init__(self, message: str, *, status: FrontierCallStatus) -> None:
        super().__init__(message)
        self.status = status


class FrontierUnavailableError(FrontierAdapterError):
    """Credentials or the optional SDK/client are unavailable."""


class FrontierBudgetExceededError(FrontierAdapterError):
    """The conservative pre-call budget gate rejected the call."""


class FrontierResponseValidationError(FrontierAdapterError):
    """The provider response was not an exact canonical structured result."""

    def __init__(
        self,
        message: str,
        *,
        status: FrontierCallStatus,
        validation_stage: str = "provider_response",
    ) -> None:
        super().__init__(message, status=status)
        self.validation_stage = validation_stage


class FrontierProviderCallError(FrontierAdapterError):
    """A hosted request started but returned no trustworthy usage/result."""


@dataclass(frozen=True, slots=True)
class FrontierCostEstimate:
    input_token_cap: int
    output_token_cap: int
    call_cap: int
    per_call_cost_usd: float
    maximum_cost_usd: float
    usd_ceiling: float


@dataclass(frozen=True, slots=True)
class FrontierCallRecord:
    """Redacted provenance for one attempted hosted call."""

    status: FrontierCallStatus
    requested_model: str
    response_model: str | None
    response_model_version: str | None
    response_id: str | None
    requested_reasoning_effort: str
    reasoning_tokens: int | None
    input_tokens: int
    output_tokens: int
    latency_ms: int | None
    estimated_cost_usd: float
    actual_cost_usd: float | None
    prompt_fingerprint: str
    schema_fingerprint: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class FrontierErrorEvidence:
    """Allowlisted Provider failure metadata with no request or header content."""

    error_class: str
    status_code: int | None
    request_id: str | None
    provider_code: str | None
    provider_type: str | None
    provider_param: str | None
    call_index: int | None


@dataclass(frozen=True, slots=True)
class PromptBundle:
    """A Chat Completions input plus prompt/schema fingerprints."""

    messages: tuple[dict[str, object], ...]
    output_schema: dict[str, object]
    prompt_fingerprint: str
    schema_fingerprint: str
    output_model: type[BaseModel]

    def to_request(self, *, name: str) -> dict[str, object]:
        del name
        return {
            "messages": list(self.messages),
            "response_format": self.output_model,
        }


class FastStructuredOutput(FastModelOutput):
    """Shared strict semantic Fast proposal used by hosted structured output."""


class ProviderProbeOutput(BaseModel):
    """Tiny non-evaluation structured response used by the r4 transport gate."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ok: Literal[True]
    label: str


class OpenAIFrontierAdapter:
    """One exact-model adapter implementing both Fast and Slow seams."""

    def __init__(
        self,
        *,
        client: object | None = None,
        model: str = FRONTIER_MODEL,
        reasoning_effort: str = "medium",
        max_output_tokens: int = 1_024,
        input_token_cap: int = 8_192,
        call_cap: int = 1,
        usd_ceiling: float = 5.0,
    ) -> None:
        if model != FRONTIER_MODEL:
            raise ValueError(f"frontier model is frozen to {FRONTIER_MODEL}")
        if reasoning_effort not in {"low", "medium", "high"}:
            raise ValueError("reasoning_effort must be low, medium, or high")
        for value, name in (
            (max_output_tokens, "max_output_tokens"),
            (input_token_cap, "input_token_cap"),
            (call_cap, "call_cap"),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if type(usd_ceiling) not in {int, float} or usd_ceiling < 0:
            raise ValueError("usd_ceiling must be non-negative")

        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens
        self.input_token_cap = input_token_cap
        self.output_token_cap = max_output_tokens
        self.call_cap = call_cap
        self.usd_ceiling = float(usd_ceiling)
        self._client = client
        self._calls_started = 0
        self._last_call: FrontierCallRecord | None = None
        self._last_structured_output: str | None = None
        self._last_error: FrontierErrorEvidence | None = None
        self._error_history: list[FrontierErrorEvidence] = []

    @property
    def last_call(self) -> FrontierCallRecord | None:
        return self._last_call

    @property
    def calls_started(self) -> int:
        return self._calls_started

    @property
    def last_structured_output(self) -> str | None:
        return self._last_structured_output

    @property
    def last_error(self) -> FrontierErrorEvidence | None:
        return self._last_error

    @property
    def error_history(self) -> tuple[FrontierErrorEvidence, ...]:
        return tuple(self._error_history)

    @property
    def cost_estimate(self) -> FrontierCostEstimate:
        return estimate_frontier_cost(
            input_token_cap=self.input_token_cap,
            output_token_cap=self.output_token_cap,
            call_cap=self.call_cap,
            usd_ceiling=self.usd_ceiling,
        )

    def decide(self, view: FastModelView) -> FastAdapterResult:
        """Call the exact frontier model for one typed Fast view."""

        if not isinstance(view, FastModelView):
            raise TypeError("Fast adapter accepts only FastModelView")
        self._last_structured_output = None
        bundle = build_fast_prompt(view)
        response, record = self._invoke(bundle)
        raw = _raw_message_content(response)
        if raw is not None:
            self._last_structured_output = raw[:16384]
        try:
            parsed = _parsed_output(response, FastStructuredOutput)
            self._last_structured_output = _structured_output_text(parsed)
        except Exception as exc:
            self._capture_error(exc)
            self._finish(
                record,
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                error=str(exc),
            )
            raise FrontierResponseValidationError(
                f"frontier Fast response failed output-schema validation: {exc}",
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                validation_stage="schema",
            ) from exc
        try:
            decision = compile_fast_output(view, parsed)
        except Exception as exc:
            self._capture_error(exc)
            self._finish(
                record,
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                error=str(exc),
            )
            raise FrontierResponseValidationError(
                f"frontier Fast response failed canonical validation: {exc}",
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                validation_stage="canonical",
            ) from exc
        self._finish(record, status=FrontierCallStatus.SUCCEEDED)
        return FastAdapterResult(pins=view.pins, decision=decision)

    def reason(self, request: SlowWorkRequest) -> SlowWorkResult:
        """Call the exact frontier model for one typed Slow request."""

        if not isinstance(request, SlowWorkRequest):
            raise TypeError("Slow adapter accepts only SlowWorkRequest")
        self._last_structured_output = None
        bundle = build_slow_prompt(request)
        response, record = self._invoke(bundle)
        raw = _raw_message_content(response)
        if raw is not None:
            self._last_structured_output = raw[:16384]
        try:
            parsed = _parsed_output(response, SlowModelOutput)
            self._last_structured_output = _structured_output_text(parsed)
        except Exception as exc:
            self._capture_error(exc)
            self._finish(
                record,
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                error=str(exc),
            )
            raise FrontierResponseValidationError(
                f"frontier Slow response failed output-schema validation: {exc}",
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                validation_stage="schema",
            ) from exc
        try:
            result = compile_slow_output(request, parsed)
        except Exception as exc:
            self._capture_error(exc)
            self._finish(
                record,
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                error=str(exc),
            )
            raise FrontierResponseValidationError(
                f"frontier Slow response failed semantic validation: {exc}",
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                validation_stage="semantic",
            ) from exc
        try:
            _validate_slow_binding(request, result)
        except Exception as exc:
            self._capture_error(exc)
            self._finish(
                record,
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                error=str(exc),
            )
            raise FrontierResponseValidationError(
                f"frontier Slow response failed canonical binding: {exc}",
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                validation_stage="canonical",
            ) from exc
        self._finish(record, status=FrontierCallStatus.SUCCEEDED)
        return result

    def probe(self, *, label: str) -> ProviderProbeOutput:
        """Run one fixed, non-evaluation structured transport/usage probe."""

        bundle = build_probe_prompt(label)
        response, record = self._invoke(bundle)
        raw = _raw_message_content(response)
        if raw is not None:
            self._last_structured_output = raw[:16384]
        try:
            parsed = cast(
                ProviderProbeOutput,
                _parsed_output(response, ProviderProbeOutput),
            )
            if parsed.label != label:
                raise ValueError("probe response label does not match the request")
            self._last_structured_output = _structured_output_text(parsed)
        except Exception as exc:
            self._capture_error(exc)
            self._finish(
                record,
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                error=type(exc).__name__,
            )
            raise FrontierResponseValidationError(
                "frontier probe response failed strict validation",
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                validation_stage="probe_schema",
            ) from exc
        self._finish(record, status=FrontierCallStatus.SUCCEEDED)
        return parsed

    def build_fast_prompt(self, view: FastModelView) -> PromptBundle:
        return build_fast_prompt(view)

    def build_slow_prompt(self, request: SlowWorkRequest) -> PromptBundle:
        return build_slow_prompt(request)

    def _invoke(self, bundle: PromptBundle) -> tuple[object, FrontierCallRecord]:
        self._last_error = None
        estimate = self.cost_estimate
        if estimate.maximum_cost_usd - self.usd_ceiling > 1e-12:
            record = self._not_run_record(
                bundle,
                status=FrontierCallStatus.NOT_RUN_BUDGET_EXCEEDED,
                error=(
                    f"worst-case hosted cost ${estimate.maximum_cost_usd:.6f} "
                    f"exceeds ceiling ${self.usd_ceiling:.6f}"
                ),
            )
            raise FrontierBudgetExceededError(
                record.error or "frontier budget ceiling exceeded",
                status=record.status,
            )
        if self._calls_started >= self.call_cap:
            record = self._not_run_record(
                bundle,
                status=FrontierCallStatus.NOT_RUN_BUDGET_EXCEEDED,
                error="frontier call cap exhausted",
            )
            raise FrontierBudgetExceededError(
                record.error or "frontier call cap exhausted",
                status=record.status,
            )

        client = self._client
        if client is None:
            if not os.environ.get(FRONTIER_API_KEY_ENV):
                record = self._not_run_record(
                    bundle,
                    status=FrontierCallStatus.NOT_RUN_MISSING_CREDENTIALS,
                    error=(
                        f"{FRONTIER_API_KEY_ENV} is not present in the process "
                        "environment"
                    ),
                )
                raise FrontierUnavailableError(
                    record.error or f"missing {FRONTIER_API_KEY_ENV}",
                    status=record.status,
                )
            try:
                # Keep the provider SDK optional and out of the import path for
                # all deterministic tests and runtime packages.
                openai_module = cast(Any, importlib.import_module("openai"))
                openai_client = openai_module.OpenAI

                client = openai_client(
                    api_key=os.environ[FRONTIER_API_KEY_ENV],
                    base_url=FRONTIER_BASE_URL,
                    max_retries=0,
                )
                self._client = client
            except Exception as exc:
                self._capture_error(exc)
                record = self._not_run_record(
                    bundle,
                    status=FrontierCallStatus.NOT_RUN_MODEL_UNAVAILABLE,
                    error=type(exc).__name__,
                )
                raise FrontierUnavailableError(
                    "OpenAI-compatible Chat Completions client is unavailable",
                    status=record.status,
                ) from exc

        self._calls_started += 1
        started = time.perf_counter()
        try:
            completions = cast(Any, client).chat.completions
            response = completions.parse(
                model=FRONTIER_MODEL,
                messages=list(bundle.messages),
                reasoning_effort=self.reasoning_effort,
                max_completion_tokens=self.max_output_tokens,
                response_format=bundle.output_model,
            )
        except Exception as exc:
            self._capture_error(exc)
            record = FrontierCallRecord(
                status=FrontierCallStatus.FAILED_PROVIDER_CALL,
                requested_model=FRONTIER_MODEL,
                response_model=None,
                response_model_version=None,
                response_id=None,
                requested_reasoning_effort=self.reasoning_effort,
                reasoning_tokens=None,
                input_tokens=0,
                output_tokens=0,
                latency_ms=max(
                    0,
                    round((time.perf_counter() - started) * 1000),
                ),
                estimated_cost_usd=estimate.per_call_cost_usd,
                actual_cost_usd=None,
                prompt_fingerprint=bundle.prompt_fingerprint,
                schema_fingerprint=bundle.schema_fingerprint,
                error=type(exc).__name__,
            )
            self._last_call = record
            raise FrontierProviderCallError(
                "Terra Chat Completions call started but returned no auditable result",
                status=FrontierCallStatus.FAILED_PROVIDER_CALL,
            ) from exc

        try:
            record = _record_response(
                response,
                bundle=bundle,
                estimate=estimate,
                requested_reasoning_effort=self.reasoning_effort,
                latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
            )
        except FrontierResponseValidationError as exc:
            self._capture_error(exc, response=response)
            record = FrontierCallRecord(
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                requested_model=FRONTIER_MODEL,
                response_model=_optional_string(_field(response, "model")),
                response_model_version=_optional_string(
                    _field(response, "model_version")
                ),
                response_id=_optional_string(_field(response, "id")),
                requested_reasoning_effort=self.reasoning_effort,
                reasoning_tokens=None,
                input_tokens=0,
                output_tokens=0,
                latency_ms=max(
                    0,
                    round((time.perf_counter() - started) * 1000),
                ),
                estimated_cost_usd=estimate.per_call_cost_usd,
                actual_cost_usd=None,
                prompt_fingerprint=bundle.prompt_fingerprint,
                schema_fingerprint=bundle.schema_fingerprint,
                error=str(exc),
            )
            self._last_call = record
            raise
        self._last_call = record
        if record.response_id is None:
            self._capture_error_evidence(
                FrontierErrorEvidence(
                    error_class="MissingResponseId",
                    status_code=None,
                    request_id=None,
                    provider_code=None,
                    provider_type=None,
                    provider_param=None,
                    call_index=self._calls_started,
                )
            )
            self._finish(
                record,
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                error="response ID metadata is missing",
            )
            raise FrontierResponseValidationError(
                "frontier response did not include response ID metadata",
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
            )
        if record.response_model is None:
            self._capture_metadata_error("MissingResponseModel")
            self._finish(
                record,
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                error="response model metadata is missing",
            )
            raise FrontierResponseValidationError(
                "frontier response did not include model metadata",
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
            )
        if not (
            record.response_model == FRONTIER_MODEL
            or record.response_model.startswith(f"{FRONTIER_MODEL}-")
        ):
            self._capture_metadata_error("ResponseModelMismatch")
            self._finish(
                record,
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                error="response model does not match the frozen frontier model",
            )
            raise FrontierResponseValidationError(
                f"frontier response model does not match {FRONTIER_MODEL}",
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
            )
        if (
            record.input_tokens > self.input_token_cap
            or record.output_tokens > self.output_token_cap
        ):
            self._capture_metadata_error("UsageCapExceeded")
            self._finish(
                record,
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                error="response usage exceeded the frozen token caps",
            )
            raise FrontierResponseValidationError(
                "frontier response usage exceeded token caps",
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
            )
        return response, record

    def _not_run_record(
        self,
        bundle: PromptBundle,
        *,
        status: FrontierCallStatus,
        error: str,
    ) -> FrontierCallRecord:
        record = FrontierCallRecord(
            status=status,
            requested_model=FRONTIER_MODEL,
            response_model=None,
            response_model_version=None,
            response_id=None,
            requested_reasoning_effort=self.reasoning_effort,
            reasoning_tokens=None,
            input_tokens=0,
            output_tokens=0,
            latency_ms=None,
            estimated_cost_usd=self.cost_estimate.per_call_cost_usd,
            actual_cost_usd=None,
            prompt_fingerprint=bundle.prompt_fingerprint,
            schema_fingerprint=bundle.schema_fingerprint,
            error=error,
        )
        self._last_call = record
        return record

    def _capture_error(
        self,
        error: BaseException,
        *,
        response: object | None = None,
    ) -> None:
        self._capture_error_evidence(
            _provider_error_evidence(
                error,
                response=response,
                call_index=self._calls_started or None,
            )
        )

    def _capture_metadata_error(self, error_class: str) -> None:
        self._capture_error_evidence(
            FrontierErrorEvidence(
                error_class=error_class,
                status_code=None,
                request_id=None,
                provider_code=None,
                provider_type=None,
                provider_param=None,
                call_index=self._calls_started or None,
            )
        )

    def _capture_error_evidence(self, detail: FrontierErrorEvidence) -> None:
        self._last_error = detail
        self._error_history.append(detail)

    def _finish(
        self,
        record: FrontierCallRecord,
        *,
        status: FrontierCallStatus,
        error: str | None = None,
    ) -> None:
        self._last_call = replace(record, status=status, error=error)


def estimate_frontier_cost(
    *,
    input_token_cap: int,
    output_token_cap: int,
    call_cap: int,
    usd_ceiling: float,
) -> FrontierCostEstimate:
    """Conservatively estimate cost before any hosted call."""

    for value, name in (
        (input_token_cap, "input_token_cap"),
        (output_token_cap, "output_token_cap"),
        (call_cap, "call_cap"),
    ):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if usd_ceiling < 0:
        raise ValueError("usd_ceiling must be non-negative")
    per_call = (
        input_token_cap * INPUT_PRICE_USD_PER_MILLION / 1_000_000
        + output_token_cap * OUTPUT_PRICE_USD_PER_MILLION / 1_000_000
    )
    return FrontierCostEstimate(
        input_token_cap=input_token_cap,
        output_token_cap=output_token_cap,
        call_cap=call_cap,
        per_call_cost_usd=per_call,
        maximum_cost_usd=per_call * call_cap,
        usd_ceiling=float(usd_ceiling),
    )


def build_fast_prompt(view: FastModelView) -> PromptBundle:
    if not isinstance(view, FastModelView):
        raise TypeError("Fast prompt builder accepts only FastModelView")
    payload = view.model_dump(mode="json")
    _assert_prompt_allowlist(payload)
    schema = cast(dict[str, object], FastStructuredOutput.model_json_schema())
    messages: tuple[dict[str, object], ...] = (
        {
            "role": "system",
            "content": (
                "Return one strict semantic Fast proposal. Infrastructure IDs, "
                "timestamps, and current pins are compiled outside the model. "
                "Set action_intent to null. Do not authorize or execute."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"typed_fast_view": payload},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        },
    )
    return _bundle(messages, schema, FastStructuredOutput)


def build_slow_prompt(request: SlowWorkRequest) -> PromptBundle:
    if not isinstance(request, SlowWorkRequest):
        raise TypeError("Slow prompt builder accepts only SlowWorkRequest")
    payload = request.model_dump(mode="json")
    _assert_prompt_allowlist(payload)
    schema = cast(dict[str, object], SlowModelOutput.model_json_schema())
    messages: tuple[dict[str, object], ...] = (
        {
            "role": "system",
            "content": (
                "Return one strict semantic Slow strategy and one optional "
                "next_capability. Hard-constraint IDs, soft-preference IDs, offer "
                "IDs, timestamps, pins, and inert ActionIntent proposals are "
                "compiled outside the model. ranked_preference_positions and "
                "accept_offer.offer_position are zero-based positions in the "
                "visible constraint/offer lists. Propose only; do not authorize "
                "or execute."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"typed_slow_request": payload},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        },
    )
    return _bundle(messages, schema, SlowModelOutput)


def build_probe_prompt(label: str) -> PromptBundle:
    """Build a fixed synthetic probe that contains no evaluation payload."""

    if not label or len(label) > 64:
        raise ValueError("probe label must contain 1-64 characters")
    schema = cast(dict[str, object], ProviderProbeOutput.model_json_schema())
    messages: tuple[dict[str, object], ...] = (
        {
            "role": "system",
            "content": "Return the requested strict probe object and nothing else.",
        },
        {
            "role": "user",
            "content": json.dumps(
                {"ok": True, "label": label},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        },
    )
    return _bundle(messages, schema, ProviderProbeOutput)


def _bundle(
    messages: tuple[dict[str, object], ...],
    schema: dict[str, object],
    output_model: type[BaseModel],
) -> PromptBundle:
    prompt_fingerprint = _fingerprint(messages)
    schema_fingerprint = _fingerprint(schema)
    return PromptBundle(
        messages=messages,
        output_schema=schema,
        prompt_fingerprint=prompt_fingerprint,
        schema_fingerprint=schema_fingerprint,
        output_model=output_model,
    )


def _assert_prompt_allowlist(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in FORBIDDEN_PROMPT_KEYS:
                raise ValueError(f"forbidden prompt field: {key}")
            _assert_prompt_allowlist(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            _assert_prompt_allowlist(child)


def _validate_slow_binding(
    request: SlowWorkRequest,
    result: SlowWorkResult,
) -> None:
    if result.request_id != request.request_id:
        raise ValueError("Slow result request binding is stale")
    if result.case_id != request.case_id:
        raise ValueError("Slow result case binding is stale")
    if result.pins != request.pins:
        raise ValueError("Slow result pins are stale")
    if result.planning_basis != request.planning_basis:
        raise ValueError("Slow result planning basis is stale")


def _parsed_output(response: object, model: type[BaseModel]) -> Any:
    """Accept only the SDK parse helper's typed first-choice value."""

    choices = _field(response, "choices")
    first = choices[0] if isinstance(choices, Sequence) and choices else None
    parsed = _field(_field(first, "message"), "parsed")
    if not isinstance(parsed, model):
        raise ValueError(
            "Chat Completions parsed output is missing or has the wrong type"
        )
    return parsed


def _raw_message_content(response: object) -> str | None:
    choices = _field(response, "choices")
    first = choices[0] if isinstance(choices, Sequence) and choices else None
    content = _field(_field(first, "message"), "content")
    return content if isinstance(content, str) and content else None


def _structured_output_text(value: BaseModel) -> str:
    return json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _record_response(
    response: object,
    *,
    bundle: PromptBundle,
    estimate: FrontierCostEstimate,
    requested_reasoning_effort: str,
    latency_ms: int,
) -> FrontierCallRecord:
    usage = _field(response, "usage")
    input_tokens = _integer_field(usage, "prompt_tokens")
    output_tokens = _integer_field(usage, "completion_tokens")
    details = _field(usage, "completion_tokens_details")
    reasoning_tokens = _optional_nonnegative_integer(
        _field(details, "reasoning_tokens")
    )
    actual_cost = (
        input_tokens * INPUT_PRICE_USD_PER_MILLION / 1_000_000
        + output_tokens * OUTPUT_PRICE_USD_PER_MILLION / 1_000_000
    )
    response_model = _optional_string(_field(response, "model"))
    response_model_version = None
    if response_model not in {None, FRONTIER_MODEL}:
        response_model_version = response_model
    return FrontierCallRecord(
        status=FrontierCallStatus.SUCCEEDED,
        requested_model=FRONTIER_MODEL,
        response_model=response_model,
        response_model_version=response_model_version,
        response_id=_optional_string(_field(response, "id")),
        requested_reasoning_effort=requested_reasoning_effort,
        reasoning_tokens=reasoning_tokens,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        estimated_cost_usd=estimate.per_call_cost_usd,
        actual_cost_usd=actual_cost,
        prompt_fingerprint=bundle.prompt_fingerprint,
        schema_fingerprint=bundle.schema_fingerprint,
    )


def _field(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _integer_field(value: object, name: str) -> int:
    field = _field(value, name)
    if type(field) is not int or field < 0:
        raise FrontierResponseValidationError(
            f"Chat Completions usage field {name} is missing",
            status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
        )
    return field


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_nonnegative_integer(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise FrontierResponseValidationError(
            "Chat Completions reasoning token usage is invalid",
            status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
        )
    return value


def _provider_error_evidence(
    error: BaseException,
    *,
    response: object | None = None,
    call_index: int | None = None,
) -> FrontierErrorEvidence:
    body = getattr(error, "body", None)
    detail: Mapping[object, object] | None = body if isinstance(body, Mapping) else None
    if detail is not None and isinstance(detail.get("error"), Mapping):
        detail = cast(Mapping[object, object], detail["error"])

    def text_field(name: str) -> str | None:
        if detail is None:
            return None
        value = detail.get(name)
        return _sanitize_provider_text(value) if isinstance(value, str) else None

    status = getattr(error, "status_code", None)
    status_code = (
        status if isinstance(status, int) and not isinstance(status, bool) else None
    )
    request_id = getattr(error, "request_id", None)
    if not isinstance(request_id, str):
        request_id = _optional_string(_field(response, "_request_id"))
    return FrontierErrorEvidence(
        error_class=type(error).__name__,
        status_code=status_code,
        request_id=_sanitize_provider_text(request_id) if request_id else None,
        provider_code=text_field("code"),
        provider_type=text_field("type"),
        provider_param=text_field("param"),
        call_index=call_index,
    )


def _sanitize_provider_text(value: str) -> str:
    bounded = value[:512]
    secret = os.environ.get(FRONTIER_API_KEY_ENV)
    if secret:
        bounded = bounded.replace(secret, "[REDACTED]")
    bounded = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", bounded)
    return re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", bounded)


def _fingerprint(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "FORBIDDEN_PROMPT_KEYS",
    "FRONTIER_API_KEY_ENV",
    "FRONTIER_BASE_URL",
    "FRONTIER_MODEL",
    "FRONTIER_PROVIDER",
    "FRONTIER_RUNTIME",
    "FastStructuredOutput",
    "FrontierAdapterError",
    "FrontierBudgetExceededError",
    "FrontierCallRecord",
    "FrontierCallStatus",
    "FrontierCostEstimate",
    "FrontierErrorEvidence",
    "FrontierProviderCallError",
    "FrontierResponseValidationError",
    "FrontierUnavailableError",
    "OpenAIFrontierAdapter",
    "PromptBundle",
    "ProviderProbeOutput",
    "build_fast_prompt",
    "build_probe_prompt",
    "build_slow_prompt",
    "estimate_frontier_cost",
]
