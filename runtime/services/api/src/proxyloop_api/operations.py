"""Allowlisted, API-local observation for one HTTP operation."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Protocol

_LOGGER = logging.getLogger("proxyloop_api.operations")
_LOGGER.setLevel(logging.INFO)
CORRELATION_ID_HEADER = "X-ProxyLoop-Correlation-ID"

ERROR_CATEGORIES = frozenset(
    {
        "none",
        "storage_unavailable",
        "model_configuration",
        "model_timeout",
        "model_transport",
        "model_invalid_output",
        "model_metadata",
        "model_stale_pins",
        "model_result_rejected",
        "case_not_found",
        "request_invalid",
        "stale_cas",
        "case_conflict",
        "approval_expired",
        "invalid_command",
        "state_invalid",
        "model_path",
        "temporal_unavailable",
        "dependency_not_ready",
        "internal_error",
        "invalid_fixture_authenticity",
        "stale_unknown_event",
        "malformed_channel_event",
        "unknown_binding",
        "channel_replay_mismatch",
        "channel_conflict",
        "channel_dependency_unavailable",
    }
)

OPERATION_RECORD_FIELDS = frozenset(
    {
        "correlation_id",
        "operation",
        "route",
        "case_id",
        "revision",
        "deterministic_route",
        "adapter_mode",
        "storage_mode",
        "policy_outcome",
        "approval_outcome",
        "execution_outcome",
        "verifier_outcome",
        "error_category",
        "status",
        "latency_ms",
        "channel_kind",
        "channel_event_kind",
        "delivery_state",
    }
)


@dataclass(frozen=True, slots=True)
class OperationRecord:
    """The complete allowlist for one observed API operation."""

    correlation_id: str
    operation: str
    route: str
    case_id: str | None
    revision: int | None
    deterministic_route: str | None
    adapter_mode: str
    storage_mode: str
    policy_outcome: str | None
    approval_outcome: str | None
    execution_outcome: str | None
    verifier_outcome: str | None
    error_category: str
    status: int
    latency_ms: float
    channel_kind: str | None = None
    channel_event_kind: str | None = None
    delivery_state: str | None = None

    def __post_init__(self) -> None:
        if self.error_category not in ERROR_CATEGORIES:
            raise ValueError("operation error category is not allowlisted")

    def as_json(self) -> dict[str, object]:
        """Return an allowlist-only JSON-compatible mapping."""

        return asdict(self)


def _allowlisted_json(operation: OperationRecord) -> dict[str, object]:
    payload = operation.as_json()
    if set(payload) != OPERATION_RECORD_FIELDS:
        raise ValueError("operation record contains an unknown field")
    return payload


class OperationRecorder(Protocol):
    """Small sink interface kept inside the API application module."""

    def record(self, operation: OperationRecord) -> None: ...


class JsonLoggingOperationRecorder:
    """Non-retaining recorder that emits one allowlisted JSON log line."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger if logger is not None else _LOGGER

    def record(self, operation: OperationRecord) -> None:
        payload = _allowlisted_json(operation)
        self._logger.info(json.dumps(payload, sort_keys=True, separators=(",", ":")))


class InMemoryOperationRecorder:
    """Thread-safe test adapter retaining records in process memory."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._records: list[OperationRecord] = []

    def record(self, operation: OperationRecord) -> None:
        _allowlisted_json(operation)
        with self._lock:
            self._records.append(operation)

    @property
    def records(self) -> tuple[OperationRecord, ...]:
        with self._lock:
            return tuple(self._records)

    def json_records(self) -> tuple[Mapping[str, object], ...]:
        return tuple(record.as_json() for record in self.records)


__all__ = [
    "CORRELATION_ID_HEADER",
    "ERROR_CATEGORIES",
    "OPERATION_RECORD_FIELDS",
    "InMemoryOperationRecorder",
    "JsonLoggingOperationRecorder",
    "OperationRecord",
    "OperationRecorder",
]
