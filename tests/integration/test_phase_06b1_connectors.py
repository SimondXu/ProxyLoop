from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from proxyloop_connectors import (
    BINDING_REF,
    DeliveryAdapterConflict,
    DeliveryAttempt,
    DeliveryObservation,
    DeliveryObservationState,
    FaultInjectingLocalMailboxAdapter,
    LocalMailboxAdapter,
    LocalMailboxVerificationError,
    UnknownDelivery,
    build_fixture_headers,
    verify_local_mailbox_event,
)


def _event(now: datetime, **updates: object) -> tuple[bytes, dict[str, str]]:
    payload: dict[str, object] = {
        "schema_version": "local-mailbox-v1",
        "event_id": str(uuid4()),
        "binding_ref": BINDING_REF,
        "occurred_at": now.isoformat().replace("+00:00", "Z"),
        "kind": "provider_message",
        "content": "Synthetic Provider message.",
    }
    payload.update(updates)
    raw = json.dumps(payload, separators=(",", ":")).encode()
    headers = build_fixture_headers(raw)
    headers["X-ProxyLoop-Local-Timestamp"] = now.isoformat().replace("+00:00", "Z")
    return raw, headers


def test_verifier_binds_exact_raw_bytes_and_strict_shape() -> None:
    now = datetime.now(UTC)
    raw, headers = _event(now)
    verified = verify_local_mailbox_event(raw, headers, now)
    assert verified.raw_payload_hash == hashlib.sha256(raw).hexdigest()
    assert verified.content == "Synthetic Provider message."
    assert verified.fixture_timestamp == now

    with pytest.raises(LocalMailboxVerificationError) as raised:
        verify_local_mailbox_event(raw + b" ", headers, now)
    assert raised.value.category == "invalid_fixture_authenticity"
    assert "Synthetic" not in str(raised.value)

    malformed, malformed_headers = _event(now, unknown="rejected")
    with pytest.raises(LocalMailboxVerificationError) as raised:
        verify_local_mailbox_event(malformed, malformed_headers, now)
    assert raised.value.category == "malformed_channel_event"


def test_verifier_rejects_stale_unknown_event_but_can_recheck_duplicate() -> None:
    now = datetime.now(UTC)
    raw, headers = _event(now - timedelta(minutes=6))
    with pytest.raises(LocalMailboxVerificationError) as raised:
        verify_local_mailbox_event(raw, headers, now)
    assert raised.value.category == "stale_unknown_event"
    verified = verify_local_mailbox_event(raw, headers, now, require_fresh=False)
    assert verified.event_id


def test_local_adapter_reuses_one_acceptance_and_rejects_changed_semantics() -> None:
    adapter = LocalMailboxAdapter()
    delivery_id = uuid4()
    attempt = DeliveryAttempt(
        delivery_id=delivery_id,
        idempotency_key=str(delivery_id),
        binding_ref=BINDING_REF,
        body="I am checking that and will update you.",
        body_hash=hashlib.sha256(
            b"I am checking that and will update you."
        ).hexdigest(),
    )
    first = adapter.send(attempt)
    second = adapter.send(attempt)
    assert first == second
    assert first.state is DeliveryObservationState.ACCEPTED
    assert first.provider_message_id
    assert adapter.lookup(attempt) == first
    replacement_id = uuid4()
    replacement_attempt = replace(
        attempt, delivery_id=replacement_id, idempotency_key=str(replacement_id)
    )
    assert isinstance(adapter.lookup(replacement_attempt), UnknownDelivery)

    with pytest.raises(DeliveryAdapterConflict):
        adapter.send(replace(attempt, body="changed"))


def test_fault_adapter_lookup_recovers_after_lost_acceptance_response() -> None:
    adapter = FaultInjectingLocalMailboxAdapter(lose_response_after_accept=1)
    delivery_id = uuid4()
    body = "I am checking that and will update you."
    attempt = DeliveryAttempt(
        delivery_id=delivery_id,
        idempotency_key=str(delivery_id),
        binding_ref=BINDING_REF,
        body=body,
        body_hash=hashlib.sha256(body.encode()).hexdigest(),
    )
    with pytest.raises(TimeoutError):
        adapter.send(attempt)
    observation = adapter.lookup(attempt)
    assert isinstance(observation, DeliveryObservation)
    assert observation.state is DeliveryObservationState.ACCEPTED


def test_fresh_adapter_lookup_reports_unknown_without_send() -> None:
    adapter = FaultInjectingLocalMailboxAdapter(lose_response_after_accept=1)
    delivery_id = uuid4()
    body = "I am checking that and will update you."
    attempt = DeliveryAttempt(
        delivery_id=delivery_id,
        idempotency_key=str(delivery_id),
        binding_ref=BINDING_REF,
        body=body,
        body_hash=hashlib.sha256(body.encode()).hexdigest(),
    )
    with pytest.raises(TimeoutError):
        adapter.send(attempt)
    expected = adapter.lookup(attempt)
    assert isinstance(expected, DeliveryObservation)

    replacement = LocalMailboxAdapter()
    recovered = replacement.lookup(attempt)
    assert isinstance(recovered, UnknownDelivery)
