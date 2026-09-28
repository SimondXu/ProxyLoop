"""S1-SYS-57 round 2 (M1): while an ask_final_offer is sent but not yet heard
(queued in ``s2f_pending``, or voiced by a turn still playing), the close line
says so and tells Slow to wait, so the playbook never asks it again; a dead
ask (cancelled, cut, no speech) lets Slow ask again. Guard's refusal is not
masked. EQ: the three-state classification leaves ``_heard`` (#219) exactly
as it was. The test plays the kernel."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from random import Random

import pytest
from hypothesis import event, given, settings
from hypothesis import strategies as st
from tests.slow import test_close_levers as levers
from tests.slow.test_authority import ASKED, Host
from tests.slow.test_close_levers import BEST, FINAL, NO_DEAL

from proxyloop.contract.events import Event
from proxyloop.contract.messages import Guide, GuideMove, SlowToFast
from proxyloop.contract.state import Line
from proxyloop.guard.needs import spoke

PENDING = (
    "close: final offer asked, not yet heard by the rep (wait for it; do not ask "
    "again); "
)
REFUSED = "no closing reply; finish(no_deal) blocked: final_offer_not_asked"
WAIT = PENDING + REFUSED
DEAD = "close: final offer not asked; " + REFUSED
HEARD = (
    "close: final offer asked; no closing reply; finish(no_deal) blocked: "
    "no_closing_reply"
)
THEN = "Is that your best and final offer?"
_agrees = levers._agrees  # pyright: ignore[reportPrivateUsage]
_bar = levers._bar  # pyright: ignore[reportPrivateUsage]
_declined = levers._declined  # pyright: ignore[reportPrivateUsage]


def _line(h: Host) -> str:
    return _bar(h).close.line()


def _two(h: Host) -> str:
    """FastC voicing the newest cp guide in two sentences; the first delivered
    whole, the second still playing. Its gen id."""
    (msg,) = [e for e in h.of("s2f.msg") if e.payload["lane"] == "cp"][-1:]
    gen = f"c-g{len(h.of('fast.turn')) + 1}"
    items = [{"kind": "speech", "text": t} for t in (ASKED, THEN)]
    turn = {"lane": "cp", "gen_id": gen, "call_id": "c", "ttft_ms": 1, "ttfs_ms": 1}
    cause = h.emit("fast.turn", "fast.cp", turn | {"items": items}, [msg.event_id])
    voiced = {"msg_id": msg.payload["msg_id"], "gen_id": gen}
    h.emit("s2f.voiced", "fast.cp", voiced, [cause.event_id])
    for n, text in enumerate((ASKED, THEN)):
        line = {"lane": "cp", "gen_id": gen, "utt_id": f"{gen}-u{n}", "text": text}
        h.emit("fast.sentence", "fast.cp", line, [cause.event_id])
    _play(h, f"{gen}-u0")
    return gen


def _play(h: Host, utt: str, *, cut: bool = False) -> None:
    (s,) = [e for e in h.of("fast.sentence") if e.payload["utt_id"] == utt]
    text = str(s.payload["text"])
    said = {"lane": "cp", "utt_id": utt, "text_generated": text}
    said |= {"text_heard": "" if cut else text, "interrupted": cut}
    h.emit("utt.delivered", "kernel", said, [s.event_id])


def _cancel(h: Host, gen: str) -> None:
    (turn,) = [e for e in h.of("fast.turn") if e.payload["gen_id"] == gen]
    cancel = {"gen_id": gen, "reason": "verbatim"}
    h.emit("fast.cancelled", "fast.cp", cancel, [turn.event_id])


def _refused_now(h: Host) -> None:
    """Guard's truth, unmasked: finish(no_deal) is refused until it is heard."""
    (got,) = h.act(NO_DEAL)
    assert "final_offer_not_asked" in got and not h.ended


def test_m1a_a_sent_unvoiced_final_ask_is_pending(tmp_path: Path) -> None:
    h = _declined(tmp_path)
    h.act(FINAL)
    assert (h.tools.final_pending, h.tools.asked_final) == (True, None)
    assert _line(h) == WAIT
    _refused_now(h)
    assert _line(h) == WAIT  # still queued: never ask again


