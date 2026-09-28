"""S1-SYS-66 (ADR-0018 V3/V5 amended): the full playbook negotiates before it
asks the user or declines. For a confirmed offer outside the granted mandate,
the offers line names an available lever first (one per rep reply: wait while
one is on its way); only once none is left does it say request_approval. After
a denial the playbook again tries an available lever before decline_offer and
ask_final_offer. The levers line keys "heard" on what the rep heard
(``slow.heard.fates``): heard, still on its way (queued or playing), or dead
(cancelled, cut, no speech: available again). No world wording (rule 12).
The test plays the kernel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.slow import test_authority as auth
from tests.slow.test_authority import HINT, Host

from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.views import view_slow
from proxyloop.slow import prompt, state

_confirmed = auth._confirmed  # pyright: ignore[reportPrivateUsage]
_mandate = auth._mandate  # pyright: ignore[reportPrivateUsage]

TENURE = {"tool": "guide_fast", "move": "mention_tenure"}  # slot-free (state.WHY)
CANCEL = {"tool": "guide_fast", "move": "cancel_lever"}
REQUEST = {"tool": "request_approval", "offer_ref": "save-2"}
OUTSIDE = "save-2 confirmed, outside mandate → "
COMPETITOR = (
    "cite_competitor unavailable (competitor_quote_not_shareable: no competitor "
    "quote the user shared is public)"
)
CANCELLING = (
    "cancel_lever unavailable (cancel_lever_not_authorized: cancelling cannot be "
    "authorised in this build)"
)
WAIT = "sent, not heard yet (wait): mention_tenure"
HEARD = "heard by the rep: mention_tenure"
FORBIDDEN = ("rung", "ladder", "unlock", "second offer")


def _more(h: Host) -> state.Bar:
    h.tools.readback()
    return state.bar(h.bb, "full", h.tools)


def _levers(h: Host) -> str:
    (line,) = [x for x in _more(h).lines() if x.startswith("levers: ")]
    return line


def _offers(h: Host, mode: SlowViewMode = SlowViewMode.RELAY_ONLY) -> str:
    bar = prompt.status_bar(view_slow(h.bb, mode, "b"), h.now(), None, _more(h))
    (line,) = [x for x in bar.splitlines() if x.startswith("offers: ")]
    return line


def _next(h: Host, mode: SlowViewMode = SlowViewMode.RELAY_ONLY) -> str:
    """The approval hint's next step: its text after the arrow, to the first
    semicolon (or the end)."""
    line = _offers(h, mode)
    assert OUTSIDE in line, line
    return line.split(OUTSIDE, 1)[1].split(";", 1)[0]


def _outside(tmp_path: Path) -> Host:
    """save-2 ($69) confirmed against a granted $65 mandate (ed5063)."""
    h = _confirmed(tmp_path)
    _mandate(h, 6500)
    return h


def _deny(h: Host) -> None:
    """The user denies the pending card (UI post, kernel decision)."""
    card = h.bb.private.pending_approval
    assert card is not None
    post: dict[str, Any] = {"subject": "approval", "subject_id": card.approval_id}
    post |= {"decision": "denied", "subject_hash": card.terms_hash}
    post |= {"authority_epoch": card.authority_epoch}
    posted = h.emit("approval.post", "ui", post)
    decided = {"approval_id": card.approval_id, "decision": "denied", "by": "ui"}
    ev = h.emit("approval.decided", "kernel", decided, [posted.event_id])
    back = {"previous": "AWAITING_APPROVAL", "status": "IN_CALL"}
    h.emit("status.changed", "guard", back, [ev.event_id])


def _authorise_cancel(h: Host) -> None:
    said = h.emit("user.msg", "kernel", {"text": "You may say I will cancel."})
    grant = {"key": "authorization.cancel_lever", "value": "granted"}
    grant |= {"source_ref": said.event_id, "source": "shareable", "scope": "public"}
    h.emit("fact.recorded", "guard", grant, [said.event_id])


# P1: an out-of-mandate confirmed offer with an unused lever names a lever


@pytest.mark.parametrize("mode", list(SlowViewMode))
def test_p1_an_available_lever_comes_before_request_approval(
    tmp_path: Path, mode: SlowViewMode
) -> None:
    """a806fc / 21988c: the playbook went straight to request_approval; the
    slot-free mention_tenure was never sent. Same hint in both modes: the
    levers line is state-derived, not transcript text."""
    h = _outside(tmp_path)
    step = _next(h, mode)
    assert "guide_fast(mention_tenure)" in step, step
    assert "request_approval" not in step
    assert HINT not in _offers(h, mode)


def test_p1_without_the_bar_the_hint_is_unchanged(tmp_path: Path) -> None:
    h = _outside(tmp_path)
    view = view_slow(h.bb, SlowViewMode.RELAY_ONLY, "b")
    assert HINT in prompt.status_bar(view, h.now())


def test_p1_a_lever_on_its_way_means_wait_not_another_lever(tmp_path: Path) -> None:
    """One lever per rep reply: with mention_tenure sent but not heard, the
    hint waits even though cancel_lever is now available too."""
    h = _outside(tmp_path)
    _authorise_cancel(h)
    assert "guide_fast(cancel_lever)" in _next(h)
    h.act(TENURE)
    step = _next(h)
    assert "wait" in step and "guide_fast(" not in step, step
    assert "request_approval" not in step


# P3: every lever heard or unavailable -> request_approval (before any denial)


def test_p3_all_levers_heard_or_unavailable_means_request_approval(
    tmp_path: Path,
) -> None:
    h = _outside(tmp_path)
    h.act(TENURE)
    h.voice()  # heard whole
    assert _next(h) == "request_approval(save-2)"
    assert HINT in _offers(h)
    _authorise_cancel(h)  # a new lever turns available: it comes first again
    assert "guide_fast(cancel_lever)" in _next(h)
    h.act(CANCEL)
    h.voice()
    assert _next(h) == "request_approval(save-2)"


# P2: after a denial, a lever while one is left; then decline + final offer


def test_p2_after_a_denial_an_unused_lever_is_still_listed(tmp_path: Path) -> None:
    h = _outside(tmp_path)
    (sent,) = h.act(REQUEST)
    assert sent.startswith("request_approval: card"), sent
    _deny(h)
    assert "request_approval" not in _offers(h)  # decided: no second card
    assert _levers(h).startswith("levers: available: mention_tenure; ")
    h.act(TENURE)
    h.voice()
    line = _levers(h)
    assert line.startswith("levers: available: none; ") and HEARD in line


def test_p2_the_playbook_orders_lever_approval_decline() -> None:
    pb = prompt.PLAYBOOK["full"]
    outside = pb.index("outside the granted mandate")
    lever = pb.index("available lever", outside)
    assert lever < pb.index("request_approval", outside)
    denied = pb.index("After the user denies")
    lever = pb.index("available lever", denied)
    decline = pb.index("decline_offer", denied)
    assert denied < lever < decline < pb.index("guide_fast(ask_final_offer)", decline)
    assert "levers line" in pb[outside:]


# L1: the levers line keys "used" on what the rep heard (slow.heard.fates)


def test_l1_nothing_sent_lists_the_available_lever(tmp_path: Path) -> None:
    h = _outside(tmp_path)
    assert _levers(h) == (
        f"levers: available: mention_tenure; {COMPETITOR}; {CANCELLING}"
    )


def _queued(h: Host) -> None:
    assert h.bb.s2f_pending["cp"]  # not voiced yet


def _playing(h: Host) -> None:
    h.voice(deliver=False)


def _heard(h: Host) -> None:
    h.voice()


def _cancel(h: Host, gen: str) -> None:
    (turn,) = [e for e in h.of("fast.turn") if e.payload["gen_id"] == gen]
    h.emit("fast.cancelled", "fast.cp", {"gen_id": gen, "reason": "verbatim"},
           [turn.event_id])  # fmt: skip


def _cancelled(h: Host) -> None:
    _cancel(h, h.voice())  # spoke and delivered, then cancelled (S1-SYS-59)


def _cancelled_playing(h: Host) -> None:
    _cancel(h, h.voice(deliver=False))


def _cut(h: Host) -> None:
    h.deliver(h.voice(deliver=False), interrupted=True)


def _silent(h: Host) -> None:
    h.voice(spoke=False)


@pytest.mark.parametrize(
    ("fate", "want"),
    [
        (_queued, WAIT),
        (_playing, WAIT),
        (_heard, HEARD),
        (_cancelled, "available: mention_tenure"),
        (_cancelled_playing, "available: mention_tenure"),
        (_cut, "available: mention_tenure"),
        (_silent, "available: mention_tenure"),
    ],
)
def test_l1_each_fate_of_a_sent_lever(tmp_path: Path, fate: Any, want: str) -> None:
    h = _outside(tmp_path)
    (sent,) = h.act(TENURE)
    assert sent.startswith("guide_fast: sent"), sent
    fate(h)
    line = _levers(h)
    assert want in line, line
    others = {WAIT, HEARD, "available: mention_tenure"} - {want}
    assert not any(x in line for x in others), line
    if want != "available: mention_tenure":
        assert line.startswith("levers: available: none; ")


def test_l1_a_resend_after_a_dead_one_counts_by_its_own_fate(tmp_path: Path) -> None:
    h = _outside(tmp_path)
    h.act(TENURE)
    _cut(h)
    h.act(TENURE)
    assert WAIT in _levers(h)
    h.voice()
    assert HEARD in _levers(h)


def test_l1_a_lever_guard_refuses_stays_unavailable_and_is_not_sent(
    tmp_path: Path,
) -> None:
    h = _outside(tmp_path)
    (got,) = h.act(CANCEL)
    assert "cancel_lever needs the public fact" in got, got
    line = _levers(h)
    assert CANCELLING in line and "cancel_lever" not in line.split(";", 1)[0]
    assert "sent" not in line and "heard by" not in line


def test_l1_unavailable_wins_over_heard() -> None:
    unavailable = (("cancel_lever", "cancel_lever_not_authorized"),)
    line = state.levers_line(unavailable, {"cancel_lever": "heard"})
    assert line == (f"levers: available: cite_competitor, mention_tenure; {CANCELLING}")


def test_l1_the_tenure_slot_clause_keeps_the_move_available() -> None:
    """n6: only the private slot is unavailable; the move works without it."""
    line = state.levers_line((("mention_tenure", "guide_slot_not_public"),))
    assert line.startswith(
        "levers: available: cite_competitor, mention_tenure, cancel_lever; "
    )
    assert "mention_tenure with fact:tenure_years unavailable" in line


# L2: the wording (same request, no pressure) and no world coupling


def test_l2_asking_again_is_the_same_request_and_adds_no_pressure() -> None:
    pb = prompt.PLAYBOOK["full"]
    assert "same request" in pb and "adds no pressure" in pb
    assert pb.index("lower price") < pb.index("adds no pressure")


def test_l2_no_world_wording_anywhere_slow_reads(tmp_path: Path) -> None:
    h = _outside(tmp_path)
    texts = [*prompt.PLAYBOOK.values(), *(prompt.system(m) for m in SlowViewMode)]
    texts += [_levers(h), _offers(h)]
    h.act(TENURE)
    texts += [_levers(h), _offers(h)]
    for text in texts:
        low = text.lower()
        assert not [w for w in FORBIDDEN if w in low], text
