"""P3 and /pl/attest at session start (ARCHITECTURE §12, §13), over transport
doubles: the vLLM adapter is the real one, the tokenizer a deterministic fake."""

from __future__ import annotations

import asyncio
import itertools
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from tests.contract.samples import QWEN
from tests.kernel.test_session import SCRIPTS, UNTIL
from tests.llm.wire import completion_chunks, set_env, sse
from tests.support.sessions import FakeTokenizer, fake_config, only_bundle, run

from proxyloop.contract.config import SessionConfig
from proxyloop.contract.state import Blackboard
from proxyloop.contract.views import Trigger, view_cp
from proxyloop.evidence.check import check_path
from proxyloop.kernel.lanes import p3
from proxyloop.llm.factory import make_client
from proxyloop.llm.vllm import VLLMClient

ATTEST = {
    "schema": "pl.attest/1",
    "shards": {"model-00001.safetensors": "a" * 64},
    "tokenizer": {"tokenizer.json": "b" * 64},
    "adapters": {"Qwen3.5-9B-zero": {"adapter_model.safetensors": "c" * 64}},
}
REPLY = ["Could you lower the price?", "\n@slow: fact monthly_price=75.00"]


def vllm(broken: bool = False) -> httpx.MockTransport:
    """vLLM's /tokenize, /pl/attest and /v1/completions; ``broken``: the served
    template disagrees with the pinned one on the pre-rendered prompt."""
    tok, ids = FakeTokenizer(), itertools.count()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/pl/attest":
            return httpx.Response(200, json=ATTEST)
        if request.url.path == "/tokenize":
            body: dict[str, Any] = json.loads(request.content)
            chat = body.get("messages")
            text = tok.apply_chat_template(chat) if chat else body["prompt"]
            tokens = tok.ids(text) + ([0] if broken and not chat else [])
            return httpx.Response(200, json={"tokens": tokens})
        chunks = completion_chunks(QWEN, REPLY)
        for chunk in chunks:  # one request id per call
            chunk["id"] = f"cmpl-{next(ids)}"
        return httpx.Response(200, content=sse(*chunks))

    return httpx.MockTransport(handle)


def _check(broken: bool) -> bool:
    client = make_client(
        QWEN, live=False, clock=lambda: 0, on_record=print, transport=vllm(broken)
    )
    assert isinstance(client, VLLMClient)
    view = view_cp(Blackboard(), Trigger(kind="call_connected"), "Ask for a discount.")
    return asyncio.run(p3(client, view, FakeTokenizer()))


def test_p3_passes_when_both_tokenize_paths_equal_the_pinned_ids(
    monkeypatch: Any,
) -> None:
    set_env(monkeypatch, "vllm")
    assert _check(broken=False)


def test_p3_fails_when_the_served_ids_differ(monkeypatch: Any) -> None:
    set_env(monkeypatch, "vllm")
    assert not _check(broken=True)


def _vllm_cp() -> SessionConfig:
    return SessionConfig.model_validate(fake_config().model_dump() | {"fast_cp": QWEN})


def test_a_session_refuses_to_start_on_a_p3_mismatch(
    tmp_path: Path, monkeypatch: Any
) -> None:
    set_env(monkeypatch, "vllm")
    with pytest.raises(RuntimeError, match="P3"):
        run(tmp_path, SCRIPTS, cfg=_vllm_cp(), vllm=vllm(broken=True))
    bundle = only_bundle(tmp_path)
    assert [e.type for e in bundle.events] == ["session.started", "session.ended"]
    assert bundle.events[0].payload["parity"] == "fail"
    assert bundle.events[-1].payload["reason"] == "p3_failed"  # never a claim reason
    assert bundle.manifest.p3 == "fail"
    assert check_path(next(tmp_path.iterdir()), "offline").ok


def test_a_session_on_vllm_records_p3_pass_and_the_attestation(
    tmp_path: Path, monkeypatch: Any
) -> None:
    set_env(monkeypatch, "vllm")
    result = run(tmp_path, SCRIPTS, cfg=_vllm_cp(), until=UNTIL, vllm=vllm())
    assert result.reason == "info_only"
    bundle = only_bundle(tmp_path)
    assert bundle.manifest.p3 == "pass"
    assert bundle.manifest.attestation == {
        "shards/model-00001.safetensors": "a" * 64,
        "tokenizer/tokenizer.json": "b" * 64,
        "adapters/Qwen3.5-9B-zero/adapter_model.safetensors": "c" * 64,
    }
    assert bundle.events[0].payload["attest"] == ATTEST
    calls = [
        e
        for e in bundle.events
        if e.type == "llm.call" and e.payload["role"] == "fast_cp"
    ]
    assert calls and all(e.payload["adapter_kind"] == "real_http" for e in calls)
    report = check_path(result.path, "offline")
    assert report.ok, report.failures


def test_p3_is_not_applicable_without_a_vllm_role(tmp_path: Path) -> None:
    run(tmp_path, SCRIPTS, until=UNTIL)
    bundle = only_bundle(tmp_path)
    assert (
        bundle.manifest.p3 == "not_applicable" and bundle.manifest.attestation is None
    )
    assert bundle.events[0].payload["parity"] == "not_applicable"


def test_a_dead_vllm_at_start_ends_with_llm_unavailable(
    tmp_path: Path, monkeypatch: Any
) -> None:
    set_env(monkeypatch, "vllm")

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(httpx.ConnectError):
        run(tmp_path, SCRIPTS, cfg=_vllm_cp(), vllm=httpx.MockTransport(refuse))
    events = only_bundle(tmp_path).events
    assert events[-1].payload["reason"] == "llm_unavailable"
    assert not [e for e in events if e.type == "utt.delivered"]
