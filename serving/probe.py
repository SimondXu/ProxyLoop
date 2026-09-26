"""Serving probe (ADR-0002): raw measurements of the deployed vLLM endpoint, run from the Mac.

    python -m serving.probe --out docs/decisions/data/vllm-probe.json
    python -m serving.probe --wait-healthy --out docs/decisions/data/vllm-coldstart.json

Endpoint: PROXYLOOP_VLLM_BASE_URL, else discovered from the Modal app; key: PROXYLOOP_VLLM_API_KEY.
Neither is written out. No retries: a failed request is recorded with its error and counted.
TTFT/TTFS are client-side, from request start to the first token / first sentence end.
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

import httpx

from serving import config

SENTENCE_END = re.compile(r"[.!?](?:\s|$)")


def base_url(variant: str) -> str:
    url = os.environ.get("PROXYLOOP_VLLM_BASE_URL")
    if not url:
        import modal

        url = modal.Function.from_name(config.app_name(variant), "serve").get_web_url()
    if not url:
        raise SystemExit(f"no URL: set PROXYLOOP_VLLM_BASE_URL or deploy {config.app_name(variant)}")
    return url.rstrip("/")


def summarise(records: list[dict]) -> dict:
    """Counts plus p50/p95 (linear interpolation, numpy's default) over successful requests."""
    ok = [r for r in records if r["error"] is None]
    out = {"n": len(records), "failed": len(records) - len(ok)}
    for name in ("ttft", "ttfs"):
        vals = [r[f"{name}_s"] for r in ok if r[f"{name}_s"] is not None]
        cuts = statistics.quantiles(vals, n=20, method="inclusive") if len(vals) > 1 else vals * 19
        out.update({f"{name}_n": len(vals), f"{name}_p50_s": cuts[9] if cuts else None,
                    f"{name}_p95_s": cuts[18] if cuts else None})
    return out


def absorb(record: dict, line: str, elapsed: float) -> None:
    """Fold one SSE line of a streamed /v1/completions response into the record."""
    if not line.startswith("data: ") or line == "data: [DONE]":
        return
    chunk = json.loads(line[len("data: "):])
    if "error" in chunk:
        record["error"] = f"stream error: {json.dumps(chunk['error'])[:500]}"
        return
    record["server_id"] = record["server_id"] or chunk.get("id")
    if usage := chunk.get("usage"):
        record["prompt_tokens"], record["completion_tokens"] = usage["prompt_tokens"], usage["completion_tokens"]
    for choice in chunk.get("choices") or []:
        if text := choice.get("text"):
            record["text"] += text
            if record["ttft_s"] is None:
                record["ttft_s"] = elapsed
            if record["ttfs_s"] is None and SENTENCE_END.search(record["text"]):
                record["ttfs_s"] = elapsed


async def stream_one(client: httpx.AsyncClient, model: str, ids: list[int], phase: str,
                     max_tokens: int) -> dict:
    record = {"client_request_id": f"pl-probe-{uuid.uuid4().hex[:16]}", "model": model,
              "phase": phase, "server_id": None, "status": None, "ttft_s": None, "ttfs_s": None,
              "total_s": None, "prompt_tokens": None, "completion_tokens": None, "text": "",
              "error": None}
    body = {"model": model, "prompt": ids, "max_tokens": max_tokens, "temperature": 0,
            "stream": True, "stream_options": {"include_usage": True}}
    start = time.perf_counter()
    try:
        async with client.stream("POST", "/v1/completions", json=body,
                                 headers={"X-Request-Id": record["client_request_id"]}) as resp:
            record["status"] = resp.status_code
            if resp.status_code != 200:
                record["error"] = f"HTTP {resp.status_code}: {(await resp.aread()).decode()[:500]}"
            else:
                async for line in resp.aiter_lines():
                    absorb(record, line, time.perf_counter() - start)
    except httpx.HTTPError as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["total_s"] = time.perf_counter() - start
    if record["error"] is None and record["ttft_s"] is None:
        record["error"] = "stream ended without a token"
    return record


async def latency(url: str, headers: dict, prompts: list[list[int]], models: list[str],
                  max_tokens: int) -> dict:
    """Per model: 2 warm-up requests, then len(prompts) requests at concurrency 1 and at 4."""
    out = {}
    async with httpx.AsyncClient(base_url=url, headers=headers, timeout=300) as client:
        for model in models:
            out[f"{model}@warmup"] = {"requests": [
                await stream_one(client, model, prompts[0], "warmup", max_tokens) for _ in range(2)]}
            for concurrency in (1, 4):
                gate = asyncio.Semaphore(concurrency)

                async def one(ids: list[int], model: str = model, gate=gate) -> dict:
                    async with gate:
                        return await stream_one(client, model, ids, "measured", max_tokens)

                records = await asyncio.gather(*(one(ids) for ids in prompts))
                out[f"{model}@c{concurrency}"] = {"summary": summarise(records), "requests": records}
    return out


def prompt_logprobs(body: dict, ids: list[int], start: int) -> list[float]:
    rows = body["choices"][0]["prompt_logprobs"]
    return [rows[i][str(ids[i])]["logprob"] for i in range(start, len(ids))]


def liveness(client: httpx.Client, pairs: list[tuple[list[int], int]], lora: str) -> dict:
    """prompt_logprobs of the completion tokens, base vs the zero-LoRA slot, same process."""
    rows, diffs = [], []
    for ids, start in pairs:
        row = {}
        for label, model in (("base", config.SERVED_NAME), ("lora", lora)):
            resp = client.post("/v1/completions", json={"model": model, "prompt": ids, "max_tokens": 1,
                                                        "temperature": 0, "prompt_logprobs": 0})
            row[f"{label}_status"] = resp.status_code
            if resp.status_code != 200:
                row["error"] = f"{label}: HTTP {resp.status_code}: {resp.text[:500]}"
                break
            row[f"{label}_server_id"], row[label] = resp.json()["id"], prompt_logprobs(resp.json(), ids, start)
        else:
            row["abs_diff"] = [abs(a - b) for a, b in zip(row["base"], row["lora"], strict=True)]
            diffs += row["abs_diff"]
        rows.append(row)
    ok = diffs and not any("error" in r for r in rows)
    return {"lora": lora, "pairs": rows, "max_abs_diff": max(diffs, default=None),
            "within_zero_max": bool(ok) and max(diffs) <= config.ZERO_MAX_DIFF}


def tokenize_parity(client: httpx.Client, tokenizer) -> dict:
    rows = []
    for index, (messages, _) in enumerate(config.PAIRS):
        resp = client.post("/tokenize", json={"model": config.SERVED_NAME, "messages": messages,
                                              "add_generation_prompt": True,
                                              "chat_template_kwargs": {"enable_thinking": False}})
        hf_ids = config.chat_ids(tokenizer, messages)
        vllm_ids = resp.json().get("tokens") if resp.status_code == 200 else None
        rows.append({"prompt_index": index, "status": resp.status_code, "hf_ids": hf_ids,
                     "vllm_ids": vllm_ids, "equal": vllm_ids == hf_ids})
    return {"prompts": rows, "all_equal": all(r["equal"] for r in rows)}


def wait_healthy(url: str, timeout_s: float) -> dict:
    attempts, requested_at, start = [], time.time(), time.perf_counter()
    while (elapsed := time.perf_counter() - start) < timeout_s:
        try:
            status = httpx.get(f"{url}/health", timeout=60, follow_redirects=True).status_code
            attempts.append({"t_s": elapsed, "status": status})
            if status == 200:
                return {"healthy": True, "requested_at": requested_at,
                        "seconds_to_healthy": time.perf_counter() - start, "attempts": attempts}
        except httpx.HTTPError as exc:
            attempts.append({"t_s": elapsed, "error": f"{type(exc).__name__}: {exc}"})
        time.sleep(5)
    return {"healthy": False, "requested_at": requested_at, "attempts": attempts}


def measure(url: str, key: str, args: argparse.Namespace) -> dict:
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(config.MODEL_ID, revision=config.MODEL_REVISION)
    headers, report = {"Authorization": f"Bearer {key}"}, {}
    with httpx.Client(base_url=url, headers=headers, timeout=300) as client:
        for field, path in (("version", "/version"), ("models", "/v1/models"), ("attest", "/pl/attest")):
            report[field] = client.get(path).raise_for_status().json()
        report["gpu_name"] = report["attest"]["runtime"]["gpu_name"]
        report["tokenize"] = tokenize_parity(client, tokenizer)
        pairs = [config.pair_ids(tokenizer, pair) for pair in config.PAIRS]
        report["zero_lora_liveness"] = liveness(client, pairs, config.ZERO_LORA_NAME)
    n_notes = 1
    while len(config.chat_ids(tokenizer, config.latency_messages(0, n_notes))) < args.prompt_tokens:
        n_notes += 1
    prompts = [config.chat_ids(tokenizer, config.latency_messages(k, n_notes)) for k in range(args.requests)]
    report["latency_prompt_tokens"] = len(prompts[0])
    report["latency"] = asyncio.run(latency(url, headers, prompts, [config.SERVED_NAME, config.ZERO_LORA_NAME],
                                            args.max_tokens))
    report["checks"] = {"tokenize_all_equal": report["tokenize"]["all_equal"],
                        "zero_lora_within_1e-4": report["zero_lora_liveness"]["within_zero_max"],
                        "failed_requests": sum(v["summary"]["failed"] for v in report["latency"].values()
                                               if "summary" in v)}
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="vLLM serving probe (ADR-0002)")
    parser.add_argument("--out", required=True)
    parser.add_argument("--variant", default="pinned", choices=sorted(config.VARIANTS))
    parser.add_argument("--wait-healthy", action="store_true", help="only time /health to 200")
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--prompt-tokens", type=int, default=1500)
    parser.add_argument("--max-tokens", type=int, default=64)
    args = parser.parse_args(argv)
    url, key = base_url(args.variant), os.environ.get("PROXYLOOP_VLLM_API_KEY", "")
    if not args.wait_healthy and not key:
        raise SystemExit("PROXYLOOP_VLLM_API_KEY is not set")
    report = {"variant": args.variant, "measured_at": time.time()}
    if args.wait_healthy:
        report["cold_start"] = wait_healthy(url, args.timeout)
        ok = report["cold_start"]["healthy"]
    else:
        report.update(measure(url, key, args))
        checks = report["checks"]
        ok = checks["tokenize_all_equal"] and checks["zero_lora_within_1e-4"] and not checks["failed_requests"]
    Path(args.out).write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report.get("checks", {"healthy": ok}), indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
