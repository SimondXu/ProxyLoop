# /// script
# requires-python = ">=3.11"
# dependencies = ["openai==2.45.0", "anthropic==0.116.0", "google-genai==2.11.0", "httpx"]
# ///
"""S0-ROOT-04 relay capability probe (ADR-0001). Root-run only: needs the relay key.

Reads `base_url` and the relay key from the git-ignored `.env` (`key:value` lines) at run time,
never prints them, and scrubs the relay host from everything it writes.

    uv run --no-project scripts/spikes/relay_probe.py --env .env --out docs/decisions/data/relay-probe.json
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import pathlib
import statistics
import time
import traceback
from typing import Any

import anthropic
import httpx
import openai
from google import genai
from google.genai import types as gtypes

MODELS = ["claude-sonnet-5", "claude-haiku-4-5", "gemini-3.6-flash", "claude-opus-4-8", "gemini-3.5-flash"]
TTFT_N = 20
TOOLS = [
    {"type": "function", "function": {"name": "get_weather", "description": "Current weather for a city.",
     "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}},
    {"type": "function", "function": {"name": "get_local_time", "description": "Current local time for a city.",
     "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}},
]
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["offer_usd", "accepted"],
          "properties": {"offer_usd": {"type": "number"}, "accepted": {"type": "boolean"}}}


def load_env(path: pathlib.Path) -> tuple[str, str]:
    kv = {}
    for line in path.read_text().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            kv[k.strip()] = v.strip()
    return kv["base_url"].rstrip("/"), kv["备用key2"]


class Scrub:
    def __init__(self, *secrets: str) -> None:
        self.secrets = [s for s in secrets if s]

    def __call__(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "<redacted>")
        return text


def err(e: BaseException, scrub: Scrub) -> dict[str, Any]:
    out: dict[str, Any] = {"error_type": type(e).__name__, "error": scrub(str(e))[:400]}
    status = getattr(e, "status_code", None)
    if status is not None:
        out["status_code"] = status
    return out


def oai_basic(c: openai.OpenAI, model: str) -> dict[str, Any]:
    raw = c.chat.completions.with_raw_response.create(
        model=model, max_tokens=64, messages=[{"role": "user", "content": "Reply with exactly: pong"}])
    r = raw.parse()
    return {"ok": True, "response_id": r.id, "request_id": raw.headers.get("x-request-id") or raw.headers.get("request-id"),
            "echoed_model": r.model, "text": (r.choices[0].message.content or "")[:80],
            "usage": r.usage.model_dump() if r.usage else None}


def oai_stream(c: openai.OpenAI, model: str, prompt: str = "Count from 1 to 5, comma separated.") -> dict[str, Any]:
    t0 = time.perf_counter()
    ttft = None
    rid = echoed = None
    usage = None
    text = []
    stream = c.chat.completions.create(model=model, max_tokens=48, stream=True,
                                       stream_options={"include_usage": True},
                                       messages=[{"role": "user", "content": prompt}])
    for ch in stream:
        rid = rid or ch.id
        echoed = echoed or ch.model
        if ch.usage:
            usage = ch.usage.model_dump()
        if ch.choices and ch.choices[0].delta and ch.choices[0].delta.content:
            if ttft is None:
                ttft = time.perf_counter() - t0
            text.append(ch.choices[0].delta.content)
    return {"ttft_s": ttft, "total_s": time.perf_counter() - t0, "response_id": rid, "echoed_model": echoed,
            "usage": usage, "text": "".join(text)[:80]}


def oai_tools(c: openai.OpenAI, model: str) -> dict[str, Any]:
    r = c.chat.completions.create(
        model=model, max_tokens=256, tools=TOOLS, parallel_tool_calls=True,
        messages=[{"role": "user", "content": "Call get_weather AND get_local_time for Paris, both in this one turn."}])
    calls = r.choices[0].message.tool_calls or []
    parsed = []
    for tc in calls:
        try:
            parsed.append({"name": tc.function.name, "args": json.loads(tc.function.arguments), "valid_json": True})
        except json.JSONDecodeError:
            parsed.append({"name": tc.function.name, "args_raw": tc.function.arguments[:120], "valid_json": False})
    names = {p["name"] for p in parsed}
    return {"response_id": r.id, "echoed_model": r.model, "n_tool_calls": len(calls), "calls": parsed,
            "tool_calls_ok": bool(calls) and all(p["valid_json"] for p in parsed),
            "parallel_ok": {"get_weather", "get_local_time"} <= names,
            "usage": r.usage.model_dump() if r.usage else None}


def oai_json_schema(c: openai.OpenAI, model: str) -> dict[str, Any]:
    r = c.chat.completions.create(
        model=model, max_tokens=128,
        response_format={"type": "json_schema", "json_schema": {"name": "offer", "schema": SCHEMA, "strict": True}},
        messages=[{"role": "user", "content": "The rep offered $65/month and the customer did not accept yet. Report it."}])
    txt = r.choices[0].message.content or ""
    try:
        obj = json.loads(txt)
        ok = isinstance(obj, dict) and set(obj) == {"offer_usd", "accepted"} and isinstance(obj["accepted"], bool)
    except json.JSONDecodeError:
        obj, ok = None, False
    return {"response_id": r.id, "echoed_model": r.model, "json_schema_ok": ok, "raw": txt[:160]}


def anthropic_native(root: str, key: str, model: str) -> dict[str, Any]:
    c = anthropic.Anthropic(base_url=root, api_key=key, max_retries=0, timeout=60)
    raw = c.messages.with_raw_response.create(model=model, max_tokens=64,
                                              messages=[{"role": "user", "content": "Reply with exactly: pong"}])
    m = raw.parse()
    tool = c.messages.create(
        model=model, max_tokens=256,
        tools=[{"name": t["function"]["name"], "description": t["function"]["description"],
                "input_schema": t["function"]["parameters"]} for t in TOOLS],
        messages=[{"role": "user", "content": "Call get_weather AND get_local_time for Paris, both in this one turn."}])
    uses = [b for b in tool.content if b.type == "tool_use"]
    return {"ok": True, "message_id": m.id, "request_id": raw.headers.get("request-id") or raw.headers.get("x-request-id"),
            "echoed_model": m.model, "text": "".join(b.text for b in m.content if b.type == "text")[:80],
            "usage": m.usage.model_dump(), "tool_use_n": len(uses), "tool_use_names": [u.name for u in uses],
            "tool_message_id": tool.id}


def gemini_native(root: str, key: str, model: str) -> dict[str, Any]:
    c = genai.Client(api_key=key, http_options=gtypes.HttpOptions(base_url=root, timeout=60_000))
    r = c.models.generate_content(model=model, contents="Reply with exactly: pong")
    um = r.usage_metadata
    return {"ok": True, "response_id": getattr(r, "response_id", None), "echoed_model": getattr(r, "model_version", None),
            "text": (r.text or "")[:80],
            "usage": {"prompt": um.prompt_token_count, "candidates": um.candidates_token_count} if um else None}


def balance(root_v1: str, key: str, scrub: Scrub) -> dict[str, Any]:
    out: dict[str, Any] = {}
    h = {"Authorization": f"Bearer {key}", "User-Agent": "OpenAI/Python 2.45.0"}
    for path in ("/dashboard/billing/subscription", "/dashboard/billing/usage"):
        try:
            r = httpx.get(root_v1 + path, headers=h, timeout=20)
            out[path] = {"status": r.status_code, "body": json.loads(r.text) if r.headers.get("content-type", "").startswith("application/json") else scrub(r.text[:200])}
        except Exception as e:  # noqa: BLE001 - a probe records every failure
            out[path] = err(e, scrub)
    return out


def probe_model(root_v1: str, root: str, key: str, model: str, scrub: Scrub) -> dict[str, Any]:
    c = openai.OpenAI(base_url=root_v1, api_key=key, max_retries=0, timeout=90)
    res: dict[str, Any] = {"model": model}
    for name, fn in (("openai_basic", lambda: oai_basic(c, model)), ("tools", lambda: oai_tools(c, model)),
                     ("json_schema", lambda: oai_json_schema(c, model))):
        try:
            res[name] = fn()
        except Exception as e:  # noqa: BLE001
            res[name] = err(e, scrub)
    streams = []
    for _ in range(TTFT_N):
        try:
            streams.append(oai_stream(c, model))
        except Exception as e:  # noqa: BLE001
            streams.append(err(e, scrub))
    res["streams"] = streams
    ttfts = [s["ttft_s"] for s in streams if s.get("ttft_s") is not None]
    res["ttft_p50_s"] = statistics.median(ttfts) if ttfts else None
    res["ttft_n_ok"] = len(ttfts)
    res["stream_usage_ok"] = any(s.get("usage") for s in streams)
    native = anthropic_native if model.startswith("claude") else gemini_native
    try:
        res["native"] = {"route": "anthropic /v1/messages" if model.startswith("claude") else "gemini generateContent",
                         **native(root, key, model)}
    except Exception as e:  # noqa: BLE001
        res["native"] = {"route": "anthropic /v1/messages" if model.startswith("claude") else "gemini generateContent",
                         "ok": False, **err(e, scrub)}
    return res


def summarise(r: dict[str, Any]) -> dict[str, Any]:
    ok = lambda d: isinstance(d, dict) and "error" not in d  # noqa: E731
    return {
        "available": ok(r["openai_basic"]),
        "echoed_model": r["openai_basic"].get("echoed_model") if ok(r["openai_basic"]) else None,
        "streaming": r["ttft_n_ok"] > 0, "streaming_usage": r["stream_usage_ok"],
        "tool_calls": ok(r["tools"]) and r["tools"]["tool_calls_ok"],
        "parallel_tool_calls": ok(r["tools"]) and r["tools"]["parallel_ok"],
        "json_schema": ok(r["json_schema"]) and r["json_schema"]["json_schema_ok"],
        "native_route": bool(r["native"].get("ok")),
        "native_tool_use": r["native"].get("tool_use_n", 0) >= 2 if r["model"].startswith("claude") else None,
        "ttft_p50_s": r["ttft_p50_s"], "ttft_n_ok": r["ttft_n_ok"],
    }


def gemini_native_structured(root: str, key: str, model: str) -> dict[str, Any]:
    c = genai.Client(api_key=key, http_options=gtypes.HttpOptions(base_url=root, timeout=60_000))
    r = c.models.generate_content(
        model=model, contents="The rep offered $65/month and the customer did not accept yet. Report it.",
        config=gtypes.GenerateContentConfig(response_mime_type="application/json", response_schema={
            "type": "OBJECT", "required": ["offer_usd", "accepted"],
            "properties": {"offer_usd": {"type": "NUMBER"}, "accepted": {"type": "BOOLEAN"}}}))
    try:
        obj = json.loads(r.text or "")
        schema_ok = isinstance(obj, dict) and set(obj) == {"offer_usd", "accepted"}
    except json.JSONDecodeError:
        schema_ok = False
    decls = [gtypes.FunctionDeclaration(name=t["function"]["name"], description=t["function"]["description"],
                                        parameters=t["function"]["parameters"]) for t in TOOLS]
    f = c.models.generate_content(
        model=model, contents="Call get_weather AND get_local_time for Paris, both in this one turn.",
        config=gtypes.GenerateContentConfig(tools=[gtypes.Tool(function_declarations=decls)],
                                            automatic_function_calling=gtypes.AutomaticFunctionCallingConfig(disable=True)))
    calls = f.function_calls or []
    return {"json_schema_ok": schema_ok, "json_raw": (r.text or "")[:160],
            "function_calls": [{"name": fc.name, "args": dict(fc.args or {})} for fc in calls],
            "parallel_ok": {"get_weather", "get_local_time"} <= {fc.name for fc in calls}}


def oai_json_object(c: openai.OpenAI, model: str) -> dict[str, Any]:
    r = c.chat.completions.create(
        model=model, max_tokens=128, response_format={"type": "json_object"},
        messages=[{"role": "user", "content": "Return JSON {\"offer_usd\": number, \"accepted\": boolean}: "
                                              "the rep offered $65/month, not accepted yet."}])
    txt = r.choices[0].message.content or ""
    try:
        json.loads(txt)
        ok = True
    except json.JSONDecodeError:
        ok = False
    return {"json_object_ok": ok, "raw": txt[:160]}


def usage_total(root_v1: str, key: str) -> float:
    r = httpx.get(root_v1 + "/dashboard/billing/usage", headers={"Authorization": f"Bearer {key}"}, timeout=20)
    r.raise_for_status()
    return float(r.json()["total_usage"])


def cost_probe(root_v1: str, key: str, model: str, n: int = 4) -> dict[str, Any]:
    """Sequential, one model at a time: usage delta over n fixed calls (units as the relay reports them)."""
    c = openai.OpenAI(base_url=root_v1, api_key=key, max_retries=0, timeout=90)
    prompt = "Summarise in about 80 words why phone bills rise after promotional periods end. " * 8
    before = usage_total(root_v1, key)
    pt = ct = 0
    ids = []
    for _ in range(n):
        r = c.chat.completions.create(model=model, max_tokens=150, messages=[{"role": "user", "content": prompt}])
        ids.append(r.id)
        pt += r.usage.prompt_tokens
        ct += r.usage.completion_tokens
    time.sleep(8)
    after = usage_total(root_v1, key)
    return {"calls": n, "response_ids": ids, "prompt_tokens": pt, "completion_tokens": ct,
            "usage_before": before, "usage_after": after, "usage_delta": round(after - before, 6),
            "note": "total_usage is reported in the OpenAI dashboard unit (cents); delta covers input+output together"}


def followup(root_v1: str, root: str, key: str, scrub: Scrub) -> dict[str, Any]:
    out: dict[str, Any] = {}

    def guard(name: str, fn: Any) -> None:
        try:
            out[name] = fn()
        except Exception as e:  # noqa: BLE001 - a probe records every failure
            out[name] = err(e, scrub)

    for m in ("gemini-3.6-flash", "gemini-3.5-flash"):
        guard(f"gemini_native_structured:{m}", lambda m=m: gemini_native_structured(root, key, m))
    c = openai.OpenAI(base_url=root_v1, api_key=key, max_retries=0, timeout=90)
    for m in ("claude-sonnet-5", "gemini-3.6-flash"):
        guard(f"json_object:{m}", lambda m=m: oai_json_object(c, m))
    guard("haiku_dated:claude-haiku-4-5-20251001", lambda: probe_model(root_v1, root, key, "claude-haiku-4-5-20251001", scrub))
    if "error" not in out["haiku_dated:claude-haiku-4-5-20251001"]:
        out["haiku_dated_summary"] = summarise(out["haiku_dated:claude-haiku-4-5-20251001"])
    for m in ("claude-sonnet-5", "claude-haiku-4-5-20251001", "gemini-3.6-flash", "claude-opus-4-8", "gemini-3.5-flash"):
        guard(f"cost:{m}", lambda m=m: cost_probe(root_v1, key, m))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=".env")
    ap.add_argument("--out", required=True)
    ap.add_argument("--part", choices=["main", "followup"], default="main")
    args = ap.parse_args()
    root_v1, key = load_env(pathlib.Path(args.env))
    root = root_v1.removesuffix("/v1")
    host = httpx.URL(root).host
    scrub = Scrub(key, root_v1, root, host)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if args.part == "followup":
        res = followup(root_v1, root, key, scrub)
        report = {"schema": "pl.relay_probe_followup/1", "task": "S0-ROOT-04", "started_utc": started,
                  "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "results": res}
        out = pathlib.Path(args.out)
        out.write_text(scrub(json.dumps(report, indent=2, ensure_ascii=False, default=str)) + "\n")
        print(scrub(json.dumps({k: v for k, v in res.items() if not k.startswith("haiku_dated:")}, indent=1, default=str))[:6000])
        return
    bal0 = balance(root_v1, key, scrub)
    with cf.ThreadPoolExecutor(len(MODELS)) as ex:
        futs = {m: ex.submit(probe_model, root_v1, root, key, m, scrub) for m in MODELS}
        results = {}
        for m, f in futs.items():
            try:
                results[m] = f.result()
            except Exception:  # noqa: BLE001
                results[m] = {"model": m, "crash": scrub(traceback.format_exc())[-800:]}
    bal1 = balance(root_v1, key, scrub)
    report = {
        "schema": "pl.relay_probe/1", "task": "S0-ROOT-04", "started_utc": started,
        "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "relay": "OpenAI-compatible third-party relay (host redacted; see the git-ignored .env)",
        "sdk_versions": {"openai": openai.__version__, "anthropic": anthropic.__version__},
        "ttft_calls_per_model": TTFT_N, "ttft_note": "wall clock from the Mac, sequential per model, 5 models in parallel",
        "balance_before": bal0, "balance_after": bal1,
        "summary": {m: summarise(r) for m, r in results.items() if "crash" not in r},
        "results": results,
    }
    text = scrub(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
