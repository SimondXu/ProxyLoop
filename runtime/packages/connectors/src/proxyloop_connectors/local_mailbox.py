"""Credential-free raw-byte verification and deterministic mailbox adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import Lock
from typing import Protocol
from uuid import RFC_4122, UUID

CHANNEL_KIND = "local_mailbox"
BINDING_REF = "fictional-provider-local-mailbox"
SCHEMA_VERSION = "local-mailbox-v1"
FRESHNESS_WINDOW = timedelta(minutes=5)


class LocalMailboxEventKind(StrEnum):
    PROVIDER_MESSAGE = "provider_message"
    DELIVERY = "delivery"


class DeliveryObservationState(StrEnum):
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    UNKNOWN = "unknown"


class LocalMailboxVerificationError(ValueError):
    """Stable verifier category; never includes raw input or header values."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


class DeliveryAdapterConflict(RuntimeError):
    """A delivery identity was reused with different immutable semantics."""


@dataclass(frozen=True, slots=True)
class VerifiedLocalMailboxEvent:
    """Allowlisted, already-verified channel event data."""

    event_id: UUID
    binding_ref: str
    occurred_at: datetime
    kind: LocalMailboxEventKind
    raw_payload_hash: str
    content: str | None = None
    delivery_id: UUID | None = None
    provider_message_id: str | None = None
    delivery_status: str | None = None
    fixture_timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class DeliveryAttempt:
    """Exact immutable attempt loaded from the authoritative OutboxRecord."""

    delivery_id: UUID
    idempotency_key: str
    binding_ref: str
    body: str
    body_hash: str


@dataclass(frozen=True, slots=True)
class DeliveryObservation:
    """A local adapter observation, not a Case completion claim."""

    delivery_id: UUID
    idempotency_key: str
    state: DeliveryObservationState
    provider_message_id: str | None = None
    artifact_hash: str | None = None
    failure_category: str | None = None


@dataclass(frozen=True, slots=True)
class UnknownDelivery:
    delivery_id: UUID
    idempotency_key: str


class DeliveryAdapter(Protocol):
    def send(self, attempt: DeliveryAttempt) -> DeliveryObservation: ...

    def lookup(
        self, attempt: DeliveryAttempt
    ) -> DeliveryObservation | UnknownDelivery: ...


