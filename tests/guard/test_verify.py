"""verify_completion and the non-omniscient verify_no_deal (§9.3)."""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from tests.guard.build import agent, board, confirm, mandate, offer, rep

from proxyloop.contract.state import (
    Approval,
    Blackboard,
    Capability,
    CompletionDecision,
    Evidence,
    Line,
)
from proxyloop.guard.readback import has_cue
from proxyloop.guard.verify import (
    closing_at,
    reopens,
    verify_completion,
    verify_no_deal,
)

O1 = confirm(offer())
TH = str(O1.terms_hash)
ROOT = Path(__file__).resolve().parents[2]


def _cap(cap_id: str = "cap-1", consumed: bool = True) -> Capability:
    return Capability(
        cap_id=cap_id,
        business_action_id="bid-1",
        intent="accept_offer",
        terms_hash=TH,
        epoch=0,
        expires_ms=9_000,
        consumed=consumed,
    )


def _ledger(
    terms_hash: str = TH, kind: str = "ledger", bid: str | None = None
) -> Evidence:
    return Evidence.model_validate(
        {
            "evidence_id": "e1",
            "kind": kind,
            "confirmation_id": "NW-1",
            "terms_hash": terms_hash,
            "business_action_id": bid,
        }
    )


def _done(
    *caps: Capability, evidence: tuple[Evidence, ...] = (), **kw: object
) -> Blackboard:
    bb = board(O1, caps=caps, **kw)  # type: ignore[arg-type]
    return bb.model_copy(update={"evidence": evidence})


def _fail(*reasons: str) -> CompletionDecision:
    return CompletionDecision(verdict="fail", reasons=reasons)


OK = CompletionDecision(verdict="ok")


@pytest.mark.parametrize(
    ("bb", "decision"),
    [
        (_done(_cap(), evidence=(_ledger(),)), OK),
        (_done(_cap(), evidence=(_ledger(kind="portal", bid="bid-1"),)), OK),
        (_done(evidence=(_ledger(),)), _fail("no_released_accept")),
        (
            _done(_cap(consumed=False), evidence=(_ledger(),)),
            _fail("no_released_accept"),
        ),
        (
            _done(_cap(), _cap("cap-2"), evidence=(_ledger(),)),
            _fail("multiple_released_accepts"),
        ),
        (_done(_cap()), _fail("no_bound_evidence")),
        (_done(_cap(), evidence=(_ledger("other"),)), _fail("no_bound_evidence")),
        (
            _done(_cap(), evidence=(_ledger(kind="portal", bid="bid-9"),)),
            _fail("no_bound_evidence"),
        ),
        (
            _done(_cap(), evidence=(_ledger(),)).model_copy(
                update={"public": board(confirm(offer(monthly="6900"))).public}
            ),
            _fail("accepted_terms_unknown"),
        ),
    ],
)
def test_verify_completion(bb: Blackboard, decision: CompletionDecision) -> None:
    assert verify_completion(bb) == decision


def test_completion_fails_on_a_forbidden_change_in_the_accepted_terms() -> None:
    changed = confirm(offer(change="plan_change"))
    cap = _cap().model_copy(update={"terms_hash": changed.terms_hash})
    bb = board(
        changed, caps=(cap,), mandate=mandate(forbidden_changes=("plan_change",))
    )
    bb = bb.model_copy(update={"evidence": (_ledger(str(changed.terms_hash)),)})
    assert verify_completion(bb) == _fail("policy_violation")


ASK = 2  # the cp line count when guide(ask_final_offer) went out
CLOSING = (
    rep("c1", "I can offer $68 a month."),
    rep("c2", "Ok."),
    rep("c3", "I am afraid I cannot do better than that."),
)


def _declined() -> Blackboard:
    return board(O1.model_copy(update={"status": "declined"}), cp=CLOSING)


def test_no_deal_is_verified_from_agent_observable_evidence() -> None:
    assert verify_no_deal(_declined(), ASK) == OK
    denied = Approval(
        approval_id="apr-1",
        decision="denied",
        by="ui",
        terms_hash=TH,
        authority_epoch=0,
    )
    bb = board(O1, approvals=(denied,), cp=CLOSING)
    assert verify_no_deal(bb, ASK) == OK
    bad = confirm(offer(change="plan_change"))
    bb = board(bad, mandate=mandate(forbidden_changes=("plan_change",)), cp=CLOSING)
    assert verify_no_deal(bb, ASK) == OK


