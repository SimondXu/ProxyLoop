"""S1-SYS-74: identify before the rep asks. The call opens once the identity
facts are public; Slow, woken by ``call_opened``, guides ``identify`` with
them at once; FastC's first cp turn after the disclosure voices it, before
the rep's first ask, so no unguided refusal comes first (the live runs:
ordering, not latency). The needs ledger and Slow's status bar then hold no
push to identify again. A real ``Kernel`` on virtual time; Slow answers from
a script, and its tool calls run through the session's real ``SlowTools``."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from tests.concurrency.harness import SCRIPTS, VirtualTime
from tests.concurrency.test_cases import arun
from tests.kernel.test_calls import IDENTITY, L4, Clocked, H, Intake
from tests.support.fakes import RepeatingLLM
from tests.support.sessions import act, fake_config, patient_task

from proxyloop.contract.events import Event
from proxyloop.contract.llm import (
    LLMClient,
    LLMRole,
    ModelRef,
    TextRequest,
    ToolRequest,
)
from proxyloop.guard import needs
from proxyloop.kernel.channels import Channel
from proxyloop.kernel.session import ChannelSpec, Kernel
from proxyloop.llm.http import RecordSink

NOTED = act("Noted.")
IDENTIFY = act(
    "Identify first.",
    {"tool": "guide_fast", "move": "identify", "slots": [f"fact:{H}", f"fact:{L4}"]},
)
ASK = "Thanks for calling. Can I have the account holder's name and last four?"


def wake_line(notes: str) -> str:
    (line,) = [x for x in notes.split("\n") if x.startswith("[WAKE] ")]
    return line


def woken(e: Event) -> list[str]:
    return list(cast(list[str], e.payload["wake_reasons"]))


class OnOpen(RepeatingLLM):
    """Slow: ``IDENTIFY`` at the step woken by ``call_opened``, else noted.
    Keeps the newest message of every request (its notes and status bar)."""

    def __init__(self, ref: ModelRef, vt: VirtualTime, sink: RecordSink) -> None:
        super().__init__(ref, [NOTED], vt, False, sink)
        self.newest: list[str] = []

    async def _next(self, request: TextRequest | ToolRequest) -> tuple[str, int]:
        newest = request.messages[-1].content
        self.newest.append(newest)
        opened = "call_opened" in wake_line(newest)
        self._responses[self.calls :] = [IDENTIFY if opened else NOTED]
        return await super()._next(request)


class Opening(Intake):
    """``Intake`` (the S0 family's identity keys are shareable) with ``OnOpen``
    as Slow."""

    slow_llm: OnOpen

    def __init__(self, root: Path) -> None:
        self.vt, self.rep, self.user = VirtualTime(), Clocked(), Channel()
        self._run, self._rep = None, 0
        self.rep_turns, self.rep_busy, self.llms = [], [], {}
        lines = {**SCRIPTS, "fast_cp": ["I'm calling for Dana Reyes, last four 4821."]}
        vt = self.vt

        def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
            if role == "slow":
                self.slow_llm = OnOpen(ref, vt, sink)
                return self.slow_llm
            self.llms[role] = RepeatingLLM(ref, list(lines[role]), vt, False, sink)
            return self.llms[role]

        specs: dict[str, ChannelSpec] = {"user": self.user, "cp": self.rep}
        self.k = Kernel(
            fake_config(), patient_task(), specs, root, vt, vt.sleep, make, None
        )


def session(root: Path) -> Opening:
    """The user gives both identity facts; Slow records them (the call opens,
    ``ready``); the rep asks 12 s after the open, as in the live runs."""
    sim = Opening(root)

    async def case() -> None:
        await sim.start()
        sim.user_says(IDENTITY)
        await sim.vt.run_for(100)
        assert sim.identify() == ["record_fact: recorded public"] * 2
        await sim.vt.run_for(12_000)
        sim.rep_says(ASK)
        await sim.vt.run_for(20_000)
        await sim.stop()

    arun(case())
    return sim


def _guide(sim: Opening) -> Event:
    (guide,) = [e for e in sim.of("s2f.msg", lane="cp") if e.payload.get("guide")]
    return guide


def test_t1_fastc_s_first_cp_turn_is_the_identify_before_the_rep_asks(
    tmp_path: Path,
) -> None:
    sim = session(tmp_path)
    (opened,) = sim.cp_opened()
    assert opened.payload["reason"] == "ready"
    (woke,) = [s for s in sim.of("slow.step.started") if "call_opened" in woken(s)]
    guide = _guide(sim)
    assert guide.payload["guide"] == {
        "move": "identify",
        "slots": [f"fact:{H}", f"fact:{L4}"],
    }
    assert opened.seq < woke.seq < guide.seq
    first, *_ = sim.of("fast.request", lane="cp")  # FastC's first cp generation
    assert first.payload["trigger"] == "guidance"
    assert first.seq > sim.disclosed().seq  # FastC starts after the disclosure
    prompt = sim.k.prompts[str(first.payload["prompt_sha"])].content
    assert f"fact:{H} = Dana Reyes" in prompt and f"fact:{L4} = 4821" in prompt
    (asked,) = sim.of("utt.final", speaker="partner")
    turns = sim.of("fast.turn", lane="cp")
    assert turns[0].cause_ids[0] == first.event_id and turns[0].seq < asked.seq
    msg = guide.payload["msg_id"]
    voiced = sim.of("s2f.voiced", msg_id=msg)
    assert [v.payload["gen_id"] for v in voiced] == [first.payload["gen_id"]]


def test_t3_an_identify_with_no_ask_leaves_no_need_and_no_push_to_repeat(
    tmp_path: Path,
) -> None:
    """The identify was voiced with no rep ask before it: the needs ledger
    holds only the two answered facts (no pending, unvoiced or keyless ask),
    and when the rep then asks, Slow's status bar shows nothing missing and
    the identify as heard: nothing pushes a second one."""
    sim = session(tmp_path)
    ledger = needs.fold(sim.events)
    assert ledger == sim.k.calls.needs
    assert ledger.states() == {H: "answered", L4: "answered"}
    assert all(n.asks == 0 for n in ledger.needs.values())
    assert (ledger.unvoiced, ledger.keyless, ledger.asking, ledger.voicing) == (
        frozenset(),
        0,
        {},
        {},
    )
    (asked,) = sim.of("utt.final", speaker="partner")
    after = [
        s
        for s in sim.of("slow.step.started")
        if int(str(s.payload["basis_seq"])) >= asked.seq
    ]
    assert after, "Slow steps after the rep's ask"
    n = sim.of("slow.step.started").index(after[0])
    bar = sim.slow_llm.newest[n]
    assert "rep_turn" in wake_line(bar), bar
    assert "readiness: call open (ready)\n" in bar and "still missing" not in bar
    assert "asks: none" in bar
    assert "identify: heard by the rep" in bar, bar
    assert len([e for e in sim.of("s2f.msg", lane="cp") if e.payload.get("guide")]) == 1
