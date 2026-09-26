"""llm-smoke (S0-SYS-04; root-run, flags L+G): the adapters against the real endpoints.

    uv run python -m scripts.sys.llm_smoke --out docs/decisions/data/llm-smoke.json

Needs the vLLM app up (``make serve-up``) and, exported in the shell,
``PL_VLLM_BASE_URL``/``PL_VLLM_API_KEY`` and ``PL_RELAY_BASE_URL``/``PL_RELAY_API_KEY``
(server roots, without ``/v1``). Calls only ``proxyloop.llm`` adapters; no key or
URL is written out. No retries beyond the adapters' own rule: a failure is recorded
and counted. The JSON is written either way; the exit status is non-zero when a
check fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from tests.golden.cases import CASES, GOLDEN
from tests.golden.tokenizer import load_tokenizer

from proxyloop.contract.llm import (
    AdapterKind,
    ChatMessage,
    LLMCallRecord,
    LLMUnavailable,
    ModelRef,
    TextRequest,
    ToolRequest,
    ToolSpec,
)
from proxyloop.contract.protocol import render_messages, render_prompt
from proxyloop.llm.factory import make_client
from proxyloop.llm.parity import GoldenPrompt, check_parity
from proxyloop.llm.vllm import VLLMClient
from serving import config

Json = dict[str, Any]
SONNET = ModelRef(
    kind=AdapterKind.REAL_HTTP, endpoint="relay", model_id="claude-sonnet-5"
)
QWEN = ModelRef(
    kind=AdapterKind.REAL_HTTP, endpoint="vllm", model_id=config.SERVED_NAME
)
CLASSIFY = ToolSpec(
    name="classify",
    description="Classify the representative's utterance.",
    parameters={
        "type": "object",
        "properties": {
            "act": {
                "type": "string",
                "enum": ["offer", "question", "refusal", "other"],
            },
            "amount_usd": {"type": ["number", "null"]},
        },
        "required": ["act", "amount_usd"],
    },
)
UTTERANCES = (
    "We can take $10 off your monthly bill if you stay twelve months.",
    "Can you confirm the account holder's full name?",
    "I'm sorry, there are no discounts available on this plan.",
)


def golden_prompts() -> list[GoldenPrompt]:
    """The P2 cases: rendered messages and the committed P2 ids (ARCHITECTURE §12)."""
    p2: Json = json.loads((GOLDEN / "p2_ids.json").read_text("utf-8"))
    out: list[GoldenPrompt] = []
    for case in CASES:
        messages = tuple(
            {"role": m.role, "content": m.content}
            for m in render_messages(case.view(), case.profile)
        )
        ids = tuple(int(i) for i in p2["cases"][case.name].split())
        out.append(GoldenPrompt(case.name, messages, ids))
    return out


def clock() -> int:
    return int(time.monotonic() * 1000)


def row(record: LLMCallRecord) -> Json:
    out = record.model_dump(mode="json", exclude={"model_ref"})
    first = record.t_first_token
    out["ttft_ms"] = None if first is None else first - record.t_start
    return out


async def vllm_streams(
    llm: VLLMClient, n: int, retries: list[LLMCallRecord]
) -> list[Json]:
    tok = load_tokenizer()  # the pinned P2 tokenizer (= the serving revision)
    rows: list[Json] = []
    for k in range(n):
        case = CASES[k % len(CASES)]
        prompt = render_prompt(case.view(), case.profile, tok)
        request = TextRequest(
            call_id=f"smoke-fast-{k}",
            role="fast_user" if case.profile == "pl_user_v1" else "fast_cp",
            prompt=prompt,
            max_tokens=160,
            temperature=0.3,
            top_p=0.9,
            seed=k,
        )
        try:
            items = [item async for item in llm.stream_text(request)]
            record = items[-1]
            assert isinstance(record, LLMCallRecord)
            rows.append({"case": case.name, **row(record)})
        except LLMUnavailable as exc:
            rows.append({"case": case.name, **row(exc.record)})
    return rows + [{"retried": True, **row(r)} for r in retries]


async def sonnet_tools(retries: list[LLMCallRecord]) -> list[Json]:
    llm = make_client(SONNET, live=True, clock=clock, on_retry=retries.append)
    rows: list[Json] = []
    for k, text in enumerate(UTTERANCES):
        request = ToolRequest(
            call_id=f"smoke-slow-{k}",
            role="slow",
            messages=(ChatMessage(role="user", content=f"Representative: {text}"),),
            tools=(CLASSIFY,),
            tool_choice="classify",
            max_tokens=256,
        )
        try:
            response = await llm.chat_tools(request)
        except LLMUnavailable as exc:
            rows.append(row(exc.record))
            continue
        calls = [c.model_dump(mode="json") for c in response.tool_calls]
        well_formed = [
            c.name == "classify" and _json_object(c.arguments)
            for c in response.tool_calls
        ]
        rows.append(
            {
                **row(response.record),
                "text": response.text,
                "tool_calls": calls,
                "well_formed": bool(well_formed) and all(well_formed),
            }
        )
    return rows + [{"retried": True, **row(r)} for r in retries]


def _json_object(text: str) -> bool:
    try:
        return isinstance(json.loads(text), dict)
    except ValueError:
        return False


async def smoke(n_streams: int) -> Json:
    retries: list[LLMCallRecord] = []
    llm = make_client(QWEN, live=True, clock=clock, on_retry=retries.append)
    assert isinstance(llm, VLLMClient)
    parity = await check_parity(llm, golden_prompts())
    report: Json = {
        "task": "S0-SYS-04",
        "measured_at": time.time(),
        "attest": await llm.attest(),
        "p3": {
            "served_model": parity.served_model,
            "equal": dict(parity.equal),
            "passed": parity.passed,
        },
        "vllm_streams": await vllm_streams(llm, n_streams, retries),
        "sonnet_tool_calls": await sonnet_tools([]),  # its own retry list
    }
    streams = [r for r in report["vllm_streams"] if not r.get("retried")]
    tools = [r for r in report["sonnet_tool_calls"] if not r.get("retried")]
    report["checks"] = {
        "p3_passed": parity.passed,
        "vllm_streams_ok": sum(
            r["error"] is None and bool(r["request_id"]) for r in streams
        ),
        "vllm_echo_ok": all(r["served_model_echo"] == QWEN.model_id for r in streams),
        "sonnet_tools_ok": sum(r.get("well_formed") is True for r in tools),
    }
    return report


def passed(report: Json, n_streams: int) -> bool:
    checks = report["checks"]
    return (
        checks["p3_passed"] is True
        and checks["vllm_streams_ok"] == n_streams
        and checks["vllm_echo_ok"] is True
        and checks["sonnet_tools_ok"] == len(UTTERANCES)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="llm-smoke (S0-SYS-04)")
    parser.add_argument("--out", required=True)
    parser.add_argument("--streams", type=int, default=20)
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = asyncio.run(smoke(args.streams))
    except (
        Exception
    ) as exc:  # recorded, then re-raised: the smoke never hides a failure
        out.write_text(
            json.dumps({"task": "S0-SYS-04", "error": f"{type(exc).__name__}: {exc}"})
            + "\n"
        )
        raise
    out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report["checks"], indent=1))
    return 0 if passed(report, args.streams) else 1


if __name__ == "__main__":
    sys.exit(main())