def test_no_deal_reasons() -> None:
    assert verify_no_deal(board(O1, cp=CLOSING), ASK) == _fail("offer_open:o1")
    assert verify_no_deal(_declined(), None) == _fail("final_offer_not_asked")
    assert verify_no_deal(_declined(), 3) == _fail("no_closing_reply")
    released = _declined().model_copy(update={"capabilities": {"cap-1": _cap()}})
    assert verify_no_deal(released, ASK) == _fail("accept_released")


# S1-SYS-57: only the rep's final line after the last ask counts
SAID = (rep("c1", "I can offer $68 a month."),)  # ask_final_offer after c1
CLOSE = rep("c2", "That is our best offer, and I cannot do any better.")


def _no_deal(*after: Line, ask: int = 1) -> CompletionDecision:
    declined = O1.model_copy(update={"status": "declined"})
    return verify_no_deal(board(declined, cp=(*SAID, *after)), ask)


@pytest.mark.parametrize(
    "later",
    [
        "I can waive the activation fee.",  # a concession
        "Actually, I can do 55.",  # a retraction
    ],
)
def test_a_line_after_the_closing_one_reopens_it(later: str) -> None:
    assert _no_deal(CLOSE) == OK
    assert _no_deal(CLOSE, rep("c3", later)) == _fail("no_closing_reply")


def test_the_agents_lines_after_the_closing_one_do_not_count() -> None:
    assert _no_deal(CLOSE, agent("c3", "Can you do $55?")) == OK


def test_a_second_ask_resets_the_window() -> None:
    again = (CLOSE, agent("c3", "Is that really your final offer?"))
    assert _no_deal(*again, ask=3) == _fail("no_closing_reply")
    assert _no_deal(*again, rep("c4", "Yes, it is our best offer."), ask=3) == OK


def test_a_rep_silent_since_the_last_ask_has_not_closed() -> None:
    assert _no_deal(ask=1) == _fail("no_closing_reply")
    assert _no_deal(CLOSE, agent("c3", "Final offer?"), ask=2) == _fail(
        "no_closing_reply"
    )


# S1-SYS-113 (ADR-0033): a closing line stands until a later rep line reopens
# it; filler does not (runs/v2-2862d54 247b62: finish refused at 472 s and
# 483 s). The fillers are verbatim from 247b62.
FILLER = (
    "No problem at all! How can I help with the account today?",  # cp-35
    "Sorry about that! How can I help with the account today?",  # cp-39
    "No worries at all! What can I help you with on the account today?",  # cp-59
    "I completely understand.",  # cp-41
    "Understood, that makes total sense!",  # cp-57
    "I'm sorry, but that offer is no longer available.",  # cp-36: a withdrawal
    "You're looking at $68.00 a month.",  # an amount a recorded offer carries
    "There is a $0 charge to switch back.",  # $0 is no offer
)
MONEY = (  # no reopen cue: only the unrecorded amount reopens them
    "That comes to $55 then.",
    "It would be 55 a month.",
    "There is a $10 credit on the account.",
)
CUE = (  # no amount: only the cue reopens them
    "I can waive the activation fee.",  # a concession
    "There is a loyalty promotion I could apply.",  # names an offer
    "We could offer you a free month.",  # makes one
    "What about a longer term?",
    "Actually, hold on.",  # a retraction
    "Let me check with my supervisor.",
)
REOPEN = (
    "Actually I can do $70",  # the brief's cases
    "How about 70 a month?",
    *MONEY,
    *CUE,
)


@pytest.mark.parametrize("filler", FILLER)
def test_filler_after_the_closing_line_keeps_it(filler: str) -> None:
    assert not reopens(filler, {Decimal(68)})
    assert _no_deal(CLOSE, rep("c3", filler)) == OK
    assert _no_deal(CLOSE, rep("c3", filler), rep("c4", filler)) == OK
    assert _no_deal(rep("c2", filler)) == _fail("no_closing_reply")  # filler only
    assert closing_at(_board(CLOSE, rep("c3", filler)), 1) == 1


