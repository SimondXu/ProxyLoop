"""obs's closing reply (``grading.closing_reply``) follows Guard's
``verify_no_deal`` rule (S1-SYS-57, #227): the rep's last cp line since the
last ask_final_offer the rep heard. The parity test plays one cp script into a
bundle and into a Blackboard and asks both; obs cannot call Guard (it needs
kernel state). An ask is ``("ask", how)``: ``""`` voiced and delivered whole
(heard), ``unvoiced`` never voiced, ``cut`` delivered interrupted,
``cancelled`` voiced by a cancelled turn, ``late`` delivered whole only after
the finish; two lines: ``playing`` only the first delivered, ``split`` both
(heard) with a rep closing line between the two deliveries."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.guard.build import agent, board, confirm, offer, rep
from tests.obs.bundles import Log, manifest, write
from tests.obs.triage_bundle import P, s2f, sentence, turn
from tests.obs.triage_bundle import heard as heard_

from proxyloop.contract.state import Line
from proxyloop.guard.verify import verify_no_deal
from proxyloop.obs import detectors, grading, runs, triage

ASK = ("ask", "")  # heard
UNHEARD = (("ask", "unvoiced"), ("ask", "cut"), ("ask", "cancelled"))
SAID = ("rep", "I can offer $68 a month.")
CLOSE = ("rep", "That is our best offer, and I cannot do any better.")
LINE = "Is that your final offer?"  # the agent's voiced ask
NO_DEAL = ("finish", "no_deal")  # a successful finish with this outcome
Script = tuple[tuple[str, str], ...]


def _log(script: Script) -> Log:
    log, late = Log("rC"), list[tuple[str, str]]()
    for n, (who, text) in enumerate(script):
        if who == "finish":
            done: P = {"name": "finish", "args": {"outcome": text}}
            done |= {"result_text": "verified", "ok": True}
            log.add("slow.tool", "slow", "agent", done, (log.start,))
        elif who == "ask":
            final: P = {"move": "ask_final_offer", "slots": []}
            ask = s2f(log, f"s2f-{n}", "cp", "GUIDE", log.start, guide=final)
            _voice(log, f"s2f-{n}", f"cp-g{n}", text, ask, late)
        elif who == "rep":
            said: P = {"lane": "cp", "speaker": "partner", "utt_id": f"c{n}"}
            log.add("utt.final", "kernel", "agent", said | {"text": text})
        else:
            heard: P = {"lane": "cp", "utt_id": f"c{n}", "text_generated": text}
            heard |= {"text_heard": text, "interrupted": False}
            log.add("utt.delivered", "kernel", "agent", heard, (log.start,))
    for utt, said_ in late:  # after the script, so after its finish
        heard_(log, "cp", utt, LINE, False, said_)
    log.add("session.ended", "kernel", "ops", {"reason": "timeout"})
    return log


def _voice(
    log: Log, msg: str, gen: str, how: str, ask: str, late: list[tuple[str, str]]
) -> None:
    """FastC voices ``msg`` in ``gen`` and speaks one line, two for
    ``playing`` and ``split`` (``how``: see the module docstring); ``late``
    collects the deliveries ``_log`` adds after the finish."""
    if how == "unvoiced":
        return
    spoke = turn(log, "cp", gen, f"c-{gen}", ask)
    voiced: P = {"msg_id": msg, "gen_id": gen}
    log.add("s2f.voiced", "fast.cp", "agent", voiced, (spoke,))
    n = 2 if how in ("playing", "split") else 1
    said = [sentence(log, "cp", gen, i, LINE, spoke) for i in range(n)]
    if how == "cancelled":
        cancelled: P = {"gen_id": gen, "reason": "verbatim"}
        log.add("fast.cancelled", "fast.cp", "agent", cancelled, (said[0],))
        return
    for i, s in enumerate(said):
        if i and how == "playing":
            return  # the second line is still to come
        if i and how == "split":
            line: P = {"lane": "cp", "speaker": "partner", "utt_id": f"{gen}-r"}
            log.add("utt.final", "kernel", "agent", line | {"text": CLOSE[1]})
        if how == "late":
            late.append((f"{gen}-u{i}", s))
        else:
            heard_(log, "cp", f"{gen}-u{i}", LINE, how == "cut", s)


def _inputs(tmp_path: Path, script: Script, finish: bool = True) -> detectors.Inputs:
    log = _log((*script, NO_DEAL) if finish else script)
    run = write(tmp_path / "rC", log, manifest("rC"))
    return triage.read(run, runs.Seal(), content=True)[1]


def _guard_closed(script: Script) -> bool:
    lines, asked = list[Line](), None
    for n, (who, text) in enumerate(script):
        if who == "ask":  # the lines delivered before the finish
            u0, u1 = agent(f"cp-g{n}-u0", LINE), agent(f"cp-g{n}-u1", LINE)
            said = {"": [u0], "cut": [u0], "playing": [u0],
                    "split": [u0, rep(f"cp-g{n}-r", CLOSE[1]), u1]}  # fmt: skip
            lines += said.get(text, [])
            asked = len(lines) if text in ("", "split") else asked  # heard
        else:
            lines.append((rep if who == "rep" else agent)(f"c{n}", text))
    declined = confirm(offer()).model_copy(update={"status": "declined"})
    decision = verify_no_deal(board(declined, cp=tuple(lines)), asked)
    return not {"no_closing_reply", "final_offer_not_asked"} & set(decision.reasons)


# tests/guard/test_verify.py's S1-SYS-57 cases, plus the ask never sent
CASES: dict[str, tuple[Script, bool]] = {
    "closing_last": ((SAID, ASK, CLOSE), True),
    "concession_after": (
        (SAID, ASK, CLOSE, ("rep", "I can waive the activation fee.")), False,
    ),
    "retraction_after": ((SAID, ASK, CLOSE, ("rep", "Actually, I can do 55.")), False),
    "agent_after": ((SAID, ASK, CLOSE, ("agent", "Can you do $55?")), True),
    "second_ask_silent": (
        (SAID, ASK, CLOSE, ("agent", "Is that really your final offer?"), ASK), False,
    ),
    "second_ask_closed": (
        (SAID, ASK, CLOSE, ("agent", "Is that really your final offer?"), ASK,
         ("rep", "Yes, it is our best offer.")),
        True,
    ),
    "silent_since_ask": ((SAID, ASK), False),
    "silent_since_second_ask": (
        (SAID, ASK, CLOSE, ("agent", "Final offer?"), ASK), False,
    ),
    "never_asked": ((SAID, CLOSE), False),
    "closing_before_ask": ((CLOSE, ASK, SAID), False),
    # #227: only a heard ask opens the window
    **{f"unheard_{a[1]}": ((SAID, a, CLOSE), False) for a in UNHEARD},
    **{f"heard_then_{a[1]}": ((SAID, ASK, CLOSE, a), True) for a in UNHEARD},
    "heard_then_unheard_then_close": (
        (SAID, ASK, ("rep", "Let me check."), ("ask", "cut"), CLOSE), True,
    ),
    # B is voiced before the finish but heard only after it: A anchors
    "heard_then_heard_after_finish": ((SAID, ASK, CLOSE, ("ask", "late")), True),
    # still playing (one of two lines delivered): not heard
    "playing_then_close": ((SAID, ("ask", "playing"), CLOSE), False),
    # heard at its last delivery: a closing line between the two is early
    "closing_inside_a_split_ask": ((SAID, ("ask", "split")), False),
}  # fmt: skip


@pytest.mark.parametrize("case", CASES)
def test_obs_closing_reply_equals_guards_verdict(tmp_path: Path, case: str) -> None:
    script, closed = CASES[case]
    assert _guard_closed(script) is closed
    x = _inputs(tmp_path, script)
    reply = grading.closing_reply(x, x.of("slow.tool")[-1].seq)  # at the finish
    assert (reply is not None) is closed
    if reply is not None:  # the rep's last line, not the first closing one
        assert reply is x.of("utt.final")[-1]


def test_a_retraction_after_the_closing_line_is_not_a_pass(tmp_path: Path) -> None:
    script = CASES["retraction_after"][0]
    for finish in (True, False):
        values = detectors.run_all(_inputs(tmp_path / str(finish), script, finish))
        for name in (
            "close.reply_to_finish_steps", "end.unclosed_after_reply",
            "user.told_terms",
        ):  # fmt: skip
            assert values[name] is None, (finish, name)


def _close(tmp_path: Path, script: Script) -> object:
    return detectors.run_all(_inputs(tmp_path, script, False))[
        "close.reply_to_finish_steps"
    ]


def test_the_finish_bounds_the_window(tmp_path: Path) -> None:
    """Lines after the first successful no_deal finish are not Guard's: a
    closing line said after it does not make the finish a close."""
    x = _inputs(tmp_path, (SAID, ASK, NO_DEAL, CLOSE), False)
    assert grading.closing_reply(x, len(x.events)) is not None  # at the log's end
    assert _close(tmp_path / "b", (SAID, ASK, NO_DEAL, CLOSE)) is None


def test_an_ask_after_the_finish_is_ignored(tmp_path: Path) -> None:
    """1 said, 2-6 the ask heard, 7 closing, 8 finish, 9 a late ask: the
    reply stays 7."""
    value = _close(tmp_path, (SAID, ASK, CLOSE, NO_DEAL, ASK))
    assert value == {"count": 0, "reply_seq": 7, "finish_seq": 8, "h5_pass": True}


def test_a_deal_finish_does_not_bound_the_window(tmp_path: Path) -> None:
    """A deal finish goes through verify_completion, not verify_no_deal: the
    window runs to the log's end and no finish is claimed to have judged it."""
    value = _close(tmp_path, (SAID, ASK, CLOSE, ("finish", "completed")))
    assert value == {"count": 0, "reply_seq": 7, "finish_seq": None, "h5_pass": False}


