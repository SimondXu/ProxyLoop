"""Test doubles for ``scripts/mod/probe_roles.py`` (S0-ROOT-12).

``write_probe_bundle`` writes a small synthetic run bundle with recorded Slow,
Ear and Fast requests in the shapes a real run stores them. ``FakeTeamRouter`` is
an ``httpx.MockTransport`` speaking the OpenAI-compatible chat wire, so the probe
runs through the real ``make_client`` adapters with no network.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from tests.contract.samples import SONNET, session_config
from tests.golden.cases import CASES

from proxyloop.contract import CONTRACT_VERSION
from proxyloop.contract.base import canonical_json, sha256_text
from proxyloop.contract.bundle import (
    EVENTS,
    MANIFEST,
    PROMPTS,
    Manifest,
    PromptRecord,
    RoleModel,
)
from proxyloop.contract.config import config_hash
from proxyloop.contract.events import Event
from proxyloop.contract.llm import (
    ChatMessage,
    LLMCallRecord,
    LLMRole,
    ModelRef,
    ToolRequest,
    ToolSpec,
    Usage,
    request_content,
)
from proxyloop.contract.state import Spend
from proxyloop.slow import prompt as slow_prompt

Json = dict[str, Any]
RUN_ID = "run-probe"
KEY = "sk-probe-secret"
PROFILES = ("pl_user_v1", "pl_cp_v1")
HEARD = "Is there a better price? My name is Dana Reyes."
RECORDED_USAGE = Usage(prompt_tokens=1000, completion_tokens=50, reasoning_tokens=10)
CLASSIFY = ToolSpec(
    name="classify",
    description="The act.",
    parameters={
        "type": "object",
        "properties": {
            "act": {
                "type": "string",
                "enum": ["ask_discount", "provide_fact", "other"],
            },
            "offer_ref": {"type": "string", "enum": ["o1"]},
            "price_usd": {"type": "number"},
            "value": {"type": "string"},
            "key": {"type": "string", "enum": ["account.holder_name", "account.last4"]},
        },
        "required": ["act"],
        "additionalProperties": False,
    },
)


def set_env(monkeypatch: Any) -> None:
    monkeypatch.setenv("PL_TEAMROUTER_BASE_URL", "https://tr.test")
    monkeypatch.setenv("PL_TEAMROUTER_API_KEY", KEY)


class _Log:
    def __init__(self) -> None:
        self.events: list[Event] = []
        self.prompts: dict[str, PromptRecord] = {}

    def store(self, kind: str, content: str) -> str:
        sha = sha256_text(content)
        self.prompts[sha] = PromptRecord.model_validate(
            {"sha": sha, "kind": kind, "content": content}
        )
        return sha

    def emit(
        self, type_: str, actor: str, payload: Json, causes: tuple[str, ...] = ()
    ) -> str:
        seq = len(self.events)
        stream = "world" if actor.startswith("world.") else "agent"
        self.events.append(
            Event.model_validate(
                {
                    "run_id": RUN_ID,
                    "seq": seq,
                    "event_id": f"{RUN_ID}:{seq}",
                    "t_ms": 1000 * seq,
                    "wall": datetime(2026, 9, 26, tzinfo=UTC),
                    "type": type_,
                    "actor": actor,
                    "stream": stream,
                    "cause_ids": causes,
                    "epoch": 0,
                    "payload": payload,
                }
            )
        )
        return f"{RUN_ID}:{seq}"

    def call(self, call_id: str, role: LLMRole, prompt_sha: str, cause: str) -> None:
        ref = ModelRef.model_validate(SONNET.model_dump() | {"model_id": "recorded"})
        record = LLMCallRecord(
            call_id=call_id,
            role=role,
            model_ref=ref,
            adapter_kind=ref.kind,
            requested_model=ref.model_id,
            served_model_echo=ref.model_id,
            request_id="rec",
            prompt_sha=prompt_sha,
            response_sha=None,
            usage=RECORDED_USAGE,
            t_start=0,
            t_first_token=None,
            t_end=1,
            finish_reason="stop",
            attempt=0,
        )
        actor = "world.ear" if role == "ear" else role.replace("_", ".")
        self.emit("llm.call", actor, record.model_dump(mode="json"), (cause,))


LANE_CASES = [next(c for c in CASES if c.profile == p) for p in PROFILES]


def write_probe_bundle(run_dir: Path, n: int = 4) -> Path:
    """``n`` Slow steps, ``n`` Ear requests and ``n`` Fast requests per lane."""

    log = _Log()
    for i in range(n):
        started = log.emit(
            "slow.step.started", "slow", {"basis_seq": 0, "wake_reasons": []}
        )
        system = ChatMessage(role="system", content=slow_prompt.SYSTEM)
        note = ChatMessage(role="user", content=f"[WAKE] relay {i}")
        slow = ToolRequest(
            call_id=f"slow:{i + 1}",
            role="slow",
            messages=(system, note),
            tools=(slow_prompt.ACT,),
            tool_choice="act",
            max_tokens=slow_prompt.MAX_TOKENS,
        )
        log.call(
            slow.call_id, "slow", log.store("messages", request_content(slow)), started
        )

        said = log.emit(
            "utt.final",
            "kernel",
            {"lane": "cp", "speaker": "agent", "utt_id": f"a{i}", "text": HEARD},
        )
        heard = {"lane": "cp", "utt_id": f"a{i}", "text_generated": HEARD}
        heard |= {"text_heard": HEARD, "interrupted": False}
        delivered = log.emit("utt.delivered", "kernel", heard, (said,))
        ear = ToolRequest(
            call_id=f"ear:{delivered}:0",
            role="ear",
            messages=(ChatMessage(role="user", content=f"The caller said: {HEARD}"),),
            tools=(CLASSIFY,),
            tool_choice="classify",
            max_tokens=512,
            temperature=0,
        )
        log.call(
            ear.call_id, "ear", log.store("messages", request_content(ear)), delivered
        )

        for case in LANE_CASES:
            view = case.view()
            lane = view.lane
            asked = {
                "lane": lane,
                "gen_id": f"{lane}-g{i + 1}",
                "trigger": view.trigger.kind,
            }
            asked |= {
                "view_sha": log.store(
                    "view", canonical_json(view.model_dump(mode="json"))
                )
            }
            asked |= {"prompt_sha": "unused", "profile": case.profile, "basis_seq": 0}
            asked |= {"model_ref": SONNET.model_dump(mode="json")}
            ask = log.emit("fast.request", f"fast.{lane}", asked)
            role: LLMRole = "fast_user" if lane == "user" else "fast_cp"
            log.call(f"{role}:{i + 1}", role, "unused", ask)

    run_dir.mkdir(parents=True, exist_ok=True)
    events = "".join(e.model_dump_json(by_alias=True) + "\n" for e in log.events)
    (run_dir / EVENTS).write_text(events, "utf-8")
    prompts = "".join(p.model_dump_json() + "\n" for p in log.prompts.values())
    (run_dir / PROMPTS).write_text(prompts, "utf-8")
    cfg = session_config()
    manifest = Manifest(
        run_id=RUN_ID,
        git_sha="test",
        contract_version=CONTRACT_VERSION,
        cfg=cfg,
        cfg_hash=config_hash(cfg),
        task_ref="cp-direct-discount@1",
        instance_hash="i1",
        split="train",
        fingerprints={},
        models={"slow": RoleModel(ref=SONNET)},
        p3="not_applicable",
        reality={"slow": SONNET.kind},
        spend=Spend(),
    )
    (run_dir / MANIFEST).write_text(manifest.model_dump_json(), "utf-8")
    return run_dir


ToolAnswer = Callable[[Json], list[tuple[str, str]]]  # body -> [(name, arguments)]


@dataclass
class FakeTeamRouter:
    """Answers tool calls with ``tools(body)`` and streams with ``text``; any
    ``status(body)`` other than 200 is returned as an error body."""

    tools: ToolAnswer = lambda body: []
    text: str = "Sure, one moment."
    status: Callable[[Json], int] = lambda body: 200
    requests: list[Json] = field(default_factory=list[Json])

    def usage(self, body: Json) -> Json:
        reasoning = 0 if body.get("reasoning_effort") == "none" else 7
        details = {"reasoning_tokens": reasoning}
        return {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "completion_tokens_details": details,
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body: Json = json.loads(request.content)
        self.requests.append(body)
        n, model = len(self.requests), body["model"]
        headers = {"x-request-id": f"req-{n}"}
        if (status := self.status(body)) != 200:
            return httpx.Response(status, text=f"unsupported parameter {n}")
        if not body.get("stream"):
            calls = [
                {
                    "id": f"c{n}.{i}",
                    "type": "function",
                    "function": {"name": name, "arguments": args},
                }
                for i, (name, args) in enumerate(self.tools(body))
            ]
            message = {"role": "assistant", "content": "", "tool_calls": calls}
            choice = {"index": 0, "message": message, "finish_reason": "tool_calls"}
            out = {
                "id": f"r{n}",
                "model": model,
                "choices": [choice],
                "usage": self.usage(body),
            }
            return httpx.Response(200, json=out, headers=headers)
        half = len(self.text) // 2
        chunks: list[Json] = [
            {"choices": [{"index": 0, "delta": {"content": part}}]}
            for part in (self.text[:half], self.text[half:])
        ]
        chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        chunks.append({"choices": [], "usage": self.usage(body)})
        lines = [
            f"data: {json.dumps({'id': f'r{n}', 'model': model} | c)}" for c in chunks
        ]
        sse = "\n\n".join([*lines, "data: [DONE]"]) + "\n\n"
        return httpx.Response(200, text=sse, headers=headers)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)