@pytest.mark.parametrize("later", REOPEN)
def test_a_later_line_that_reopens_drops_the_close(later: str) -> None:
    assert _no_deal(CLOSE, rep("c3", later)) == _fail("no_closing_reply")
    assert closing_at(_board(CLOSE, rep("c3", later)), 1) is None
    filler = rep("c4", FILLER[0])  # filler after a reopening line closes nothing
    assert _no_deal(CLOSE, rep("c3", later), filler) == _fail("no_closing_reply")
    again = rep("c5", "I'm afraid that is our best offer.")  # a new close stands
    assert _no_deal(CLOSE, rep("c3", later), filler, again) == OK
    assert closing_at(_board(CLOSE, rep("c3", later), filler, again), 1) == 4


@pytest.mark.parametrize("later", MONEY)
def test_an_unrecorded_amount_alone_reopens(later: str) -> None:
    assert not has_cue(later, "reopen")
    assert reopens(later, {Decimal(68)})
    assert not reopens(later, {Decimal(68), Decimal(55), Decimal(10)})  # carried


@pytest.mark.parametrize("later", CUE)
def test_a_reopen_cue_alone_reopens(later: str) -> None:
    assert has_cue(later, "reopen") and reopens(later, set())


def test_an_amount_a_recorded_offer_carries_does_not_reopen() -> None:
    assert not reopens("That comes to $55 then.", {Decimal(55)})
    assert reopens("That comes to $55 then.", {Decimal(68)})
    assert not reopens("There is a $0 charge.", set())
    seventy = confirm(offer("o2", monthly="7000")).model_copy(
        update={"status": "declined"}
    )
    said = (*SAID, CLOSE, rep("c3", "That comes to $70 then."))
    bb = board(O1.model_copy(update={"status": "declined"}), seventy, cp=said)
    assert verify_no_deal(bb, 1) == OK  # $70 is a recorded offer's (declined)


def test_the_filler_case_of_247b62_verifies() -> None:
    """247b62 cp-58..cp-61: the close, then filler, a line no cue matches and
    filler; finish(no_deal) was refused at 472 s and 483 s."""
    lines = (
        rep("c1", "I can offer $68 a month."),
        rep("c2", "That monthly price is my absolute best offer, so I really "
                  "can't do any better!"),
        rep("c3", "No worries at all! What can I help you with on the account "
                  "today?"),
        rep("c4", "That is indeed my absolute best offer for Priya's account!"),
        rep("c5", "Sorry about that! How can I help with the account today?"),
    )  # fmt: skip
    declined = O1.model_copy(update={"status": "declined"})
    assert verify_no_deal(board(declined, cp=lines), 1) == OK


def _board(*after: Line) -> Blackboard:
    declined = O1.model_copy(update={"status": "declined"})
    return board(declined, cp=(*SAID, *after))


def _lint_imports(tree: Path, verify_source: str) -> subprocess.CompletedProcess[str]:
    """Run the repository's guard-never-imports-env contract over a tiny tree."""
    real = configparser.ConfigParser()
    real.read(ROOT / ".importlinter")
    config = configparser.ConfigParser()
    config["importlinter"] = {"root_packages": "\nproxyloop"}
    section = "importlinter:contract:agent-is-not-env"
    config[section] = dict(real[section])
    tree.mkdir()
    with (tree / ".importlinter").open("w") as fh:
        config.write(fh)
    for package in ("proxyloop", "proxyloop/guard", "proxyloop/env"):
        (tree / package).mkdir(parents=True, exist_ok=True)
        (tree / package / "__init__.py").write_text("")
    (tree / "proxyloop/guard/verify.py").write_text(verify_source)
    exe = shutil.which("lint-imports", path=str(Path(sys.executable).parent))
    assert exe is not None
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run(
        [exe, "--config", str(tree / ".importlinter"), "--no-cache"],
        cwd=tree,
        env=env | {"PYTHONPATH": str(tree), "PYTHONSAFEPATH": "1"},
        capture_output=True,
        text=True,
        check=False,
    )


def test_guard_verify_importing_env_fails_import_linter(tmp_path: Path) -> None:
    kept = _lint_imports(tmp_path / "kept", "import proxyloop.guard\n")
    assert kept.returncode == 0, kept.stdout + kept.stderr
    broken = _lint_imports(tmp_path / "broken", "import proxyloop.env\n")
    assert broken.returncode != 0
    assert "proxyloop.guard.verify -> proxyloop.env" in broken.stdout
