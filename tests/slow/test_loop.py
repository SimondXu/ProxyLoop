"""SlowLoop on a real, idle kernel (the test is its only writer, so ids are known):
the ROOT-05 identity-deadlock replay, the bounded context (ADR-0009), and the S0
runaway guard (step cap, whole-call timeout)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from tests.kernel.test_session import SCRIPTS
from tests.support.fakes import RepeatingLLM, ScriptedLLM
from tests.support.manual_clock import ScaledClock
from tests.support.sessions import act, clients, fake, fake_config, only_bundle, run
from tests.support.sessions import patient_task as task

from proxyloop.contract.llm import LLMClient, LLMRole, ModelRef
from proxyloop.contract.messages import FastToSlow
from proxyloop.contract.protocol import render_messages
from proxyloop.contract.views import Trigger, view_cp
from proxyloop.kernel import session, watchdog
from proxyloop.kernel.session import ChannelSpec, Kernel, run_session
from proxyloop.kernel.watchdog import Abort
from proxyloop.llm.http import RecordSink
from proxyloop.slow import loop
from proxyloop.slow.loop import SlowLoop

WAIT = act("Waiting.", {"tool": "wait", "seconds": 15})


class Idle:
    """A kernel that never runs, and Slow loops built on it from a script."""

    def __init__(self, tmp_path: Path) -> None:
        self.clock, sinks = ScaledClock(100), dict[str, RecordSink]()

        def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
            sinks[role] = sink
            return RepeatingLLM(ref, ["unused"], self.clock, on_record=sink)

        specs: dict[str, ChannelSpec] = {"user": "sim", "cp": "sim"}
        clock, t = self.clock, task()
        self.k = Kernel(
            fake_config(), t, specs, tmp_path, clock, clock.sleep, make, None
        )
        self._sink = sinks["slow"]

    def slow(self, script: list[str]) -> SlowLoop:
        client = RepeatingLLM(fake("slow"), script, self.clock, on_record=self._sink)
        t = self.k.task
        return SlowLoop(self.k, client, t.slow_brief, frozenset(t.disclosure.shareable))

    def relay(self, cause: str, **fields: Any) -> str:
        msg = FastToSlow(msg_id=self.k.next_event_id(), gen_id="g", **fields)
        payload = msg.model_dump(mode="json")
        return self.k.emit("f2s.msg", f"fast.{msg.lane}", payload, [cause]).event_id

    def requests(self) -> list[list[dict[str, Any]]]:  # Slow's messages, in order
        calls = [e for e in self.k.bus.events if e.type == "llm.call"]
        shas = [str(e.payload["prompt_sha"]) for e in calls]
        return [json.loads(self.k.prompts[s].content)["messages"] for s in shas]


def test_the_identity_deadlock_replay_resolves_on_the_first_step(
    tmp_path: Path,
) -> None:  # ROOT-05 (a): IDENTIFY looped 54x, the guide denied every time
    idle = Idle(tmp_path)
    k = idle.k
    text = "It's Dana Reyes, and my last four are 4821."
    said = k.emit("user.msg", "kernel", {"text": text}).event_id
    facts = (("account_last_4", "4821"), ("name", "Dana Reyes"))  # non-canonical
    idle.relay(said, lane="user", utt_ref=said, type="USER_UPDATE", facts=facts)
    slots = ["fact:account.holder_name", "fact:account.last4"]
    identify = act(
        "Identity given.",
        {"tool": "record_fact", "key": "account.holder_name",
         "value": "Dana Reyes", "utt_ref": said},
        {"tool": "record_fact", "key": "account.last4", "value": "4821",
         "utt_ref": said},
        {"tool": "guide_fast", "move": "identify", "slots": slots},
    )  # fmt: skip
    asyncio.run(idle.slow([identify]).step(["relay"]))
    assert not [e for e in k.bus.events if e.type == "action.denied"]
    public = k.bb.public.facts
    assert {key: (f.value, f.source, f.source_ref) for key, f in public.items()} == {
        "account.holder_name": ("Dana Reyes", "shareable", said),
        "account.last4": ("4821", "shareable", said),
    }
    (guide,) = [m.guide for m in k.bb.s2f_pending["cp"]]
    assert guide is not None and (guide.move, list(guide.slots)) == ("identify", slots)
    view = view_cp(k.bb, Trigger(kind="guidance"), k.task.fast_brief_cp)
    rendered = "".join(m.content for m in render_messages(view, "pl_cp_v2"))
    assert "4821" in rendered and "Dana Reyes" in rendered  # FastC can answer
    k.bus.close()


def test_slow_holds_for_a_missing_identity_fact_then_is_told_to_identify(
    tmp_path: Path,
) -> None:  # S0-SYS-07, run aeab91: deflected while waiting, recorded, never identified
    idle = Idle(tmp_path)
    k = idle.k
    ask = "What is the account holder name and the last 4 of the account?"
    hold = act(
        "The rep asks for identity; asking the user.",
        {"tool": "ask_user", "text": ask},
        {"tool": "guide_fast", "move": "hold_for_fact"},
    )
    start = k.emit("user.msg", "kernel", {"text": "Find me a lower price."}).event_id
    text = "My name is Dana Reyes and the last 4 digits are 4821."
    said = k.emit("user.msg", "kernel", {"text": text}).event_id  # relayed later
    record = act(
        "Identity given.",
        {
            "tool": "record_fact",
            "key": "account.holder_name",
            "value": "Dana Reyes",
            "utt_ref": said,
        },
        {
            "tool": "record_fact",
            "key": "account.last4",
            "value": "4821",
            "utt_ref": said,
        },
    )  # fmt: skip: as in aeab91, no guide follows
    slow = idle.slow([hold, record])
    idle.relay(start, lane="cp", utt_ref=None, type="HOLD", text="fact_request")
    asyncio.run(slow.step(["relay"]))
    (guide,) = [m.guide for m in k.bb.s2f_pending["cp"]]
    assert guide is not None and guide.move == "hold_for_fact"
    kinds = {e.type for e in k.bus.events}
    assert not {"approval.requested", "authority.fence", "authority.epoch"} & kinds
    assert "status.changed" not in kinds and "action.denied" not in kinds
    idle.relay(said, lane="user", utt_ref=said, type="USER_UPDATE", text=text)
    asyncio.run(slow.step(["relay"]))
    assert set(k.bb.public.facts) == {"account.holder_name", "account.last4"}
    asyncio.run(slow.step(["timer"]))
    first, _, third = (m[-1]["content"] for m in idle.requests())
    assert "not given yet" in first and "hold_for_fact" in first
    system = idle.requests()[0][0]["content"]  # S1-SYS-20: the fact hold (ADR-0011)
    assert "guide_fast(hold_for_fact)" in system and "hold_for_decision" not in system
    slots = "slots=[fact:account.holder_name, fact:account.last4]"
    assert f"guide_fast(identify, {slots})" in third
    k.bus.close()


def _paired(messages: list[dict[str, Any]]) -> bool:  # each tool call, its result
    for n, m in enumerate(messages):
        ids = [c["call_id"] for c in m.get("tool_calls") or ()]
        after = [x.get("tool_call_id") for x in messages[n + 1 : n + 1 + len(ids)]]
        if after != ids:
            return False
    answered = {c["call_id"] for m in messages for c in m.get("tool_calls") or ()}
    return all(m["tool_call_id"] in answered for m in messages if m["role"] == "tool")


def test_slow_context_is_bounded_and_keeps_every_call_with_its_result(
    tmp_path: Path,
) -> None:  # ROOT-05 (f), ADR-0009
    idle = Idle(tmp_path)
    k, steps, window = idle.k, 3 * loop.WINDOW, loop.WINDOW
    public = "Calling Northwind for the account holder."
    silent = json.dumps({"text": "Thinking.", "tool_calls": []})  # no tool call
    script = [act(f"Digest {n}.", public=public) if n % 4 else silent
              for n in range(steps)]  # fmt: skip
    slow = idle.slow(script)
    for n in range(steps):
        line = k.emit("user.msg", "kernel", {"text": f"message {n}"}).event_id
        idle.relay(line, lane="user", utt_ref=line, type="NOTE", text=f"<{n}>")
        asyncio.run(slow.step(["relay"]))
    requests = idle.requests()
    assert len(requests) == steps
    for n, messages in enumerate(requests):
        roles = [m["role"] for m in messages]
        assert roles[:2] == ["system", "user"] and _paired(messages), n
        assert roles.count("assistant") == min(n, window)
        assert f"<{n}>" in messages[-1]["content"]  # the new notes come last
        text = json.dumps(messages)
        kept = [r for r in range(n + 1) if f"<{r}>" in text]
        assert kept == list(range(n - window + 1 if n > window else 0, n + 1))
    head, latest = requests[-1][1]["content"], max(n for n in range(steps - 1) if n % 4)
    assert "[EARLIER]" in head and f"Digest {latest}." in head and public in head
    sizes = [len(json.dumps(m)) for m in requests[window + 1 :]]
    assert max(sizes) < 1.5 * min(sizes)  # it no longer grows with the session
    k.bus.close()


def test_the_step_cap_ends_the_session_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # the S0 runaway guard
    assert (loop.MAX_STEPS, watchdog.MAX_SESSION_S) == (40, 480.0)
    assert session.PROJECTED == (300_000, 150)
    monkeypatch.setattr(loop, "MAX_STEPS", 2)
    scripts = SCRIPTS | {"slow": [act("Waiting.", {"tool": "wait", "seconds": 1})]}
    with pytest.raises(Abort, match="2 steps"):
        run(tmp_path, scripts)
    events = only_bundle(tmp_path).events
    assert events[-1].payload["reason"] == "slow_step_cap"
    assert len([e for e in events if e.type == "slow.step.started"]) == 2


def test_a_slow_call_past_its_deadline_ends_the_session_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # provisional until S0-ROOT-12; no retry, no fallback (rule 6)
    assert loop.CALL_S == 180.0
    monkeypatch.setattr(loop, "CALL_S", 0.05)
    clock = ScaledClock(100)
    others = clients(SCRIPTS, clock, (), {})

    def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
        if role == "slow":  # it answers after 5 s of real time
            return ScriptedLLM(ref, [WAIT], clock, on_record=sink, hang_s=5)
        return others(role, ref, sink)

    with pytest.raises(Abort, match=r"took over 0\.05 s"):
        asyncio.run(
            run_session(fake_config(), task(), runs_dir=tmp_path, clock=clock,
                        sleep=clock.sleep, clients=make)
        )  # fmt: skip
    events = only_bundle(tmp_path).events
    assert events[-1].payload["reason"] == "slow_timeout"
    slow = [e for e in events if e.type == "llm.call" and e.payload["role"] == "slow"]
    assert [e.payload["error"] for e in slow] == ["cancelled"]  # the call's record
