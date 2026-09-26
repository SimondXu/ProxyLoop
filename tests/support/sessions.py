"""Whole sessions from fakes: a ``test_fake`` config, scripted clients for every
role (through the kernel's record sink, as a real adapter), the S0 family with
slow patience, and a scripted person. Tests only (I8)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from tests.support.fakes import RepeatingLLM
from tests.support.manual_clock import ScaledClock

from proxyloop.contract.bundle import Bundle, read_bundle
from proxyloop.contract.config import Sampling, SessionConfig, WorldModels
from proxyloop.contract.llm import AdapterKind, LLMClient, LLMRole, ModelRef
from proxyloop.env.tasks.loader import load_task
from proxyloop.env.tasks.schema import Task
from proxyloop.kernel.channels import Channel, Incoming
from proxyloop.kernel.session import ChannelSpec, ClientFactory, RunResult, run_session
from proxyloop.llm.http import RecordSink

Scripts = Mapping[str, Sequence[str]]
Until = Mapping[str, tuple[str, str]]  # role -> (marker, response)


def fake(role: str, world: bool = False) -> ModelRef:
    effort = "minimal" if world else None
    kind = AdapterKind.TEST_FAKE
    return ModelRef(
        kind=kind, endpoint=None, model_id=f"{role}-fake", reasoning_effort=effort
    )


def fake_config() -> SessionConfig:
    world = WorldModels(
        ear=fake("ear", True), mouth=fake("mouth", True), simuser=fake("simuser", True)
    )
    return SessionConfig(
        fast_user=fake("fast_user"),
        fast_cp=fake("fast_cp"),
        slow=fake("slow"),
        world=world,
        fast_sampling=Sampling(temperature=0.3, top_p=0.9, max_tokens=160),
        seed=7,
        live=False,
    )


def patient_task() -> Task:
    """The S0 family with a patient rep: fake turns must not strike out."""

    data = load_task("cp-direct-discount").model_dump(mode="json")
    data["counterparty"]["patience"]["silence_s"] = 600
    return Task.model_validate(data)


def reply(text: str, **revealed: str) -> str:
    """A SimUser ``reply`` tool call, as ScriptedLLM's JSON."""

    args = json.dumps({"text": text, "revealed": revealed})
    return json.dumps(
        {
            "text": "",
            "tool_calls": [{"call_id": "t", "name": "reply", "arguments": args}],
        }
    )


def ear(act: str, **args: object) -> str:
    call = {
        "call_id": "t",
        "name": "classify",
        "arguments": json.dumps({"act": act} | args),
    }
    return json.dumps({"text": "", "tool_calls": [call]})


def act(private: str, *calls: Mapping[str, object], public: str | None = None) -> str:
    body: dict[str, object] = {"private_summary": private, "calls": list(calls)}
    if public is not None:
        body["public_summary"] = public
    call = {"call_id": "a", "name": "act", "arguments": json.dumps(body)}
    return json.dumps({"text": "", "tool_calls": [call]})


def clients(
    scripts: Scripts, clock: ScaledClock, dead: Sequence[str], until: Until
) -> ClientFactory:
    """Each role answers from its script (the last answer repeats)."""

    def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
        script, stop = scripts.get(role, ["unused"]), until.get(role)
        return RepeatingLLM(ref, script, clock, role in dead, sink, stop)

    return make


class Person(Channel):
    """A scripted person at the terminal: one line per turn they hear."""

    def __init__(self, lines: Sequence[str]) -> None:
        super().__init__()
        self.lines, self.heard = list(lines), list[str]()

    def say(self) -> None:
        if self.lines:
            text = self.lines.pop(0)
            quit_ = text == "/quit"
            self.incoming.put_nowait(
                Incoming(() if quit_ else ((text, None),), end="quit" if quit_ else "")
            )

    async def send(self, text: str | None, utt_id: str, cause: str, t_ms: int) -> None:
        if text:
            self.heard.append(text)
            self.say()


def run(
    tmp_path: Path,
    scripts: Scripts,
    channels: Mapping[str, ChannelSpec] | None = None,
    dead: Sequence[str] = (),
    cfg: SessionConfig | None = None,
    until: Until | None = None,
) -> RunResult:
    clock = ScaledClock(100)
    session = run_session(
        cfg or fake_config(),
        patient_task(),
        channels,
        runs_dir=tmp_path,
        clock=clock,
        sleep=clock.sleep,
        clients=clients(scripts, clock, dead, until or {}),
    )
    return asyncio.run(asyncio.wait_for(session, timeout=30))


def only_bundle(tmp_path: Path) -> Bundle:
    (run_dir,) = [p for p in tmp_path.iterdir() if p.is_dir()]
    return read_bundle(run_dir)
