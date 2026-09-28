"""Whole sessions from fakes: a ``test_fake`` config, scripted clients for every
role (through the kernel's record sink, as a real adapter), the S0 family with
slow patience, and a scripted person. A role's ``gate`` is awaited before each
of its streamed calls: a test holds a generation open while partner lines land.
Tests only (I8)."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import httpx
from tests.support.fakes import RepeatingLLM
from tests.support.manual_clock import ScaledClock

from proxyloop.contract.bundle import Bundle, read_bundle
from proxyloop.contract.config import Sampling, SessionConfig, WorldModels
from proxyloop.contract.llm import (
    AdapterKind,
    LLMCallRecord,
    LLMClient,
    LLMRole,
    ModelRef,
    TextRequest,
    ToolRequest,
    ToolResponse,
)
from proxyloop.contract.protocol import EMPTY_THINK
from proxyloop.env.tasks.loader import load_task
from proxyloop.env.tasks.schema import Task
from proxyloop.kernel.channels import Channel, Incoming
from proxyloop.kernel.session import ChannelSpec, ClientFactory, RunResult, run_session
from proxyloop.llm.factory import make_client
from proxyloop.llm.http import RecordSink

Scripts = Mapping[str, Sequence[str]]
Until = Mapping[str, tuple[str, str]]  # role -> (marker, response)
Gates = Mapping[str, Callable[[], Awaitable[None]]]  # role -> awaited per stream


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
    """An Ear ``classify`` call with one act: a block of one utterance."""
    return ears({"act": act} | args)


def ears(*items: Mapping[str, object]) -> str:
    """An Ear ``classify`` call for a heard block: one act per utterance."""
    call = {
        "call_id": "t",
        "name": "classify",
        "arguments": json.dumps({"acts": [dict(item) for item in items]}),
    }
    return json.dumps({"text": "", "tool_calls": [call]})


_UTTERANCE = re.compile(r"^\d+\. ", re.M)  # a numbered line of the Ear's prompt


def _acts(raw: str) -> list[object] | None:
    """The acts of a scripted single ``classify`` call; None: any other answer."""
    calls = json.loads(raw)["tool_calls"]
    if len(calls) != 1 or calls[0]["name"] != "classify":
        return None
    try:
        args: object = json.loads(calls[0]["arguments"])
    except json.JSONDecodeError:
        return None
    acts = cast(dict[str, object], args).get("acts") if isinstance(args, dict) else None
    return cast(list[object], acts) if isinstance(acts, list) else None


class BlockEar(RepeatingLLM):
    """The Ear's script, one act per heard utterance whatever the blocks
    (ADR-0021): a request listing n utterances takes scripted answers until
    they hold n acts, and answers them as one ``classify`` call. Any other
    scripted answer (an invalid one) is given as it is."""

    async def _next(self, request: TextRequest | ToolRequest) -> tuple[str, int]:
        raw, start = await super()._next(request)
        acts, want = _acts(raw), len(_UTTERANCE.findall(request.messages[-1].content))
        if acts is None:
            return raw, start
        while len(acts) < want and (more := _acts((await super()._next(request))[0])):
            acts += more
        return ears(*cast(list[Mapping[str, object]], acts)), start


def act(private: str, *calls: Mapping[str, object], public: str | None = None) -> str:
    body: dict[str, object] = {"private_summary": private, "calls": list(calls)}
    if public is not None:
        body["public_summary"] = public
    call = {"call_id": "a", "name": "act", "arguments": json.dumps(body)}
    return json.dumps({"text": "", "tool_calls": [call]})


class Gated:
    """A client whose streamed calls first await ``gate`` (a controllable hang)."""

    def __init__(self, inner: LLMClient, gate: Callable[[], Awaitable[None]]) -> None:
        self._inner, self._gate = inner, gate

    @property
    def ref(self) -> ModelRef:
        return self._inner.ref

    async def stream_text(
        self, request: TextRequest
    ) -> AsyncIterator[str | LLMCallRecord]:
        await self._gate()
        async for item in self._inner.stream_text(request):
            yield item

    async def chat_tools(self, request: ToolRequest) -> ToolResponse:
        return await self._inner.chat_tools(request)


def clients(
    scripts: Scripts,
    clock: ScaledClock,
    dead: Sequence[str],
    until: Until,
    vllm: httpx.MockTransport | None = None,
    gates: Gates | None = None,
) -> ClientFactory:
    """Each role answers from its script (the last answer repeats); a vLLM ref
    gets the real adapter over the ``vllm`` transport double."""

    def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
        if ref.endpoint == "vllm":
            now = clock.monotonic_ms
            return make_client(
                ref, live=False, clock=now, on_record=sink, transport=vllm
            )
        script, stop = scripts.get(role, ["unused"]), until.get(role)
        scripted = BlockEar if role == "ear" else RepeatingLLM
        client = scripted(ref, script, clock, role in dead, sink, stop)
        gate = (gates or {}).get(role)
        return client if gate is None else Gated(client, gate)

    return make


class FakeTokenizer:
    """A chat template whose ids are a function of the text (P3 doubles)."""

    @staticmethod
    def ids(text: str) -> list[int]:
        return [len(text), *map(ord, text[-40:])]

    def apply_chat_template(
        self, conversation: list[dict[str, str]], /, **kwargs: Any
    ) -> Any:
        text = "".join(f"<{m['role']}>{m['content']}" for m in conversation)
        text += EMPTY_THINK
        return {"input_ids": self.ids(text)} if kwargs.get("tokenize") else text


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
    vllm: httpx.MockTransport | None = None,
    task: Task | None = None,
    gates: Gates | None = None,
) -> RunResult:
    clock = ScaledClock(100)
    session = run_session(
        cfg or fake_config(),
        task or patient_task(),
        channels,
        runs_dir=tmp_path,
        clock=clock,
        sleep=clock.sleep,
        clients=clients(scripts, clock, dead, until or {}, vllm, gates),
        tokenizer=FakeTokenizer() if vllm else None,
    )
    return asyncio.run(asyncio.wait_for(session, timeout=30))


def only_bundle(tmp_path: Path) -> Bundle:
    (run_dir,) = [p for p in tmp_path.iterdir() if p.is_dir()]
    return read_bundle(run_dir)
