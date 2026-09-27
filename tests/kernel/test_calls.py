"""Plan before act (ADR-0012, S1-SYS-21): the cp call's gate on virtual time.

R1: no ``chan.opened{cp}`` while a readiness key is missing, unless the
reason is ``slow_start`` (every missing key asked and replied) or
``intake_deadline``. R2: no rep clock and no FastC generation before it.
Whichever condition fires first opens exactly one call. Slow's tool calls run
through the session's real ``SlowTools``; the partners are silent channels
the test speaks for."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest
from tests.concurrency.harness import SCRIPTS, Sim, VirtualTime, called
from tests.concurrency.test_cases import arun
from tests.kernel.test_session import SCRIPTS as SESSION
from tests.support.fakes import RepeatingLLM
from tests.support.sessions import fake_config, only_bundle, patient_task, run

from proxyloop.contract.events import Event
from proxyloop.contract.llm import LLMClient, LLMRole, ModelRef
from proxyloop.contract.messages import FastToSlow
from proxyloop.contract.state import CaseStatus
from proxyloop.env.tasks.schema import Task
from proxyloop.kernel import calls, watchdog
from proxyloop.kernel.calls import DISCLOSURE, INTAKE_S, Calls
from proxyloop.kernel.channels import Channel
from proxyloop.kernel.session import ChannelSpec, Kernel
from proxyloop.llm.http import RecordSink
from proxyloop.slow import asks

H, L4 = "account.holder_name", "account.last4"
IDENTITY = "I'm Dana Reyes, and the last 4 are 4821."
DEADLINE = 1000 * INTAKE_S


class Clocked(Channel):
    """A rep whose clock ticks are recorded (a SimRep strikes from them)."""

    def __init__(self) -> None:
        super().__init__()
        self.ticks: list[int] = []

    async def tick(self, t_ms: int) -> None:
        self.ticks.append(t_ms)


class Intake(Sim):
    """A session on the S0 family as it is: its identity keys are shareable,
    so the call waits for them (``Sim`` starts in the call)."""

    def __init__(
        self,
        root: Path,
        scripts: Mapping[str, Sequence[str]] | None = None,
        keys: Sequence[str] = ("user", "cp"),
    ) -> None:
        self.vt, self.rep, self.user = VirtualTime(), Clocked(), Channel()
        self._run, self._rep = None, 0
        self.rep_turns, self.rep_busy, self.llms = [], [], {}
        lines, vt = {**SCRIPTS, **(scripts or {})}, self.vt

        def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
            said = list(lines.get(role, ["unused"]))
            self.llms[role] = RepeatingLLM(ref, said, vt, False, sink)
            return self.llms[role]

        every: dict[str, ChannelSpec] = {
            "user": self.user, "cp": self.rep, "cp_agent": Channel(),
        }  # fmt: skip
        specs: dict[str, ChannelSpec] = {k: every[k] for k in keys}
        self.k = Kernel(
            fake_config(), patient_task(), specs, root, vt, vt.sleep, make, None
        )

    def cp_opened(self) -> list[Event]:
        return self.of("chan.opened", lane="cp")

    def identify(self) -> list[str]:
        """Slow records both identity facts from the user's latest message."""
        (said, *_) = reversed(self.of("user.msg"))
        cite = {"tool": "record_fact", "utt_ref": said.event_id}
        return self.act(
            cite | {"key": H, "value": "Dana Reyes"},
            cite | {"key": L4, "value": "4821"},
        )

    def disclosed(self) -> Event:
        (said,) = self.of("utt.delivered", utt_id="disclosure")
        return said


def test_the_call_waits_for_readiness_and_opens_ready_after_the_act(
    tmp_path: Path,
) -> None:
    async def case() -> None:
        sim = Intake(tmp_path)
        await sim.start()
        assert [e.payload for e in sim.of("chan.opened")] == [{"lane": "user"}]
        assert sim.bb.public.status is CaseStatus.INTAKE and not sim.rep.ticks
        sim.user_says(IDENTITY)
        await sim.vt.run_for(100)
        out = sim.identify()
        assert out == ["record_fact: recorded public"] * 2, out
        assert not sim.cp_opened()  # R1: never inside the act that recorded it
        await sim.vt.run_for(100)
        (opened,) = sim.cp_opened()
        payload = {"lane": "cp", "call": 1, "reason": "ready"}
        assert opened.payload == payload | {"missing": [], "ready": True}
        last = sim.of("fact.recorded")[-1]
        assert opened.cause_ids == (last.event_id,)
        (moved,) = sim.of("status.changed")
        assert moved.payload == {"previous": "INTAKE", "status": "IN_CALL"}
        (line,) = sim.of("speak.verbatim", kind="disclosure")
        assert line.payload["text"] == DISCLOSURE
        assert line.cause_ids == (opened.event_id,)
        await sim.stop()

    arun(case())


