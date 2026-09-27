"""obs's closing reply (``grading.closing_reply``) follows Guard's
``verify_no_deal`` rule (S1-SYS-57): the rep's last cp line since the last
ask_final_offer. The parity test plays one cp script into a bundle and into a
Blackboard and asks both; obs cannot call Guard (it needs kernel state)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.guard.build import agent, board, confirm, offer, rep
from tests.obs.bundles import Log, manifest, write
from tests.obs.triage_bundle import P, s2f

from proxyloop.contract.state import Line
from proxyloop.guard.verify import verify_no_deal
from proxyloop.obs import detectors, grading, runs, triage

ASK = ("ask", "")
SAID = ("rep", "I can offer $68 a month.")
CLOSE = ("rep", "That is our best offer, and I cannot do any better.")
Script = tuple[tuple[str, str], ...]


def _log(script: Script, finish: bool = True) -> Log:
    log = Log("rC")
    for n, (who, text) in enumerate(script):
        if who == "ask":
            final: P = {"move": "ask_final_offer", "slots": []}
            s2f(log, f"s2f-{n}", "cp", "GUIDE", log.start, guide=final)
        elif who == "rep":
            said: P = {"lane": "cp", "speaker": "partner", "utt_id": f"c{n}"}
            log.add("utt.final", "kernel", "agent", said | {"text": text})
        else:
            heard: P = {"lane": "cp", "utt_id": f"c{n}", "text_generated": text}
            heard |= {"text_heard": text, "interrupted": False}
            log.add("utt.delivered", "kernel", "agent", heard, (log.start,))
    if finish:
        done: P = {"name": "finish", "args": {"outcome": "no_deal"}}
        done |= {"result_text": "verified no deal", "ok": True}
        log.add("slow.tool", "slow", "agent", done, (log.start,))
    log.add("session.ended", "kernel", "ops", {"reason": "timeout"})
    return log


def _inputs(tmp_path: Path, script: Script, finish: bool = True) -> detectors.Inputs:
    run = write(tmp_path / "rC", _log(script, finish), manifest("rC"))
    return triage.read(run, runs.Seal(), content=True)[1]


def _guard_closed(script: Script) -> bool:
    lines, asked = list[Line](), None
    for n, (who, text) in enumerate(script):
        if who == "ask":
            asked = len(lines)
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
}  # fmt: skip


@pytest.mark.parametrize("case", CASES)
def test_obs_closing_reply_equals_guards_verdict(tmp_path: Path, case: str) -> None:
    script, closed = CASES[case]
    assert _guard_closed(script) is closed
    x = _inputs(tmp_path, script)
    reply = grading.closing_reply(x, len(x.events))
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


def test_the_finish_bounds_the_window(tmp_path: Path) -> None:
    """Lines after the first successful finish are not Guard's: a closing line
    said after it does not make the finish a close."""
    log = _log((SAID, ASK))  # 1 said, 2 ask, 3 finish, 4 ended
    log.events.pop()
    said: P = {"lane": "cp", "speaker": "partner", "utt_id": "late"}
    log.add("utt.final", "kernel", "agent", said | {"text": CLOSE[1]})  # 4
    run = write(tmp_path / "rC", log, manifest("rC"))
    x = triage.read(run, runs.Seal(), content=True)[1]
    assert grading.closing_reply(x, len(x.events)) is not None  # at the log's end
    assert detectors.run_all(x)["close.reply_to_finish_steps"] is None
