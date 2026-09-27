"""Regressions from the #126 review probes (probe_bus.py): the bus never writes
an authority event that a replay could not justify. Probe 5 (a release
without ``cap_id``) is M7, owned by S1-SYS-02 and evidence-check."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from tests.guard.build import CASE, offer
from tests.support.manual_clock import ManualClock

from proxyloop.contract.events import ApprovalPost
from proxyloop.contract.state import OfferPublic
from proxyloop.core.bus import Bus
from proxyloop.guard.authorize import Denial, accept_offer, decide, request_approval
from proxyloop.guard.mandate import proposal
from proxyloop.guard.status import status_change
from proxyloop.guard.terms import offer_terms_hash


class Session:
    def __init__(self, tmp_path: Path) -> None:
        self.clock = ManualClock()
        self.bus = Bus(tmp_path / "events.jsonl", "r1", self.clock)
        self.last = self.bus.emit(
            "user.msg", "kernel", "agent", {"text": "go"}
        ).event_id

    def emit(self, type_: str, actor: str, payload: Mapping[str, object]) -> str:
        self.last = self.bus.emit(type_, actor, "agent", payload, [self.last]).event_id
        return self.last

    def confirmed(self, raw: OfferPublic | None = None) -> None:
        raw = raw or offer()
        recorded = raw.model_dump(
            mode="json", include={"offer_ref", "revision", "slots"}
        )
        self.emit("offer.recorded", "guard", recorded | {"terms_hash": None})
        done = raw.model_copy(
            update={
                "slots": tuple(
                    s.model_copy(update={"status": "confirmed"}) for s in raw.slots
                )
            }
        )
        statuses = {s.field: "confirmed" for s in raw.slots}
        update: dict[str, object] = {"offer_ref": "o1", "revision": raw.revision}
        update |= {"slot_statuses": statuses, "terms_hash": offer_terms_hash(done)}
        self.emit("readback.updated", "guard", update)

    def card(self) -> dict[str, object]:
        effects = request_approval(self.bus.bb, "o1", CASE)
        assert not isinstance(effects, Denial), effects
        ((kind, card),) = effects
        self.emit(kind, "guard", card)
        return card

    def post(
        self, card: dict[str, object], decision: str = "granted", **kw: object
    ) -> str:
        post: dict[str, object] = {
            "subject": "approval",
            "subject_id": card["approval_id"],
        }
        post |= {"decision": decision, "subject_hash": card["terms_hash"]}
        return self.emit("approval.post", "ui", post | {"authority_epoch": 0} | kw)

    def decided(self, card: dict[str, object], decision: str = "granted") -> None:
        payload = {"approval_id": card["approval_id"], "decision": decision, "by": "ui"}
        self.emit("approval.decided", "kernel", payload)

    def accept(self) -> str:
        effects = accept_offer(self.bus.bb, "o1", CASE)
        assert not isinstance(effects, Denial), effects
        for kind, payload in effects:
            self.emit(kind, "guard", payload)
        return str(effects[1][1]["cap_id"])


def test_1_a_post_must_bind_the_cards_terms_and_epoch(tmp_path: Path) -> None:
    s = Session(tmp_path)
    s.confirmed()
    card = s.card()
    with pytest.raises(ValueError, match="not the pending approval"):
        s.post(card, subject_hash="deadbeef")
    with pytest.raises(ValueError, match="not the pending approval"):
        s.post(card, authority_epoch=7)
    assert s.bus.bb.private.approvals == {}


def test_2_an_expired_card_cannot_be_decided(tmp_path: Path) -> None:
    s = Session(tmp_path)
    s.confirmed()
    card = s.card()
    s.clock.advance(10_000_000)
    s.post(card)
    with pytest.raises(ValueError, match="superseded, stale or expired"):
        s.decided(card)
    assert accept_offer(s.bus.bb, "o1", CASE) == Denial("not_authorized")


def test_3_a_later_denial_of_the_same_terms_wins(tmp_path: Path) -> None:
    s = Session(tmp_path)
    s.confirmed()
    first = s.card()
    s.post(first)
    s.decided(first)
    second = s.card()
    s.post(second, "denied")
    s.decided(second, "denied")
    assert accept_offer(s.bus.bb, "o1", CASE) == Denial("approval_denied")


def test_4_a_denial_overrides_a_covering_mandate(tmp_path: Path) -> None:
    s = Session(tmp_path)
    s.confirmed()
    kind, m = proposal(s.bus.bb, "m1", max_monthly_price_minor=9000)
    s.emit(kind, "guard", m)
    post: dict[str, object] = {"subject": "mandate", "subject_id": "m1"}
    post |= {"decision": "granted", "subject_hash": m["mandate_hash"]}
    s.emit("approval.post", "ui", post | {"authority_epoch": 0})
    decided = {"mandate_id": "m1", "mandate_hash": m["mandate_hash"]}
    s.emit("mandate.decided", "kernel", decided | {"decision": "granted", "by": "ui"})
    assert not isinstance(accept_offer(s.bus.bb, "o1", CASE), Denial)  # it covers
    card = s.card()
    s.post(card, "denied")
    s.decided(card, "denied")
    assert accept_offer(s.bus.bb, "o1", CASE) == Denial("approval_denied")


def _queued(tmp_path: Path) -> tuple[Session, str]:
    s = Session(tmp_path)
    s.confirmed()
    card = s.card()
    s.post(card)
    s.decided(card)
    return s, s.accept()


@pytest.mark.parametrize("change", ["fence", "epoch", "declined", "new_terms"])
def test_6_a_release_needs_the_time_free_revalidation(
    tmp_path: Path, change: str
) -> None:
    s, cap_id = _queued(tmp_path)
    if change == "fence":
        s.emit(
            "authority.fence",
            "kernel",
            {"op": "raised", "fence_id": "f1", "utt_id": "u9"},
        )
    elif change == "epoch":
        s.emit("authority.epoch", "kernel", {"new": 1, "reason": "f2s_revoke"})
    elif change == "declined":
        line = {"lane": "cp", "kind": "decline", "text": "No.", "offer_ref": "o1"}
        s.emit("speak.verbatim", "guard", line)
    else:
        s.confirmed(offer(monthly="6500").model_copy(update={"revision": 2}))
    with pytest.raises(ValueError, match=f"release of {cap_id}"):
        s.emit("speak.released", "kernel", {"lane": "cp", "cap_id": cap_id})
    assert not s.bus.bb.capabilities[cap_id].consumed


def test_6_a_release_passes_when_nothing_changed(tmp_path: Path) -> None:
    s, cap_id = _queued(tmp_path)
    s.emit("speak.released", "kernel", {"lane": "cp", "cap_id": cap_id})
    assert s.bus.bb.capabilities[cap_id].consumed


def test_7_the_status_machine_holds_in_the_fold(tmp_path: Path) -> None:
    s = Session(tmp_path)
    s.emit("status.changed", "guard", {"previous": "INTAKE", "status": "IN_CALL"})
    s.emit("completion.decided", "guard", {"verdict": "ok", "reasons": []})
    with pytest.raises(ValueError, match="but the case is IN_CALL"):
        s.emit(
            "status.changed",
            "guard",
            {"previous": "COMMITTED", "status": "VERIFIED_COMPLETE"},
        )
    with pytest.raises(ValueError, match="not a status transition"):
        s.emit(
            "status.changed",
            "guard",
            {"previous": "IN_CALL", "status": "VERIFIED_COMPLETE"},
        )
    s.emit(
        "status.changed", "guard", {"previous": "IN_CALL", "status": "VERIFIED_NO_DEAL"}
    )
    with pytest.raises(ValueError, match="not a status transition"):  # terminal
        s.emit(
            "status.changed",
            "guard",
            {"previous": "VERIFIED_NO_DEAL", "status": "IN_CALL"},
        )
    with pytest.raises(ValueError, match="not a status transition"):
        s.emit(
            "status.changed",
            "guard",
            {"previous": "VERIFIED_NO_DEAL", "status": "ABANDONED"},
        )


def test_7_verified_no_deal_needs_no_released_accept(tmp_path: Path) -> None:
    s, cap_id = _queued(tmp_path)
    s.emit("speak.released", "kernel", {"lane": "cp", "cap_id": cap_id})
    s.emit("status.changed", "guard", {"previous": "INTAKE", "status": "IN_CALL"})
    s.emit("completion.decided", "guard", {"verdict": "ok", "reasons": []})
    with pytest.raises(ValueError, match="of its kind"):
        s.emit(
            "status.changed",
            "guard",
            {"previous": "IN_CALL", "status": "VERIFIED_NO_DEAL"},
        )


def test_8_a_superseded_card_neither_blocks_nor_decides(tmp_path: Path) -> None:
    s = Session(tmp_path)
    s.confirmed()
    old = s.card()
    s.confirmed(offer(monthly="6500").model_copy(update={"revision": 2}))
    s.clock.advance(119_000)
    effects = request_approval(s.bus.bb, "o1", CASE)
    assert not isinstance(effects, Denial)
    post = ApprovalPost.model_validate(
        {
            "subject": "approval",
            "subject_id": old["approval_id"],
            "decision": "granted",
            "subject_hash": old["terms_hash"],
            "authority_epoch": 0,
        }
    )
    assert decide(s.bus.bb, post, "ui") == Denial("card_superseded")
    s.post(old)
    with pytest.raises(ValueError, match="superseded, stale or expired"):
        s.decided(old)


def test_9_authority_is_minted_only_in_the_current_epoch(tmp_path: Path) -> None:
    s = Session(tmp_path)
    s.confirmed()
    kind, m = proposal(s.bus.bb, "m1", max_monthly_price_minor=9000)
    with pytest.raises(ValueError, match="epoch 1, not 0"):
        s.emit(kind, "guard", m | {"epoch": 1})
    effects = request_approval(s.bus.bb, "o1", CASE)
    assert not isinstance(effects, Denial)
    card = dict(effects[0][1]) | {"authority_epoch": 1}
    card["binding"] = dict(card["binding"]) | {"authority_epoch": 1}  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="not minted in epoch 0"):
        s.emit("approval.requested", "guard", card)
    s.emit(kind, "guard", m)
    s.emit("authority.epoch", "kernel", {"new": 1, "reason": "slow_revoke"})
    decided = {
        "mandate_id": "m1",
        "mandate_hash": m["mandate_hash"],
        "decision": "granted",
    }
    with pytest.raises(ValueError, match="no such proposed mandate"):  # stale proposal
        s.emit("mandate.decided", "kernel", decided | {"by": "ui"})


def _later(s: Session, ms: int) -> None:
    """Advance the clock; Guard's now is the last event's time, so a rep speaks."""
    s.clock.advance(ms)
    said = {"lane": "cp", "speaker": "partner", "utt_id": f"c-{ms}", "text": "Hi?"}
    s.emit("utt.final", "kernel", said)


def _second_grant(s: Session) -> None:
    """Grant B for the same terms 30 s after A; then the clock passes A's expiry."""
    first = next(iter(s.bus.bb.private.approvals.values()))
    _later(s, 30_000)
    b = s.card()
    s.post(b)
    s.decided(b)
    assert first.expires_ms is not None
    _later(s, first.expires_ms - s.clock.monotonic_ms() + 1)
    assert s.bus.bb.t_ms > first.expires_ms


