"""P3 parity over vLLM ``/tokenize``; the spend ledger's pricing and runaway guard."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from tests.contract.samples import GEMINI, QWEN, SONNET, call_record
from tests.golden.cases import CASES
from tests.llm.wire import Recorder, counter_clock, set_env

from proxyloop.contract.llm import ModelRef, Usage
from proxyloop.llm.parity import GoldenPrompt, check_parity
from proxyloop.llm.spend import RunawaySpend, SpendLedger
from proxyloop.llm.vllm import VLLMClient
from scripts.sys.llm_smoke import golden_prompts

GOLDENS = [
    GoldenPrompt("a", ({"role": "user", "content": "Hi"},), (1, 2, 3)),
    GoldenPrompt("b", ({"role": "user", "content": "Yo"},), (4, 5)),
]


def _vllm(monkeypatch: Any, wire: Recorder) -> VLLMClient:
    set_env(monkeypatch, "vllm")
    return VLLMClient(QWEN, counter_clock(), transport=wire.transport())


def test_parity_passes_when_every_golden_matches(monkeypatch: Any) -> None:
    wire = Recorder(
        httpx.Response(200, json={"tokens": [1, 2, 3]}),
        httpx.Response(200, json={"tokens": [4, 5]}),
    )
    result = asyncio.run(check_parity(_vllm(monkeypatch, wire), GOLDENS))
    assert result.passed and result.served_model == "Qwen3.5-9B"
    sent = wire.body()
    assert wire.requests[0].url.path == "/tokenize"
    assert sent["chat_template_kwargs"] == {"enable_thinking": False}
    assert sent["add_generation_prompt"] is True
    assert sent["messages"] == [{"role": "user", "content": "Hi"}]


def test_parity_fails_on_one_mismatch(monkeypatch: Any) -> None:
    wire = Recorder(
        httpx.Response(200, json={"tokens": [1, 2, 3]}),
        httpx.Response(200, json={"tokens": [4, 6]}),
    )
    result = asyncio.run(check_parity(_vllm(monkeypatch, wire), GOLDENS))
    assert not result.passed and result.equal == {"a": True, "b": False}


def test_parity_with_no_goldens_does_not_pass(monkeypatch: Any) -> None:
    result = asyncio.run(check_parity(_vllm(monkeypatch, Recorder()), []))
    assert not result.passed


def test_tokenize_error_is_loud(monkeypatch: Any) -> None:
    wire = Recorder(httpx.Response(500, text="boom"))
    with pytest.raises(RuntimeError, match="HTTP 500"):
        asyncio.run(check_parity(_vllm(monkeypatch, wire), GOLDENS))


def test_smoke_goldens_are_the_p2_cases() -> None:
    goldens = golden_prompts()
    assert [g.name for g in goldens] == [c.name for c in CASES]
    for golden in goldens:
        assert [m["role"] for m in golden.messages] == ["system", "user"]
        assert len(golden.ids) > 100


def _record(ref: ModelRef, prompt: int, completion: int, **update: object) -> Any:
    usage = Usage(prompt_tokens=prompt, completion_tokens=completion)
    return call_record(ref, usage=usage, **update)


def test_relay_calls_are_priced_from_the_rate_card() -> None:
    ledger = SpendLedger(projected_episode_micro_usd=1_000_000)
    charge = ledger.charge(_record(SONNET, 1_000, 200, role="slow"))
    assert (charge.basis, charge.micro_usd) == ("tokens", 3_000 + 3_000)
    assert ledger.spend.micro_usd == 6_000 and ledger.spend.by_role == {"slow": 6_000}


@pytest.mark.parametrize(
    ("ref", "basis"),
    [
        (QWEN, "gpu_time"),  # Modal bills the GPU per second, outside the ledger
        (GEMINI, "unpriced"),  # TeamRouter: no measured rate (ADR-0005)
        (SONNET.model_copy(update={"model_id": "gpt-5.4-mini-2026-03-17"}), "unpriced"),
    ],
)
def test_calls_without_a_token_rate_are_never_priced_at_zero(
    ref: ModelRef, basis: str
) -> None:
    ledger = SpendLedger(projected_episode_micro_usd=1_000)
    charge = ledger.charge(_record(ref, 5_000, 500, requested_model=ref.model_id))
    assert (charge.basis, charge.micro_usd) == (basis, None)
    assert ledger.spend.micro_usd == 0
    assert ledger.unpriced_calls == (basis == "unpriced")


def test_failed_call_without_usage_is_unpriced() -> None:
    ledger = SpendLedger(projected_episode_micro_usd=1_000)
    failed = call_record(SONNET, usage=None, error="HTTP 503", response_sha=None)
    assert ledger.charge(failed).basis == "unpriced"


def test_runaway_guard_raises_past_10x_the_projection() -> None:
    ledger = SpendLedger(projected_episode_micro_usd=1_000)  # limit 10,000 micro-USD
    ledger.charge(_record(SONNET, 2_000, 0))  # 6,000
    ledger.charge(_record(SONNET, 1_000, 0))  # 9,000
    with pytest.raises(RunawaySpend, match="10x") as caught:
        ledger.charge(_record(SONNET, 1_000, 0, call_id="k9"))  # 12,000
    assert caught.value.charge.call_id == "k9"
    assert ledger.spend.micro_usd == 12_000  # the crossing charge is kept


def test_projection_must_be_positive() -> None:
    with pytest.raises(ValueError):
        SpendLedger(projected_episode_micro_usd=0)
