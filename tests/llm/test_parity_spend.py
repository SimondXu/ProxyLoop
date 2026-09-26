"""P3 parity over vLLM ``/tokenize``; the spend ledger's pricing and runaway guard."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from tests.contract.samples import GEMINI, QWEN, SONNET, call_record
from tests.golden.cases import CASES
from tests.golden.tokenizer import encode, load_tokenizer
from tests.llm.wire import Recorder, counter_clock, set_env

from proxyloop.contract.llm import ModelRef, Usage
from proxyloop.llm.parity import GoldenPrompt, check_parity
from proxyloop.llm.spend import RunawaySpend, SpendLedger
from proxyloop.llm.vllm import VLLMClient
from scripts.sys.llm_smoke import golden_prompts

GOLDENS = [
    GoldenPrompt("a", ({"role": "user", "content": "Hi"},), "<p>Hi", (1, 2, 3)),
    GoldenPrompt("b", ({"role": "user", "content": "Yo"},), "<p>Yo", (4, 5)),
]


def _ids(*ids: int) -> httpx.Response:
    return httpx.Response(200, json={"tokens": list(ids)})


def _vllm(monkeypatch: Any, wire: Recorder) -> VLLMClient:
    set_env(monkeypatch, "vllm")
    return VLLMClient(QWEN, counter_clock(), print, wire.transport())


def test_parity_passes_when_every_golden_matches(monkeypatch: Any) -> None:
    wire = Recorder(_ids(1, 2, 3), _ids(1, 2, 3), _ids(4, 5), _ids(4, 5))
    result = asyncio.run(check_parity(_vllm(monkeypatch, wire), GOLDENS))
    assert result.passed and result.requested_model == "Qwen3.5-9B"
    chat, prompt = wire.body(0), wire.body(1)
    assert {r.url.path for r in wire.requests} == {"/tokenize"}
    assert chat["chat_template_kwargs"] == {"enable_thinking": False}
    assert chat["add_generation_prompt"] is True
    assert chat["messages"] == [{"role": "user", "content": "Hi"}]
    assert prompt == {
        "model": "Qwen3.5-9B",
        "prompt": "<p>Hi",
        "add_special_tokens": False,
    }


@pytest.mark.parametrize(
    "responses",
    [
        (_ids(1, 2, 3), _ids(1, 2, 3), _ids(4, 6), _ids(4, 5)),  # chat template path
        (_ids(1, 2, 3), _ids(1, 2, 3), _ids(4, 5), _ids(9, 4, 5)),
    ],  # the prompt sent
    ids=["messages", "prompt"],
)
def test_parity_fails_on_one_mismatch(monkeypatch: Any, responses: Any) -> None:
    wire = Recorder(*responses)
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
    goldens = golden_prompts(load_tokenizer())
    assert [g.name for g in goldens] == [c.name for c in CASES]
    for golden in goldens:
        assert [m["role"] for m in golden.messages] == ["system", "user"]
        assert tuple(encode(golden.prompt)) == golden.ids  # P2 on the prompt sent


def _record(ref: ModelRef, prompt: int, completion: int, **update: object) -> Any:
    usage = Usage(prompt_tokens=prompt, completion_tokens=completion)
    return call_record(ref, usage=usage, **update)


def test_relay_calls_are_priced_from_the_rate_card() -> None:
    ledger = SpendLedger(projected_episode_micro_usd=1_000_000, projected_calls=50)
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
    ledger = SpendLedger(projected_episode_micro_usd=1_000, projected_calls=50)
    charge = ledger.charge(_record(ref, 5_000, 500, requested_model=ref.model_id))
    assert (charge.basis, charge.micro_usd) == (basis, None)
    assert ledger.spend.micro_usd == 0
    assert ledger.unpriced_calls == (basis == "unpriced")


def test_failed_call_without_usage_is_unpriced() -> None:
    ledger = SpendLedger(projected_episode_micro_usd=1_000, projected_calls=50)
    failed = call_record(SONNET, usage=None, error="HTTP 503", response_sha=None)
    assert ledger.charge(failed).basis == "unpriced"


def test_runaway_guard_raises_past_10x_the_projection() -> None:
    ledger = SpendLedger(
        projected_episode_micro_usd=1_000, projected_calls=50
    )  # limit 10,000 micro-USD
    ledger.charge(_record(SONNET, 2_000, 0))  # 6,000
    ledger.charge(_record(SONNET, 1_000, 0))  # 9,000
    with pytest.raises(RunawaySpend, match="runaway spend") as caught:
        ledger.charge(_record(SONNET, 1_000, 0, call_id="k9"))  # 12,000
    assert caught.value.charge.call_id == "k9"
    assert ledger.spend.micro_usd == 12_000  # the crossing charge is kept


def test_unpriced_call_guard_raises_past_10x_the_projected_calls() -> None:
    ledger = SpendLedger(projected_episode_micro_usd=1_000, projected_calls=2)
    for k in range(20):  # limit: 20 unpriced calls
        ledger.charge(_record(GEMINI, 5_000, 500, call_id=f"w{k}"))
    ledger.charge(_record(QWEN, 5_000, 500))  # gpu_time: not an unpriced call
    with pytest.raises(RunawaySpend, match="runaway calls") as caught:
        ledger.charge(_record(GEMINI, 5_000, 500, call_id="w20"))
    assert caught.value.charge.call_id == "w20" and ledger.unpriced_calls == 21


@pytest.mark.parametrize(("cost", "calls"), [(0, 5), (1_000, 0)])
def test_projections_must_be_positive(cost: int, calls: int) -> None:
    with pytest.raises(ValueError):
        SpendLedger(projected_episode_micro_usd=cost, projected_calls=calls)
