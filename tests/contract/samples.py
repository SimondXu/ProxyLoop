"""Plain contract values shared by the contract tests (data, not fakes)."""

from __future__ import annotations

from proxyloop.contract.config import Sampling, SessionConfig, WorldModels
from proxyloop.contract.llm import AdapterKind, LLMCallRecord, ModelRef, Usage

QWEN = ModelRef(kind=AdapterKind.REAL_HTTP, endpoint="vllm", model_id="Qwen3.5-9B")
SONNET = ModelRef(
    kind=AdapterKind.REAL_HTTP, endpoint="relay", model_id="claude-sonnet-5"
)
GEMINI = ModelRef(
    kind=AdapterKind.REAL_HTTP,
    endpoint="teamrouter",
    model_id="gemini-3.8-flash",
    reasoning_effort="minimal",
)


def session_config(**update: object) -> SessionConfig:
    cfg = SessionConfig(
        fast_user=QWEN,
        fast_cp=QWEN,
        slow=SONNET,
        world=WorldModels(ear=GEMINI, mouth=GEMINI, simuser=GEMINI),
        fast_sampling=Sampling(temperature=0.3, top_p=0.9, max_tokens=160),
        seed=7,
        live=True,
    )
    return SessionConfig.model_validate(cfg.model_dump() | update)


def call_record(ref: ModelRef = QWEN, **update: object) -> LLMCallRecord:
    base = LLMCallRecord(
        call_id="k1",
        role="fast_cp",
        model_ref=ref,
        adapter_kind=ref.kind,
        requested_model=ref.model_id,
        served_model_echo=ref.model_id,
        request_id="req_1",
        prompt_sha="0" * 64,
        response_sha="1" * 64,
        usage=Usage(prompt_tokens=10, completion_tokens=3),
        t_start=100,
        t_first_token=150,
        t_end=300,
    )
    return LLMCallRecord.model_validate(base.model_dump() | update)
