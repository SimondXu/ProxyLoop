"""W1 (P-WEB's ``make demo``, S1-SYS-34 round 2): after an approved accept the
rep's closing CONFIRMED line closes the call, so FastC never answers it and
never relays the confirmation id. In ``transcript`` mode Slow's
``call_closed`` step reads that line and binds it with ``check_account``: the
session ends ``completed`` at VERIFIED_COMPLETE. Under ``relay_only`` (A5) the
id never reaches Slow: a known A5 limitation, pinned below."""

from __future__ import annotations

from pathlib import Path

from tests.concurrency.harness import A5, Sim, SlowGate, granted
from tests.concurrency.test_cases import arun
from tests.support.sessions import act

from proxyloop.contract.config import SessionConfig
from proxyloop.contract.state import CaseStatus
from proxyloop.evidence.check import check_path
from proxyloop.kernel.channels import Incoming

CONFIRMED = "All set: your confirmation number is 482913. Goodbye."
BINDING = {  # the world's ledger entry for the $68, 12-month offer (harness)
    "offer_ref": "o1",
    "revision": 1,
    "term_months": 12,
    "terms": {
        "monthly_price": "68.00",
        "fees_none": "true",
        "changes_none": "true",
        "expires": "none",
    },
}
DONE = {"tool": "finish", "outcome": "completed", "summary": "done"}
CHECK = {"tool": "check_account", "confirmation_id": "482913"}


async def _closed(tmp_path: Path, cfg: SessionConfig | None, answer: str) -> Sim:
    """Approve, release the accept, then the rep's closing CONFIRMED line and
    its ledger write; Slow answers ``answer`` once its request says the call
    closed."""
    sim = Sim(tmp_path, until={"slow": ("call_closed", answer)}, cfg=cfg)
    await sim.start()
    await granted(sim)
    assert sim.accept().startswith("accept_offer: accept line queued")
    await sim.vt.run_for(15_000)
    assert sim.of("speak.released", cap_id="cap-1")
    assert sim.bb.public.status is CaseStatus.COMMITTED
    gate = SlowGate(sim)
    gate.let(0)  # the step the close wakes waits for the world's write
    sim.rep.incoming.put_nowait(Incoming(((CONFIRMED, None),), end="closed"))
    await sim.vt.run_for(500)
    (said,) = sim.of("utt.final", text=CONFIRMED)
    (closed,) = sim.of("chan.closed")
    assert said.payload["utt_id"] == "cp-3" and closed.seq > said.seq
    assert not [e for e in sim.of("fast.request", lane="cp") if e.seq > said.seq]
    write = {"confirmation_id": "482913", "binding": BINDING}
    sim.k.emit("ledger.write", "world.ledger", write, [said.event_id], "world")
    gate.let(None)
    await sim.vt.run_for(5_000)
    return sim


def test_a_closing_confirmation_completes_the_case(tmp_path: Path) -> None:
    async def case() -> None:
        cite = CHECK | {"utt_ref": "cp-3"}  # the line as [CONVERSATIONS] shows it
        sim = await _closed(tmp_path, None, act("Confirmed.", cite, DONE))
        (said,) = sim.of("utt.final", text=CONFIRMED)
        step = next(
            e
            for e in sim.of("slow.step.started")
            if "call_closed" in str(e.payload["wake_reasons"])
        )
        assert int(str(step.payload["basis_seq"])) > said.seq
        (evidence,) = sim.of("evidence.recorded")
        assert said.event_id in evidence.cause_ids
        assert sim.bb.public.status is CaseStatus.VERIFIED_COMPLETE
        ended = sim.events[-1]
        assert ended.type == "session.ended"
        assert ended.payload["reason"] == "completed"
        assert check_path(sim.k.path, "offline").ok

    arun(case())


def test_a5_known_limitation_a_closing_confirmation_is_never_relayed(
    tmp_path: Path,
) -> None:
    """A5 pinned as it is: FastC is never triggered after the close, so no
    relay carries the id; check_account refuses it and the case stays
    COMMITTED (the session does not end on its own)."""

    async def case() -> None:
        sim = await _closed(tmp_path, A5, act("Confirmed?", CHECK, DONE))
        tried = sim.of("slow.tool", name="check_account")
        assert tried and not any(e.payload["ok"] for e in tried)
        assert "no such confirmation relayed" in str(tried[0].payload["result_text"])
        assert not sim.of("evidence.recorded") and not sim.of("session.ended")
        assert sim.bb.public.status is CaseStatus.COMMITTED
        await sim.stop()

    arun(case())