class LocalMailboxAdapter:
    """Deterministic local transport with one stable accepted observation."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._attempts: dict[UUID, DeliveryAttempt] = {}
        self._observations: dict[UUID, DeliveryObservation] = {}

    def send(self, attempt: DeliveryAttempt) -> DeliveryObservation:
        _validate_attempt(attempt)
        with self._lock:
            prior = self._attempts.get(attempt.delivery_id)
            if prior is not None and prior != attempt:
                raise DeliveryAdapterConflict("delivery identity semantics changed")
            if prior is None:
                self._attempts[attempt.delivery_id] = attempt
            observation = self._observations.get(attempt.delivery_id)
            if observation is None:
                observation = _accepted_observation(attempt)
                self._observations[attempt.delivery_id] = observation
            return observation

    def lookup(self, attempt: DeliveryAttempt) -> DeliveryObservation | UnknownDelivery:
        _validate_attempt(attempt)
        with self._lock:
            prior_attempt = self._attempts.get(attempt.delivery_id)
            if prior_attempt is not None and prior_attempt != attempt:
                raise DeliveryAdapterConflict("delivery identity semantics changed")
            observation = self._observations.get(attempt.delivery_id)
            if observation is None:
                return UnknownDelivery(attempt.delivery_id, attempt.idempotency_key)
            elif observation.idempotency_key != attempt.idempotency_key:
                raise DeliveryAdapterConflict("delivery identity semantics changed")
            return observation


class FaultInjectingLocalMailboxAdapter(LocalMailboxAdapter):
    """Deterministic adapter used to prove retry and lost-response behavior."""

    def __init__(
        self,
        *,
        fail_before_accept: int = 0,
        lose_response_after_accept: int = 0,
        retryable_failure_category: str = "channel_dependency_unavailable",
    ) -> None:
        super().__init__()
        self.fail_before_accept = fail_before_accept
        self.lose_response_after_accept = lose_response_after_accept
        self.retryable_failure_category = retryable_failure_category

    def send(self, attempt: DeliveryAttempt) -> DeliveryObservation:
        if self.fail_before_accept > 0:
            self.fail_before_accept -= 1
            raise RuntimeError(self.retryable_failure_category)
        observation = super().send(attempt)
        if self.lose_response_after_accept > 0:
            self.lose_response_after_accept -= 1
            raise TimeoutError("local adapter response lost")
        return observation


def build_fixture_headers(raw_bytes: bytes) -> dict[str, str]:
    """Build conspicuously non-secret fixture headers for local tests."""

    return {
        "X-ProxyLoop-Local-Timestamp": datetime.now(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "X-ProxyLoop-Local-Signature": "sha256="
        + hashlib.sha256(raw_bytes).hexdigest(),
    }


def verify_local_mailbox_event(
    raw_bytes: bytes,
    headers: Mapping[str, str],
    received_at: datetime,
    *,
    require_fresh: bool = True,
) -> VerifiedLocalMailboxEvent:
    """Verify exact fixture bytes, strict JSON shape, and event identity."""

    if received_at.tzinfo is None or received_at.utcoffset() != timedelta(0):
        raise LocalMailboxVerificationError("invalid_fixture_authenticity")
    timestamp_text = _header(headers, "X-ProxyLoop-Local-Timestamp")
    signature = _header(headers, "X-ProxyLoop-Local-Signature")
    fixture_timestamp = _parse_utc(timestamp_text)
    expected_signature = "sha256=" + hashlib.sha256(raw_bytes).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise LocalMailboxVerificationError("invalid_fixture_authenticity")
    if require_fresh and abs(received_at - fixture_timestamp) > FRESHNESS_WINDOW:
        raise LocalMailboxVerificationError("stale_unknown_event")

    try:
        payload = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise LocalMailboxVerificationError("malformed_channel_event") from None
    if not isinstance(payload, dict):
        raise LocalMailboxVerificationError("malformed_channel_event")
    event = _parse_payload(payload, hashlib.sha256(raw_bytes).hexdigest())
    if require_fresh and abs(received_at - event.occurred_at) > FRESHNESS_WINDOW:
        raise LocalMailboxVerificationError("stale_unknown_event")
    return replace(event, fixture_timestamp=fixture_timestamp)


def _parse_payload(
    payload: dict[str, object], payload_hash: str
) -> VerifiedLocalMailboxEvent:
    common = {"schema_version", "event_id", "binding_ref", "occurred_at", "kind"}
    if set(payload) < common or payload.get("schema_version") != SCHEMA_VERSION:
        raise LocalMailboxVerificationError("malformed_channel_event")
    event_id = _uuid4(payload.get("event_id"), "event_id")
    binding_ref = payload.get("binding_ref")
    if binding_ref != BINDING_REF:
        raise LocalMailboxVerificationError("unknown_binding")
    occurred_at = _parse_utc_value(payload.get("occurred_at"))
    kind_value = payload.get("kind")
    if not isinstance(kind_value, str):
        raise LocalMailboxVerificationError("malformed_channel_event")
    try:
        kind = LocalMailboxEventKind(kind_value)
    except (TypeError, ValueError):
        raise LocalMailboxVerificationError("malformed_channel_event") from None
    if kind is LocalMailboxEventKind.PROVIDER_MESSAGE:
        allowed = common | {"content"}
        content_value = payload.get("content")
        if set(payload) != allowed or not isinstance(content_value, str):
            raise LocalMailboxVerificationError("malformed_channel_event")
        content = content_value
        if not 1 <= len(content) <= 4000:
            raise LocalMailboxVerificationError("malformed_channel_event")
        return VerifiedLocalMailboxEvent(
            event_id=event_id,
            binding_ref=BINDING_REF,
            occurred_at=occurred_at,
            kind=kind,
            raw_payload_hash=payload_hash,
            content=content,
        )
    allowed = common | {"delivery_id", "provider_message_id", "delivery_status"}
    if set(payload) != allowed:
        raise LocalMailboxVerificationError("malformed_channel_event")
    delivery_id = _uuid4(payload.get("delivery_id"), "delivery_id")
    provider_message_id = payload.get("provider_message_id")
    if not isinstance(provider_message_id, str) or not provider_message_id.strip():
        raise LocalMailboxVerificationError("malformed_channel_event")
    delivery_status = payload.get("delivery_status")
    if delivery_status not in {"delivered", "bounced"}:
        raise LocalMailboxVerificationError("malformed_channel_event")
    return VerifiedLocalMailboxEvent(
        event_id=event_id,
        binding_ref=BINDING_REF,
        occurred_at=occurred_at,
        kind=kind,
        raw_payload_hash=payload_hash,
        delivery_id=delivery_id,
        provider_message_id=provider_message_id,
        delivery_status=delivery_status,
    )


def _header(headers: Mapping[str, str], name: str) -> str:
    value = headers.get(name)
    if not isinstance(value, str) or not value:
        raise LocalMailboxVerificationError("invalid_fixture_authenticity")
    return value


def _parse_utc(value: str) -> datetime:
    return _parse_utc_value(value)


def _parse_utc_value(value: object) -> datetime:
    if not isinstance(value, str):
        raise LocalMailboxVerificationError("malformed_channel_event")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise LocalMailboxVerificationError("malformed_channel_event") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise LocalMailboxVerificationError("malformed_channel_event")
    return parsed.astimezone(UTC)


def _uuid4(value: object, name: str) -> UUID:
    if not isinstance(value, str) or value.lower() != value:
        raise LocalMailboxVerificationError("malformed_channel_event")
    try:
        parsed = UUID(value)
    except ValueError:
        raise LocalMailboxVerificationError("malformed_channel_event") from None
    if parsed.version != 4 or parsed.variant != RFC_4122 or str(parsed) != value:
        raise LocalMailboxVerificationError("malformed_channel_event")
    del name
    return parsed


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _validate_attempt(attempt: DeliveryAttempt) -> None:
    if attempt.delivery_id.version != 4:
        raise DeliveryAdapterConflict("delivery id must be UUIDv4")
    expected_hash = hashlib.sha256(attempt.body.encode("utf-8")).hexdigest()
    if attempt.body_hash != expected_hash or not attempt.idempotency_key:
        raise DeliveryAdapterConflict("delivery attempt hash is invalid")
    if attempt.binding_ref != BINDING_REF:
        raise DeliveryAdapterConflict("delivery binding is invalid")


def _accepted_observation(attempt: DeliveryAttempt) -> DeliveryObservation:
    return DeliveryObservation(
        delivery_id=attempt.delivery_id,
        idempotency_key=attempt.idempotency_key,
        state=DeliveryObservationState.ACCEPTED,
        provider_message_id=_stable_provider_message_id(attempt.delivery_id),
        artifact_hash=hashlib.sha256(attempt.body.encode("utf-8")).hexdigest(),
    )


def _stable_provider_message_id(delivery_id: UUID) -> str:
    raw = bytearray(hashlib.sha256(f"local:{delivery_id}".encode()).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return "local-provider-" + str(UUID(bytes=bytes(raw)))


verify = verify_local_mailbox_event

__all__ = [
    "BINDING_REF",
    "CHANNEL_KIND",
    "FRESHNESS_WINDOW",
    "SCHEMA_VERSION",
    "DeliveryAdapter",
    "DeliveryAdapterConflict",
    "DeliveryAttempt",
    "DeliveryObservation",
    "DeliveryObservationState",
    "FaultInjectingLocalMailboxAdapter",
    "LocalMailboxAdapter",
    "LocalMailboxEventKind",
    "LocalMailboxVerificationError",
    "UnknownDelivery",
    "VerifiedLocalMailboxEvent",
    "build_fixture_headers",
    "verify",
    "verify_local_mailbox_event",
]
