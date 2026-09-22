"""Phase 03C Stage 1b hosted teacher adapter on the OpenAI-compatible relay.

The teacher sends exactly the Phase 03C Fast prompt that
``Phase03CQwenAdapter.build_prompt`` produces for the configured
``prompt_version`` (Stage 1c default v6), so training prompts cannot drift
from evaluation prompts.  It samples ``k`` independent Chat Completions calls
per view, returns the raw JSON-object strings for strict downstream parsing,
and keeps a per-model ledger whose USD figures are an accounted estimate: the
relay does not expose prices, so returned usage is multiplied by the
user-maintained ``ml/configs/teacher-rates.json``.

The OpenAI SDK is imported only when no client is injected.  Tests inject a
fake ``chat.completions.create`` client and never need credentials or network
access.  There are no retries, no streaming, and no policy or completion
authority here.  One circuit breaker exists: a hard relay error (401/403) or
``CONSECUTIVE_FAILURE_LIMIT`` failed calls in a row sets ``stop_reason`` and
every later ``sample`` call raises ``TeacherStoppedError`` before reserving
or sending anything, so an outage cannot burn the whole budget at the
worst-case failed-call charge.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, cast

from proxyloop_contracts import FastModelView

from .fast_output import FastModelOutput
from .openai_frontier import (
    FRONTIER_API_KEY_ENV,
    FRONTIER_BASE_URL,
    FrontierAdapterError,
    FrontierBudgetExceededError,
    FrontierCallRecord,
    FrontierCallStatus,
    FrontierErrorEvidence,
    FrontierUnavailableError,
    _field,
    _optional_string,
    _provider_error_evidence,
)
from .phase03c_experiment import PromptVersion
from .phase03c_prompt_set import STAGE1B_PROMPT_VERSION, prompt_builder

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TEACHER_RATES_PATH = ROOT / "ml" / "configs" / "teacher-rates.json"
TEACHER_RATES_LABEL = "ml/configs/teacher-rates.json"
TEACHER_ACCOUNTING_LABEL = (
    "estimate; relay prices not exposed; rates from ml/configs/teacher-rates.json; "
    "failed calls and calls with missing usage are charged at the pre-call worst "
    "case, so a relay outage inflates the estimate and the ledger must be reset "
    "deliberately before a rerun: --reset-failed-charges rebuilds it from the "
    "samples JSONL, keeping each succeeded call's recorded estimate and counting "
    "failed calls at zero"
)
TEACHER_TIMEOUT_SECONDS = 60
# Circuit breaker: these relay responses mean every further call will fail
# the same way, so the batch stops instead of paying the worst case per call.
HARD_ERROR_STATUS_CODES: Final = frozenset({401, 403})
HARD_ERROR_CLASSES: Final = frozenset({"AuthenticationError", "PermissionDeniedError"})
CONSECUTIVE_FAILURE_LIMIT: Final = 5
# Pre-call worst case: prompt characters divided by this many characters per
# token, plus the full output budget.  Deliberately coarse and conservative.
PROMPT_CHARS_PER_TOKEN = 3


class TeacherCredentialError(FrontierUnavailableError):
    """The configured API key environment variable is absent."""


class TeacherBudgetExceededError(FrontierBudgetExceededError):
    """The pre-call ledger gate rejected a call; nothing was sent."""

    def __init__(
        self,
        message: str,
        *,
        completed: tuple[TeacherSample, ...] = (),
    ) -> None:
        super().__init__(message, status=FrontierCallStatus.NOT_RUN_BUDGET_EXCEEDED)
        self.completed = completed


class TeacherStoppedError(FrontierAdapterError):
    """The circuit breaker tripped; the remaining calls were never sent."""

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        completed: tuple[TeacherSample, ...] = (),
    ) -> None:
        super().__init__(message, status=FrontierCallStatus.FAILED_PROVIDER_CALL)
        self.reason = reason
        self.completed = completed


@dataclass(frozen=True, slots=True)
class TeacherRate:
    """USD per one million tokens for one relay model id."""

    model: str
    input_usd_per_million: float
    output_usd_per_million: float

    def cost_usd(self, *, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_usd_per_million / 1_000_000
            + output_tokens * self.output_usd_per_million / 1_000_000
        )


def load_teacher_rate(model: str, rates_path: Path) -> TeacherRate:
    """Read one model's rate from the user-maintained rates file."""

    with rates_path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    rates = _field(document, "rates")
    entry = _field(rates, model)
    if entry is None:
        raise ValueError(f"no teacher rate for {model!r} in {rates_path}")
    return TeacherRate(
        model=model,
        input_usd_per_million=_rate_number(_field(entry, "input"), model, "input"),
        output_usd_per_million=_rate_number(_field(entry, "output"), model, "output"),
    )