def test_m1b_a_final_ask_still_playing_is_pending(tmp_path: Path) -> None:
    """527345 seq 346-369: u0 delivered, u1 still playing when Slow steps."""
    h = _declined(tmp_path)
    h.act(FINAL)
    gen = _two(h)
    assert (h.tools.final_pending, h.tools.asked_final) == (True, None)
    assert _line(h) == WAIT
    _refused_now(h)
    _play(h, f"{gen}-u1")  # heard whole: the window opens (M1e)
    assert h.tools.final_pending is False
    assert _line(h) == HEARD


@pytest.mark.parametrize("how", ["cancelled", "cut", "silent"])
def test_m1c_a_dead_final_ask_is_not_pending(tmp_path: Path, how: str) -> None:
    """Cancelled, cut or voiced without speech: the rep will never hear it,
    so the bar lets Slow ask again (no stall)."""
    h = _declined(tmp_path)
    h.act(FINAL)
    if how == "cancelled":
        _cancel(h, h.voice(deliver=False))
    elif how == "cut":
        h.deliver(h.voice(deliver=False), interrupted=True)
    else:
        h.voice(spoke=False)
    assert (h.tools.final_pending, h.tools.asked_final) == (False, None)
    assert _line(h) == DEAD
    _refused_now(h)


@pytest.mark.parametrize("newer", ["queued", "playing"])
def test_m1d_an_older_heard_ask_anchors_while_a_newer_one_is_pending(
    tmp_path: Path, newer: str
) -> None:
    h = _declined(tmp_path)
    h.act(FINAL)
    h.voice()
    h.rep("cp-10", BEST)
    anchor = h.tools.asked_final
    assert anchor is not None and h.tools.final_pending is False
    h.act(FINAL)
    if newer == "playing":
        _two(h)
    assert (h.tools.final_pending, h.tools.asked_final) == (True, anchor)
    said = "the rep's closing reply cp-10; tell_user the terms and the outcome "
    said += "before finish; finish(no_deal) would verify"
    assert _line(h) == PENDING + said  # the rest as before
    c = _agrees(h)  # Guard anchors at the older, heard ask
    assert (c.reply, c.reasons) == ("cp-10", ()) and h.ended == ["no_deal"]


@pytest.mark.parametrize("how", ["cancelled", "cut"])
def test_m1f_a_playing_ask_that_dies_is_no_longer_pending(
    tmp_path: Path, how: str
) -> None:
    """Root: the turn playing the ask is cancelled (or its second sentence is
    cut): the line flips from "not yet heard" to "not asked"."""
    h = _declined(tmp_path)
    h.act(FINAL)
    gen = _two(h)
    assert _line(h) == WAIT
    if how == "cancelled":
        _cancel(h, gen)
    else:
        _play(h, f"{gen}-u1", cut=True)
    assert (h.tools.final_pending, h.tools.asked_final) == (False, None)
    assert _line(h) == DEAD


def test_m1e_a_final_ask_heard_whole_is_asked(tmp_path: Path) -> None:
    h = _declined(tmp_path)
    h.act(FINAL)
    h.voice()
    assert h.tools.final_pending is False and h.tools.asked_final is not None
    assert _line(h) == HEARD
    h.rep("cp-10", BEST)
    c = _agrees(h)
    assert (c.reply, c.reasons) == ("cp-10", ()) and h.ended == ["no_deal"]


