"""S1-SYS-57 (heard): ``verify_no_deal``'s window opens at the last
``ask_final_offer`` the rep HEARD, by #219's rule (``SlowTools._heard``):
voiced by a turn that spoke, was never cancelled and whose every sentence
was delivered uncut; it opens at the first cp line after that delivery. A
superseded, cancelled, cut or still-playing ask does not anchor. The test
plays the kernel; each close line's dry run agrees with the real finish."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.slow.test_authority import Host
from tests.slow.test_close_levers import (
    BEST,
    DECLINE,
    FINAL,
    RESTATED,
    _agrees,
    _close,
    _offered,
)

CONCEDE = "Actually, I can waive the activation fee."  # no closing cue
NOT_ASKED = ("final_offer_not_asked",)
NO_REPLY = ("no_closing_reply",)


def _declined(tmp_path: Path) -> Host:
    """offer-1 stated, recorded and declined: only the ask and reply remain."""
    h = _offered(tmp_path)
    h.act(DECLINE)
    return h


def _refused(h: Host, reasons: tuple[str, ...]) -> None:
    c = _agrees(h)
    assert c.reasons == reasons and not h.ended
    asked = "not asked" if reasons == NOT_ASKED else "asked"
    assert c.line().startswith(f"close: final offer {asked}; ")


def test_r1_a_final_ask_never_voiced_does_not_anchor(tmp_path: Path) -> None:
    """Superseded before FastC voiced it: the rep never heard it, so a closing
    line after it is no reply to it."""
    h = _declined(tmp_path)
    h.act(FINAL)
    h.rep("cp-10", BEST)
    assert _close(h).asked is False
    _refused(h, NOT_ASKED)


@pytest.mark.parametrize("delivered", [False, True])
def test_r2_a_final_ask_voiced_by_a_cancelled_turn_does_not_anchor(
    tmp_path: Path, delivered: bool
) -> None:
    h = _declined(tmp_path)
    h.act(FINAL)
    gen = h.voice(deliver=delivered)
    turn = h.of("fast.turn")[-1].event_id  # it spoke, then was cancelled
    h.emit("fast.cancelled", "fast.cp", {"gen_id": gen, "reason": "verbatim"}, [turn])
    h.rep("cp-10", BEST)
    _refused(h, NOT_ASKED)


def test_r3_a_final_ask_cut_mid_sentence_does_not_anchor(tmp_path: Path) -> None:
    h = _declined(tmp_path)
    h.act(FINAL)
    gen = h.voice(deliver=False)
    h.deliver(gen, interrupted=True)
    h.rep("cp-10", BEST)
    _refused(h, NOT_ASKED)


@pytest.mark.parametrize("when", ["playing", "before_voiced"])
def test_r4_a_rep_line_said_before_the_ask_was_heard_is_no_reply(
    tmp_path: Path, when: str
) -> None:
    """527345 seq 334-369: the rep's "best offer" came before FastC voiced
    the ask (or while it played); the window opens after its last sentence."""
    h = _declined(tmp_path)
    h.act(FINAL)
    if when == "playing":
        gen = h.voice(deliver=False)
        h.rep("cp-10", BEST)
        h.deliver(gen)
    else:
        h.rep("cp-10", BEST)
        h.voice()
    assert _close(h).asked is True
    _refused(h, NO_REPLY)


@pytest.mark.parametrize("second", ["unvoiced", "cut"])
def test_r5_an_unheard_later_ask_leaves_the_heard_one_anchoring(
    tmp_path: Path, second: str
) -> None:
    h = _declined(tmp_path)
    h.act(FINAL)
    h.voice()
    h.rep("cp-10", BEST)
    h.act(FINAL)
    if second == "cut":
        h.deliver(h.voice(deliver=False), interrupted=True)
    c = _agrees(h)
    assert (c.reply, c.reasons) == ("cp-10", ()) and h.ended == ["no_deal"]


def test_g1_a_heard_ask_and_a_closing_reply_after_it_verify(tmp_path: Path) -> None:
    h = _declined(tmp_path)
    h.act(FINAL)
    h.voice()
    h.rep("cp-10", BEST)
    h.rep("cp-11", RESTATED)  # 45d7ed: the rep's last line does not close
    _refused(h, NO_REPLY)
    h.rep("cp-12", BEST)
    c = _agrees(h)
    assert (c.reply, c.reasons) == ("cp-12", ()) and h.ended == ["no_deal"]


def test_g2_a_later_heard_ask_moves_the_window_forward(tmp_path: Path) -> None:
    h = _declined(tmp_path)
    h.act(FINAL)
    h.voice()
    h.rep("cp-10", BEST)
    assert _close(h).reply == "cp-10"
    h.rep("cp-11", CONCEDE)  # a concession after the closing line reopens it
    assert _close(h).reasons == NO_REPLY
    h.act(FINAL)
    h.voice()
    h.rep("cp-12", BEST)
    h.act(FINAL)
    h.voice()  # heard: cp-12 answered the previous ask, not this one
    _refused(h, NO_REPLY)
    h.rep("cp-13", BEST)
    c = _agrees(h)
    assert (c.reply, c.reasons) == ("cp-13", ()) and h.ended == ["no_deal"]