def test_10_one_released_accept_per_terms(tmp_path: Path) -> None:
    """Reviewer probe (MAJOR-1): grant A, accept, released; grant B 30 s later;
    past A's expiry, B must not mint a second accept of these terms."""
    s, cap_a = _queued(tmp_path)
    s.emit("speak.released", "kernel", {"lane": "cp", "cap_id": cap_a})
    _second_grant(s)
    assert accept_offer(s.bus.bb, "o1", CASE) == Denial("already_accepted")


def test_10_the_fold_releases_one_accept_per_terms(tmp_path: Path) -> None:
    s, cap_a = _queued(tmp_path)
    _second_grant(s)
    cap_b = s.accept()  # B's capability, queued while A's is still unreleased
    s.emit("speak.released", "kernel", {"lane": "cp", "cap_id": cap_a})
    with pytest.raises(ValueError, match="already released"):
        s.emit("speak.released", "kernel", {"lane": "cp", "cap_id": cap_b})
    assert not s.bus.bb.capabilities[cap_b].consumed


def test_10_the_fold_mints_no_accept_after_one_was_released(tmp_path: Path) -> None:
    s, cap_a = _queued(tmp_path)
    _second_grant(s)
    effects = accept_offer(s.bus.bb, "o1", CASE)  # minted before A's release...
    assert not isinstance(effects, Denial)
    s.emit("speak.released", "kernel", {"lane": "cp", "cap_id": cap_a})
    with pytest.raises(ValueError, match="already released"):  # ...emitted after
        s.emit(effects[0][0], "guard", effects[0][1])