def _rate_number(value: object, model: str, name: str) -> float:
    if type(value) not in {int, float} or cast(float, value) < 0:
        raise ValueError(f"teacher rate {name} for {model!r} must be non-negative")
    return float(cast(float, value))


@dataclass(slots=True)
class TeacherModelTotals:
    calls: int = 0
    succeeded: int = 0
    failed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_usd: float = 0.0


@dataclass(slots=True)
class TeacherLedger:
    """Accumulated per-model usage and estimated USD across all sampled calls.

    Thread-safe: concurrent samplers share one ledger, and a call is admitted
    only by ``reserve`` (worst case, atomic with the ceiling check) and then
    settled by ``record`` to the actual cost, so N workers can never jointly
    exceed ``usd_ceiling``.
    """

    usd_ceiling: float
    rates_path: Path = DEFAULT_TEACHER_RATES_PATH
    per_model: dict[str, TeacherModelTotals] = field(default_factory=dict)
    reserved_usd: float = 0.0
    # Why the last sampling run over this ledger stopped early (``None`` when
    # it ran to completion): ``budget_exceeded``, ``hard_error:<class>``, or
    # ``consecutive_failures``.  Set by the sampling pipeline, not here.
    stop_reason: str | None = None
    _lock: threading.RLock = field(
        default_factory=threading.RLock, repr=False, compare=False
    )

    @property
    def total_estimated_usd(self) -> float:
        with self._lock:
            return sum(item.estimated_usd for item in self.per_model.values())

    @property
    def total_calls(self) -> int:
        with self._lock:
            return sum(item.calls for item in self.per_model.values())

    def would_exceed(self, worst_case_usd: float) -> bool:
        with self._lock:
            return (
                self.total_estimated_usd
                + self.reserved_usd
                + worst_case_usd
                - self.usd_ceiling
                > 1e-12
            )

    def reserve(self, worst_case_usd: float) -> bool:
        """Admit one call by holding its worst case; ``False`` sends nothing."""

        with self._lock:
            if self.would_exceed(worst_case_usd):
                return False
            self.reserved_usd += worst_case_usd
            return True

    def release(self, reserved_usd: float) -> None:
        """Give back a reservation whose call was never started."""

        with self._lock:
            self._settle(reserved_usd)

    def _settle(self, reserved_usd: float) -> None:
        # Caller holds the lock.  Snap float residue so a fully settled
        # ledger reports exactly zero outstanding reservation.
        remaining = self.reserved_usd - reserved_usd
        self.reserved_usd = remaining if remaining > 1e-12 else 0.0

    def record(self, record: FrontierCallRecord, *, reserved_usd: float = 0.0) -> None:
        with self._lock:
            self._settle(reserved_usd)
            totals = self.per_model.setdefault(
                record.requested_model, TeacherModelTotals()
            )
            totals.calls += 1
            if record.status is FrontierCallStatus.SUCCEEDED:
                totals.succeeded += 1
            else:
                totals.failed += 1
            totals.input_tokens += record.input_tokens
            totals.output_tokens += record.output_tokens
            totals.estimated_usd += record.estimated_cost_usd

    def to_dict(self) -> dict[str, object]:
        with self._lock:
            return {
                "accounting": TEACHER_ACCOUNTING_LABEL,
                "rates_path": TEACHER_RATES_LABEL,
                "usd_ceiling": self.usd_ceiling,
                "total_calls": self.total_calls,
                "total_estimated_usd": self.total_estimated_usd,
                "stop_reason": self.stop_reason,
                "per_model": {
                    model: {
                        "calls": totals.calls,
                        "succeeded": totals.succeeded,
                        "failed": totals.failed,
                        "input_tokens": totals.input_tokens,
                        "output_tokens": totals.output_tokens,
                        "estimated_usd": totals.estimated_usd,
                    }
                    for model, totals in sorted(self.per_model.items())
                },
            }


@dataclass(frozen=True, slots=True)
class TeacherSample:
    """One attempted teacher call: raw content (if any) plus redacted provenance."""

    call_index: int
    content: str | None
    record: FrontierCallRecord
    error: FrontierErrorEvidence | None = None
    finish_reason: str | None = None
    usage_missing: bool = False


