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
NO_DEAL = ("finish", "no_deal")  # a successful finish with this outcome
Script = tuple[tuple[str, str], ...]


def _log(script: Script) -> Log:
    log = Log("rC")
    for n, (who, text) in enumerate(script):
        if who == "finish":
            done: P = {"name": "finish", "args": {"outcome": text}}
            done |= {"result_text": "verified", "ok": True}
            log.add("slow.tool", "slow", "agent", done, (log.start,))
        elif who == "ask":
            final: P = {"move": "ask_final_offer", "slots": []}
            s2f(log, f"s2f-{n}", "cp", "GUIDE", log.start, guide=final)
        elif who == "rep":
            said: P = {"lane": "cp", "speaker": "partner", "utt_id": f"c{n}"}
            log.add("utt.final", "kernel", "agent", said | {"text": text})
        else:
            heard: P = {"lane": "cp", "utt_id": f"c{n}", "text_generated": text}
            heard |= {"text_heard": text, "interrupted": False}
            log.add("utt.delivered", "kernel", "agent", heard, (log.start,))
    log.add("session.ended", "kernel", "ops", {"reason": "timeout"})
    return log


def _inputs(tmp_path: Path, script: Script, finish: bool = True) -> detectors.Inputs:
    log = _log((*script, NO_DEAL) if finish else script)
    run = write(tmp_path / "rC", log, manifest("rC"))
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
    """1 said, 2 ask, 3 closing, 4 finish, 5 a late ask: the reply stays 3."""
    value = _close(tmp_path, (SAID, ASK, CLOSE, NO_DEAL, ASK))
    assert value == {"count": 0, "reply_seq": 3, "finish_seq": 4, "h5_pass": True}


def test_a_deal_finish_does_not_bound_the_window(tmp_path: Path) -> None:
    """A deal finish goes through verify_completion, not verify_no_deal: the
    window runs to the log's end and no finish is claimed to have judged it."""
    value = _close(tmp_path, (SAID, ASK, CLOSE, ("finish", "completed")))
    assert value == {"count": 0, "reply_seq": 3, "finish_seq": None, "h5_pass": False}
