"""The partner fence under ``slow_view=transcript`` (ADR-0016 note, S1-SYS-34):
Slow reads the rep's lines itself, so a rep line is covered once any Slow step
whose ``basis_seq`` is at or after the line's ``utt.final`` has completed,
whether FastC answered it or not. A step that started before the line does not
cover it. (``relay_only`` keeps S1-SYS-23's rule: ``test_partner_fence``.)"""

from __future__ import annotations

from pathlib import Path

from tests.concurrency.harness import Sim, SlowGate, granted
from tests.concurrency.test_cases import FIX, Valve, arun

from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.events import Event
from proxyloop.evidence.check import check_path

ELSE = "Anything else?"


def _one(sim: Sim, type_: str, **match: object) -> Event:
    (e,) = sim.of(type_, **match)
    return e


def _ends(sim: Sim) -> list[Event]:
    return sim.of("speak.released", cap_id="cap-1") + sim.of(
        "speak.revoked", cap_id="cap-1"
    )


def _step_of(sim: Sim, cleared: Event) -> Event:
    (step,) = [e for e in sim.events if e.event_id == cleared.cause_ids[0]]
    assert step.type == "slow.step.completed"
    return step


def _up(sim: Sim, fence: Event) -> bool:
    return fence.payload["fence_id"] in {f.fence_id for f in sim.bb.fences}


async def _started(tmp_path: Path, fast_cp: Valve) -> Sim:
    sim = Sim(tmp_path, gates={"fast_cp": fast_cp})
    assert sim.k.cfg.slow_view is SlowViewMode.TRANSCRIPT  # the default
    await sim.start()
    await granted(sim)
    return sim


def test_a_rep_line_is_covered_once_a_step_read_it_without_fastc(
    tmp_path: Path,
) -> None:
    """FastC never answers the line: the fence is bound at once and cleared by
    the first step that read it; then the accept is released."""

    async def case() -> None:
        fast_cp = Valve()
        sim = await _started(tmp_path, fast_cp)
        fast_cp.open.clear()
        sim.rep_composes()
        assert sim.accept().startswith("accept_offer: accept line queued")
        await sim.vt.run_for(1_000)
        sim.rep_done(ELSE)
        await sim.vt.run_for(5_000)
        said = _one(sim, "utt.final", text=ELSE)
        fence = _one(sim, "authority.fence", op="raised")
        assert fence.cause_ids == (said.event_id,)
        cleared = _one(sim, "authority.fence", op="cleared")
        step = _step_of(sim, cleared)
        assert int(str(step.payload["basis_seq"])) >= said.seq
        assert not [t for t in sim.of("fast.turn", lane="cp") if t.seq > said.seq]
        (released,) = _ends(sim)
        assert released.type == "speak.released" and released.seq > cleared.seq
        fast_cp.open.set()
        await sim.stop()
        assert check_path(sim.k.path, "offline").ok

    arun(case())


def test_a_step_that_started_before_the_line_does_not_cover_it(
    tmp_path: Path,
) -> None:
    async def case() -> None:
        fast_cp = Valve()
        sim = await _started(tmp_path, fast_cp)
        fast_cp.open.clear()
        gate = SlowGate(sim)
        gate.let(0)
        assert sim.k.slow is not None
        sim.k.slow.wake("fence")  # a step starts and is held in flight
        await sim.vt.run_for(100)
        early = sim.of("slow.step.started")[-1]
        sim.rep_composes()
        assert sim.accept().startswith("accept_offer: accept line queued")
        sim.rep_done(FIX)
        await sim.vt.run_for(500)
        said = _one(sim, "utt.final", text=FIX)
        fence = _one(sim, "authority.fence", op="raised")
        assert int(str(early.payload["basis_seq"])) < said.seq
        gate.let(1)  # the early step completes; the next one is held
        await sim.vt.run_for(3_000)
        done = [e for e in sim.of("slow.step.completed") if e.seq > said.seq]
        assert [int(str(e.payload["basis_seq"])) for e in done] == [
            int(str(early.payload["basis_seq"]))
        ]
        assert _up(sim, fence) and _ends(sim) == []
        gate.let(None)  # the step that read the line completes
        await sim.vt.run_for(5_000)
        step = _step_of(sim, _one(sim, "authority.fence", op="cleared"))
        assert int(str(step.payload["basis_seq"])) >= said.seq
        (released,) = _ends(sim)
        assert released.type == "speak.released"
        fast_cp.open.set()
        await sim.stop()

    arun(case())


def test_a_line_before_the_mint_is_fenced_until_a_step_reads_it(
    tmp_path: Path,
) -> None:
    """The mint path: the rep's correction lands with no accept in flight and
    no step read it yet; the mint fences it (bound at once), a step reads it."""

    async def case() -> None:
        fast_cp = Valve()
        sim = await _started(tmp_path, fast_cp)
        fast_cp.open.clear()
        gate = SlowGate(sim)
        gate.let(0)
        sim.rep_says(FIX)
        await sim.vt.run_for(500)
        said = _one(sim, "utt.final", text=FIX)
        assert sim.of("authority.fence") == []  # no accept in flight yet
        assert sim.accept().startswith("accept_offer: accept line queued")
        auth = _one(sim, "action.authorized")
        fence = _one(sim, "authority.fence", op="raised")
        assert fence.cause_ids == (said.event_id, auth.event_id)
        await sim.vt.run_for(3_000)
        assert _up(sim, fence) and _ends(sim) == []
        gate.let(None)
        await sim.vt.run_for(5_000)
        step = _step_of(sim, _one(sim, "authority.fence", op="cleared"))
        assert int(str(step.payload["basis_seq"])) >= said.seq
        (released,) = _ends(sim)
        assert released.type == "speak.released"
        fast_cp.open.set()
        await sim.stop()
        assert check_path(sim.k.path, "offline").ok

    arun(case())


def test_a_line_a_step_already_read_raises_no_fence_at_the_mint(
    tmp_path: Path,
) -> None:
    async def case() -> None:
        fast_cp = Valve()
        sim = await _started(tmp_path, fast_cp)
        fast_cp.open.clear()  # FastC never answers: in relay_only it would fence
        sim.rep_says(FIX)
        await sim.vt.run_for(500)
        said = _one(sim, "utt.final", text=FIX)
        assert sim.k.slow is not None
        sim.k.slow.wake("fence")
        await sim.vt.run_for(2_000)
        step = sim.of("slow.step.completed")[-1]
        assert int(str(step.payload["basis_seq"])) >= said.seq
        assert sim.accept().startswith("accept_offer: accept line queued")
        await sim.vt.run_for(15_000)
        assert sim.of("authority.fence") == []
        (released,) = _ends(sim)
        assert released.type == "speak.released"
        fast_cp.open.set()
        await sim.stop()

    arun(case())
