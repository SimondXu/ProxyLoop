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
from proxyloop.llm.spend import (
    RUNAWAY_FACTOR,
    SESSION_CAP_MICRO_USD,
    Rate,
    RunawaySpend,
    SpendLedger,
)
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


def _ledger(tokens: int = 10**9, calls: int = 50, **kw: Any) -> SpendLedger:
    return SpendLedger(projected_tokens=tokens, projected_calls=calls, **kw)


def test_relay_calls_are_priced_from_the_rate_card() -> None:
    ledger = _ledger()
    charge = ledger.charge(_record(SONNET, 1_000, 200, role="slow"))
    assert (charge.basis, charge.micro_usd) == ("tokens", 3_000 + 3_000)
    assert ledger.spend.micro_usd == 6_000 and ledger.spend.by_role == {"slow": 6_000}


@pytest.mark.parametrize(
    ("ref", "basis"),
    [
        (QWEN, "gpu_time"),  # Modal bills the GPU per second, outside the ledger
        (GEMINI, "unpriced"),  # TeamRouter: no measured rate yet (S0-ROOT-12)
        (SONNET.model_copy(update={"model_id": "gpt-5.4-mini-2026-03-17"}), "unpriced"),
    ],
)
def test_calls_without_a_token_rate_are_never_priced_at_zero(
    ref: ModelRef, basis: str
) -> None:
    ledger = _ledger()
    charge = ledger.charge(_record(ref, 5_000, 500, requested_model=ref.model_id))
    assert (charge.basis, charge.micro_usd) == (basis, None)
    assert ledger.spend.micro_usd == 0
    assert ledger.unpriced_calls == (basis == "unpriced")


def test_failed_call_without_usage_is_unpriced() -> None:
    failed = call_record(SONNET, usage=None, error="HTTP 503", response_sha=None)
    assert _ledger().charge(failed).basis == "unpriced"


def test_the_absolute_session_cap_is_2_usd() -> None:  # root decision, 2026-09-26
    assert SESSION_CAP_MICRO_USD == 2_000_000 and RUNAWAY_FACTOR == 3
    test_rate = {SONNET.model_id: Rate(100.0, 0.0)}  # test-only: $1 per 10k tokens
    ledger = _ledger(rates=test_rate)
    ledger.charge(_record(SONNET, 10_000, 0))  # $1
    ledger.charge(_record(SONNET, 10_000, 0))  # $2: at the cap, not past it
    with pytest.raises(RunawaySpend, match="runaway spend") as caught:
        ledger.charge(_record(SONNET, 1, 0, call_id="k9"))
    assert caught.value.charge.call_id == "k9"
    assert ledger.spend.micro_usd == 2_000_100  # the crossing charge is kept


def test_the_token_guard_counts_hosted_tokens_past_3x_the_projection() -> None:
    ledger = _ledger(tokens=1_000)  # limit: 3,000 hosted tokens
    for k in range(3):
        ledger.charge(_record(GEMINI, 900, 100, call_id=f"w{k}"))
    ledger.charge(_record(QWEN, 5_000, 500))  # gpu_time: Modal bills it, not tokens
    assert ledger.tokens == 3_000
    with pytest.raises(RunawaySpend, match="runaway tokens") as caught:
        ledger.charge(_record(SONNET, 1, 0, call_id="s1"))  # priced ones count too
    assert caught.value.charge.call_id == "s1"


def test_unpriced_call_guard_raises_past_3x_the_projected_calls() -> None:
    ledger = _ledger(calls=2)
    for k in range(6):  # limit: 6 unpriced calls
        ledger.charge(_record(GEMINI, 5, 5, call_id=f"w{k}"))
    ledger.charge(_record(QWEN, 5_000, 500))  # gpu_time: not an unpriced call
    with pytest.raises(RunawaySpend, match="runaway calls") as caught:
        ledger.charge(_record(GEMINI, 5, 5, call_id="w6"))
    assert caught.value.charge.call_id == "w6" and ledger.unpriced_calls == 7


@pytest.mark.parametrize(("tokens", "calls", "cap"), [(0, 5, 1), (9, 0, 1), (9, 5, 0)])
def test_limits_must_be_positive(tokens: int, calls: int, cap: int) -> None:
    with pytest.raises(ValueError):
        _ledger(tokens, calls, cap_micro_usd=cap)


@pytest.mark.parametrize(
    ("refs", "factor"),
    [
        ((), RUNAWAY_FACTOR),
        ((SONNET, QWEN), RUNAWAY_FACTOR),  # every role priced (or GPU time)
        ((SONNET, QWEN, GEMINI), 1),  # TeamRouter: no rate card row yet
        ((SONNET.model_copy(update={"model_id": "no-such-rate"}),), 1),
    ],
)
def test_an_unpriced_role_drops_the_guard_factor_to_1(
    refs: tuple[ModelRef, ...], factor: int
) -> None:  # main root decision, #133 round 2
    ledger = _ledger(tokens=1_000, calls=10, refs=refs)
    assert ledger.factor == factor
    assert (ledger.limit_tokens, ledger.limit_unpriced_calls) == (
        factor * 1_000,
        factor * 10,
    )
    assert ledger.limit_micro_usd == SESSION_CAP_MICRO_USD  # absolute either way


def test_totals_count_unpriced_calls_beside_the_priced_subtotal() -> None:
    ledger = _ledger()
    ledger.charge(_record(GEMINI, 900, 100, role="ear"))  # unpriced, with usage
    assert ledger.totals() == {
        "priced_micro_usd": 0,
        "priced_by_role": {},
        "unpriced_calls": 1,
        "unpriced_by_role": {"ear": 1},
        "gpu_time_calls": 0,
        "tokens": 1_000,
    }
    ledger.charge(_record(SONNET, 1_000, 200, role="slow"))  # 6,000 micro-USD
    ledger.charge(_record(QWEN, 5_000, 500))  # gpu_time: no $ and no tokens here
    totals = ledger.totals()
    assert (totals["priced_micro_usd"], totals["priced_by_role"]) == (
        6_000,
        {"slow": 6_000},
    )
    assert (totals["unpriced_calls"], totals["gpu_time_calls"]) == (1, 1)
    assert totals["tokens"] == 2_200