def test_a_delivery_after_the_finish_does_not_make_the_ask_heard(
    tmp_path: Path,
) -> None:
    """Guard judges the finish with the events so far (``_heard``'s
    ``before``): the ask's line is delivered only after the finish (8)."""
    log = _log((SAID,))  # 1; its session.ended (2) is dropped below
    log.events.pop()
    final: P = {"move": "ask_final_offer", "slots": []}
    ask = s2f(log, "s2f-a", "cp", "GUIDE", log.start, guide=final)  # 2
    spoke = turn(log, "cp", "cp-ga", "c-ga", ask)  # 3
    voiced: P = {"msg_id": "s2f-a", "gen_id": "cp-ga"}
    log.add("s2f.voiced", "fast.cp", "agent", voiced, (spoke,))  # 4
    said = sentence(log, "cp", "cp-ga", 0, "Final offer?", spoke)  # 5
    rep_line: P = {"lane": "cp", "speaker": "partner", "utt_id": "c6"}
    log.add("utt.final", "kernel", "agent", rep_line | {"text": CLOSE[1]})  # 6
    done: P = {"name": "finish", "args": {"outcome": "no_deal"}, "ok": True}
    log.add("slow.tool", "slow", "agent", done | {"result_text": "v"}, (ask,))  # 7
    heard_(log, "cp", "cp-ga-u0", "Final offer?", False, said)  # 8
    run = write(tmp_path / "rC", log, manifest("rC"))
    x = triage.read(run, runs.Seal(), content=True)[1]
    assert grading._heard(x) == {"s2f-a": 8}  # pyright: ignore[reportPrivateUsage]
    assert grading._heard(x, before=7) == {}  # pyright: ignore[reportPrivateUsage]
    assert grading.closing_reply(x, 7) is None
    assert detectors.run_all(x)["close.reply_to_finish_steps"] is None