def test_r2_no_rep_clock_and_no_fastc_before_the_call(tmp_path: Path) -> None:
    """INTAKE time never becomes a rep strike: the rep's clock starts once the
    disclosure is said. A GUIDE given in INTAKE is voiced after it."""

    async def case() -> None:
        sim = Intake(tmp_path)
        await sim.start()
        (guide,) = sim.act({"tool": "guide_fast", "move": "ask_discount"})
        assert guide.startswith("guide_fast: sent s2f-"), guide
        await sim.vt.run_for(DEADLINE)
        (opened,) = sim.cp_opened()
        assert opened.payload["reason"] == "intake_deadline"
        await sim.vt.run_for(10_000)
        said = sim.disclosed()
        assert sim.rep.ticks and min(sim.rep.ticks) >= said.t_ms
        asked = sim.of("fast.request", lane="cp")
        assert asked and min(e.seq for e in asked) > said.seq  # FastC after it
        (msg,) = [e for e in sim.of("s2f.msg") if e.payload["lane"] == "cp"]
        (voiced,) = sim.of("s2f.voiced", msg_id=msg.payload["msg_id"])
        assert voiced.seq > said.seq > opened.seq > msg.seq
        assert not sim.of("chan.strike")
        await sim.stop()

    arun(case())


def test_the_deadline_opens_the_call_with_what_is_missing(tmp_path: Path) -> None:
    async def case() -> None:
        sim = Intake(tmp_path)
        await sim.start()  # 5 s
        await sim.vt.run_for(DEADLINE - 5_100)
        assert not sim.cp_opened() and sim.k.calls.deadline_ms == DEADLINE
        await sim.vt.run_for(200)
        (opened,) = sim.cp_opened()
        payload = {"lane": "cp", "call": 1, "reason": "intake_deadline"}
        assert opened.payload == payload | {"missing": [H, L4], "ready": False}
        assert opened.t_ms == DEADLINE and opened.cause_ids == (sim.k.authority.root,)
        await sim.stop()

    arun(case())


def test_ready_and_the_deadline_together_open_one_call(tmp_path: Path) -> None:
    async def case() -> None:
        sim = Intake(tmp_path)
        await sim.start()
        sim.user_says(IDENTITY)
        await sim.vt.run_for(DEADLINE - 5_000 - 1)  # 1 ms before the deadline
        sim.identify()  # ready is spawned, the deadline is due
        await sim.vt.run_for(10)
        (opened,) = sim.cp_opened()
        assert opened.payload["reason"] == "ready"
        assert len(sim.of("status.changed")) == 1
        assert len(sim.of("speak.verbatim", kind="disclosure")) == 1
        await sim.vt.run_for(DEADLINE)
        assert len(sim.cp_opened()) == 1
        await sim.stop()

    arun(case())


def test_start_call_is_refused_until_every_missing_key_is_replied(
    tmp_path: Path,
) -> None:
    """A1 and R1; ``replied`` needs a ``user.msg`` newer than the ask's
    voicing: an echo relay citing the old message is no reply."""

    async def case() -> None:
        sim = Intake(tmp_path)
        await sim.start()
        old = sim.k.emit("user.msg", "kernel", {"text": "Hi, lower my bill."})
        start = {"tool": "start_call"}
        (refused,) = sim.act(start)
        assert "not asked yet: account.holder_name, account.last4" in refused
        ask = {"tool": "ask_user", "text": "Your name and last 4?", "keys": [H, L4]}
        (sent,) = sim.act(ask)
        assert sent.startswith("ask_user: sent s2f-"), sent
        (again,) = sim.act(ask | {"keys": [L4]})  # A1: pending, not asked again
        assert "already asked, waiting for the user: account.last4" in again
        await sim.vt.run_for(1_000)  # FastU voices the ask
        (msg,) = sim.of("s2f.msg", type="ASK_USER")
        assert sim.of("s2f.voiced", msg_id=msg.payload["msg_id"])
        echo = FastToSlow(
            msg_id=sim.k.next_event_id(), lane="user", gen_id="u-g9",
            utt_ref=old.event_id, type="USER_UPDATE", facts=((L4, "4821"),),
        )  # fmt: skip
        sim.k.emit("f2s.msg", "fast.user", echo.model_dump(mode="json"), [old.event_id])
        (refused,) = sim.act(start)
        assert "no reply from the user yet" in refused and not sim.cp_opened()
        sim.user_says("Dana Reyes. I don't know the last 4.")
        await sim.vt.run_for(100)
        (ok,) = sim.act(start)
        assert ok == "start_call: the call opens now; the phone voice discloses first"
        await sim.vt.run_for(100)
        (opened,) = sim.cp_opened()
        payload = {"lane": "cp", "call": 1, "reason": "slow_start"}
        assert opened.payload == payload | {"missing": [H, L4], "ready": False}
        (tool,) = [e for e in sim.of("slow.tool") if e.payload["name"] == "start_call"
                   and e.payload["ok"]]  # fmt: skip
        assert opened.cause_ids == (tool.event_id,)
        denied = [e.payload["reason"] for e in sim.of("action.denied")]
        assert denied == ["readiness_not_replied"] * 2
        assert [e.payload["ok"] for e in sim.of("slow.tool", name="ask_user")] == [
            True, False,
        ]  # fmt: skip
        (after,) = sim.act(start)
        assert after == "start_call: the call is already open"
        await sim.stop()

    arun(case())


