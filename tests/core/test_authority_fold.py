"""The authority reducers (S1-SYS-01): joins, grants, consumption, statuses."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from tests.guard.build import CASE, offer

from proxyloop.contract.events import Event
from proxyloop.contract.state import Blackboard
from proxyloop.core.fold import apply
from proxyloop.guard.authorize import Denial, accept_offer, request_approval
from proxyloop.guard.mandate import proposal
from proxyloop.guard.terms import offer_terms_hash

RUN = "r1"
_ACTOR = {
    "approval.post": "ui",
    "approval.decided": "kernel",
    "mandate.decided": "kernel",
    "speak.released": "kernel",
    "speak.revoked": "kernel",
    "user.msg": "kernel",
    "utt.final": "kernel",
}


class Log:
    """Builds a folded log one event at a time; each event cites the previous."""

    def __init__(self) -> None:
        self.bb, self.seq = Blackboard(), 0

    def emit(self, type_: str, payload: Mapping[str, object]) -> Blackboard:
        e = Event.model_validate(
            {
                "run_id": RUN,
                "seq": self.seq,
                "event_id": f"{RUN}:{self.seq}",
                "t_ms": 100 * self.seq,
                "wall": "2026-09-26T00:00:00Z",
                "type": type_,
                "actor": _ACTOR.get(type_, "guard"),
                "stream": "agent",
                "cause_ids": [f"{RUN}:{self.seq - 1}"] if self.seq else [],
                "epoch": self.bb.epoch,
                "payload": payload,
            }
        )
        self.bb, self.seq = apply(self.bb, e), self.seq + 1
        return self.bb


def _confirmed_offer(log: Log) -> None:
    raw = offer()
    recorded = raw.model_dump(mode="json", include={"offer_ref", "revision", "slots"})
    log.emit("user.msg", {"text": "go"})
    log.emit("offer.recorded", recorded | {"terms_hash": None})
    statuses = {s.field: "confirmed" for s in raw.slots}
    done = raw.model_copy(
        update={
            "slots": tuple(
                s.model_copy(update={"status": "confirmed"}) for s in raw.slots
            )
        }
    )
    update = {"offer_ref": "o1", "revision": 1, "slot_statuses": statuses}
    log.emit("readback.updated", update | {"terms_hash": offer_terms_hash(done)})


def _granted(log: Log) -> object:
    """Card, post, decision: the approval path to an accept; the card's expiry."""
    effects = request_approval(log.bb, "o1", CASE)
    assert not isinstance(effects, Denial)
    ((kind, card),) = effects
    log.emit(kind, card)
    post = {"subject": "approval", "subject_id": card["approval_id"]}
    post |= {"decision": "granted", "subject_hash": card["terms_hash"]}
    log.emit("approval.post", post | {"authority_epoch": 0})
    decided = {"approval_id": card["approval_id"], "decision": "granted", "by": "ui"}
    log.emit("approval.decided", decided)
    return card["expires_ms"]


def _accept(log: Log) -> str:
    effects = accept_offer(log.bb, "o1", CASE)
    assert not isinstance(effects, Denial)
    for kind, payload in effects:
        log.emit(kind, payload)
    return str(effects[1][1]["cap_id"])


def test_readback_card_decision_accept_release() -> None:
    log = Log()
    _confirmed_offer(log)
    o = log.bb.public.offers["o1"]
    assert {s.status for s in o.slots} == {"confirmed"} and o.terms_hash
    expires = _granted(log)
    assert log.bb.private.pending_approval is None
    (approval,) = log.bb.private.approvals.values()
    assert (approval.decision, approval.terms_hash) == ("granted", o.terms_hash)
    assert approval.expires_ms == expires is not None  # the card's (ADR-0007)
    cap_id = _accept(log)
    assert log.bb.authorizations[0].offer_ref == "o1"
    assert not log.bb.capabilities[cap_id].consumed
    log.emit("speak.released", {"lane": "cp", "cap_id": cap_id})
    assert log.bb.capabilities[cap_id].consumed
    with pytest.raises(ValueError, match="unknown or used"):
        log.emit("speak.released", {"lane": "cp", "cap_id": cap_id})  # once only


def test_a_revoked_capability_is_never_released() -> None:
    log = Log()
    _confirmed_offer(log)
    _granted(log)
    cap_id = _accept(log)
    log.emit("speak.revoked", {"reason": "fence", "cap_id": cap_id})
    assert cap_id not in log.bb.capabilities
    with pytest.raises(ValueError, match="unknown or used"):
        log.emit("speak.released", {"lane": "cp", "cap_id": cap_id})
    assert accept_offer(log.bb, "o1", CASE) != Denial("already_authorized")


