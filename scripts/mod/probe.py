"""Serving probe (ADR-0002): raw measurements of the deployed vLLM endpoint, run from
the Mac.

    python -m scripts.mod.probe --out docs/decisions/data/vllm-probe.json
    python -m scripts.mod.probe --wait-healthy \
        --out docs/decisions/data/vllm-coldstart.json

Endpoint: PROXYLOOP_VLLM_BASE_URL, else looked up from the Modal app; key:
PROXYLOOP_VLLM_API_KEY. Neither is written out. No retries: a failed request is recorded
with its error and counted. TTFT/TTFS are client-side, from request start to the first
token / first sentence end. Exit status is non-zero when any check fails; the JSON is
written either way.
"""

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from serving import config, liveness

SENTENCE_END = re.compile(r"[.!?]\s")  # mid-stream: a terminator followed by whitespace
FINAL_END = re.compile(r"[.!?]$")  # only once the stream has finished
Json = dict[str, Any]


def base_url(variant: str) -> str:
    url = os.environ.get("PROXYLOOP_VLLM_BASE_URL")
    if not url:
        import modal

        # modal leaves Function.from_name partially untyped.
        fn = modal.Function.from_name(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            config.app_name(variant), "serve"
        )
        url = fn.get_web_url()
    if not url:
        raise SystemExit(
            f"no URL: set PROXYLOOP_VLLM_BASE_URL or deploy {config.app_name(variant)}"
        )
    return url.rstrip("/")


def latency_messages(index: int, n_notes: int) -> list[dict[str, str]]:
    """Synthetic latency prompt: a shared n_notes-line prefix and a unique last line."""
    notes = "\n".join(
        f"Note {i}: the customer asked about invoice {1000 + i} and the monthly "
        "service charge."
        for i in range(n_notes)
    )
    return [
        {
            "role": "system",
            "content": "You are a concise assistant. Answer in two sentences.",
        },
        {
            "role": "user",
            "content": f"{notes}\n\nRequest {index}: summarise the notes above.",
        },
    ]


def new_record(model: str, phase: str, index: int) -> Json:
    return {
        "client_request_id": f"pl-probe-{uuid.uuid4().hex[:16]}",
        "model": model,
        "phase": phase,
        "prompt_index": index,
        "server_id": None,
        "echoed_models": [],
        "status": None,
        "ttft_s": None,
        "ttfs_s": None,
        "total_s": None,
        "finished": False,
        "prompt_tokens": None,
        "completion_tokens": None,
        "text": "",
        "error": None,
    }


def _finish(record: Json, elapsed: float) -> None:
    if not record["finished"]:
        record["finished"] = True
        if record["ttfs_s"] is None and FINAL_END.search(record["text"]):
            record["ttfs_s"] = elapsed


def absorb(record: Json, line: str, elapsed: float) -> None:
    """Fold one SSE line of a streamed /v1/completions response into the record."""
    if not line.startswith("data: "):
        return
    if line == "data: [DONE]":
        _finish(record, elapsed)
        return
    chunk = json.loads(line[len("data: ") :])
    if "error" in chunk:
        record["error"] = f"stream error: {json.dumps(chunk['error'])[:500]}"
        return
    record["server_id"] = record["server_id"] or chunk.get("id")
    if chunk.get("model") not in record["echoed_models"]:
        record["echoed_models"].append(chunk.get("model"))
    if chunk.get("model") != record["model"] and record["error"] is None:
        record["error"] = (
            f"echoed model {chunk.get('model')!r} != requested {record['model']!r}"
        )
    if usage := chunk.get("usage"):
        record["prompt_tokens"], record["completion_tokens"] = (
            usage["prompt_tokens"],
            usage["completion_tokens"],
        )
    choices: list[Json] = chunk.get("choices") or []
    for choice in choices:
        if text := choice.get("text"):
            record["text"] += text
            if record["ttft_s"] is None:
                record["ttft_s"] = elapsed
            if record["ttfs_s"] is None and SENTENCE_END.search(record["text"]):
                record["ttfs_s"] = elapsed
        if choice.get("finish_reason"):
            _finish(record, elapsed)


def summarise(records: list[Json]) -> Json:
    """Counts and p50/p95 (linear, numpy's default). A request without a sentence end
    fails TTFS."""
    ok = [r for r in records if r["error"] is None]
    out: Json = {"n": len(records), "failed": len(records) - len(ok)}
    for name in ("ttft", "ttfs"):
        vals = [r[f"{name}_s"] for r in ok if r[f"{name}_s"] is not None]
        cuts = (
            statistics.quantiles(vals, n=20, method="inclusive")
            if len(vals) > 1
            else vals * 19
        )
        out.update(
            {
                f"{name}_n": len(vals),
                f"{name}_p50_s": cuts[9] if cuts else None,
                f"{name}_p95_s": cuts[18] if cuts else None,
            }
        )
    out["ttfs_complete"] = out["ttfs_n"] == out["n"]
    return out


