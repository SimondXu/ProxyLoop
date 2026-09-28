"""#238 review D2 (root, §0.5a, 2026-09-28): "while the hint shows a lever or
a wait, offer_note drops 'ask again or ask_final_offer', so there's one next
step per state." An offer recorded outside the mandate whose read-back the rep
did not read back gets the lever (or the wait) as its one next step; only
once no lever is free or waiting does the V4 "ask again or ask_final_offer"
come back (asking again is then how the offer gets confirmed). The read-back
facts stay either way."""

from __future__ import annotations

from pathlib import Path

from tests.slow import test_lever_before_readback as lbr
from tests.slow import test_negotiate as neg
from tests.slow.test_authority import Host

_recorded = lbr._recorded  # pyright: ignore[reportPrivateUsage]
_offers = neg._offers  # pyright: ignore[reportPrivateUsage]
_reply = neg._reply  # pyright: ignore[reportPrivateUsage]
READBACK, TENURE = lbr.READBACK, neg.TENURE
AGAIN = "ask again or ask_final_offer"
FACTS = "read-back asked 1×; the rep has not read the offer back"  # noqa: RUF001
LEVER = "first one lever: guide_fast(mention_tenure)"


def _unread(tmp_path: Path) -> Host:
    """save-2 recorded outside the $65 mandate, its read-back asked with the
    record and heard; the rep answered without reading anything back."""
    h = _recorded(tmp_path, 6500, READBACK)
    h.voice()
    h.rep("cp-2", "Sorry about that. How can I help with the account?")
    return h


def test_a_free_lever_is_the_one_next_step(tmp_path: Path) -> None:
    line = _offers(_unread(tmp_path))
    assert LEVER in line and FACTS in line, line
    assert AGAIN not in line, line


def test_a_lever_waiting_is_the_one_next_step(tmp_path: Path) -> None:
    h = _unread(tmp_path)
    h.act(TENURE)  # sent, not heard yet
    line = _offers(h)
    assert lbr.prompt.WAIT_LEVER in line and FACTS in line, line
    assert AGAIN not in line, line


def test_with_no_lever_left_asking_again_comes_back(tmp_path: Path) -> None:
    h = _unread(tmp_path)
    h.act(TENURE)
    h.voice()
    _reply(h)  # answered: no lever left (the others are unavailable)
    line = _offers(h)
    assert "guide_fast(mention_tenure)" not in line and "wait" not in line, line
    assert f"{FACTS}; {AGAIN}" in line, line


# #242 round-2 review D1 (root, §0.5a, 2026-09-28): "the stuck clause only
# when no lever step is shown". Two read-backs that omitted slots keep their
# facts; with a free lever the lever is the one next step, not a decline.

STUCK = "read-back asked 2×, omitted from 2 read-backs: "  # noqa: RUF001
DECLINE = "then decline_offer and guide_fast(ask_final_offer)"


def _stuck(tmp_path: Path) -> Host:
    """save-2 outside the $65 mandate; two read-backs stated only the price."""
    h = _recorded(tmp_path, 6500, READBACK)
    h.voice()
    h.rep("cp-2", "Yes, it is $69 a month.")
    h.act(READBACK)
    h.voice()
    h.rep("cp-3", "Like I said, $69 a month.")
    return h


def test_a_free_lever_comes_before_the_stuck_decline(tmp_path: Path) -> None:
    line = _offers(_stuck(tmp_path))
    assert LEVER in line and STUCK in line, line
    assert "decline_offer" not in line and "stop asking" not in line, line


def test_with_no_lever_left_the_stuck_clause_comes_back(tmp_path: Path) -> None:
    h = _stuck(tmp_path)
    h.act(TENURE)
    h.voice()
    _reply(h)  # answered: no lever left (the others are unavailable)
    line = _offers(h)
    assert "guide_fast(mention_tenure)" not in line and "wait" not in line, line
    assert STUCK in line and "stop asking" in line and DECLINE in line, line


# D2: inside the mandate no lever step is shown, so an unread read-back keeps
# "ask again" as its one next step (never zero).


def test_inside_the_mandate_an_unread_read_back_keeps_ask_again(
    tmp_path: Path,
) -> None:
    h = _recorded(tmp_path, 10000, READBACK)
    h.voice()
    h.rep("cp-2", "Sorry about that. How can I help with the account?")
    line = _offers(h)
    assert "guide_fast(mention_tenure)" not in line and "wait" not in line, line
    assert line.endswith(f"{FACTS}; {AGAIN}"), line
    assert line.count(AGAIN) == 1, line
