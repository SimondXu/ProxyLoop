"""Slow's S1 tools over a real bus and fold (the test plays the kernel and world
sides): Guard decides every rule, denials come back as text, models restrict but
never grant, and the approval chain holds end to end (ARCHITECTURE §8, §9)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from tests.support.manual_clock import ManualClock

from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.events import Event, Stream
from proxyloop.contract.llm import ToolCall
from proxyloop.contract.protocol import GuideMoveError
from proxyloop.contract.state import Blackboard, CaseStatus
from proxyloop.contract.views import view_slow
from proxyloop.core.bus import Bus
from proxyloop.eval.metrics import Log, approval_b
from proxyloop.guard import needs
from proxyloop.guard.authorize import CARD_TTL_MS
from proxyloop.kernel.lanes import PROFILE
from proxyloop.slow import asks
from proxyloop.slow import tools as slow_tools
from proxyloop.slow.prompt import ACT, status_bar
from proxyloop.slow.tools import SlowTools, case_ref

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

KEYS = frozenset({"account.holder_name", "account.last4", "competitor.price_usd"})
TERMS = (
    "It is $69 a month on a 24-month term, no fees, no other changes, "
    "and the offer does not expire."
)
SLOTS = [  # {field, value, utt_ref}: role and unit follow from the field
    {"field": "monthly_price", "value": "6900", "utt_ref": "cp-1"},
    {"field": "term_months", "value": "24", "utt_ref": "cp-1"},
    {"field": "fees_none", "value": "true", "utt_ref": "cp-1"},
    {"field": "changes_none", "value": "true", "utt_ref": "cp-1"},
    {"field": "expires", "value": "none", "utt_ref": "cp-1"},
]  # fmt: skip
ASKED = "Could you read the full terms back to me?"  # FastC's read-back ask
BOUND = {  # the world's ledger binding, in dollars
    "monthly_price": "69.00",
    "fees_none": "true",
    "changes_none": "true",
    "expires": "none",
}


class Calls:
    """The kernel's call gate as Slow's tools read it: the needs ledger, folded
    from the bus (the gate itself is tests/kernel/test_calls.py's)."""

    def __init__(self, bus: Bus) -> None:
        self.needs = needs.Ledger()
        bus.subscribe(self.on_event)

    def on_event(self, e: Event) -> None:
        self.needs = needs.step(self.needs, e)


class Host:
    """The kernel's seams Slow's tools use, over a real bus (not a model fake)."""

    def __init__(self, tmp_path: Path) -> None:
        self.clock = ManualClock()
        self.bus = Bus(tmp_path / "events.jsonl", "r1", self.clock)
        self.calls, self.counts = Calls(self.bus), Counter[str]()
        self.ended: list[str] = []
        self.delivered: Event | None = None  # the accept line as heard
        self.tools = SlowTools(cast("Kernel", self), KEYS, case_ref("case-1"))
        self.root = self.emit("user.msg", "kernel", {"text": "Lower my bill."})

    @property
    def bb(self) -> Blackboard:  # at the clock's now, as ``Kernel.bb``
        bb = self.bus.bb
        return bb.model_copy(update={"t_ms": max(bb.t_ms, self.now())})

    def emit(
        self,
        type_: str,
        actor: str,
        payload: Any,
        causes: Any = (),
        stream: Stream = "agent",
    ) -> Event:
        self.clock.advance(100)
        return self.bus.emit(type_, actor, stream, payload, causes)

    def finish(self, outcome: str) -> None:
        self.ended.append(outcome)

    def now(self) -> int:
        return self.clock.monotonic_ms()

    def relay(self, cause: Event, text: str) -> None:
        """FastC's typed relay of a rep line, as SlowLoop hands it to Slow."""
        msg_id = f"r1:{len(self.bus.events)}"  # the kernel's: its own event id
        msg = {"msg_id": msg_id, "lane": "cp", "gen_id": "g"}
        msg |= {"utt_ref": cause.payload["utt_id"], "type": "CP_UPDATE", "text": text}
        self.emit("f2s.msg", "fast.cp", msg, [cause.event_id])
        self.tools.received.add(msg_id)

    def act(self, *calls: dict[str, Any]) -> list[str]:
        body = {"private_summary": "digest", "calls": list(calls)}
        call = ToolCall(call_id="c", name="act", arguments=json.dumps(body))
        seen = self.bb.seq  # the step's view: everything so far
        return self.tools.act(call, [self.root.event_id], basis=seen).splitlines()[1:]

    def rep(self, utt_id: str, text: str) -> Event:
        said = {"lane": "cp", "speaker": "partner", "utt_id": utt_id, "text": text}
        return self.emit("utt.final", "kernel", said)

    def of(self, type_: str) -> list[Event]:
        return [e for e in self.bus.events if e.type == type_]

    def voice(self, *, spoke: bool = True, deliver: bool = True) -> str:
        """FastC's turn voicing the newest cp guide (ADR-0013: the only one),
        with one sentence (delivered whole unless ``deliver`` is False) or with
        none; its gen id."""
        (msg,) = [e for e in self.of("s2f.msg") if e.payload["lane"] == "cp"][-1:]
        gen = f"c-g{len(self.of('fast.turn')) + 1}"
        said = [{"kind": "speech", "text": ASKED}] if spoke else []
        turn = {"lane": "cp", "gen_id": gen, "call_id": "c", "ttft_ms": 1}
        cause = self.emit("fast.turn", "fast.cp", turn | {"ttfs_ms": 1, "items": said},
                          [msg.event_id])  # fmt: skip
        voiced = {"msg_id": msg.payload["msg_id"], "gen_id": gen}
        self.emit("s2f.voiced", "fast.cp", voiced, [cause.event_id])
        if spoke:
            line = {"lane": "cp", "gen_id": gen, "utt_id": f"{gen}-u0", "text": ASKED}
            self.emit("fast.sentence", "fast.cp", line, [cause.event_id])
            if deliver:
                self.deliver(gen)
        return gen

    def deliver(self, gen: str, *, interrupted: bool = False) -> None:
        """The playout of ``gen``'s sentence: whole, or cut before a word."""
        (s,) = [e for e in self.of("fast.sentence") if e.payload["gen_id"] == gen]
        heard = "" if interrupted else ASKED
        said = {"lane": "cp", "utt_id": s.payload["utt_id"], "text_generated": ASKED}
        said |= {"text_heard": heard, "interrupted": interrupted}
        self.emit("utt.delivered", "kernel", said, [s.event_id])

    def call(self) -> None:  # chan.opened(cp): INTAKE -> IN_CALL
        moved = {"previous": "INTAKE", "status": "IN_CALL"}
        self.emit("status.changed", "guard", moved, [self.root.event_id])


def _confirmed(tmp_path: Path) -> Host:
    """An offer the rep stated, read back after Slow asked for this revision."""
    h = Host(tmp_path)
    h.call()
    h.rep("cp-1", TERMS)
    ask = {"tool": "guide_fast", "move": "ask_readback", "slots": ["offer:save-2"]}
    record = {"tool": "record_offer", "offer_ref": "save-2", "offer_slots": SLOTS}
    out = h.act(record, ask)
    assert out[-1].endswith("read-back asked for save-2 r1"), out
    h.voice()  # heard whole (#219 D-B)
    h.rep("cp-2", TERMS)
    h.tools.readback()
    offer = h.bb.public.offers["save-2"]
    assert {s.status for s in offer.slots} == {"confirmed"} and offer.terms_hash
    return h


def tenure_public(h: Host) -> None:
    """S1-SYS-94: the user states the tenure in the allow-listed form and it
    is recorded public (the test plays record_fact's publication, as for a
    shared quote: ``KEYS`` holds no tenure_years): fact:tenure_years, the
    slot mention_tenure needs."""
    said = h.emit("user.msg", "kernel", {"text": "I've been with you for 8 years."})
    fact = {"key": "tenure_years", "value": "8", "source": "shareable"}
    fact |= {"source_ref": said.event_id, "scope": "public"}
    h.emit("fact.recorded", "guard", fact, [said.event_id])


def _granted(h: Host) -> None:
    """The sim approver's post and the kernel's decision (S1-SYS-02/05 wire it)."""
    (text,) = h.act({"tool": "request_approval", "offer_ref": "save-2"})
    assert text.startswith("request_approval: card apr-save-2-r1-e"), text
    assert h.bb.public.status is CaseStatus.AWAITING_APPROVAL
    card = h.bb.private.pending_approval
    assert card is not None
    (notice,) = [e for e in h.of("s2f.msg") if e.payload["type"] == "APPROVAL_NOTICE"]
    assert notice.payload["approval_id"] == card.approval_id
    post = {"subject": "approval", "subject_id": card.approval_id}
    post |= {"decision": "granted", "subject_hash": card.terms_hash}
    epoch = {"authority_epoch": card.authority_epoch}
    posted = h.emit("approval.post", "sim_approver", post | epoch)
    decided = {"approval_id": card.approval_id, "decision": "granted"}
    ev = h.emit(
        "approval.decided",
        "kernel",
        decided | {"by": "sim_approver"},
        [posted.event_id],
    )
    back = {"previous": "AWAITING_APPROVAL", "status": "IN_CALL"}
    h.emit("status.changed", "guard", back, [ev.event_id])


def _heard(h: Host, ledger: dict[str, Any], committed: bool = True) -> None:
    """The Speaker releases the accept, the rep hears it and its system writes
    the ledger, and FastC relays the confirmation id (the kernel and world
    sides); ``committed``: the kernel has moved the case to COMMITTED."""
    (line,) = [e for e in h.of("speak.verbatim") if e.payload["kind"] == "accept"]
    cap_id = line.payload["cap_id"]
    released = h.emit(
        "speak.released", "kernel", {"lane": "cp", "cap_id": cap_id}, [line.event_id]
    )
    heard = {"lane": "cp", "utt_id": "a-1", "text_generated": line.payload["text"]}
    heard |= {"text_heard": line.payload["text"], "interrupted": False}
    h.delivered = h.emit("utt.delivered", "kernel", heard, [released.event_id])
    if committed:
        _committed(h)
    done = h.rep(
        "cp-3", "Done, the offer is accepted. Your confirmation number is 482913."
    )
    binding = {"offer_ref": "save-2", "revision": 1, "term_months": 24} | ledger
    write = {"confirmation_id": "482913", "binding": binding}
    h.emit("ledger.write", "world.ledger", write, [done.event_id], "world")
    h.relay(done, "accepted, confirmation number 482913")


def _committed(h: Host) -> None:
    assert h.delivered is not None
    moved = {"previous": "COMMIT_AUTHORIZED", "status": "COMMITTED"}
    h.emit("status.changed", "guard", moved, [h.delivered.event_id])


CHECK = {"tool": "check_account", "confirmation_id": "482913"}
DONE = {"tool": "finish", "outcome": "completed", "summary": "done"}


def _accepted(tmp_path: Path) -> Host:
    h = _confirmed(tmp_path)
    _granted(h)
    h.act({"tool": "accept_offer", "offer_ref": "save-2"})
    return h


def test_the_approval_chain_reaches_verified_complete(tmp_path: Path) -> None:
    h = _confirmed(tmp_path)
    (denied,) = h.act({"tool": "accept_offer", "offer_ref": "save-2"})
    assert "denied: not_authorized" in denied and "request_approval" in denied
    _granted(h)
    (accepted,) = h.act({"tool": "accept_offer", "offer_ref": "save-2"})
    assert "accept line queued (cap-1)" in accepted
    assert h.bb.public.status is CaseStatus.COMMIT_AUTHORIZED
    (authorized,) = h.of("action.authorized")
    (decided,) = h.of("approval.decided")
    assert decided.event_id in authorized.cause_ids  # the grant it used
    _heard(h, {"terms": BOUND})
    (early,) = h.act({"tool": "finish", "outcome": "completed", "summary": "done"})
    assert "needs EVIDENCE_PENDING; the case is COMMITTED" in early and not h.ended
    account, done = h.act(CHECK, DONE)
    assert "482913 binds the accepted terms" in account
    (evidence,) = h.of("evidence.recorded")
    (write,) = h.of("ledger.write")
    assert write.event_id in evidence.cause_ids
    assert done == "finish: verified complete" and h.ended == ["completed"]
    assert h.bb.public.status is CaseStatus.VERIFIED_COMPLETE
    chain = [
        "approval.requested", "approval.decided", "action.authorized",
        "speak.released", "utt.delivered", "ledger.write", "evidence.recorded",
        "completion.decided",
    ]  # fmt: skip
    firsts = [h.of(t)[-1].seq for t in chain]  # the read-back ask was delivered too
    assert firsts == sorted(firsts)
    held, _ = approval_b(Log(h.bus.events))
    assert held == {"held": True, "accepts": 1, "via_approval": 1, "via_mandate": 0}
    (again,) = h.act(CHECK)
    assert again == "check_account: 482913 is already recorded"


def test_a_ledger_binding_other_terms_never_verifies(tmp_path: Path) -> None:
    h = _accepted(tmp_path)
    _heard(h, {"terms": BOUND, "term_months": 36})  # misquote: +12 months
    account, done = h.act(CHECK, DONE)
    assert "does not bind" in account
    assert "not verified: no_bound_evidence" in done and not h.ended
    assert h.bb.public.status is CaseStatus.NEEDS_REPLAN
    (escalated,) = h.act({"tool": "finish", "outcome": "escalate", "summary": "x"})
    assert escalated == "finish: case closed" and h.ended == ["escalate"]


def test_evidence_read_before_the_commit_still_moves_the_case(
    tmp_path: Path,
) -> None:  # review M1: no livelock when check_account runs before COMMITTED
    h = _accepted(tmp_path)
    _heard(h, {"terms": BOUND}, committed=False)
    (first,) = h.act(CHECK)
    assert "binds the accepted terms" in first
    assert h.bb.public.status is CaseStatus.COMMIT_AUTHORIZED
    _committed(h)
    again, done = h.act(CHECK, DONE)
    assert again == "check_account: 482913 is already recorded"
    assert len(h.of("evidence.recorded")) == 1
    assert done == "finish: verified complete" and h.ended == ["completed"]
    assert h.bb.public.status is CaseStatus.VERIFIED_COMPLETE


@pytest.mark.parametrize("price", ["69.009", "sixty-nine", "NaN", "Infinity"])
def test_ledger_money_must_be_exact_and_readable(tmp_path: Path, price: str) -> None:
    """Review M2: $69.009 is not $69.00 (no truncation); N2: a malformed world
    value fails closed as evidence that binds nothing, not as a Slow error."""
    h = _accepted(tmp_path)
    _heard(h, {"terms": BOUND | {"monthly_price": price}})
    account, done = h.act(CHECK, DONE)
    assert account == "check_account: 482913: evidence unreadable, it binds nothing"
    (evidence,) = h.of("evidence.recorded")
    assert evidence.payload["terms_hash"] is None
    assert "not verified: no_bound_evidence" in done and not h.ended


_UNSTATED = {k: v for k, v in BOUND.items() if k not in ("fees_none", "changes_none")}


@pytest.mark.parametrize(
    "ledger",
    [
        BOUND | {"changes_none": "false"},  # a change it never records
        BOUND | {"fees_none": "false"},  # a fee it never records
        {k: v for k, v in BOUND.items() if k != "fees_none"},  # completeness unstated
        {k: v for k, v in BOUND.items() if k != "changes_none"},
        _UNSTATED,
        _UNSTATED | {"applied_change:plan_swap": "false"},  # no change applied, no list
        BOUND | {"applied_change:plan_swap": "true"},  # no changes, yet a change
        BOUND | {"fee:activation": "20.00"},  # no fees, yet a fee
        # review of #151: a boolean outside true/false is unreadable, not dropped
        *(BOUND | {"applied_change:plan_swap": v} for v in ("True", "yes", "1", "")),
        BOUND | {"feature:hotspot": "True"},
    ],
)
def test_a_ledger_must_state_fee_and_change_completeness(
    tmp_path: Path, ledger: dict[str, str]
) -> None:
    """S1-SYS-19: an unrecorded fee or change, or no completeness statement at
    all, never verifies as the accepted terms (fail closed: it binds nothing)."""
    h = _accepted(tmp_path)
    _heard(h, {"terms": ledger})
    account, done = h.act(CHECK, DONE)
    assert account == "check_account: 482913: evidence unreadable, it binds nothing"
    (evidence,) = h.of("evidence.recorded")
    assert evidence.payload["terms_hash"] is None
    assert "not verified: no_bound_evidence" in done and not h.ended
    assert h.bb.public.status is CaseStatus.NEEDS_REPLAN


def test_a_confirmation_counts_only_if_it_was_relayed_to_slow(
    tmp_path: Path,
) -> None:  # I5: Slow looks up only an id it was told
    h = _accepted(tmp_path)
    _heard(h, {"terms": BOUND})
    h.tools.received.clear()  # the relay exists, but Slow never received it
    (unseen,) = h.act(CHECK)
    assert "no such confirmation relayed" in unseen
    guess = CHECK | {"confirmation_id": "4829"}  # a part of the id is no id
    h.tools.received.update(str(e.payload["msg_id"]) for e in h.of("f2s.msg"))
    (partial,) = h.act(guess)
    assert "no such confirmation relayed" in partial
    assert not h.of("evidence.recorded")
    h.relay(h.of("utt.final")[-1], "their number is 777777")
    (absent,) = h.act(CHECK | {"confirmation_id": "777777"})
    assert "the account shows no confirmation 777777" in absent
    assert not h.of("evidence.recorded")


def test_a_mandate_restriction_is_never_dropped(tmp_path: Path) -> None:
    h = Host(tmp_path)  # review N1: a malformed restriction is refused, loudly
    for bad in ("roaming", {"x": 1}, [3]):
        (text,) = h.act(
            {"tool": "propose_mandate", "envelope": {"required_features": bad}}
        )
        assert text.startswith("propose_mandate: invalid arguments"), text
    assert h.bb.private.mandate is None


def test_a_read_back_confirms_only_the_revision_it_was_asked_for(
    tmp_path: Path,
) -> None:
    h = Host(tmp_path)
    h.call()
    h.rep("cp-1", TERMS)
    h.act({"tool": "record_offer", "offer_ref": "save-2", "offer_slots": SLOTS})
    h.rep("cp-2", TERMS)  # repeated, but nobody asked for a read-back
    h.tools.readback()
    assert {s.status for s in h.bb.public.offers["save-2"].slots} == {"heard"}
    (denied,) = h.act({"tool": "request_approval", "offer_ref": "save-2"})
    assert "denied: readback_not_confirmed" in denied and "ask_readback" in denied
    ask = {"tool": "guide_fast", "move": "ask_readback", "slots": ["offer:save-2"]}
    h.act(ask)
    h.voice()
    h.rep("cp-3", TERMS)
    h.tools.readback()
    assert {s.status for s in h.bb.public.offers["save-2"].slots} == {"confirmed"}
    h.rep("cp-4", TERMS.replace("$69", "$68"))  # S1-SYS-28: r2 changes a term
    cheaper = [
        s | {"utt_ref": "cp-4"} | ({"value": "6800"} if s["value"] == "6900" else {})
        for s in SLOTS
    ]
    h.act({"tool": "record_offer", "offer_ref": "save-2", "offer_slots": cheaper})
    assert h.bb.public.offers["save-2"].revision == 2
    h.tools.readback()  # r2: the r1 request confirms nothing
    assert {s.status for s in h.bb.public.offers["save-2"].slots} == {"heard"}
    (updated,) = {e.payload["offer_ref"] for e in h.of("readback.updated")}
    assert updated == "save-2"


def test_models_restrict_authority_but_never_grant_it(tmp_path: Path) -> None:
    h = _confirmed(tmp_path)
    envelope = {"max_monthly_price_minor": 7000, "max_term_months": 24}
    proposed, accept = h.act(
        {"tool": "propose_mandate", "envelope": envelope},
        {"tool": "accept_offer", "offer_ref": "save-2"},
    )
    assert "grants nothing until the user decides it" in proposed
    assert "denied: not_authorized" in accept
    m = h.bb.private.mandate
    assert m is not None and m.status == "proposed" and m.decided_by is None
    (looser,) = h.act(
        {"tool": "tighten_mandate", "changes": {"max_monthly_price_minor": 9000}}
    )
    assert "only restricts" in looser and h.bb.epoch == 0
    (tighter,) = h.act(
        {"tool": "tighten_mandate", "changes": {"max_monthly_price_minor": 6500}}
    )
    m = h.bb.private.mandate
    assert "re-grant" in tighter and h.bb.epoch == 1
    assert m is not None and (m.status, m.epoch, m.max_monthly_price_minor) == (
        "proposed",
        1,
        6500,
    )
    _granted(h)  # a card at epoch 1, granted
    (revoked,) = h.act({"tool": "revoke", "reason": "the user said stop"})
    assert "epoch 2" in revoked and h.bb.epoch == 2
    (stale,) = h.act({"tool": "accept_offer", "offer_ref": "save-2"})
    assert "denied: approval_stale_epoch" in stale
    reasons = [e.payload["reason"] for e in h.of("action.denied")]
    assert reasons == ["not_authorized", "loosen", "approval_stale_epoch"]


def test_a_granted_mandate_authorises_an_accept_that_cites_it(
    tmp_path: Path,
) -> None:
    h = _confirmed(tmp_path)
    envelope = {"max_monthly_price_minor": 7000, "max_term_months": 24}
    h.act({"tool": "propose_mandate", "envelope": envelope})
    m = h.bb.private.mandate
    assert m is not None
    post = {"subject": "mandate", "subject_id": m.mandate_id, "decision": "granted"}
    post |= {"subject_hash": m.mandate_hash, "authority_epoch": 0}
    posted = h.emit("approval.post", "ui", post)
    decision = {"mandate_id": m.mandate_id, "mandate_hash": m.mandate_hash}
    decision |= {"decision": "granted", "by": "ui"}
    decided = h.emit("mandate.decided", "kernel", decision, [posted.event_id])
    bump = {"new": 1, "reason": "mandate_decided"}
    h.emit("authority.epoch", "kernel", bump, [decided.event_id])
    (accepted,) = h.act({"tool": "accept_offer", "offer_ref": "save-2"})
    assert "accept line queued" in accepted
    (authorized,) = h.of("action.authorized")
    assert decided.event_id in authorized.cause_ids


def test_levers_need_the_users_facts(tmp_path: Path) -> None:
    h = Host(tmp_path)
    h.call()
    h.rep("cp-1", "Orbit Mobile charges 62 dollars, you say?")
    slot = "fact:competitor.price_usd"
    cite = {"tool": "guide_fast", "move": "cite_competitor", "slots": [slot]}
    record = {"tool": "record_fact", "key": "competitor.price_usd", "value": "62"}
    unrecorded, _, rep_said, cancel = h.act(
        cite,
        record | {"utt_ref": "cp-1"},  # public, but the rep's word, not the user's
        cite,
        {"tool": "guide_fast", "move": "cancel_lever"},
    )
    assert h.bb.public.facts["competitor.price_usd"].source == "cp_utt"
    assert "no fabricated quotes" in unrecorded and "no fabricated quotes" in rep_said
    assert "authorization.cancel_lever=granted" in cancel
    reasons = [e.payload["reason"] for e in h.of("action.denied")]
    assert reasons == [
        "competitor_quote_not_shareable",
        "competitor_quote_not_shareable",
        "cancel_lever_not_authorized",
    ]
    assert not [e for e in h.of("s2f.msg") if e.payload["type"] == "GUIDE"]


def test_a_shared_fact_follows_the_record_fact_rule(tmp_path: Path) -> None:
    h = Host(tmp_path)
    said = h.emit("user.msg", "kernel", {"text": "I'm Marcus Bell, 5190."})
    # S1-SYS-94: cite a message without it (a ref naming no line is refused)
    other = h.root.event_id
    record = {"tool": "record_fact", "key": "account.last4", "utt_ref": other}
    out = h.act(
        record | {"value": "5190"},  # not the message that says it: private
        {"tool": "share_fact", "key": "account.holder_name"},
        {"tool": "share_fact", "key": "tenure_years"},
        {"tool": "share_fact", "key": "account.last4"},
    )
    assert "account.holder_name is not recorded" in out[1]
    assert "denied: not_shareable" in out[2]
    assert "account.last4 stays private" in out[3]
    ids = ("account.holder_name", "account.last4")
    intake = asks.Intake(ids, None, 120_000, h.calls.needs)
    bar = status_bar(view_slow(h.bb, SlowViewMode.RELAY_ONLY, "b"), 0, intake)
    private = "account.last4 answered, recorded private: re-record it citing"
    assert private in bar and "account.holder_name not asked" in bar  # #140
    h.act(record | {"value": "5190", "utt_ref": said.event_id})
    assert h.bb.public.facts["account.last4"].source_ref == said.event_id


def test_no_deal_needs_the_final_offer_asked_and_a_closing_reply(
    tmp_path: Path,
) -> None:
    h = Host(tmp_path)
    h.call()
    finish = {"tool": "finish", "outcome": "no_deal", "summary": "no deal"}
    (early,) = h.act(finish)
    assert "final_offer_not_asked" in early and not h.ended
    h.act({"tool": "guide_fast", "move": "ask_final_offer"})
    h.voice()  # heard whole: it anchors the window (S1-SYS-57)
    h.rep("cp-1", "I am afraid I cannot do better than what I offered.")
    (done,) = h.act(finish)
    assert done == "finish: verified no deal" and h.ended == ["no_deal"]
    assert h.bb.public.status is CaseStatus.VERIFIED_NO_DEAL


def test_no_deal_judges_the_rep_after_the_last_final_offer_ask(
    tmp_path: Path,
) -> None:  # S1-SYS-57
    h = Host(tmp_path)
    h.call()
    finish = {"tool": "finish", "outcome": "no_deal", "summary": "no deal"}
    ask = {"tool": "guide_fast", "move": "ask_final_offer"}
    h.act(ask)
    h.voice()  # each ask heard whole
    h.rep("cp-1", "I am afraid I cannot do better than what I offered.")
    h.act(ask)  # a second ask: the window starts again here
    h.voice()
    (early,) = h.act(finish)
    assert "no_closing_reply" in early and not h.ended
    h.rep("cp-2", "That is our best offer.")
    (done,) = h.act(finish)
    assert done == "finish: verified no deal" and h.ended == ["no_deal"]


def test_record_offer_sets_the_stated_expiry_on_the_session_clock(
    tmp_path: Path,
) -> None:
    h = Host(tmp_path)
    h.rep("cp-1", "It is $69 a month, valid until 2026-09-26T00:10:00Z.")
    slot = {"field": "expires", "value": "2026-09-26T00:10:00Z", "utt_ref": "cp-1"}
    (text,) = h.act({"tool": "record_offer", "offer_ref": "o1", "offer_slots": [slot]})
    offer = h.bb.public.offers["o1"]  # ten minutes from the session's start
    assert offer.expires_ms == 600_000 and "expires at t=600000 ms" in text
    bar = status_bar(view_slow(h.bb, SlowViewMode.RELAY_ONLY, "b"), 300_000)
    assert "expires in 300 s" in bar and "not recorded: monthly_price" in bar


def test_the_status_bar_shows_authority_state(tmp_path: Path) -> None:
    h = _confirmed(tmp_path)
    h.act({"tool": "request_approval", "offer_ref": "save-2"})
    raised = {"op": "raised", "fence_id": "f1", "utt_id": h.root.event_id}
    h.emit("authority.fence", "kernel", raised, [h.root.event_id])
    bar = status_bar(view_slow(h.bb, SlowViewMode.RELAY_ONLY, "b"), 0)
    assert "\ncase: AWAITING_APPROVAL;" in bar and "fences raised: 1" in bar
    assert "apr-save-2-r1-e0-0 for save-2 r1 pending, expires in 1" in bar
    assert "save-2 r1 (open, read-back confirmed)" in bar and "mandate: none" in bar


def test_finish_moves_only_along_the_status_machine(tmp_path: Path) -> None:
    h = Host(tmp_path)
    h.call()
    escalate, completed, bogus = h.act(
        {"tool": "finish", "outcome": "escalate", "summary": "x"},
        {"tool": "finish", "outcome": "completed", "summary": "x"},
        {"tool": "finish", "outcome": "won", "summary": "x"},
    )
    assert "not possible while the case is IN_CALL" in escalate
    assert "needs EVIDENCE_PENDING" in completed and "unknown outcome" in bogus
    assert not h.ended and not h.tools.finished
    (closed,) = h.act({"tool": "finish", "outcome": "info_only", "summary": "x"})
    assert closed == "finish: case closed" and h.ended == ["info_only"]


SNAPSHOT = Path(__file__).parent / "snapshots" / "act_tool.json"


def test_the_act_tool_schema_matches_its_snapshot() -> None:
    """A deliberate schema change updates the snapshot in the same PR."""
    got = json.dumps(ACT.model_dump(mode="json"), indent=1, sort_keys=True) + "\n"
    assert got == SNAPSHOT.read_text("utf-8")


@pytest.mark.parametrize(
    "tool",
    ["share_fact", "propose_mandate", "tighten_mandate", "revoke",
     "request_approval", "accept_offer", "decline_offer", "check_account"],
)  # fmt: skip
def test_every_authority_tool_is_in_the_schema(tool: str) -> None:
    calls = cast(dict[str, Any], ACT.parameters["properties"])["calls"]
    assert tool in calls["items"]["properties"]["tool"]["enum"]


def test_slow_judges_guides_with_the_kernels_cp_profile() -> None:
    """One cp profile (#154 review): what Slow checks is what FastC renders."""
    assert slow_tools.CP_PROFILE == PROFILE["cp"] == "pl_cp_v3"


def test_a_move_the_cp_profile_cannot_render_raises_out_of_act(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # #154 review: a GuideMoveError is a bug, never "invalid arguments"
    monkeypatch.setattr(slow_tools, "CP_PROFILE", "pl_cp_v1")  # ADR-0011: no text
    h = Host(tmp_path)
    (sent,) = h.act({"tool": "guide_fast", "move": "hold_for_decision"})
    assert sent.startswith("guide_fast: sent")
    with pytest.raises(GuideMoveError, match="hold_for_fact"):
        h.act({"tool": "guide_fast", "move": "hold_for_fact"})


def test_the_same_terms_again_are_unchanged_and_a_change_is_a_revision(
    tmp_path: Path,
) -> None:
    """ed5063 r3: identical to r2 but for utt_ref, it was another revision and
    another read-back; the confirmed revision now stands."""
    h = _confirmed(tmp_path)
    asked = dict(h.tools.asked)
    h.rep("cp-4", "Again: $69 a month for 24 months.")
    again = [s | {"utt_ref": "cp-4"} for s in SLOTS]
    record = {"tool": "record_offer", "offer_ref": "save-2"}
    (text,) = h.act(record | {"offer_slots": again})
    assert text == "record_offer: unchanged save-2 r1"
    offer = h.bb.public.offers["save-2"]
    assert offer.revision == 1 and {s.status for s in offer.slots} == {"confirmed"}
    assert len(h.of("offer.recorded")) == 1 and h.tools.asked == asked
    h.rep("cp-5", "It is $68 a month on a 24-month term.")
    cheaper = [
        s | {"value": "6800", "utt_ref": "cp-5"} if s["field"] == "monthly_price" else s
        for s in SLOTS
    ]
    (text,) = h.act(record | {"offer_slots": cheaper})
    assert text == "record_offer: recorded save-2 r2"
    assert h.bb.public.offers["save-2"].revision == 2


def _mandate(h: Host, max_minor: int, **more: Any) -> None:
    """A granted mandate, as the UI and the kernel decide it."""
    envelope = {"max_monthly_price_minor": max_minor, **more}
    h.act({"tool": "propose_mandate", "envelope": envelope})
    m = h.bb.private.mandate
    assert m is not None
    post = {"subject": "mandate", "subject_id": m.mandate_id, "decision": "granted"}
    post |= {"subject_hash": m.mandate_hash, "authority_epoch": 0}
    posted = h.emit("approval.post", "ui", post)
    decision = {"mandate_id": m.mandate_id, "mandate_hash": m.mandate_hash}
    decision |= {"decision": "granted", "by": "ui"}
    decided = h.emit("mandate.decided", "kernel", decision, [posted.event_id])
    bump = {"new": 1, "reason": "mandate_decided"}
    h.emit("authority.epoch", "kernel", bump, [decided.event_id])


HINT = "save-2 confirmed, outside mandate → request_approval(save-2)"


def _bar(h: Host) -> str:
    return status_bar(view_slow(h.bb, SlowViewMode.RELAY_ONLY, "b"), h.now())


def test_a_confirmed_offer_outside_the_mandate_shows_request_approval(
    tmp_path: Path,
) -> None:
    h = _confirmed(tmp_path)  # $69
    _mandate(h, 6500)  # ed5063: $78 against a $65 envelope
    assert HINT in _bar(h)
    h.act({"tool": "request_approval", "offer_ref": "save-2"})
    assert "outside mandate" not in _bar(h)  # its card is out: wait for the user


def test_a_confirmed_offer_inside_the_mandate_shows_no_hint(tmp_path: Path) -> None:
    h = _confirmed(tmp_path)
    _mandate(h, 7000)
    assert "outside mandate" not in _bar(h)


def test_no_hint_when_guard_would_refuse_the_request(tmp_path: Path) -> None:
    """#166 review D1: the hint fires only when Guard would allow
    request_approval; a hard violation, unbound terms or an expired offer
    would be denied, and a hint repeated after a denial drives a loop."""
    h = _confirmed(tmp_path)
    _mandate(h, 6500, required_features=["unlimited_data"])
    assert "outside mandate" not in _bar(h)
    (denied,) = h.act({"tool": "request_approval", "offer_ref": "save-2"})
    assert "denied: policy_violation" in denied
    (tmp_path / "b").mkdir()
    h = _confirmed(tmp_path / "b")
    _mandate(h, 6500)
    view = view_slow(h.bb, SlowViewMode.RELAY_ONLY, "b")
    assert HINT in status_bar(view, h.now())
    (o,) = view.offers
    for change in ({"terms_hash": "0" * 64}, {"expires_ms": h.now()}):
        bad = view.model_copy(update={"offers": (o.model_copy(update=change),)})
        assert "outside mandate" not in status_bar(bad, h.now()), change


@pytest.mark.parametrize("end", ["expires", "decided"])
def test_a_pending_card_for_another_offer_hides_the_hint(
    tmp_path: Path, end: str
) -> None:
    """#166 review D1 (round 3c): Guard refuses any new card while one is
    pending, whatever its offer; the hint for a second offer waits for it."""
    h = _confirmed(tmp_path)  # save-2, $69
    _mandate(h, 6500)
    h.act({"tool": "request_approval", "offer_ref": "save-2"})
    card = h.bb.private.pending_approval
    assert card is not None
    seventy = TERMS.replace("$69", "$70")
    h.rep("cp-5", seventy)
    s3 = [
        s | {"utt_ref": "cp-5"} | ({"value": "7000"} if s["value"] == "6900" else {})
        for s in SLOTS
    ]
    ask = {"tool": "guide_fast", "move": "ask_readback", "slots": ["offer:save-3"]}
    h.act({"tool": "record_offer", "offer_ref": "save-3", "offer_slots": s3}, ask)
    h.voice()
    h.rep("cp-6", seventy)
    h.tools.readback()
    assert {s.status for s in h.bb.public.offers["save-3"].slots} == {"confirmed"}
    hint = "save-3 confirmed, outside mandate → request_approval(save-3)"
    assert "request_approval(save-3)" not in _bar(h)
    (pending,) = h.act({"tool": "request_approval", "offer_ref": "save-3"})
    assert "denied: approval_pending" in pending
    if end == "expires":
        h.clock.advance(CARD_TTL_MS)
    else:  # the user denies the save-2 card
        post = {"subject": "approval", "subject_id": card.approval_id}
        post |= {"decision": "denied", "subject_hash": card.terms_hash}
        post |= {"authority_epoch": card.authority_epoch}
        posted = h.emit("approval.post", "ui", post)
        decided = {"approval_id": card.approval_id, "decision": "denied", "by": "ui"}
        h.emit("approval.decided", "kernel", decided, [posted.event_id])
    assert hint in _bar(h)
    (sent,) = h.act({"tool": "request_approval", "offer_ref": "save-3"})
    assert sent.startswith("request_approval: card apr-save-3-r1-e"), sent
