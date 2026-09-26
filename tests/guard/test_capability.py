"""Capabilities (§9.4): business_action_id and release revalidation."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from tests.guard.build import CASE, FENCE, approval, board, confirm, offer

from proxyloop.contract.events import Event
from proxyloop.contract.state import Blackboard, Capability
from proxyloop.core.fold import fold
from proxyloop.guard.authorize import Denial, accept_offer
from proxyloop.guard.capability import business_action_id, revalidate

O1 = confirm(offer())


def _event(run: str, seq: int, type_: str, payload: Mapping[str, object]) -> Event:
    actor = {"offer.recorded": "guard", "readback.updated": "guard"}.get(
        type_, "kernel"
    )
    return Event.model_validate(
        {
            "run_id": run,
            "seq": seq,
            "event_id": f"{run}:{seq}",
            "t_ms": 100 + seq,
            "wall": "2026-09-26T00:00:00Z",
            "type": type_,
            "actor": actor,
            "stream": "agent",
            "cause_ids": [f"{run}:{seq - 1}"] if seq else [],
            "epoch": 0,
            "payload": payload,
        }
    )


def _folded(run: str, padding: int) -> Blackboard:
    """o1, confirmed, after ``padding`` unrelated user messages."""
    raw = offer()
    recorded = raw.model_dump(mode="json", include={"offer_ref", "revision", "slots"})
    statuses = {s.field: "confirmed" for s in raw.slots}
    readback: dict[str, object] = {"offer_ref": "o1", "revision": 1}
    readback["slot_statuses"] = statuses
    readback["terms_hash"] = O1.terms_hash
    steps = [("user.msg", {"text": "hi"})] * (1 + padding)
    steps += [("offer.recorded", recorded | {"terms_hash": None})]
    steps += [("readback.updated", readback)]
    return fold(_event(run, n, t, p) for n, (t, p) in enumerate(steps))


def _bid(bb: Blackboard) -> str:
    bb = bb.model_copy(
        update={
            "private": bb.private.model_copy(
                update={"approvals": {"apr-1": approval(O1)}}
            )
        }
    )
    effects = accept_offer(bb, "o1", CASE)
    assert not isinstance(effects, Denial)
    return Capability.model_validate(effects[0][1]["capability"]).business_action_id


def test_business_action_id_is_stable_under_run_id_and_seq() -> None:
    a, b = _folded("run-a", 0), _folded("run-b", 7)
    assert (a.seq, b.seq) == (2, 9)
    assert _bid(a) == _bid(b)
    assert business_action_id("c", "accept_offer", "o1", 1, "h", "apr-1") != (
        business_action_id("c", "accept_offer", "o1", 2, "h", "apr-1")
    )


def _cap(**kw: object) -> Capability:
    base: dict[str, object] = {
        "cap_id": "cap-1",
        "business_action_id": "b",
        "intent": "accept_offer",
        "terms_hash": O1.terms_hash,
        "epoch": 0,
        "expires_ms": 5_000,
    }
    return Capability.model_validate(base | kw)


def _released(cap: Capability, **kw: object) -> Blackboard:
    bb = board(O1, caps=(cap,), **kw)  # type: ignore[arg-type]
    auth = {"intent": "accept_offer", "offer_ref": "o1", "terms_hash": O1.terms_hash}
    auth |= {"cap_id": cap.cap_id, "epoch": cap.epoch}
    return Blackboard.model_validate(dict(bb) | {"authorizations": [auth]})


_NEW_TERMS = board(confirm(offer(monthly="6900")), caps=(_cap(),))


@pytest.mark.parametrize(
    ("bb", "t_end", "reason"),
    [
        (_released(_cap()), 4_000, None),
        (board(O1), 4_000, "unknown_capability"),
        (_released(_cap(consumed=True)), 4_000, "consumed"),
        (_released(_cap(), epoch=1), 4_000, "epoch"),
        (_released(_cap(), fences=(FENCE,)), 4_000, "fence"),
        (
            _released(_cap()).model_copy(update={"public": _NEW_TERMS.public}),
            4_000,
            "terms_changed",
        ),
        (
            _released(_cap()).model_copy(
                update={
                    "public": board(
                        O1.model_copy(update={"status": "withdrawn"})
                    ).public
                }
            ),
            4_000,
            "offer_closed",
        ),
        (_released(_cap()), 5_000, "expired"),
        (
            _released(_cap()).model_copy(
                update={
                    "public": board(O1.model_copy(update={"expires_ms": 4_500})).public
                }
            ),
            4_500,
            "expired",
        ),
    ],
)
def test_revalidate(bb: Blackboard, t_end: int, reason: str | None) -> None:
    assert revalidate(bb, "cap-1", t_end) == reason