def test_a_decision_without_its_card_or_proposal_is_rejected() -> None:
    log = Log()
    log.emit("user.msg", {"text": "go"})
    with pytest.raises(ValueError, match="no such pending card"):
        log.emit(
            "approval.decided",
            {"approval_id": "apr-x", "decision": "granted", "by": "ui"},
        )
    decided = {"mandate_id": "m1", "mandate_hash": "h", "decision": "granted"}
    with pytest.raises(ValueError, match="no such proposed mandate"):
        log.emit("mandate.decided", decided | {"by": "ui"})
    kind, payload = proposal(log.bb, "m1", max_monthly_price_minor=7000)
    log.emit(kind, payload)
    with pytest.raises(ValueError, match="no such proposed mandate"):
        log.emit("mandate.decided", decided | {"by": "ui"})  # the wrong hash
    right = decided | {"mandate_hash": payload["mandate_hash"], "by": "ui"}
    log.emit("mandate.decided", right)
    with pytest.raises(ValueError, match="no such proposed mandate"):
        log.emit("mandate.decided", right)  # decided once


def test_a_granted_mandate_is_current_only_in_its_epoch() -> None:
    log = Log()
    _confirmed_offer(log)
    kind, payload = proposal(log.bb, "m1", max_monthly_price_minor=7000)
    log.emit(kind, payload)
    right = {"mandate_id": "m1", "mandate_hash": payload["mandate_hash"]}
    log.emit("mandate.decided", right | {"decision": "granted", "by": "ui"})
    log.emit("authority.epoch", {"new": 1, "reason": "mandate_decided"})
    assert log.bb.private.mandate is not None and log.bb.private.mandate.epoch == 1
    assert not isinstance(accept_offer(log.bb, "o1", CASE), Denial)
    log.emit("authority.epoch", {"new": 2, "reason": "slow_revoke"})
    assert accept_offer(log.bb, "o1", CASE) == Denial("mandate_stale_epoch")
    log.emit("authority.epoch", {"new": 3, "reason": "mandate_decided"})  # no decision
    assert accept_offer(log.bb, "o1", CASE) == Denial("mandate_stale_epoch")


def test_joins_on_cards_lines_and_readbacks() -> None:
    log = Log()
    _confirmed_offer(log)
    effects = request_approval(log.bb, "o1", CASE)
    assert not isinstance(effects, Denial)
    card = dict(effects[0][1]) | {"revision": 2}
    card["binding"] = dict(card["binding"]) | {"revision": 2}  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="not the recorded offer"):
        log.emit("approval.requested", card)
    accept = {"lane": "cp", "kind": "accept", "text": "Yes.", "cap_id": "cap-9"}
    with pytest.raises(
        ValueError, match=r"speak\.verbatim: capability cap-9 is unknown"
    ):
        log.emit("speak.verbatim", accept)
    stale: dict[str, object] = {"offer_ref": "o1", "revision": 2, "terms_hash": None}
    stale["slot_statuses"] = {}
    with pytest.raises(ValueError, match="readback"):
        log.emit("readback.updated", stale)
    decline = {"lane": "cp", "kind": "decline", "text": "No.", "offer_ref": "o1"}
    assert log.emit("speak.verbatim", decline).public.offers["o1"].status == "declined"
    disclosure = {"lane": "cp", "kind": "disclosure", "text": "I am an AI."}
    log.emit("speak.verbatim", disclosure)
    log.emit("speak.released", {"lane": "cp"})  # the S0 form: no capability


def test_evidence_and_only_an_ok_completion_verifies() -> None:
    log = Log()
    log.emit("user.msg", {"text": "go"})
    log.emit("status.changed", {"previous": "INTAKE", "status": "IN_CALL"})
    evidence = {"evidence_id": "e1", "kind": "ledger", "confirmation_id": "NW-1"}
    assert log.emit("evidence.recorded", evidence).evidence[0].confirmation_id == "NW-1"
    verified = {"previous": "IN_CALL", "status": "VERIFIED_NO_DEAL"}
    with pytest.raises(ValueError, match="completion"):
        log.emit("status.changed", verified)
    log.emit("completion.decided", {"verdict": "fail", "reasons": ["offer_open:o1"]})
    with pytest.raises(ValueError, match="completion"):
        log.emit("status.changed", verified)
    log.emit("completion.decided", {"verdict": "ok", "reasons": []})
    assert log.emit("status.changed", verified).public.status == "VERIFIED_NO_DEAL"


def test_offer_recorded_cannot_set_statuses_or_terms() -> None:
    """Statuses and terms_hash come only from readback.updated (Guard)."""
    log = Log()
    log.emit("user.msg", {"text": "go"})
    claimed = offer().model_dump(mode="json", include={"offer_ref", "revision"})
    claimed["slots"] = [
        s.model_dump(mode="json") | {"status": "confirmed"} for s in offer().slots
    ]
    o = log.emit(
        "offer.recorded", claimed | {"terms_hash": "slow-says", "expires_ms": 90_000}
    ).public.offers["o1"]
    assert {s.status for s in o.slots} == {"unknown"} and o.terms_hash is None
    assert o.expires_ms == 90_000  # the rep's TTL, from record_offer
    assert request_approval(log.bb, "o1", CASE) == Denial("readback_not_confirmed")
    no_ttl = log.emit("offer.recorded", claimed | {"revision": 2, "terms_hash": None})
    assert no_ttl.public.offers["o1"].expires_ms is None