@dataclass(frozen=True, slots=True)
class TeacherSampleBatch:
    model: str
    seed_tag: str
    prompt_fingerprint: str
    schema_fingerprint: str
    samples: tuple[TeacherSample, ...]

    @property
    def contents(self) -> tuple[str, ...]:
        return tuple(s.content for s in self.samples if s.content is not None)

    @property
    def records(self) -> tuple[FrontierCallRecord, ...]:
        return tuple(s.record for s in self.samples)


class RelayTeacherAdapter:
    """Sample raw Fast-prompt completions from one relay model under a USD ceiling."""

    def __init__(
        self,
        *,
        model: str,
        client: object | None = None,
        temperature: float = 0.7,
        max_output_tokens: int = 512,
        usd_ceiling: float,
        rates_path: Path = DEFAULT_TEACHER_RATES_PATH,
        api_key_env: str = FRONTIER_API_KEY_ENV,
        base_url: str = FRONTIER_BASE_URL,
        ledger: TeacherLedger | None = None,
        prompt_version: PromptVersion = STAGE1B_PROMPT_VERSION,
    ) -> None:
        if not model:
            raise ValueError("model must be a non-empty relay model id")
        if type(max_output_tokens) is not int or max_output_tokens < 1:
            raise ValueError("max_output_tokens must be a positive integer")
        if type(usd_ceiling) not in {int, float} or usd_ceiling < 0:
            raise ValueError("usd_ceiling must be non-negative")
        self.model = model
        self.temperature = float(temperature)
        self.max_output_tokens = max_output_tokens
        self.usd_ceiling = float(usd_ceiling)
        self.rate = load_teacher_rate(model, rates_path)
        self.api_key_env = api_key_env
        self.base_url = base_url
        self.ledger = (
            ledger
            if ledger is not None
            else TeacherLedger(usd_ceiling=self.usd_ceiling, rates_path=rates_path)
        )
        self._client = client
        self._prompt_adapter = prompt_builder(prompt_version)
        self._schema_fingerprint = _fingerprint(FastModelOutput.model_json_schema())
        self._calls_started = 0
        self._consecutive_failures = 0
        self._stop_reason: str | None = None
        # Guards lazy client creation, the call counter, and the circuit
        # breaker across workers.
        self._lock = threading.Lock()

    @property
    def calls_started(self) -> int:
        return self._calls_started

    @property
    def stop_reason(self) -> str | None:
        """Why the circuit breaker tripped, or ``None`` while calls may go on."""

        return self._stop_reason

    @property
    def schema_fingerprint(self) -> str:
        return self._schema_fingerprint

    @property
    def prompt_version(self) -> PromptVersion:
        return self._prompt_adapter.prompt_version

    @property
    def compiler_version(self) -> str:
        return self._prompt_adapter.compiler_version

    def worst_case_call_usd(self, view: FastModelView) -> float:
        prompt = self._prompt_adapter.build_prompt(view)
        prompt_tokens = math.ceil(
            (len(prompt.system) + len(prompt.user)) / PROMPT_CHARS_PER_TOKEN
        )
        return self.rate.cost_usd(
            input_tokens=prompt_tokens,
            output_tokens=self.max_output_tokens,
        )

    def sample(
        self,
        view: FastModelView,
        *,
        k: int,
        seed_tag: str,
    ) -> TeacherSampleBatch:
        """Send ``k`` independent calls with the exact Fast prompt for one view."""

        if not isinstance(view, FastModelView):
            raise TypeError("teacher adapter accepts only FastModelView")
        if type(k) is not int or k < 1:
            raise ValueError("k must be a positive integer")
        prompt = self._prompt_adapter.build_prompt(view)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ]
        worst_case = self.worst_case_call_usd(view)
        samples: list[TeacherSample] = []
        for call_index in range(k):
            if self._stop_reason is not None:
                raise TeacherStoppedError(
                    f"teacher stopped: {self._stop_reason}",
                    reason=self._stop_reason,
                    completed=tuple(samples),
                )
            # Reserve the worst case atomically with the ceiling check; the
            # call settles it to the actual cost (or keeps it on failure).
            if not self.ledger.reserve(worst_case):
                raise TeacherBudgetExceededError(
                    f"teacher ledger ${self.ledger.total_estimated_usd:.6f} plus "
                    f"worst-case call ${worst_case:.6f} exceeds ceiling "
                    f"${self.usd_ceiling:.6f}",
                    completed=tuple(samples),
                )
            try:
                client = self._ensure_client()
            except BaseException:
                self.ledger.release(worst_case)
                raise
            samples.append(
                self._call(
                    client,
                    messages,
                    call_index=call_index,
                    prompt_fingerprint=prompt.fingerprint,
                    worst_case=worst_case,
                )
            )
        return TeacherSampleBatch(
            model=self.model,
            seed_tag=seed_tag,
            prompt_fingerprint=prompt.fingerprint,
            schema_fingerprint=self._schema_fingerprint,
            samples=tuple(samples),
        )

    def _ensure_client(self) -> object:
        with self._lock:
            return self._ensure_client_locked()

    def _ensure_client_locked(self) -> object:
        if self._client is not None:
            return self._client
        if not os.environ.get(self.api_key_env):
            raise TeacherCredentialError(
                f"{self.api_key_env} is not present in the process environment",
                status=FrontierCallStatus.NOT_RUN_MISSING_CREDENTIALS,
            )
        try:
            # Keep the provider SDK optional and out of the import path for
            # all deterministic tests and runtime packages.
            openai_module = cast(Any, importlib.import_module("openai"))
            client = openai_module.OpenAI(
                api_key=os.environ[self.api_key_env],
                base_url=self.base_url,
                max_retries=0,
                timeout=TEACHER_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            raise FrontierUnavailableError(
                "OpenAI-compatible Chat Completions client is unavailable",
                status=FrontierCallStatus.NOT_RUN_MODEL_UNAVAILABLE,
            ) from exc
        self._client = client
        return client

    def _call(
        self,
        client: object,
        messages: list[dict[str, str]],
        *,
        call_index: int,
        prompt_fingerprint: str,
        worst_case: float,
    ) -> TeacherSample:
        with self._lock:
            self._calls_started += 1
            calls_started = self._calls_started
        started = time.perf_counter()
        try:
            response = cast(Any, client).chat.completions.create(
                model=self.model,
                messages=[dict(item) for item in messages],
                temperature=self.temperature,
                max_tokens=self.max_output_tokens,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            evidence = _redact(
                _provider_error_evidence(exc, call_index=calls_started),
                os.environ.get(self.api_key_env),
            )
            record = self._failed_record(
                status=FrontierCallStatus.FAILED_PROVIDER_CALL,
                error=type(exc).__name__,
                latency_ms=_elapsed_ms(started),
                prompt_fingerprint=prompt_fingerprint,
                worst_case=worst_case,
            )
            self.ledger.record(record, reserved_usd=worst_case)
            self._note_failure(evidence)
            return TeacherSample(
                call_index=call_index,
                content=None,
                record=record,
                error=evidence,
            )
        latency_ms = _elapsed_ms(started)
        content = _raw_content(response)
        finish_reason = _finish_reason(response)
        usage = _field(response, "usage")
        input_tokens = _field(usage, "prompt_tokens")
        output_tokens = _field(usage, "completion_tokens")
        usage_missing = not (
            _nonnegative_int(input_tokens) and _nonnegative_int(output_tokens)
        )
        if content is None:
            record = self._failed_record(
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                error="MissingContent",
                latency_ms=latency_ms,
                prompt_fingerprint=prompt_fingerprint,
                worst_case=worst_case,
                response=response,
            )
            self.ledger.record(record, reserved_usd=worst_case)
            self._note_failure(None)
            return TeacherSample(
                call_index=call_index,
                content=None,
                record=record,
                error=_local_error("MissingContent", call_index=calls_started),
                finish_reason=finish_reason,
                usage_missing=usage_missing,
            )
        if usage_missing:
            # Keep the paid-for content; the ledger charges the worst case
            # because the relay did not say what the call consumed.
            record = self._failed_record(
                status=FrontierCallStatus.SUCCEEDED,
                error="MissingUsage",
                latency_ms=latency_ms,
                prompt_fingerprint=prompt_fingerprint,
                worst_case=worst_case,
                response=response,
            )
            self.ledger.record(record, reserved_usd=worst_case)
            self._note_success()
            return TeacherSample(
                call_index=call_index,
                content=content,
                record=record,
                error=_local_error("MissingUsage", call_index=calls_started),
                finish_reason=finish_reason,
                usage_missing=True,
            )
        input_count = cast(int, input_tokens)
        output_count = cast(int, output_tokens)
        response_model = _optional_string(_field(response, "model"))
        record = FrontierCallRecord(
            status=FrontierCallStatus.SUCCEEDED,
            requested_model=self.model,
            response_model=response_model,
            response_model_version=(
                response_model if response_model not in {None, self.model} else None
            ),
            response_id=_optional_string(_field(response, "id")),
            requested_reasoning_effort="none",
            reasoning_tokens=None,
            input_tokens=input_count,
            output_tokens=output_count,
            latency_ms=latency_ms,
            estimated_cost_usd=self.rate.cost_usd(
                input_tokens=input_count,
                output_tokens=output_count,
            ),
            actual_cost_usd=None,
            prompt_fingerprint=prompt_fingerprint,
            schema_fingerprint=self._schema_fingerprint,
        )
        self.ledger.record(record, reserved_usd=worst_case)
        self._note_success()
        return TeacherSample(
            call_index=call_index,
            content=content,
            record=record,
            finish_reason=finish_reason,
        )

    def _note_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0

    def _note_failure(self, evidence: FrontierErrorEvidence | None) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._stop_reason is not None:
                return
            if evidence is not None and (
                evidence.status_code in HARD_ERROR_STATUS_CODES
                or evidence.error_class in HARD_ERROR_CLASSES
            ):
                self._stop_reason = f"hard_error:{evidence.error_class}"
            elif self._consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                self._stop_reason = "consecutive_failures"

    def _failed_record(
        self,
        *,
        status: FrontierCallStatus,
        error: str,
        latency_ms: int,
        prompt_fingerprint: str,
        worst_case: float,
        response: object | None = None,
    ) -> FrontierCallRecord:
        # A failed call (or one whose usage the relay did not report) may
        # still have consumed relay quota; charge the pre-call worst case so
        # the ledger stays an upper bound.
        return FrontierCallRecord(
            status=status,
            requested_model=self.model,
            response_model=_optional_string(_field(response, "model")),
            response_model_version=None,
            response_id=_optional_string(_field(response, "id")),
            requested_reasoning_effort="none",
            reasoning_tokens=None,
            input_tokens=0,
            output_tokens=0,
            latency_ms=latency_ms,
            estimated_cost_usd=worst_case,
            actual_cost_usd=None,
            prompt_fingerprint=prompt_fingerprint,
            schema_fingerprint=self._schema_fingerprint,
            error=error,
        )


def _redact(
    evidence: FrontierErrorEvidence, secret: str | None
) -> FrontierErrorEvidence:
    """Also strip the configured key when it is not the frozen frontier env."""

    if not secret:
        return evidence

    def strip(value: str | None) -> str | None:
        return value.replace(secret, "[REDACTED]") if value else value

    return replace(
        evidence,
        request_id=strip(evidence.request_id),
        provider_code=strip(evidence.provider_code),
        provider_type=strip(evidence.provider_type),
        provider_param=strip(evidence.provider_param),
    )


def _local_error(error_class: str, *, call_index: int) -> FrontierErrorEvidence:
    return FrontierErrorEvidence(
        error_class=error_class,
        status_code=None,
        request_id=None,
        provider_code=None,
        provider_type=None,
        provider_param=None,
        call_index=call_index,
    )


def _finish_reason(response: object) -> str | None:
    choices = _field(response, "choices")
    first = choices[0] if isinstance(choices, list | tuple) and choices else None
    return _optional_string(_field(first, "finish_reason"))


def _raw_content(response: object) -> str | None:
    choices = _field(response, "choices")
    first = choices[0] if isinstance(choices, list | tuple) and choices else None
    content = _field(_field(first, "message"), "content")
    return content if isinstance(content, str) and content else None


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _fingerprint(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "CONSECUTIVE_FAILURE_LIMIT",
    "DEFAULT_TEACHER_RATES_PATH",
    "HARD_ERROR_CLASSES",
    "HARD_ERROR_STATUS_CODES",
    "PROMPT_CHARS_PER_TOKEN",
    "TEACHER_ACCOUNTING_LABEL",
    "TEACHER_TIMEOUT_SECONDS",
    "RelayTeacherAdapter",
    "TeacherBudgetExceededError",
    "TeacherCredentialError",
    "TeacherLedger",
    "TeacherModelTotals",
    "TeacherRate",
    "TeacherSample",
    "TeacherSampleBatch",
    "TeacherStoppedError",
    "load_teacher_rate",
]
