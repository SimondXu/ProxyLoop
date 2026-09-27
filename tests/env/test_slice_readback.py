"""The S1 slice families in full mode can reach a confirmed read-back (S1-SYS-37).

The sim path, with no model: the real rep ``Policy`` makes each ladder offer
and reads it back in the Mouth's line (``template``: what the Mouth model
rephrases, and what it says on a fidelity fallback). A Slow-equivalent records
the read-back's terms through the real Slow tools on a real bus, asks for the
read-back of that revision, and Guard's ``readback.updated`` must confirm every
slot with nothing required missing. x-out-of-envelope-approval then reaches its
card (``approval.requested``).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from tests.support.manual_clock import ManualClock

from proxyloop.contract.events import Event
from proxyloop.contract.llm import ToolCall
from proxyloop.contract.state import Blackboard
from proxyloop.core.bus import Bus
from proxyloop.env.counterparty.ear import EarAct
from proxyloop.env.counterparty.mouth import template
from proxyloop.env.counterparty.policy import Policy, PublicIntent
from proxyloop.env.tasks.loader import load_task
from proxyloop.guard.readback import missing_required, readback_status
from proxyloop.slow.tools import SlowTools, case_ref

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

SLICE = (
    "cp-direct-discount",
    "cp-hidden-fee-readback",
    "x-out-of-envelope-approval",
    "x-user-mind-change",
)
LEVERS = ("ask_discount", "tenure", "cite_competitor")
SLOT_KINDS = {  # field kind -> (unit, role), as Slow records it (§9.2)
    "monthly_price": ("usd_minor", "recurring"),
    "term_months": ("months", "recurring"),
    "fee": ("usd_minor", "one_time"),
    "fees_none": ("bool", "one_time"),
    "changes_none": ("bool", "change"),
    "applied_change": ("bool", "change"),
    "expires": ("iso", "expiry"),
}


class Host:
    """The kernel seams Slow's tools use, over a real bus and a manual clock."""

    def __init__(self, tmp_path: Path) -> None:
        self.clock = ManualClock()
        self.bus = Bus(tmp_path / "events.jsonl", "r1", self.clock)
        self.tools = SlowTools(cast("Kernel", self), frozenset(), case_ref("case-1"))
        self.root = self.emit("user.msg", "kernel", {"text": "Lower my bill."})
        moved = {"previous": "INTAKE", "status": "IN_CALL"}  # chan.opened(cp)
        self.emit("status.changed", "guard", moved, [self.root.event_id])

    @property
    def bb(self) -> Blackboard:
        return self.bus.bb

    def emit(self, type_: str, actor: str, payload: Any, causes: Any = ()) -> Event:
        self.clock.advance(100)
        return self.bus.emit(type_, actor, "agent", payload, causes)

    def now(self) -> int:
        return self.clock.monotonic_ms()

    def finish(self, outcome: str) -> None:
        raise AssertionError(f"unexpected finish({outcome})")

    def act(self, *calls: dict[str, Any]) -> list[str]:
        body = {"private_summary": "digest", "calls": list(calls)}
        call = ToolCall(call_id="c", name="act", arguments=json.dumps(body))
        seen = self.bb.seq  # the step's view: everything so far
        return self.tools.act(call, [self.root.event_id], basis=seen).splitlines()[1:]


class Call:
    """The rep's side: the real policy, voiced by the Mouth's line."""

    def __init__(self, family: str, host: Host) -> None:
        self.task = load_task(family, mode="full")
        cp = self.task.counterparty
        facts = self.task.profile.facts
        self.policy = Policy(cp, {k: facts[k] for k in cp.identity})
        self.host, self.n = host, 0

    def rep(self, act: str, **args: Any) -> tuple[PublicIntent, str]:
        """The caller's act, as the Ear heard it; the rep's line as a
        ``utt.final``, and its utt id."""
        self.n += 1
        ear = EarAct.model_validate({"act": act, **args})
        t_ms = 10_000 * self.n
        intent = self.policy.step(ear, f"a-{self.n}", "", t_ms)[-1].intent
        utt = f"cp-{self.n}"
        line = template(intent, self.task.counterparty.company)
        said = {"lane": "cp", "speaker": "partner", "utt_id": utt, "text": line}
        self.host.emit("utt.final", "kernel", said)
        return intent, utt


def _slot(field: str, value: str, utt: str) -> dict[str, str]:
    unit, _ = SLOT_KINDS[field.partition(":")[0]]  # Slow sends no role or unit
    if unit == "usd_minor":
        value = str(int(Decimal(value) * 100))
    return {"field": field, "value": value, "utt_ref": utt}


def _confirm_every_offer(tmp_path: Path, family: str) -> tuple[Host, Call]:
    h = Host(tmp_path)
    call = Call(family, h)
    task = call.task
    identity = task.counterparty.identity
    facts = tuple({"key": k, "value": task.profile.facts[k]} for k in identity)
    assert call.rep("provide_fact", facts=facts)[0].kind == "how_can_help"
    for lever, spec in zip(LEVERS, task.counterparty.ladder, strict=False):
        ref = spec.offer_ref
        offer, _ = call.rep(lever)
        assert (offer.kind, offer.offer_ref) in {("offer", ref), ("final_offer", ref)}
        assert dict(offer.say) == spec.terms  # hidden terms wait for a read-back
        first, utt = call.rep("ask_readback", offer_ref=ref)
        assert first.kind == "readback" and dict(first.say) == spec.all_terms
        slots = [_slot(f, v, utt) for f, v in first.say]
        record = {"tool": "record_offer", "offer_ref": ref, "offer_slots": slots}
        ask = {"tool": "guide_fast", "move": "ask_readback", "slots": [f"offer:{ref}"]}
        out = h.act(record, ask)
        assert out[-1].endswith(f"read-back asked for {ref} r1"), out
        again, _ = call.rep("ask_readback", offer_ref=ref)
        assert again.kind == "readback"
        h.tools.readback()
        recorded = h.bb.public.offers[ref]
        statuses = {s.field: s.status for s in recorded.slots}
        assert missing_required(recorded) == (), (ref, missing_required(recorded))
        assert set(statuses.values()) == {"confirmed"}, (ref, statuses)
        assert readback_status(recorded) == "confirmed" and recorded.terms_hash
    return h, call


@pytest.mark.parametrize("family", SLICE)
def test_every_offer_of_a_slice_family_reaches_a_confirmed_read_back(
    tmp_path: Path, family: str
) -> None:
    _confirm_every_offer(tmp_path, family)


def test_the_out_of_envelope_offer_reaches_its_card(tmp_path: Path) -> None:
    h, call = _confirm_every_offer(tmp_path, "x-out-of-envelope-approval")
    ref = call.task.counterparty.ladder[-1].offer_ref  # within the unstated limits
    (text,) = h.act({"tool": "request_approval", "offer_ref": ref})
    assert text.startswith(f"request_approval: card apr-{ref}-r1-"), text
    (card,) = [e for e in h.bus.events if e.type == "approval.requested"]
    assert card.payload["offer_ref"] == ref
    assert card.payload["terms_hash"] == h.bb.public.offers[ref].terms_hash
