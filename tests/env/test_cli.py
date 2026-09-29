"""The CLI's live config (model selection, per-role efforts) and the fast_cp
redirect of the dead-endpoint smoke (S0-SYS-08)."""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest
from tests.support.manual_clock import ScaledClock
from tests.support.sessions import act, clients, ear, fake_config, patient_task, reply

from proxyloop import cli
from proxyloop.contract.bundle import read_bundle
from proxyloop.contract.llm import (
    AdapterKind,
    ChatMessage,
    LLMClient,
    LLMRole,
    LLMUnavailable,
    ModelRef,
    ToolRequest,
    ToolSpec,
)
from proxyloop.kernel.session import run_session
from proxyloop.llm.factory import make_client
from proxyloop.llm.http import RecordSink
from proxyloop.llm.relay import ChatClient

REAL = AdapterKind.REAL_HTTP


def _cfg(*argv: str) -> Any:
    args = cli.build_parser().parse_args(["session", "--family", "f", *argv])
    return cli.live_config(args)


def test_the_defaults_keep_todays_models() -> None:
    cfg = _cfg()
    fast = ModelRef(kind=REAL, endpoint="vllm", model_id="Qwen3.5-9B")
    assert cfg.fast_user == cfg.fast_cp == fast  # no effort: vLLM keeps its own
    assert cfg.slow == ModelRef(
        kind=REAL, endpoint="relay", model_id="claude-sonnet-5"
    )  # reasoning_effort None: the default cfg_hash is unchanged
    world = ModelRef(
        kind=REAL, endpoint="openrouter", model_id=cli.WORLD, reasoning_effort="low"
    )  # S1-SYS-96
    assert cfg.world.ear == cfg.world.mouth == cfg.world.simuser == world
    assert cfg.live


def test_the_fast_and_slow_models_are_chosen_by_id_and_endpoint() -> None:
    cfg = _cfg(
        *("--fast-model", "gpt-6-luna", "--fast-endpoint", "teamrouter"),
        *("--slow-model", "gemini-3.8-flash", "--slow-endpoint", "teamrouter"),
        *("--slow-effort", "medium"),
    )
    assert cfg.fast_user == cfg.fast_cp
    assert cfg.fast_cp == ModelRef(
        kind=REAL, endpoint="teamrouter", model_id="gpt-6-luna", reasoning_effort="low"
    )  # a hosted Fast pins the provisional effort
    assert cfg.slow == ModelRef(
        kind=REAL,
        endpoint="teamrouter",
        model_id="gemini-3.8-flash",
        reasoning_effort="medium",
    )
    hosted = _cfg("--fast-endpoint", "relay", "--fast-effort", "minimal")
    assert hosted.fast_cp.reasoning_effort == "minimal"


def test_an_openrouter_fast_builds_a_chat_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # S1-SYS-20: FAST_ENDPOINT=openrouter FAST=openai/gpt-6-luna
    cfg = _cfg("--fast-model", "openai/gpt-6-luna", "--fast-endpoint", "openrouter")
    assert (
        cfg.fast_user
        == cfg.fast_cp
        == ModelRef(
            kind=REAL,
            endpoint="openrouter",
            model_id="openai/gpt-6-luna",
            reasoning_effort="none",  # user decision 2026-09-27 (S1-SYS-26)
        )
    )
    chosen = _cfg("--fast-endpoint", "openrouter", "--fast-effort", "low").fast_cp
    assert chosen.reasoning_effort == "low"  # an explicit effort still wins
    monkeypatch.setenv("PL_OPENROUTER_BASE_URL", "https://openrouter.test/api")
    monkeypatch.setenv("PL_OPENROUTER_API_KEY", "sekrit")
    client = make_client(cfg.fast_cp, live=True, clock=lambda: 0, on_record=print)
    assert isinstance(client, ChatClient) and client.ref == cfg.fast_cp


def test_a_teamrouter_slow_pins_the_provisional_effort() -> None:
    cfg = _cfg("--slow-model", "gemini-3.8-flash", "--slow-endpoint", "teamrouter")
    assert cfg.slow == ModelRef(
        kind=REAL,
        endpoint="teamrouter",
        model_id="gemini-3.8-flash",
        reasoning_effort="low",
    )
    relay = _cfg("--slow-effort", "high")  # an explicit override on the relay
    assert relay.slow.reasoning_effort == "high"


def test_an_openrouter_gemini_slow_pins_the_provisional_effort() -> None:  # S1-SYS-96
    gemini = (
        *("--slow-model", "google/gemini-3.8-flash", "--slow-endpoint", "openrouter"),
    )
    assert _cfg(*gemini).slow == ModelRef(
        kind=REAL,
        endpoint="openrouter",
        model_id="google/gemini-3.8-flash",
        reasoning_effort="low",
    )
    assert _cfg(*gemini, "--slow-effort", "high").slow.reasoning_effort == "high"
    other = _cfg("--slow-model", "openai/gpt-6-luna", "--slow-endpoint", "openrouter")
    assert other.slow.reasoning_effort is None  # only a Gemini Slow is pinned
    assert _cfg().slow.reasoning_effort is None  # the CLI's Slow default is unchanged