def _move(s: Session, *triggers: str) -> None:
    for trigger in triggers:
        change = status_change(s.bus.bb, trigger)
        assert change is not None, trigger
        s.emit("status.changed", "guard", change)


def test_11_a_truncated_accept_is_retried_only_on_a_new_revision(
    tmp_path: Path,
) -> None:
    """The fold does not model "truncated" yet (S1-SYS-02): a released accept
    consumed its capability, so these terms stay accepted; a new revision
    (new terms_hash) and a new grant may mint again."""
    s = Session(tmp_path)
    _move(s, "call_opened")
    s.confirmed()
    card = s.card()
    s.post(card)
    s.decided(card)
    cap = s.accept()
    _move(s, "accept_authorized")
    s.emit("speak.released", "kernel", {"lane": "cp", "cap_id": cap})
    _move(s, "accept_truncated", "replan")  # NEEDS_REPLAN, then IN_CALL
    again = s.card()
    s.post(again)
    s.decided(again)
    assert accept_offer(s.bus.bb, "o1", CASE) == Denial("already_accepted")
    s.confirmed(offer().model_copy(update={"revision": 2}))  # the same prices
    assert s.bus.bb.public.offers["o1"].terms_hash != card["terms_hash"]
    assert accept_offer(s.bus.bb, "o1", CASE) == Denial("not_authorized")
    new = s.card()
    s.post(new)
    s.decided(new)
    cap_2 = s.accept()
    s.emit("speak.released", "kernel", {"lane": "cp", "cap_id": cap_2})
    assert s.bus.bb.capabilities[cap_2].consumed