def _old_heard(events: Sequence[Event], lines: Sequence[Line]) -> dict[str, int]:
    """Round 1's ``SlowTools._heard`` (#219), frozen verbatim in logic."""
    turns = {e.event_id: e for e in events if e.type == "fast.turn"}
    cut = {e.payload["gen_id"] for e in events if e.type == "fast.cancelled"}
    sentences: dict[str, list[str]] = {}
    for p in (e.payload for e in events if e.type == "fast.sentence"):
        sentences.setdefault(str(p["gen_id"]), []).append(str(p["utt_id"]))
    cp = [
        e
        for e in events
        if e.type in ("utt.final", "utt.delivered") and e.payload["lane"] == "cp"
    ]
    delivered = {str(e.payload["utt_id"]): e for e in cp if e.type == "utt.delivered"}
    said = {str(e.payload["utt_id"]): e.seq for e in cp}
    seqs = [said[x.utt_id] for x in lines]
    at: dict[str, int] = {}
    for e in events:
        turn = turns.get(e.cause_ids[0]) if e.type == "s2f.voiced" else None
        if turn is None or not spoke(turn) or turn.payload["gen_id"] in cut:
            continue
        played = [
            delivered.get(u) for u in sentences.get(str(turn.payload["gen_id"]), ())
        ]
        if not played or any(d is None or d.payload["interrupted"] for d in played):
            continue
        end = max(d.seq for d in played if d is not None)
        at.setdefault(str(e.payload["msg_id"]), sum(q <= end for q in seqs))
    return at


OPS = ("msg", "msg", "turn", "turn", *["deliver"] * 5, "cut", "cancel", "rep")


def _program(rng: Random) -> Iterator[tuple[str, int, int]]:
    for _ in range(rng.randint(1, 40)):
        yield rng.choice(OPS), rng.randint(0, 7), rng.randint(0, 3)


@settings(max_examples=300, deadline=None)
@given(st.randoms(use_true_random=False))
def test_eq_heard_is_unchanged(rng: Random) -> None:
    """EQ: on random logs of guides, voicings (several msgs per turn, a msg
    re-voiced, silent turns, 0-3 sentences), playouts, cuts, cancellations and
    rep lines, ``_heard`` returns round 1's dict at every step."""
    with tempfile.TemporaryDirectory() as tmp:
        h = Host(Path(tmp))
        h.call()
        root = [h.root.event_id]
        msgs, gens, waiting = list[str](), list[str](), list[str]()  # undelivered
        at: dict[str, int] = {}
        for op, i, n in _program(rng):
            if op == "msg":
                guide = Guide(move=GuideMove.ASK_FINAL_OFFER)
                msg = SlowToFast(
                    msg_id=f"s2f-x{len(msgs)}", lane="cp", type="GUIDE", guide=guide
                )
                h.emit("s2f.msg", "slow", msg.model_dump(mode="json"), root)
                msgs.append(msg.msg_id)
            elif op == "turn":
                gen = f"c-g{len(gens) + 1}"
                items = [{"kind": "speech", "text": f"s{k}."} for k in range(n)]
                turn = {"lane": "cp", "gen_id": gen, "call_id": "c", "ttft_ms": 1}
                turn |= {"ttfs_ms": 1, "items": items}
                cause = h.emit("fast.turn", "fast.cp", turn, root).event_id
                voices = (
                    {msgs[k % len(msgs)] for k in (i, i // 2)} if msgs else set[str]()
                )
                for m in sorted(voices):  # one or two msgs, maybe voiced before
                    voiced = {"msg_id": m, "gen_id": gen}
                    h.emit("s2f.voiced", "fast.cp", voiced, [cause])
                for k in range(n):
                    utt = f"{gen}-u{k}"
                    line = {"lane": "cp", "gen_id": gen, "utt_id": utt}
                    h.emit(
                        "fast.sentence", "fast.cp", line | {"text": f"s{k}."}, [cause]
                    )
                    waiting.append(utt)
                gens.append(gen)
            elif op in ("deliver", "cut") and waiting:
                _play(h, waiting.pop(i % len(waiting)), cut=op == "cut")
            elif op == "cancel" and gens:
                _cancel(h, gens[i % len(gens)])
            elif op == "rep":
                h.rep(f"cp-r{len(h.of('utt.final'))}", "Anything else?")
            at = h.tools._heard()  # pyright: ignore[reportPrivateUsage]
            assert at == _old_heard(h.bus.events, h.bb.channels["cp"].lines)
        event(f"heard {min(len(at), 2)}")
