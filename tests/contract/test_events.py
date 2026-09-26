"""The ``pl.event/2`` envelope and the event-registry snapshot (ARCHITECTURE §4)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from proxyloop.contract.events import EVENT_TYPES, Event

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "event_registry.json"


def test_event_registry_matches_the_snapshot() -> None:
    current = {
        name: {
            "streams": list(spec.streams),
            "cause_required": spec.cause_required,
            "payload_keys": list(spec.payload_keys),
        }
        for name, spec in sorted(EVENT_TYPES.items())
    }
    if os.environ.get("PL_UPDATE_SNAPSHOTS"):
        SNAPSHOT.write_text(json.dumps(current, indent=1) + "\n", "utf-8")
    assert json.loads(SNAPSHOT.read_text("utf-8")) == current


def _event(**update: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema": "pl.event/2",
        "run_id": "r1",
        "seq": 5,
        "event_id": "r1:5",
        "t_ms": 1200,
        "wall": datetime(2026, 9, 26, 12, 0, tzinfo=UTC),
        "type": "fast.sentence",
        "actor": "fast.cp",
        "stream": "agent",
        "cause_ids": ["r1:3"],
        "epoch": 0,
        "payload": {"lane": "cp", "gen_id": "g1", "utt_id": "a3", "text": "Hi."},
    }
    return base | update


def test_valid_event_round_trips_with_the_schema_key() -> None:
    event = Event.model_validate(_event())
    dumped = json.loads(event.model_dump_json())
    assert dumped["schema"] == "pl.event/2" and "schema_" not in dumped
    assert Event.model_validate_json(event.model_dump_json()) == event


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"event_id": "r1:6"}, "event_id"),
        ({"type": "fast.guess"}, "unregistered"),
        ({"stream": "world"}, "not a world event"),
        ({"cause_ids": []}, "needs cause_ids"),
        ({"cause_ids": ["r1:5"]}, "not an earlier event"),
        ({"cause_ids": ["r2:1"]}, "not an earlier event"),
        ({"payload": {"lane": "cp"}}, "payload lacks"),
        ({"wall": datetime(2026, 9, 26, 12, 0)}, "timezone-aware"),
        ({"schema": "pl.event/1"}, "pl.event/2"),
    ],
)
def test_envelope_rejects(update: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Event.model_validate(_event(**update))


def test_exogenous_ingress_needs_no_cause() -> None:
    event = _event(
        type="user.msg",
        actor="user",
        cause_ids=[],
        payload={"text": "stop"},
        seq=0,
        event_id="r1:0",
    )
    assert Event.model_validate(event).cause_ids == ()


def test_llm_call_payload_keys_follow_the_record() -> None:
    keys = EVENT_TYPES["llm.call"].payload_keys
    assert {"requested_model", "served_model_echo", "request_id", "usage"} <= set(keys)
    assert EVENT_TYPES["llm.call"].streams == ("agent", "world")


CAP = {
    "cap_id": "c1",
    "business_action_id": "b1",
    "intent": "accept_offer",
    "terms_hash": "t",
    "epoch": 1,
    "expires_ms": 9,
}
TYPED_OK: list[tuple[str, dict[str, Any]]] = [
    ("approval.post", {"approval_id": "a1", "decision": "granted", "terms_hash": "t",
                       "authority_epoch": 1}),
    ("approval.decided", {"approval_id": "a1", "decision": "denied", "by": "ui"}),
    ("mandate.proposed", {"mandate_id": "m1", "mandate_hash": "h", "status": "proposed",
                          "epoch": 0}),
    ("mandate.decided", {"mandate_id": "m1", "mandate_hash": "h", "decision": "granted",
                         "by": "sim_approver"}),
    ("authority.epoch", {"new": 2, "reason": "f2s_revoke"}),
    ("action.authorized", {"intent": "accept_offer", "capability": CAP}),
    ("status.changed", {"previous": "IN_CALL", "status": "AWAITING_APPROVAL"}),
    ("completion.decided", {"verdict": "ok", "reasons": []}),
]  # fmt: skip
TYPED_BAD: list[tuple[str, dict[str, Any]]] = [
    ("approval.decided", {"approval_id": "a1", "decision": "granted", "by": "slow"}),
    ("approval.post", {"approval_id": "a1", "decision": "yes", "terms_hash": "t",
                       "authority_epoch": 1}),
    ("mandate.proposed", {"mandate_id": "m1", "mandate_hash": "h", "status": "granted",
                          "epoch": 0}),
    ("authority.epoch", {"new": 2, "reason": "the model asked"}),
    ("action.authorized", {"intent": "accept_offer", "capability": CAP, "extra": 1}),
    ("status.changed", {"previous": "IN_CALL", "status": "DONE"}),
    ("completion.decided", {"verdict": "probably", "reasons": []}),
    ("llm.call", {"call_id": "k1"}),
]  # fmt: skip


@pytest.mark.parametrize(("kind", "payload"), TYPED_OK)
def test_typed_payloads_accept(kind: str, payload: dict[str, Any]) -> None:
    Event.model_validate(_event(type=kind, actor="guard", payload=payload))


@pytest.mark.parametrize(("kind", "payload"), TYPED_BAD)
def test_typed_payloads_reject(kind: str, payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        Event.model_validate(_event(type=kind, actor="guard", payload=payload))