def test_start_call_and_ready_in_one_act_open_one_call(tmp_path: Path) -> None:
    async def case() -> None:
        sim = Intake(tmp_path)
        await sim.start()
        sim.user_says(IDENTITY)
        await sim.vt.run_for(100)
        (said,) = sim.of("user.msg")
        cite = {"tool": "record_fact", "utt_ref": said.event_id}
        out = sim.act(
            cite | {"key": H, "value": "Dana Reyes"},
            cite | {"key": L4, "value": "4821"},
            {"tool": "start_call"},
        )
        assert out[-1].startswith("start_call: the call opens now"), out
        await sim.vt.run_for(100)
        (opened,) = sim.cp_opened()
        assert opened.payload["reason"] == "ready" and opened.payload["ready"]
        await sim.stop()

    arun(case())


def test_rep_chat_and_no_user_sessions_open_at_once(tmp_path: Path) -> None:
    async def case(keys: Sequence[str], root: Path) -> None:
        root.mkdir()
        sim = Intake(root, keys=keys)
        await sim.start()
        (opened,) = sim.cp_opened()
        assert opened.payload["reason"] == "no_intake" and opened.seq <= 2
        assert opened.cause_ids == (sim.k.authority.root,)
        assert sim.k.calls.deadline_ms is None
        await sim.stop()

    arun(case(("user", "cp", "cp_agent"), tmp_path / "rep_chat"))  # no Slow
    arun(case(("cp",), tmp_path / "no_user"))


def test_a_task_that_needs_nothing_opens_at_once_ready(tmp_path: Path) -> None:
    async def case() -> None:
        sim = Sim(tmp_path)  # the harness's task: no identity key shareable
        assert sim.k.task == called(patient_task())
        await sim.start()
        (opened,) = sim.of("chan.opened", lane="cp")
        assert opened.payload["reason"] == "ready" and opened.payload["ready"]
        await sim.stop()

    arun(case())


def test_r3a_an_empty_turn_voices_no_guide_and_retriggers_once(
    tmp_path: Path,
) -> None:
    """Review R3a: a GUIDE is acknowledged only by a turn that spoke or gave
    a directive; an empty turn re-triggers it once per message."""

    async def case() -> None:
        sim = Sim(tmp_path, {"fast_cp": ["", "", "Could you lower my price?"]})
        await sim.start()
        guide = {"tool": "guide_fast", "move": "ask_discount"}
        sim.act(guide)
        await sim.vt.run_for(10_000)
        first = sim.of("s2f.msg", type="GUIDE")[0].payload["msg_id"]
        tried = sim.of("fast.request", lane="cp", trigger="guidance")
        assert len(tried) == 2 and not sim.of("s2f.voiced", msg_id=first)
        assert sim.k.counts["guide_retrigger"] == 1  # D6: counted
        turns = sim.of("fast.turn", lane="cp")
        items = [cast(list[dict[str, str]], t.payload["items"]) for t in turns]
        assert [i[0]["kind"] for i in items] == ["issue", "issue"]  # empty turns
        sim.act(guide)  # a second message: this turn speaks
        await sim.vt.run_for(10_000)
        second = sim.of("s2f.msg", type="GUIDE")[1].payload["msg_id"]
        voiced = sim.of("fast.turn", lane="cp")[-1].event_id
        for msg_id in (first, second):  # the speaking turn voices both
            (ack,) = sim.of("s2f.voiced", msg_id=msg_id)
            assert ack.cause_ids == (voiced,)
        assert len(sim.of("fast.request", lane="cp", trigger="guidance")) == 3
        assert sim.k.counts["guide_retrigger"] == 1
        await sim.stop()

    arun(case())


