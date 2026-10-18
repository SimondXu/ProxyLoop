"""ADR-0034: what ends a standing cp hold without a FastC turn (``guard.holds``).
The kernel paths are in tests/concurrency/test_hold_ends.py; these are the
cases that end nothing."""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import count
from typing import Any

from proxyloop.contract.events import Event
from proxyloop.contract.state import HoldState
from proxyloop.guard import holds
from proxyloop.guard.needs import Ledger, Need

SEQ = count(1)
GUARD = ("speak.verbatim", "fact.recorded")


def ev(type_: str, payload: dict[str, Any], *causes: str) -> Event:
    n, actor = next(SEQ), "guard" if type_ in GUARD else "kernel"
    return Event.model_validate(
        {"run_id": "r", "seq": n, "event_id": f"r:{n}", "t_ms": n, "type": type_,
         "wall": datetime(2026, 10, 17, tzinfo=UTC), "actor": actor,
         "stream": "agent", "cause_ids": causes or ("r:0",), "epoch": 0,
         "payload": payload}
    )  # fmt: skip


def hold(reason: Any) -> HoldState:
    return HoldState(reason=reason, since_ms=0)


def heard(kind: str = "decline", cut: bool = False) -> tuple[Event, frozenset[str]]:
    """Guard's line, its release and its delivery; the ids ``lines`` keeps."""
    said = ev("speak.verbatim", {"lane": "cp", "kind": kind, "text": "No."})
    released = ev("speak.released", {"lane": "cp"}, said.event_id)
    ids = holds.lines(holds.lines(frozenset(), said), released)
    out = {"lane": "cp", "utt_id": "u", "text_generated": "No.", "text_heard": "No"}
    return ev("utt.delivered", out | {"interrupted": cut}, released.event_id), ids


def fact(scope: str = "public", source: str = "shareable") -> Event:
    out = {"key": "tenure_years", "value": "8", "source_ref": "r:1"}
    return ev("fact.recorded", out | {"scope": scope, "source": source})


def test_a_line_heard_whole_ends_a_decision_hold_and_nothing_else() -> None:
    delivered, ids = heard()
    for reason in ("offer", "decision", "pressure"):
        assert holds.ended(hold(reason), delivered, ids, Ledger(), ()) == "decided"
    for reason in ("fact_request", "unclear"):
        assert holds.ended(hold(reason), delivered, ids, Ledger(), ()) is None
    assert holds.ended(None, delivered, ids, Ledger(), ()) is None


def test_a_cut_line_or_another_lines_delivery_ends_nothing() -> None:
    cut, ids = heard(cut=True)
    assert holds.ended(hold("offer"), cut, ids, Ledger(), ()) is None
    hello = {"lane": "cp", "kind": "disclosure", "text": "Hi"}
    disclosure = ev("speak.verbatim", hello)
    assert holds.lines(frozenset(), disclosure) == frozenset()
    fast, _ = heard()
    assert holds.ended(hold("offer"), fast, frozenset(), Ledger(), ()) is None


def test_only_the_users_public_fact_with_nothing_waiting_ends_a_fact_hold() -> None:
    held, answered = hold("fact_request"), fact()
    assert holds.ended(held, answered, frozenset(), Ledger(), ()) == "answered"
    assert holds.ended(hold("offer"), answered, frozenset(), Ledger(), ()) is None
    for other in (fact(scope="private", source="user"), fact(source="cp_utt")):
        assert holds.ended(held, other, frozenset(), Ledger(), ()) is None
    missing = ("account.last4",)  # a readiness key still missing
    assert holds.ended(held, answered, frozenset(), Ledger(), missing) is None
    for state in ("pending", "replied"):
        waiting = Ledger(needs={"competitor.name": Need("competitor.name", state)})
        assert holds.ended(held, answered, frozenset(), waiting, ()) is None
