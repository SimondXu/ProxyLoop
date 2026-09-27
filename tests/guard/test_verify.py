"""verify_completion and the non-omniscient verify_no_deal (§9.3)."""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from tests.guard.build import board, confirm, mandate, offer, rep

from proxyloop.contract.state import (
    Approval,
    Blackboard,
    Capability,
    CompletionDecision,
    Evidence,
)
from proxyloop.guard.verify import verify_completion, verify_no_deal

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