def test_each_world_role_takes_its_own_effort() -> None:
    cfg = _cfg("--world-effort", "medium", "--ear-effort", "minimal")
    world = (cfg.world.ear, cfg.world.mouth, cfg.world.simuser)
    efforts = [r.reasoning_effort for r in world]
    assert efforts == ["minimal", "medium", "medium"]


def test_a_vllm_fast_refuses_an_effort() -> None:
    with pytest.raises(SystemExit):
        cli.main(["session", "--family", "f", "--fast-effort", "low"])


def test_a_redirect_never_makes_a_claim_bundle(
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = ["session", "--family", "f", "--fast-cp-base-url", "http://127.0.0.1:9"]
    with pytest.raises(SystemExit) as exit_:
        cli.main([*argv, "--claim"])
    assert exit_.value.code == 2
    assert "never with --claim" in capsys.readouterr().err


def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for endpoint in ("RELAY", "VLLM"):
        monkeypatch.setenv(f"PL_{endpoint}_BASE_URL", "https://real.example")
        monkeypatch.setenv(f"PL_{endpoint}_API_KEY", "sekrit")


def test_a_redirected_client_goes_to_the_new_root_without_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch)
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(503, text="down")

    ref = ModelRef(kind=REAL, endpoint="relay", model_id="m")
    client = make_client(
        ref,
        live=True,
        clock=lambda: 0,
        on_record=lambda r: None,
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:9",
    )
    tool = ToolSpec(name="t", description="d", parameters={"type": "object"})
    request = ToolRequest(
        call_id="c",
        role="fast_cp",
        messages=(ChatMessage(role="user", content="hi"),),
        tools=(tool,),
        max_tokens=8,
        temperature=0,
    )
    with pytest.raises(LLMUnavailable):
        asyncio.run(client.chat_tools(request))
    (req,) = sent
    assert str(req.url) == "http://127.0.0.1:9/v1/chat/completions"
    assert req.headers["Host"] == "127.0.0.1:9"
    assert "Authorization" not in req.headers


@pytest.mark.parametrize(
    "bad", ["http://127.0.0.1:9/v1", "127.0.0.1:9", "http://h?q=1"]
)
def test_a_redirect_is_a_server_root(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    _env(monkeypatch)
    ref = ModelRef(kind=REAL, endpoint="relay", model_id="m")
    with pytest.raises(ValueError, match="server root"):
        make_client(ref, live=True, clock=lambda: 0, on_record=print, base_url=bad)


def test_only_fast_cp_is_redirected(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str | None] = {}

    def spy(ref: ModelRef, **kw: Any) -> str:
        seen[ref.model_id] = kw["base_url"]
        return "client"

    monkeypatch.setattr(cli, "make_client", spy)
    make = cli.redirect_fast_cp("http://127.0.0.1:9", ScaledClock())
    roles: tuple[LLMRole, ...] = ("fast_user", "fast_cp", "slow", "ear")
    for role in roles:
        make(role, ModelRef(kind=REAL, endpoint="relay", model_id=role), print)
    assert seen == {
        "fast_user": None,
        "fast_cp": "http://127.0.0.1:9",
        "slow": None,
        "ear": None,
    }


SCRIPTS = {
    "simuser": [reply("Please get me a lower price.")],
    "fast_user": ["Sure, I will call them now."],
    "ear": [ear("other")],
    "mouth": ["Northwind Mobile, how can I help?"],
    "slow": [act("Waiting for the call.", {"tool": "wait", "seconds": 5})],
}


def test_a_dead_fast_cp_endpoint_ends_the_session_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch)
    with socket.socket() as sock:  # a real closed port: connection refused
        sock.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{sock.getsockname()[1]}"
    hosted = ModelRef(kind=REAL, endpoint="relay", model_id="hosted-fast")
    cfg = fake_config().model_copy(update={"fast_cp": hosted})
    clock = ScaledClock(100)
    fakes = clients(SCRIPTS, clock, (), {})
    redirected = cli.redirect_fast_cp(dead, clock)

    def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
        return (redirected if role == "fast_cp" else fakes)(role, ref, sink)

    session = run_session(
        cfg,
        patient_task(),
        runs_dir=tmp_path,
        clock=clock,
        sleep=clock.sleep,
        clients=make,
    )
    with pytest.raises(LLMUnavailable):
        asyncio.run(asyncio.wait_for(session, timeout=30))
    (run_dir,) = [p for p in tmp_path.iterdir() if p.is_dir()]
    events = read_bundle(run_dir).events
    assert events[-1].type == "session.ended"
    assert events[-1].payload["reason"] == "llm_unavailable"
    failed = [e for e in events if e.type == "llm.call" and e.payload["error"]]
    assert failed and {e.payload["role"] for e in failed} == {"fast_cp"}
    assert all(e.actor == "fast.cp" for e in failed)
    assert json.dumps([e.payload for e in failed]).count("sekrit") == 0