def test_intake_time_never_becomes_a_rep_strike(tmp_path: Path) -> None:
    """The escalation trigger, on the world's own SimRep (silence 10 s) and a
    SimUser who never gives identity: the call opens at the deadline, and the
    rep's first silence strike comes at least 10 s after the disclosure."""
    data = patient_task().model_dump(mode="json")
    data["counterparty"]["patience"]["silence_s"] = 10
    scripts = SESSION | {"fast_cp": ["@wait"], "fast_user": ["Okay."]}
    result = run(tmp_path, scripts, task=Task.model_validate(data))
    events = only_bundle(tmp_path).events
    (opened,) = [
        e for e in events if e.type == "chan.opened" and e.payload["lane"] == "cp"
    ]
    assert opened.payload["reason"] == "intake_deadline" and opened.t_ms >= DEADLINE
    (said,) = [
        e
        for e in events
        if e.type == "utt.delivered" and e.payload["utt_id"] == "disclosure"
    ]
    strikes = [e for e in events if e.type == "chan.strike"]
    assert strikes, result  # not vacuous: the rep's clock runs in the call
    assert min(e.t_ms for e in strikes) >= said.t_ms + 10_000


def test_an_ask_voiced_by_a_turn_without_speech_is_not_voiced(tmp_path: Path) -> None:
    """Review D1: FastU acknowledged the ask with an empty turn, so the user
    never heard it; an unrelated message is no reply and start_call stays
    refused. The keys are as before the ask, so it may be asked again (A1)."""

    async def case() -> None:
        sim = Intake(tmp_path, {"fast_user": [""]})  # FastU never speaks
        await sim.start()
        ask = {"tool": "ask_user", "text": "Name and last 4?", "keys": [H, L4]}
        (sent,) = sim.act(ask)
        assert sent.startswith("ask_user: sent"), sent
        await sim.vt.run_for(1_000)
        (msg,) = sim.of("s2f.msg", type="ASK_USER")
        assert sim.of("s2f.voiced", msg_id=msg.payload["msg_id"])  # acked in lanes
        sim.user_says("What's going on?")
        await sim.vt.run_for(100)
        assert sim.k.calls.needs.states() == {}
        (refused,) = sim.act({"tool": "start_call"})
        assert "not asked yet" in refused and not sim.cp_opened()
        intake = asks.intake(sim.k)
        assert "account.last4 asked, not voiced" in asks.asks_line(intake, 0)
        (again,) = sim.act(ask)
        assert again.startswith("ask_user: sent"), again
        await sim.stop()

    arun(case())


def _ended(sim: Intake) -> Event:
    (ended,) = sim.of("session.ended")
    return ended


def test_d3_a_call_opened_at_the_deadline_gets_its_full_budget(tmp_path: Path) -> None:
    """Review D3 (root decision): the 480 s budget counts from chan.opened{cp}."""

    async def case() -> None:
        sim = Intake(tmp_path)
        await sim.start()
        await sim.vt.run_for(DEADLINE + int(1000 * watchdog.MAX_SESSION_S))
        (opened,) = sim.cp_opened()
        ended = _ended(sim)
        assert ended.payload["reason"] == "timeout"
        budget = ended.t_ms - opened.t_ms
        assert (
            1000 * watchdog.MAX_SESSION_S
            <= budget
            <= 1000 * watchdog.MAX_SESSION_S + 2_000
        )

    arun(case())


@pytest.mark.parametrize("late", ["never", "past_the_cap"])
def test_d3_the_hard_cap_holds_from_session_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, late: str
) -> None:
    """480 + INTAKE_S from session start, whichever bound comes first: a call
    that never opens, or one opened so late its own budget would run past it."""
    if late == "never":

        def never(self: Calls, cause: str, reason: str) -> None:
            return None

        monkeypatch.setattr(Calls, "_call", never)
    else:  # the deadline moved to 300 s: 300 + 480 > 600
        monkeypatch.setattr(calls, "INTAKE_S", 300)
    cap = 1000 * (watchdog.MAX_SESSION_S + INTAKE_S)

    async def case() -> None:
        sim = Intake(tmp_path)
        await sim.start()
        await sim.vt.run_for(int(cap) + 200_000)
        ended = _ended(sim)
        assert ended.payload["reason"] == "timeout"
        assert cap <= ended.t_ms <= cap + 2_000
        assert len(sim.cp_opened()) == (0 if late == "never" else 1)

    arun(case())


def test_d3_a_call_opened_at_once_keeps_todays_budget(tmp_path: Path) -> None:
    async def case() -> None:
        sim = Sim(tmp_path)  # ready at once
        await sim.start()
        await sim.vt.run_for(int(1000 * watchdog.MAX_SESSION_S) + 5_000)
        (ended,) = sim.of("session.ended")
        assert ended.payload["reason"] == "timeout"
        assert ended.t_ms <= 1000 * watchdog.MAX_SESSION_S + 2_000

    arun(case())
