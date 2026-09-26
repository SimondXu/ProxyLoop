"""The ``pl.event/2`` envelope and the event-registry snapshot (ARCHITECTURE §4)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from proxyloop.contract.events import (
    ACTORS,
    EMITTERS,
    EVENT_TYPES,
    Event,
    check_causes,
)

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
        actor="ui",
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
    ("approval.post", {"subject": "approval", "subject_id": "a1", "decision": "granted",
                       "subject_hash": "t", "authority_epoch": 1}),
    ("approval.post", {"subject": "mandate", "subject_id": "m1", "decision": "denied",
                       "subject_hash": "h", "authority_epoch": 0}),
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
    ("approval.post", {"subject": "approval", "subject_id": "a1", "decision": "yes",
                       "subject_hash": "t", "authority_epoch": 1}),
    ("approval.post", {"subject": "offer", "subject_id": "a1", "decision": "granted",
                       "subject_hash": "t", "authority_epoch": 1}),
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
    actor = min(EMITTERS.get(kind, {"guard"}))
    Event.model_validate(_event(type=kind, actor=actor, payload=payload))


@pytest.mark.parametrize(("kind", "payload"), TYPED_BAD)
def test_typed_payloads_reject(kind: str, payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        actor = min(EMITTERS.get(kind, {"guard"}))
        Event.model_validate(_event(type=kind, actor=actor, payload=payload))


ACTOR_SNAPSHOT = SNAPSHOT.parent / "actors.json"
AUTHORITY = [
    "approval.decided",
    "mandate.decided",
    "action.authorized",
    "completion.decided",
    "authority.epoch",
]
MODEL_ROLES = sorted(a for a in ACTORS if a.startswith(("fast.", "slow", "world.")))
PAYLOADS = dict(TYPED_OK)


def test_actor_tables_match_the_snapshot() -> None:
    current = {
        "actors": sorted(ACTORS),
        "emitters": {k: sorted(v) for k, v in sorted(EMITTERS.items())},
    }
    if os.environ.get("PL_UPDATE_SNAPSHOTS"):
        ACTOR_SNAPSHOT.write_text(json.dumps(current, indent=1) + "\n", "utf-8")
    assert json.loads(ACTOR_SNAPSHOT.read_text("utf-8")) == current


def test_actor_must_be_in_the_vocabulary() -> None:
    with pytest.raises(ValueError, match="may not emit"):
        Event.model_validate(_event(actor="user"))


@pytest.mark.parametrize("kind", AUTHORITY)
@pytest.mark.parametrize("actor", MODEL_ROLES)
def test_no_model_role_emits_an_authority_type(kind: str, actor: str) -> None:
    assert actor not in EMITTERS[kind]
    event = _event(type=kind, actor=actor, payload=PAYLOADS[kind])
    with pytest.raises(ValueError, match="may not emit"):
        Event.model_validate(event)


def _decision(kind: str, causes: list[str]) -> Event:
    return Event.model_validate(
        _event(type=kind, actor="kernel", payload=PAYLOADS[kind], cause_ids=causes)
    )


@pytest.mark.parametrize("kind", ["approval.decided", "mandate.decided"])
def test_a_decision_must_cite_its_approval_post(kind: str) -> None:
    post = Event.model_validate(
        _event(
            type="approval.post",
            actor="ui",
            seq=2,
            event_id="r1:2",
            cause_ids=[],
            payload=dict(TYPED_OK)["approval.post"],
        )
    )
    other = Event.model_validate(_event(seq=3, event_id="r1:3", cause_ids=["r1:2"]))
    check_causes([post, other, _decision(kind, ["r1:2"])])
    with pytest.raises(ValueError, match=r"must cite an approval\.post"):
        check_causes([post, other, _decision(kind, ["r1:3"])])
