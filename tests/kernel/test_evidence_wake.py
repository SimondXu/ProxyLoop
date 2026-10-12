"""S1-SYS-104: Slow wakes when evidence is recorded (``evidence``). Live run
aebf80: after the call closed, Slow's step bound the rep's confirmation with
``check_account`` (EVIDENCE_PENDING) and made no ``wait`` or ``finish``; with
no wake source left outside the call it never stepped again, so the
``finish(completed)`` the evidence now allows never came (``timeout``). The
evidence wakes Slow whether or not the call is open, once; a wake during the
running step merges into the next step. Outside the call a step with neither
evidence nor a wait still arms nothing (no heartbeat after the call)."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from tests.concurrency.harness import (
    SCRIPTS,
    Sim,
    SlowGate,
    VirtualTime,
    called,
    granted,
)
from tests.concurrency.test_cases import arun
from tests.kernel.test_wake import Host
from tests.slow.test_close_confirmed import BINDING, CHECK, CONFIRMED, DONE
from tests.support.fakes import RepeatingLLM
from tests.support.manual_clock import ManualClock
from tests.support.sessions import act, fake_config, patient_task

from proxyloop.contract.events import Event
from proxyloop.contract.llm import (
    LLMClient,
    LLMRole,
    ModelRef,
    TextRequest,
    ToolRequest,
)
from proxyloop.contract.state import CaseStatus
from proxyloop.core.bus import Bus
from proxyloop.evidence.check import check_path
from proxyloop.kernel import wake
from proxyloop.kernel.channels import Channel, End, Incoming
from proxyloop.kernel.session import ChannelSpec, Kernel
from proxyloop.llm.http import RecordSink

NOTED = act("Noted.")
BIND = act("Bound.", CHECK | {"utt_ref": "cp-3"})  # no wait, no finish (aebf80)
FINISH = act("Verified.", DONE)
SAID = "Your confirmation number is 482913."


def woken(e: Event) -> list[str]:
    return list(cast(list[str], e.payload["wake_reasons"]))


class ByWake(RepeatingLLM):
    """Slow: the response of the first ``routes`` reason in the step's
    ``[WAKE]`` line, else ``NOTED``."""

    def __init__(
        self, ref: ModelRef, vt: VirtualTime, sink: RecordSink, routes: dict[str, str]
    ) -> None:
        super().__init__(ref, [NOTED], vt, False, sink)
        self._routes = routes

    async def _next(self, request: TextRequest | ToolRequest) -> tuple[str, int]:
        notes = request.messages[-1].content.split("\n")
        (line,) = [x for x in notes if x.startswith("[WAKE] ")]
        said = set(line.removeprefix("[WAKE] ").split(", "))
        pick = next((r for w, r in self._routes.items() if w in said), NOTED)
        self._responses[self.calls :] = [pick]
        return await super()._next(request)


class Routed(Sim):
    """``Sim`` with ``ByWake`` as Slow."""

    def __init__(self, root: Path, routes: dict[str, str]) -> None:
        self.vt, self.user, self.llms = VirtualTime(), Channel(), {}
        vt = self.vt

        def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
            if role == "slow":
                return ByWake(ref, vt, sink, routes)
            said = list(SCRIPTS.get(role, ["unused"]))
            self.llms[role] = RepeatingLLM(ref, said, vt, False, sink)
            return self.llms[role]

        specs: dict[str, ChannelSpec] = {"user": self.user, "cp": Channel()}
        task = called(patient_task())
        self.k = Kernel(fake_config(), task, specs, root, vt, vt.sleep, make, None)
        self.rep = self.k.channels["cp"]
        self._run, self._rep = None, 0
        self.rep_turns, self.rep_busy = [], []


async def committed(sim: Sim, text: str, end: End) -> Event:
    """Approve and release the accept (COMMITTED), then the rep's line ``text``
    (closing the call if ``end``) and the world's ledger write; the Slow step
    that line wakes waits for the write."""
    await sim.start()
    await granted(sim)
    assert sim.accept().startswith("accept_offer: accept line queued")
    await sim.vt.run_for(15_000)
    assert sim.bb.public.status is CaseStatus.COMMITTED
    gate = SlowGate(sim)
    gate.let(0)
    sim.rep.incoming.put_nowait(Incoming(((text, None),), end=end))
    await sim.vt.run_for(500)
    (said,) = sim.of("utt.final", text=text)
    assert said.payload["utt_id"] == "cp-3"
    write = {"confirmation_id": "482913", "binding": BINDING}
    sim.k.emit("ledger.write", "world.ledger", write, [said.event_id], "world")
    gate.let(None)
    return said


def recorded_in(sim: Sim) -> tuple[Event, list[tuple[Event, Event]]]:
    """The one ``evidence.recorded`` and every (started, completed) step."""
    (evidence,) = sim.of("evidence.recorded")
    done = sim.of("slow.step.completed")
    return evidence, list(zip(sim.of("slow.step.started"), done, strict=False))


def test_evidence_recorded_after_the_call_wakes_slow_to_finish(tmp_path: Path) -> None:
    """Acceptance 1 (aebf80): the step ``call_closed`` wakes binds the
    evidence and stops; the evidence wakes the next step, whose
    ``finish(completed)`` verifies the case."""
    sim = Routed(tmp_path, {"call_closed": BIND, "evidence": FINISH})

    async def case() -> None:
        await committed(sim, CONFIRMED, "closed")
        await sim.vt.run_for(5_000)
        assert sim.of("chan.closed")
        evidence, steps = recorded_in(sim)
        binding = next(s for s, d in steps if s.seq < evidence.seq < d.seq)
        assert "call_closed" in woken(binding)
        nxt = [s for s, _ in steps if s.seq > evidence.seq]
        assert nxt and woken(nxt[0]) == ["evidence"], [woken(s) for s, _ in steps]
        assert sim.bb.public.status is CaseStatus.VERIFIED_COMPLETE
        ended = sim.events[-1]
        assert ended.type == "session.ended"
        assert ended.payload["reason"] == "completed"
        assert check_path(sim.k.path, "offline").ok

    arun(case())


def test_evidence_recorded_in_the_call_wakes_slow_once(tmp_path: Path) -> None:
    """Acceptance 2: in the call too, the evidence wakes Slow, once (the
    repeated ``check_account`` records nothing new and wakes nothing)."""
    sim = Routed(tmp_path, {"rep_turn": BIND})

    async def case() -> None:
        await committed(sim, SAID, "")
        await sim.vt.run_for(40_000)
        assert not sim.of("chan.closed")
        evidence, steps = recorded_in(sim)
        assert sim.bb.public.status is CaseStatus.EVIDENCE_PENDING
        (binding, done), *_ = [(s, d) for s, d in steps if s.seq < evidence.seq < d.seq]
        assert "rep_turn" in woken(binding)
        nxt, *_ = [s for s, _ in steps if s.seq > done.seq]
        assert nxt.t_ms == done.t_ms and woken(nxt) == ["evidence"]
        assert [s for s, _ in steps if "evidence" in woken(s)] == [nxt]
        await sim.stop()

    arun(case())


def test_evidence_wakes_in_and_out_of_the_call_and_nothing_else_arms(
    tmp_path: Path,
) -> None:
    """The subscriber, from the log: ``evidence.recorded`` wakes Slow whatever
    the call; outside the call a step with no wait arms no timer, evidence or
    not (acceptance 3: the rule stands)."""
    host = Host()
    bus = Bus(tmp_path / "events.jsonl", "r", ManualClock())
    bus.subscribe(wake.Wakes(cast(Kernel, host)).on_event)
    root = bus.emit("user.msg", "kernel", "agent", {"text": "Hi"})

    def emit(type_: str, cause: Event = root, by: str = "kernel", **p: object) -> Event:
        return bus.emit(type_, by, "agent", p, [cause.event_id])

    def evidence(conf: str) -> None:
        emit("evidence.recorded", by="guard", evidence_id=f"ledger:{conf}",
             kind="ledger", confirmation_id=conf, terms_hash=None)  # fmt: skip

    def step(record: str | None = None) -> None:
        started = emit("slow.step.started", basis_seq=bus.bb.seq, wake_reasons=[])
        if record is not None:
            evidence(record)
        emit("slow.step.completed", started, basis_seq=started.seq)

    assert "evidence" in wake.REASONS
    evidence("111111")  # before any call
    emit("chan.opened", lane="cp")
    evidence("222222")  # in the call
    assert host.woken == ["evidence", "call_opened", "evidence"]
    emit("chan.closed", lane="cp")
    timers = host.timers
    step()  # after the call: no wait, no evidence -> nothing armed, no wake
    assert (host.woken[-1], host.timers) == ("call_closed", timers)
    step("333333")  # evidence in the step wakes once and arms nothing
    assert host.woken[-2:] == ["call_closed", "evidence"]
    assert host.timers == timers
    bus.close()
