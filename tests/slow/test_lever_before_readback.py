"""S1-SYS-66 round 3 (root diff review, §0.5a, 2026-09-28): an offer
RECORDED outside the granted mandate gets one available lever before Slow
spends a read-back on it (a806fc: save-1 read back at cp+~290 s, then levers,
then save-2 read back again, all inside 480 s). The signal is the offers
line's Guard-derived outside-mandate one on the recorded slots
(``prompt.mandate_hint``, #218); a read-back is asked only of an offer Slow
means to accept (inside the mandate) or to send for approval (outside it, no
lever left). I6 is unchanged: accept and request_approval still need the
confirmed read-back (Guard). The test plays the kernel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.slow import test_authority as auth
from tests.slow import test_negotiate as neg
from tests.slow.test_authority import HINT, Host

from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.views import view_slow
from proxyloop.slow import prompt

_mandate = auth._mandate  # pyright: ignore[reportPrivateUsage]
_offers = neg._offers  # pyright: ignore[reportPrivateUsage]
_reply = neg._reply  # pyright: ignore[reportPrivateUsage]
_cut = neg._cut  # pyright: ignore[reportPrivateUsage]
_cancelled = neg._cancelled  # pyright: ignore[reportPrivateUsage]
TENURE = neg.TENURE
RECORD = {"tool": "record_offer", "offer_ref": "save-2", "offer_slots": auth.SLOTS}
READBACK = {"tool": "guide_fast", "move": "ask_readback", "slots": ["offer:save-2"]}
ASK_READBACK = 'guide_fast(ask_readback, ["offer:save-2"])'
SIGNAL = f"{prompt.OUTSIDE_MANDATE} → "


def _recorded(tmp_path: Path, cap: int = 6500, *calls: dict[str, Any]) -> Host:
    """save-2 ($69) recorded, not read back, against a granted ``cap``."""
    h = Host(tmp_path)
    _mandate(h, cap)
    h.call()
    h.rep("cp-1", auth.TERMS)
    got = h.act(RECORD, *calls)
    assert got[0] == "record_offer: recorded save-2 r1", got
    return h


def _step(h: Host, mode: SlowViewMode = SlowViewMode.RELAY_ONLY) -> str:
    """The recorded offer's next step: the offers line after the signal."""
    line = _offers(h, mode)
    assert SIGNAL in line, line
    return line.split(SIGNAL, 1)[1]


# T1: recorded outside + a free lever -> the lever, not ask_readback


@pytest.mark.parametrize("mode", list(SlowViewMode))
def test_t1_a_recorded_outside_offer_gets_a_lever_before_its_read_back(
    tmp_path: Path, mode: SlowViewMode
) -> None:
    h = _recorded(tmp_path)
    step = _step(h, mode)
    assert step.startswith("first one lever: guide_fast(mention_tenure)"), step
    assert "ask_readback only once none is left" in step, step
    assert ASK_READBACK not in step and "request_approval" not in step


def test_t1_without_the_bar_the_signal_is_unchanged(tmp_path: Path) -> None:
    h = _recorded(tmp_path)
    view = view_slow(h.bb, SlowViewMode.RELAY_ONLY, "b")
    (o,) = view.offers
    assert prompt.mandate_hint(view, o, h.now()) == prompt.OUTSIDE_MANDATE


# T2: recorded outside, no lever left -> ask_readback, then request_approval


def test_t2_no_lever_left_asks_the_read_back_then_request_approval(
    tmp_path: Path,
) -> None:
    h = _recorded(tmp_path)
    h.act(TENURE)
    h.voice()
    _reply(h)  # answered: no lever left (the others are unavailable)
    step = _step(h)
    assert step.startswith(f"{ASK_READBACK}, then request_approval(save-2)"), step
    assert "guide_fast(mention_tenure)" not in step
    (asked,) = h.act(READBACK)
    assert asked.endswith("read-back asked for save-2 r1"), asked
    h.voice()
    h.rep("cp-9", auth.TERMS)  # read back whole: confirmed
    h.tools.readback()
    line = _offers(h)
    assert HINT in line and prompt.OUTSIDE_MANDATE not in line, line
    (card,) = h.act({"tool": "request_approval", "offer_ref": "save-2"})
    assert card.startswith("request_approval: card"), card


def test_t2_a_read_back_already_asked_is_not_asked_again(tmp_path: Path) -> None:
    """Asked with the record (the old habit), then the lever died twice: no
    lever left and a read-back pending: wait for it, then request_approval."""
    h = _recorded(tmp_path, 6500, READBACK)
    h.act(TENURE)
    _cut(h)
    h.act(TENURE)
    _cancelled(h)
    step = _step(h)
    assert step.startswith("read-back asked: request_approval(save-2) once"), step
    assert ASK_READBACK not in step and "guide_fast(" not in step


# T3: recorded inside the mandate -> read back as today, then accept


def test_t3_a_recorded_offer_inside_the_mandate_is_read_back_as_today(
    tmp_path: Path,
) -> None:
    h = _recorded(tmp_path, 7000)
    line = _offers(h)
    # re-pinned by root decision 2026-09-29 (S1-SYS-82 e1): read back the
    # offer Slow means to accept, including an inside one (#238)
    assert "outside mandate" not in line, line
    step = f"inside the granted mandate → {ASK_READBACK}, then accept_offer(save-2)"
    assert line.endswith(step), line
    pb = prompt.PLAYBOOK["full"]
    inside = pb.index("inside the granted mandate")
    assert pb.index("read-back", inside) < pb.index("accept_offer", inside)


# T4: a lever on its way or heard but not answered -> wait, ask_readback not yet


@pytest.mark.parametrize("heard", [False, True])
def test_t4_a_lever_waiting_means_wait_not_a_read_back(
    tmp_path: Path, heard: bool
) -> None:
    h = _recorded(tmp_path)
    h.act(TENURE)
    if heard:
        h.voice()
    step = _step(h)
    assert step.startswith("wait for the rep to hear and answer the lever"), step
    assert "; ask_readback not yet" in step, step  # #242 D3
    assert "ask_readback" not in step.split("; ", 1)[0]
    assert ASK_READBACK not in step and "request_approval" not in step
    assert "guide_fast(" not in step


# the playbook: levers before the read-back of an out-of-mandate offer


def test_the_playbook_puts_a_lever_before_the_read_back_outside_the_mandate() -> None:
    pb = prompt.PLAYBOOK["full"]
    outside = pb.index("outside the granted mandate")
    lever = pb.index("available lever", outside)
    before = pb.index("before asking for its read-back", outside)
    only = pb.index("Only when no lever is available", outside)
    assert lever < before < only
    assert only < pb.index("read-back", only) < pb.index("request_approval", only)
    assert "read-back only of an offer you mean to accept" in pb
    assert "a lever comes first" in prompt.SYSTEM