async def stream_one(
    client: httpx.AsyncClient,
    model: str,
    ids: list[int],
    phase: str,
    index: int,
    max_tokens: int,
) -> Json:
    record = new_record(model, phase, index)
    body = {
        "model": model,
        "prompt": ids,
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    start = time.perf_counter()
    try:
        async with client.stream(
            "POST",
            "/v1/completions",
            json=body,
            headers={"X-Request-Id": record["client_request_id"]},
        ) as resp:
            record["status"] = resp.status_code
            if resp.status_code != 200:
                record["error"] = (
                    f"HTTP {resp.status_code}: {(await resp.aread()).decode()[:500]}"
                )
            else:
                async for line in resp.aiter_lines():
                    absorb(record, line, time.perf_counter() - start)
    except httpx.HTTPError as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["total_s"] = time.perf_counter() - start
    if record["error"] is None and (record["ttft_s"] is None or not record["finished"]):
        record["error"] = "stream ended without a token or without finishing"
    return record


async def latency(
    url: str,
    headers: dict[str, str],
    prompts: list[list[int]],
    models: list[str],
    n: int,
    max_tokens: int,
) -> Json:
    """Per model: 2 warm-ups, then n requests at concurrency 1 and n at 4. Every request
    gets its own prompt index, so only the shared prefix is ever cacheable."""
    out: Json = {}
    queue = iter(enumerate(prompts))
    async with httpx.AsyncClient(base_url=url, headers=headers, timeout=300) as client:
        for model in models:
            warm = [
                await stream_one(client, model, ids, "warmup", k, max_tokens)
                for k, ids in (next(queue) for _ in range(2))
            ]
            out[f"{model}@warmup"] = {"summary": summarise(warm), "requests": warm}
            for concurrency in (1, 4):
                gate, block = (
                    asyncio.Semaphore(concurrency),
                    [next(queue) for _ in range(n)],
                )

                async def one(
                    k: int,
                    ids: list[int],
                    model: str = model,
                    gate: asyncio.Semaphore = gate,
                ) -> Json:
                    async with gate:
                        return await stream_one(
                            client, model, ids, "measured", k, max_tokens
                        )

                records = await asyncio.gather(*(one(k, ids) for k, ids in block))
                out[f"{model}@c{concurrency}"] = {
                    "summary": summarise(records),
                    "requests": records,
                }
    return out


def tokenize_parity(client: httpx.Client, tokenizer: Any) -> Json:
    rows: list[Json] = []
    for index, (messages, _) in enumerate(config.PAIRS):
        resp = client.post(
            "/tokenize",
            json={
                "model": config.SERVED_NAME,
                "messages": messages,
                "add_generation_prompt": True,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        hf_ids = config.chat_ids(tokenizer, messages)
        vllm_ids = resp.json().get("tokens") if resp.status_code == 200 else None
        rows.append(
            {
                "prompt_index": index,
                "status": resp.status_code,
                "hf_ids": hf_ids,
                "vllm_ids": vllm_ids,
                "equal": vllm_ids == hf_ids,
            }
        )
    return {"prompts": rows, "all_equal": all(r["equal"] for r in rows)}


def wait_healthy(url: str, timeout_s: float) -> Json:
    """Timer starts after `modal deploy` returned; includes container start, first-time
    model download and hashing when the volume is cold, and vLLM start-up."""
    attempts: list[Json] = []
    requested_at, start = time.time(), time.perf_counter()
    while (elapsed := time.perf_counter() - start) < timeout_s:
        try:
            status = httpx.get(
                f"{url}/health", timeout=60, follow_redirects=True
            ).status_code
            attempts.append({"t_s": elapsed, "status": status})
            if status == 200:
                return {
                    "healthy": True,
                    "requested_at": requested_at,
                    "seconds_to_healthy": time.perf_counter() - start,
                    "attempts": attempts,
                }
        except httpx.HTTPError as exc:
            attempts.append({"t_s": elapsed, "error": f"{type(exc).__name__}: {exc}"})
        time.sleep(5)
    return {"healthy": False, "requested_at": requested_at, "attempts": attempts}


def derived(lat: Json, baseline: Json | None) -> Json:
    """Rows the ADR copies: zero-LoRA minus base, and (with --baseline) this run minus
    the baseline."""

    def delta(a: Json, b: Json, metric: str) -> float | None:
        x, y = a["summary"][metric], b["summary"][metric]
        return None if x is None or y is None else x - y

    metrics = ("ttft_p50_s", "ttfs_p50_s")
    out: Json = {
        "lora_overhead": {
            f"c{c}.{m}": delta(
                lat[f"{config.ZERO_LORA_NAME}@c{c}"],
                lat[f"{config.SERVED_NAME}@c{c}"],
                m,
            )
            for c in (1, 4)
            for m in metrics
        }
    }
    if baseline:
        out["minus_baseline"] = {
            f"{key}.{m}": delta(block, baseline["latency"][key], m)
            for key, block in lat.items()
            if not key.endswith("@warmup")
            for m in metrics
        }
    return out


def keyless_status(client: httpx.Client) -> dict[str, int]:
    """Status of protected paths requested WITHOUT the key; both must be 401."""
    return {p: client.get(p).status_code for p in ("/v1/models", "/pl/attest")}


def measure(url: str, key: str, args: argparse.Namespace) -> Json:
    """Every request of the run; the raw report. Nothing here interprets the results."""
    from transformers import AutoTokenizer

    # transformers leaves from_pretrained untyped.
    tokenizer: Any = AutoTokenizer.from_pretrained(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        config.MODEL_ID, revision=config.MODEL_REVISION
    )
    headers = {"Authorization": f"Bearer {key}"}
    report: Json = {}
    with httpx.Client(base_url=url, timeout=60) as keyless:
        report["keyless_status"] = keyless_status(keyless)
    with httpx.Client(base_url=url, headers=headers, timeout=300) as client:
        for field, path in (
            ("version", "/version"),
            ("models", "/v1/models"),
            ("attest", "/pl/attest"),
        ):
            report[field] = client.get(path).raise_for_status().json()
        report["gpu_name"] = report["attest"]["runtime"]["gpu_name"]
        report["tokenize"] = tokenize_parity(client, tokenizer)
        pairs = [config.pair_ids(tokenizer, pair) for pair in config.PAIRS]
        report["liveness"] = {
            "zero": liveness.compare(client, pairs, config.ZERO_LORA_NAME),
            "live": liveness.compare(client, pairs, config.LIVE_LORA_NAME),
        }
    n_notes = 1
    while (
        len(config.chat_ids(tokenizer, latency_messages(0, n_notes)))
        < args.prompt_tokens
    ):
        n_notes += 1
    models = [config.SERVED_NAME, config.ZERO_LORA_NAME]
    prompts = [
        config.chat_ids(tokenizer, latency_messages(k, n_notes))
        for k in range(len(models) * (2 + 2 * args.requests))
    ]
    report["latency_prompt_tokens"] = len(prompts[0])
    report["latency"] = asyncio.run(
        latency(url, headers, prompts, models, args.requests, args.max_tokens)
    )
    return report


def evaluate(report: Json, ladder: Json, baseline: Json | None) -> None:
    """Adds the derived rows and the checks to a raw report."""
    report["derived"] = derived(report["latency"], baseline)
    rung = report["attest"]["runtime"]["lora_rung"]
    blocks = report["latency"].values()
    report["checks"] = {
        "tokenize_all_equal": report["tokenize"]["all_equal"],
        "zero_lora_within_1e-4": liveness.zero_ok(report["liveness"]["zero"]),
        "live_lora_above_1e-3": liveness.live_ok(report["liveness"]["live"]),
        "failed_requests": sum(b["summary"]["failed"] for b in blocks),
        "ttfs_complete": all(b["summary"]["ttfs_complete"] for b in blocks),
        "keyless_401": all(s == 401 for s in report["keyless_status"].values()),
        f"ladder_rung_ok:{rung}": ladder["summary"].get(f"rung_ok:{rung}") is True,
    }


def passed(checks: Json) -> bool:
    return all(
        v is True or (k == "failed_requests" and v == 0) for k, v in checks.items()
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="vLLM serving probe (ADR-0002)")
    parser.add_argument("--out", required=True)
    parser.add_argument("--variant", default="pinned", choices=sorted(config.VARIANTS))
    parser.add_argument(
        "--wait-healthy", action="store_true", help="only time /health to 200"
    )
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--prompt-tokens", type=int, default=1500)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--ladder", default="docs/decisions/data/vllm-lora-ladder.json")
    parser.add_argument(
        "--baseline", help="probe JSON of the pinned variant, for derived deltas"
    )
    args = parser.parse_args(argv)
    url, key = base_url(args.variant), os.environ.get("PROXYLOOP_VLLM_API_KEY", "")
    if not args.wait_healthy and not key:
        raise SystemExit("PROXYLOOP_VLLM_API_KEY is not set")
    report: Json = {"variant": args.variant, "measured_at": time.time()}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.wait_healthy:
        report["cold_start"] = wait_healthy(url, args.timeout)
        report["checks"] = {"healthy": report["cold_start"]["healthy"]}
    else:
        # Read before any request, so a missing file costs no GPU time.
        ladder = json.loads(Path(args.ladder).read_text())
        baseline = (
            json.loads(Path(args.baseline).read_text()) if args.baseline else None
        )
        report.update(measure(url, key, args))
        # The paid-for raw run is never lost.
        out.write_text(json.dumps(report, indent=1) + "\n")
        try:
            evaluate(report, ladder, baseline)
        except Exception as exc:
            report.update(
                evaluation_error=f"{type(exc).__name__}: {exc}",
                checks={"evaluated": False},
            )
    out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report["checks"], indent=1))
    return 0 if passed(report["checks"]) else 1


if __name__ == "__main__":
    sys.exit(main())
