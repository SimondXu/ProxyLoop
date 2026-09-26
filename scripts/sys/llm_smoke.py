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
import contextlib
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import httpx
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
from proxyloop.contract.protocol import ChatTokenizer, render_messages, render_prompt
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


def golden_prompts(tok: ChatTokenizer) -> list[GoldenPrompt]:
    """The P2 cases: messages, ``render_prompt`` text and committed ids (§12)."""
    p2: Json = json.loads((GOLDEN / "p2_ids.json").read_text("utf-8"))
    out: list[GoldenPrompt] = []
    for case in CASES:
        messages = tuple(
            {"role": m.role, "content": m.content}
            for m in render_messages(case.view(), case.profile)
        )
        prompt = render_prompt(case.view(), case.profile, tok)
        ids = tuple(int(i) for i in p2["cases"][case.name].split())
        out.append(GoldenPrompt(case.name, messages, prompt, ids))
    return out


def redact(text: str) -> str:
    """``text`` without any PL_* endpoint value or host."""
    for endpoint in ("VLLM", "RELAY"):
        base = os.environ.get(f"PL_{endpoint}_BASE_URL", "").strip()
        key = os.environ.get(f"PL_{endpoint}_API_KEY", "").strip()
        host = httpx.URL(base).host if base else ""
        for secret in (key, base, host):
            if secret:
                text = text.replace(secret, "<redacted>")
    return text


def clock() -> int:
    return int(time.monotonic() * 1000)


def row(record: LLMCallRecord) -> Json:
    out = record.model_dump(mode="json", exclude={"model_ref"})
    first = record.t_first_token
    out["ttft_ms"] = None if first is None else first - record.t_start
    return out


def final(records: list[LLMCallRecord]) -> list[LLMCallRecord]:
    """Each call's last record (a retried call has two)."""
    return list({r.call_id: r for r in records}.values())


async def vllm_streams(llm: VLLMClient, tok: ChatTokenizer, n: int) -> None:
    for k in range(n):
        case = CASES[k % len(CASES)]
        request = TextRequest(
            call_id=f"smoke-fast-{k}-{case.name}",
            role="fast_user" if case.profile == "pl_user_v1" else "fast_cp",
            prompt=render_prompt(case.view(), case.profile, tok),
            max_tokens=160,
            temperature=0.3,
            top_p=0.9,
            seed=k,
        )
        with contextlib.suppress(LLMUnavailable):  # its record is in the sink
            _ = [item async for item in llm.stream_text(request)]


async def sonnet_tools(records: list[LLMCallRecord]) -> dict[str, Json]:
    llm = make_client(SONNET, live=True, clock=clock, on_record=records.append)
    extras: dict[str, Json] = {}
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
        except LLMUnavailable:
            continue  # its record is in the sink
        well_formed = [
            c.name == "classify" and _json_object(c.arguments)
            for c in response.tool_calls
        ]
        extras[request.call_id] = {
            "text": response.text,
            "tool_calls": [c.model_dump(mode="json") for c in response.tool_calls],
            "well_formed": bool(well_formed) and all(well_formed),
        }
    return extras


def _json_object(text: str) -> bool:
    try:
        return isinstance(json.loads(text), dict)
    except ValueError:
        return False


async def smoke(n_streams: int) -> Json:
    fast: list[LLMCallRecord] = []
    slow: list[LLMCallRecord] = []
    llm = make_client(QWEN, live=True, clock=clock, on_record=fast.append)
    assert isinstance(llm, VLLMClient)
    tok = load_tokenizer()  # the pinned P2 tokenizer (= the serving revision)
    parity = await check_parity(llm, golden_prompts(tok))
    attest = await llm.attest()
    await vllm_streams(llm, tok, n_streams)
    extras = await sonnet_tools(slow)
    streams, tools = final(fast), final(slow)
    return {
        "task": "S0-SYS-04",
        "measured_at": time.time(),
        "attest": attest,
        "p3": {
            "requested_model": parity.requested_model,
            "equal": dict(parity.equal),
            "passed": parity.passed,
        },
        "vllm_streams": [row(r) for r in fast],  # every attempt, retries included
        "sonnet_tool_calls": [row(r) | extras.get(r.call_id, {}) for r in slow],
        "checks": {
            "p3_passed": parity.passed,
            "vllm_streams_ok": sum(
                r.error is None and bool(r.request_id) for r in streams
            ),
            "vllm_echo_ok": all(r.served_model_echo == QWEN.model_id for r in streams),
            "sonnet_tools_ok": sum(e["well_formed"] is True for e in extras.values()),
            "sonnet_echo_ok": all(
                r.served_model_echo == SONNET.model_id for r in tools
            ),
        },
    }


def passed(report: Json, n_streams: int) -> bool:
    checks = report["checks"]
    return (
        checks["p3_passed"] is True
        and checks["vllm_streams_ok"] == n_streams
        and checks["vllm_echo_ok"] is True
        and checks["sonnet_tools_ok"] == len(UTTERANCES)
        and checks["sonnet_echo_ok"] is True
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
    except Exception as exc:  # recorded and reported, redacted, never hidden
        error = redact(f"{type(exc).__name__}: {exc}")
        out.write_text(json.dumps({"task": "S0-SYS-04", "error": error}) + "\n")
        print(redact(traceback.format_exc()), file=sys.stderr)
        return 2
    out.write_text(redact(json.dumps(report, indent=1)) + "\n")
    print(json.dumps(report["checks"], indent=1))
    return 0 if passed(report, args.streams) else 1


if __name__ == "__main__":
    sys.exit(main())
