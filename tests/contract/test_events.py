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
    ("mandate.proposed", {"mandate_id": "m1", "mandate_hash": "h", "status": "granted",
                          "epoch": 0, "decided_by": "ui"}),
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
CARD = {
    "approval_id": "a1",
    "offer_ref": "o1",
    "revision": 1,
    "terms_hash": "t",
    "readback_text": "r",
    "authority_epoch": 1,
    "expires_ms": 9,
    "binding": {
        "offer_ref": "o1",
        "revision": 1,
        "account_ref": "a",
        "principal_ref": "p",
        "purpose": "x",
        "authority_epoch": 1,
    },
}


def _payload(kind: str) -> dict[str, Any]:
    """A valid payload for ``kind``."""

    if kind == "approval.requested":
        return CARD
    typed = dict(TYPED_OK)
    return typed.get(kind) or dict.fromkeys(EVENT_TYPES[kind].payload_keys, "x")


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


def test_every_authority_type_is_restricted() -> None:
    assert set(AUTHORITY) <= set(EMITTERS)
    assert {"action.denied", "speak.revoked", "declass.denied"}.isdisjoint(EMITTERS)
    assert "fact.recorded" not in EMITTERS


@pytest.mark.parametrize("kind", sorted(EMITTERS))
@pytest.mark.parametrize("actor", MODEL_ROLES)
def test_no_model_role_emits_a_restricted_type(kind: str, actor: str) -> None:
    allowed = min(EMITTERS[kind])
    Event.model_validate(_event(type=kind, actor=allowed, payload=_payload(kind)))
    assert actor not in EMITTERS[kind]
    with pytest.raises(ValueError, match="may not emit"):
        Event.model_validate(_event(type=kind, actor=actor, payload=_payload(kind)))


@pytest.mark.parametrize("kind", ["action.denied", "speak.revoked", "declass.denied"])
def test_models_may_restrict(kind: str) -> None:
    Event.model_validate(_event(type=kind, actor="slow", payload=_payload(kind)))


POSTS = {
    "approval.decided": (
        "ui",
        {"subject": "approval", "subject_id": "a1", "decision": "granted"},
        {"approval_id": "a1", "decision": "granted", "by": "ui"},
    ),
    "mandate.decided": (
        "sim_approver",
        {"subject": "mandate", "subject_id": "m1", "decision": "granted"},
        {"mandate_id": "m1", "mandate_hash": "h", "decision": "granted",
         "by": "sim_approver"},
    ),
}  # fmt: skip


def _log(
    kind: str, post: dict[str, Any], decision: dict[str, Any], n_decisions: int = 1
) -> list[Event]:
    actor, post_body, decided = POSTS[kind]
    body = post_body | {"subject_hash": "h", "authority_epoch": 1} | post
    first = _event(
        type="approval.post", actor=actor, seq=1, event_id="r1:1", cause_ids=[],
        payload=body,
    )  # fmt: skip
    log = [Event.model_validate(first)]
    for seq in range(2, 2 + n_decisions):
        event = _event(
            type=kind, actor="kernel", seq=seq, event_id=f"r1:{seq}",
            cause_ids=["r1:1"], payload=decided | decision,
        )  # fmt: skip
        log.append(Event.model_validate(event))
    return log


@pytest.mark.parametrize("kind", sorted(POSTS))
def test_a_decision_citing_its_post_passes(kind: str) -> None:
    check_causes(_log(kind, {}, {}))


@pytest.mark.parametrize(
    ("kind", "post", "decision"),
    [
        ("approval.decided", {"subject": "mandate"}, {}),
        ("approval.decided", {"subject_id": "a2"}, {}),
        ("approval.decided", {}, {"decision": "denied"}),
        ("approval.decided", {}, {"by": "sim_approver"}),
        ("mandate.decided", {"subject": "approval"}, {}),
        ("mandate.decided", {"subject_id": "m2"}, {}),
        ("mandate.decided", {}, {"decision": "denied"}),
        ("mandate.decided", {}, {"by": "ui"}),
        ("mandate.decided", {"subject_hash": "h2"}, {}),
    ],
)
def test_a_decision_must_match_its_post(
    kind: str, post: dict[str, Any], decision: dict[str, Any]
) -> None:
    with pytest.raises(ValueError, match=r"must cite the approval\.post it decides"):
        check_causes(_log(kind, post, decision))


def test_a_decision_must_cite_a_post() -> None:
    post, decision = _log("approval.decided", {}, {})
    other = Event.model_validate(_event(seq=2, event_id="r1:2", cause_ids=["r1:1"]))
    moved = decision.model_copy(update={"cause_ids": ("r1:2",)})
    with pytest.raises(ValueError, match="must cite"):
        check_causes([post, other, moved])


@pytest.mark.parametrize("kind", sorted(POSTS))
def test_a_post_is_decided_once(kind: str) -> None:
    with pytest.raises(ValueError, match="already decided"):
        check_causes(_log(kind, {}, {}, n_decisions=2))


def test_a_cause_must_exist_earlier_in_the_log() -> None:
    orphan = Event.model_validate(_event(seq=5, event_id="r1:5", cause_ids=["r1:3"]))
    with pytest.raises(ValueError, match="cites unknown events"):
        check_causes([orphan])
