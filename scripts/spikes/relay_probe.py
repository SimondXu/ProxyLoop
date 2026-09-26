# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "openai==2.45.0",
#   "anthropic==0.116.0",
#   "google-genai==2.11.0",
#   "httpx",
# ]
# ///
"""S0-ROOT-04 relay capability probe (ADR-0001). Root-run only: needs the relay key.

Reads `base_url` and the relay key from the git-ignored `.env` (`key:value` lines)
at run time, never prints them, and scrubs the relay host and pricing-group label
from everything it writes.

    uv run --no-project scripts/spikes/relay_probe.py --env .env \\
        --out docs/decisions/data/relay-probe.json
    ... --part forced --models claude-sonnet-5,gemini-3.6-flash \\
        --out docs/decisions/data/relay-forced.json
    ... --part cost-input --out docs/decisions/data/relay-cost-input-heavy.json

The same probe against TeamRouter (S0-ROOT-08, ADR-0005; `.env.local` is dotenv style):

    ... --env .env.local --env-format dotenv --task S0-ROOT-08 \\
        --models gemini-3.8-flash --ttft-n 10 \\
        --out docs/decisions/data/teamrouter-probe-main.json
    ... --env .env.local --env-format dotenv --task S0-ROOT-08 --part forced \\
        --models gemini-3.8-flash \\
        --out docs/decisions/data/teamrouter-probe-forced.json
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import pathlib
import re
import statistics
import time
import traceback
from typing import Any

import anthropic
import httpx
import openai
from google import genai
from google.genai import types as gtypes

MODELS = [
    "claude-sonnet-5",
    "claude-haiku-4-5",
    "gemini-3.6-flash",
    "claude-opus-4-8",
    "gemini-3.5-flash",
]
TTFT_N = 20
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_local_time",
            "description": "Current local time for a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    },
]
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["offer_usd", "accepted"],
    "properties": {"offer_usd": {"type": "number"}, "accepted": {"type": "boolean"}},
}
JSON_SCHEMA_TEXT = (
    "The rep offered $65/month and the customer did not accept yet. Report it."
)
JSON_OBJECT_TEXT = (
    'Return JSON {"offer_usd": number, "accepted": boolean}: '
    "the rep offered $65/month, not accepted yet."
)
LONG_STREAM_PROMPT = (
    "In about 150 words of plain prose, explain why a phone bill often rises when a "
    "promotional period ends and what a customer can ask the rep for."
)

ACTS = ["offer", "accept", "reject", "question", "hold", "other"]
ACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["act", "amount_usd"],
    "properties": {
        "act": {"type": "string", "enum": ACTS},
        "amount_usd": {"type": ["number", "null"]},
    },
}
CLASSIFY = {
    "type": "function",
    "function": {
        "name": "classify",
        "description": "Label one rep utterance.",
        "parameters": ACT_SCHEMA,
    },
}
FORCED_CHOICE = {"type": "function", "function": {"name": "classify"}}
FORCED_UTTERANCES = [
    # clear accept
    (
        "Yes, that works. I accept: the $65 per month rate is approved "
        "and applied from today."
    ),
    # numeric offer
    "I can offer you $62.50 a month if you stay with us for twelve more months.",
    # question
    "Can you confirm the last four digits of the account holder's phone number?",
    "I'm sorry, but we can't remove the equipment fee on this plan.",
    "Please hold for a moment while I check with my supervisor.",
    "The best I can do is a $10 monthly credit for six months.",
    "Would you be willing to switch to paperless billing?",
    "No, the promotional rate cannot be extended a second time.",
    "Let me pull up your account; it will just take a second.",
    "Thanks for your patience, I have noted your request on the account.",
]

COST_INPUT_UNIT = (
    "The customer's bill rose from $55 to $80 after the promo ended; "
    "the rep may offer a loyalty credit. "
)
COST_INPUT_REPEAT = 60
COST_INPUT_SUFFIX = "\nReply with one word: ok"
COST_INPUT_PROMPT = COST_INPUT_UNIT * COST_INPUT_REPEAT + COST_INPUT_SUFFIX
COST_NOTE = (
    "total_usage is reported in the OpenAI dashboard unit (cents); "
    "delta covers input+output together"
)

GROUP_RE = re.compile(r"under group [^()]*\(")


# (base variable, key variable) per env-file format.
ENV_VARS = {
    "keyvalue": ("base_url", "备用key2"),
    "dotenv": ("TEAMOROUTER_BASE_URL", "TEAMOROUTER_API_KEY"),
}


def read_env(path: pathlib.Path, fmt: str) -> dict[str, str]:
    kv = {}
    for line in path.read_text().splitlines():
        if fmt == "keyvalue":
            if ":" in line:
                k, v = line.split(":", 1)
                kv[k.strip()] = v.strip()
            continue
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.removeprefix("export ").split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        kv[k.strip()] = v
    return kv


def load_env(
    path: pathlib.Path,
    fmt: str = "keyvalue",
    base_var: str | None = None,
    key_var: str | None = None,
) -> tuple[str, str]:
    """Return (OpenAI-compatible `/v1` root, key).

    keyvalue: `base_url` already ends in `/v1`; dotenv: the API is at BASE_URL + `/v1`.
    """
    default_base, default_key = ENV_VARS[fmt]
    kv = read_env(path, fmt)
    base = kv[base_var or default_base].rstrip("/")
    if fmt == "dotenv":
        base += "/v1"
    return base, kv[key_var or default_key]


class Scrub:
    def __init__(self, *secrets: str) -> None:
        self.secrets = [s for s in secrets if s]

    def __call__(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "<redacted>")
        return GROUP_RE.sub("under group <redacted> (", text)


def err(e: BaseException, scrub: Scrub) -> dict[str, Any]:
    out: dict[str, Any] = {"error_type": type(e).__name__, "error": scrub(str(e))[:400]}
    status = getattr(e, "status_code", None)
    if status is not None:
        out["status_code"] = status
    return out


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def oai_client(root_v1: str, key: str) -> openai.OpenAI:
    return openai.OpenAI(base_url=root_v1, api_key=key, max_retries=0, timeout=90)


def usage_of(r: Any) -> dict[str, Any] | None:
    return r.usage.model_dump() if r.usage else None


def oai_basic(c: openai.OpenAI, model: str) -> dict[str, Any]:
    raw = c.chat.completions.with_raw_response.create(
        model=model,
        max_tokens=64,
        messages=[{"role": "user", "content": "Reply with exactly: pong"}],
    )
    r = raw.parse()
    return {
        "ok": True,
        "response_id": r.id,
        "request_id": raw.headers.get("x-request-id") or raw.headers.get("request-id"),
        "echoed_model": r.model,
        "text": (r.choices[0].message.content or "")[:80],
        "usage": usage_of(r),
    }


def oai_stream(
    c: openai.OpenAI,
    model: str,
    prompt: str = "Count from 1 to 5, comma separated.",
    max_tokens: int = 48,
    gaps: bool = False,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    ttft = last = None
    rid = echoed = None
    usage = None
    text: list[str] = []
    gap_list: list[float] = []
    stream = c.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        stream=True,
        stream_options={"include_usage": True},
        messages=[{"role": "user", "content": prompt}],
    )
    for ch in stream:
        rid = rid or ch.id
        echoed = echoed or ch.model
        if ch.usage:
            usage = ch.usage.model_dump()
        if ch.choices and ch.choices[0].delta and ch.choices[0].delta.content:
            now = time.perf_counter()
            if ttft is None:
                ttft = now - t0
            if last is not None:
                gap_list.append(round(now - last, 4))
            last = now
            text.append(ch.choices[0].delta.content)
    out = {
        "ttft_s": ttft,
        "total_s": time.perf_counter() - t0,
        "response_id": rid,
        "echoed_model": echoed,
        "usage": usage,
        "content_chunks": len(text),
        "text": "".join(text)[:80],
    }
    if gaps:
        out["gaps_s"] = gap_list
    return out


def oai_tools(c: openai.OpenAI, model: str) -> dict[str, Any]:
    r = c.chat.completions.create(
        model=model,
        max_tokens=256,
        tools=TOOLS,
        parallel_tool_calls=True,
        messages=[
            {
                "role": "user",
                "content": (
                    "Call get_weather AND get_local_time for Paris, "
                    "both in this one turn."
                ),
            }
        ],
    )
    calls = r.choices[0].message.tool_calls or []
    parsed = []
    for tc in calls:
        try:
            parsed.append(
                {
                    "name": tc.function.name,
                    "args": json.loads(tc.function.arguments),
                    "valid_json": True,
                }
            )
        except json.JSONDecodeError:
            parsed.append(
                {
                    "name": tc.function.name,
                    "args_raw": tc.function.arguments[:120],
                    "valid_json": False,
                }
            )
    names = {p["name"] for p in parsed}
    return {
        "response_id": r.id,
        "echoed_model": r.model,
        "n_tool_calls": len(calls),
        "calls": parsed,
        "tool_calls_ok": bool(calls) and all(p["valid_json"] for p in parsed),
        "parallel_ok": {"get_weather", "get_local_time"} <= names,
        "usage": usage_of(r),
    }


def oai_json_schema(c: openai.OpenAI, model: str) -> dict[str, Any]:
    r = c.chat.completions.create(
        model=model,
        max_tokens=128,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "offer", "schema": SCHEMA, "strict": True},
        },
        messages=[{"role": "user", "content": JSON_SCHEMA_TEXT}],
    )
    txt = r.choices[0].message.content or ""
    try:
        obj = json.loads(txt)
        ok = (
            isinstance(obj, dict)
            and set(obj) == {"offer_usd", "accepted"}
            and isinstance(obj["accepted"], bool)
        )
    except json.JSONDecodeError:
        obj, ok = None, False
    return {
        "response_id": r.id,
        "echoed_model": r.model,
        "json_schema_ok": ok,
        "raw": txt[:160],
        "usage": usage_of(r),
    }


def oai_json_object(c: openai.OpenAI, model: str) -> dict[str, Any]:
    r = c.chat.completions.create(
        model=model,
        max_tokens=128,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": JSON_OBJECT_TEXT}],
    )
    txt = r.choices[0].message.content or ""
    try:
        json.loads(txt)
        ok = True
    except json.JSONDecodeError:
        ok = False
    return {
        "response_id": r.id,
        "echoed_model": r.model,
        "json_object_ok": ok,
        "raw": txt[:160],
        "usage": usage_of(r),
    }


def oai_plain(c: openai.OpenAI, model: str, text: str) -> dict[str, Any]:
    """Control: the same user text with no response_format, for prompt-token parity."""
    r = c.chat.completions.create(
        model=model, max_tokens=128, messages=[{"role": "user", "content": text}]
    )
    return {
        "response_id": r.id,
        "echoed_model": r.model,
        "prompt_tokens": r.usage.prompt_tokens if r.usage else None,
        "usage": usage_of(r),
    }


def validate_act(obj: Any) -> list[str]:
    """Stdlib validator for exactly ACT_SCHEMA.

    Returns the list of violations (empty = valid).
    """
    if not isinstance(obj, dict):
        return ["not an object"]
    errs = [f"missing:{k}" for k in ACT_SCHEMA["required"] if k not in obj]
    errs += [f"extra:{k}" for k in obj if k not in ACT_SCHEMA["properties"]]
    if "act" in obj and not (isinstance(obj["act"], str) and obj["act"] in ACTS):
        errs.append("act:not_in_enum")
    amt = obj.get("amount_usd")
    if "amount_usd" in obj and not (
        amt is None or (isinstance(amt, (int, float)) and not isinstance(amt, bool))
    ):
        errs.append("amount_usd:not_number_or_null")
    return errs


def oai_forced(c: openai.OpenAI, model: str, utterance: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    r = c.chat.completions.create(
        model=model,
        max_tokens=128,
        tools=[CLASSIFY],
        tool_choice=FORCED_CHOICE,
        messages=[
            {
                "role": "user",
                "content": f"Classify this customer-service rep utterance: {utterance}",
            }
        ],
    )
    latency = time.perf_counter() - t0
    calls = r.choices[0].message.tool_calls or []
    one = len(calls) == 1 and calls[0].function.name == "classify"
    out: dict[str, Any] = {
        "response_id": r.id,
        "echoed_model": r.model,
        "usage": usage_of(r),
        "latency_s": latency,
        "n_tool_calls": len(calls),
        "tool_names": [t.function.name for t in calls],
        "forced_ok": one,
        "args_json": False,
        "schema_valid": False,
    }
    if one:
        raw = calls[0].function.arguments
        try:
            args = json.loads(raw)
        except json.JSONDecodeError:
            out["args_raw"] = raw[:160]
            return out
        errs = validate_act(args)
        out.update(args_json=True, args=args, schema_errors=errs, schema_valid=not errs)
    return out


def forced_model(
    root_v1: str, key: str, model: str, n: int, scrub: Scrub
) -> dict[str, Any]:
    c = oai_client(root_v1, key)
    calls = []
    for i in range(n):
        u = FORCED_UTTERANCES[i % len(FORCED_UTTERANCES)]
        try:
            calls.append(
                {"utterance_idx": i % len(FORCED_UTTERANCES), **oai_forced(c, model, u)}
            )
        except Exception as e:
            calls.append({"utterance_idx": i % len(FORCED_UTTERANCES), **err(e, scrub)})
    return {"model": model, "calls": calls}


SKIPPED = {"skipped": "not applicable to this endpoint"}


def reasoning_summary(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Median reasoning tokens over the calls whose usage reports them."""
    details = [(x.get("usage") or {}).get("completion_tokens_details") for x in calls]
    vals = [
        d["reasoning_tokens"]
        for d in details
        if d and d.get("reasoning_tokens") is not None
    ]
    return {
        "reasoning_tokens_p50": statistics.median(vals) if vals else None,
        "reasoning_tokens_n": len(vals),
    }


def summarise_forced(r: dict[str, Any]) -> dict[str, Any]:
    calls = r["calls"]
    n = len(calls)
    lat = [x["latency_s"] for x in calls if x.get("latency_s") is not None]
    return {
        "n": n,
        "errors": sum("error" in x for x in calls),
        "forced_ok_rate": sum(bool(x.get("forced_ok")) for x in calls) / n
        if n
        else None,
        "schema_valid_rate": sum(bool(x.get("schema_valid")) for x in calls) / n
        if n
        else None,
        "latency_p50_s": statistics.median(lat) if lat else None,
        **reasoning_summary(calls),
    }


def anthropic_native(root: str, key: str, model: str) -> dict[str, Any]:
    c = anthropic.Anthropic(base_url=root, api_key=key, max_retries=0, timeout=60)
    raw = c.messages.with_raw_response.create(
        model=model,
        max_tokens=64,
        messages=[{"role": "user", "content": "Reply with exactly: pong"}],
    )
    m = raw.parse()
    tool = c.messages.create(
        model=model,
        max_tokens=256,
        tools=[
            {
                "name": t["function"]["name"],
                "description": t["function"]["description"],
                "input_schema": t["function"]["parameters"],
            }
            for t in TOOLS
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    "Call get_weather AND get_local_time for Paris, "
                    "both in this one turn."
                ),
            }
        ],
    )
    uses = [b for b in tool.content if b.type == "tool_use"]
    return {
        "ok": True,
        "message_id": m.id,
        "request_id": raw.headers.get("request-id") or raw.headers.get("x-request-id"),
        "echoed_model": m.model,
        "text": "".join(b.text for b in m.content if b.type == "text")[:80],
        "usage": m.usage.model_dump(),
        "tool_use_n": len(uses),
        "tool_use_names": [u.name for u in uses],
        "tool_message_id": tool.id,
    }


def gemini_native(root: str, key: str, model: str) -> dict[str, Any]:
    c = genai.Client(
        api_key=key, http_options=gtypes.HttpOptions(base_url=root, timeout=60_000)
    )
    r = c.models.generate_content(model=model, contents="Reply with exactly: pong")
    um = r.usage_metadata
    return {
        "ok": True,
        "response_id": getattr(r, "response_id", None),
        "echoed_model": getattr(r, "model_version", None),
        "text": (r.text or "")[:80],
        "usage": {
            "prompt": um.prompt_token_count,
            "candidates": um.candidates_token_count,
        }
        if um
        else None,
    }


def balance(root_v1: str, key: str, scrub: Scrub) -> dict[str, Any]:
    out: dict[str, Any] = {}
    h = {"Authorization": f"Bearer {key}", "User-Agent": "OpenAI/Python 2.45.0"}
    for path in ("/dashboard/billing/subscription", "/dashboard/billing/usage"):
        try:
            r = httpx.get(root_v1 + path, headers=h, timeout=20)
            out[path] = {
                "status": r.status_code,
                "body": json.loads(r.text)
                if r.headers.get("content-type", "").startswith("application/json")
                else scrub(r.text[:200]),
            }
        except Exception as e:
            out[path] = err(e, scrub)
    return out


def probe_model(
    root_v1: str,
    root: str,
    key: str,
    model: str,
    scrub: Scrub,
    ttft_n: int = TTFT_N,
    stream_max_tokens: int = 48,
    native_route: bool = True,
) -> dict[str, Any]:
    c = oai_client(root_v1, key)
    res: dict[str, Any] = {"model": model}
    for name, fn in (
        ("openai_basic", lambda: oai_basic(c, model)),
        ("tools", lambda: oai_tools(c, model)),
        ("json_schema", lambda: oai_json_schema(c, model)),
        ("json_object", lambda: oai_json_object(c, model)),
        ("json_control_schema_text", lambda: oai_plain(c, model, JSON_SCHEMA_TEXT)),
        ("json_control_object_text", lambda: oai_plain(c, model, JSON_OBJECT_TEXT)),
        (
            "long_stream",
            lambda: oai_stream(c, model, LONG_STREAM_PROMPT, max_tokens=300, gaps=True),
        ),
    ):
        try:
            res[name] = fn()
        except Exception as e:
            res[name] = err(e, scrub)
    streams = []
    for _ in range(ttft_n):
        try:
            streams.append(oai_stream(c, model, max_tokens=stream_max_tokens))
        except Exception as e:
            streams.append(err(e, scrub))
    res["streams"] = streams
    ttfts = [s["ttft_s"] for s in streams if s.get("ttft_s") is not None]
    res["ttft_p50_s"] = statistics.median(ttfts) if ttfts else None
    res["ttft_n_ok"] = len(ttfts)
    res["stream_usage_ok"] = sum(bool(s.get("usage")) for s in streams)
    if not native_route:
        res["native"] = dict(SKIPPED)
        return res
    native = anthropic_native if model.startswith("claude") else gemini_native
    try:
        res["native"] = {
            "route": "anthropic /v1/messages"
            if model.startswith("claude")
            else "gemini generateContent",
            **native(root, key, model),
        }
    except Exception as e:
        res["native"] = {
            "route": "anthropic /v1/messages"
            if model.startswith("claude")
            else "gemini generateContent",
            "ok": False,
            **err(e, scrub),
        }
    return res


def summarise(r: dict[str, Any]) -> dict[str, Any]:
    def ok(d: Any) -> bool:
        return isinstance(d, dict) and "error" not in d

    def pt(k: str) -> Any:
        return (
            (r.get(k, {}).get("usage") or {}).get("prompt_tokens")
            if ok(r.get(k))
            else None
        )

    n_streams = len(r["streams"])
    return {
        "available": ok(r["openai_basic"]),
        "echoed_model": r["openai_basic"].get("echoed_model")
        if ok(r["openai_basic"])
        else None,
        "streaming": {"ok": r["ttft_n_ok"], "n": n_streams},
        "streaming_usage": {"ok": r["stream_usage_ok"], "n": n_streams},
        "tool_calls": ok(r["tools"]) and r["tools"]["tool_calls_ok"],
        "parallel_tool_calls": ok(r["tools"]) and r["tools"]["parallel_ok"],
        "json_schema": ok(r["json_schema"]) and r["json_schema"]["json_schema_ok"],
        "json_object": ok(r.get("json_object")) and r["json_object"]["json_object_ok"],
        "json_prompt_tokens": {
            k: pt(k)
            for k in (
                "json_schema",
                "json_control_schema_text",
                "json_object",
                "json_control_object_text",
            )
        },
        "long_stream_chunks": r["long_stream"].get("content_chunks")
        if ok(r.get("long_stream"))
        else None,
        "native_route": None
        if "skipped" in r["native"]
        else bool(r["native"].get("ok")),
        "native_tool_use": r["native"].get("tool_use_n", 0) >= 2
        if r["model"].startswith("claude")
        else None,
        "ttft_p50_s": r["ttft_p50_s"],
        "ttft_n_ok": r["ttft_n_ok"],
        "streams_reasoning": reasoning_summary(r["streams"]),
    }


def gemini_native_structured(root: str, key: str, model: str) -> dict[str, Any]:
    c = genai.Client(
        api_key=key, http_options=gtypes.HttpOptions(base_url=root, timeout=60_000)
    )
    r = c.models.generate_content(
        model=model,
        contents=(
            "The rep offered $65/month and the customer did not accept yet. Report it."
        ),
        config=gtypes.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema={
                "type": "OBJECT",
                "required": ["offer_usd", "accepted"],
                "properties": {
                    "offer_usd": {"type": "NUMBER"},
                    "accepted": {"type": "BOOLEAN"},
                },
            },
        ),
    )
    try:
        obj = json.loads(r.text or "")
        schema_ok = isinstance(obj, dict) and set(obj) == {"offer_usd", "accepted"}
    except json.JSONDecodeError:
        schema_ok = False
    decls = [
        gtypes.FunctionDeclaration(
            name=t["function"]["name"],
            description=t["function"]["description"],
            parameters=t["function"]["parameters"],
        )
        for t in TOOLS
    ]
    f = c.models.generate_content(
        model=model,
        contents=(
            "Call get_weather AND get_local_time for Paris, both in this one turn."
        ),
        config=gtypes.GenerateContentConfig(
            tools=[gtypes.Tool(function_declarations=decls)],
            automatic_function_calling=gtypes.AutomaticFunctionCallingConfig(
                disable=True
            ),
        ),
    )
    calls = f.function_calls or []
    return {
        "json_schema_ok": schema_ok,
        "json_raw": (r.text or "")[:160],
        "function_calls": [
            {"name": fc.name, "args": dict(fc.args or {})} for fc in calls
        ],
        "parallel_ok": {"get_weather", "get_local_time"} <= {fc.name for fc in calls},
    }


def usage_total(root_v1: str, key: str) -> float:
    r = httpx.get(
        root_v1 + "/dashboard/billing/usage",
        headers={"Authorization": f"Bearer {key}"},
        timeout=20,
    )
    r.raise_for_status()
    return float(r.json()["total_usage"])


def cost_probe(
    root_v1: str,
    key: str,
    model: str,
    scrub: Scrub,
    n: int = 4,
    max_tokens: int = 150,
    prompt: str = (
        "Summarise in about 80 words why phone bills rise after promotional "
        "periods end. "
    )
    * 8,
    sleep_s: float = 8,
) -> dict[str, Any]:
    """Sequential, one model at a time: usage delta over n fixed calls.

    Units are as the relay reports them.
    """
    c = oai_client(root_v1, key)
    started = utc()
    before = usage_total(
        root_v1, key
    )  # no baseline -> no attribution: the caller's guard records it
    calls = []
    for _ in range(n):
        try:
            r = c.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            calls.append(
                {"response_id": r.id, "echoed_model": r.model, "usage": usage_of(r)}
            )
        except Exception as e:
            calls.append(err(e, scrub))
    time.sleep(sleep_s)
    out: dict[str, Any] = {"calls": n, "calls_ok": sum("error" not in x for x in calls)}
    try:
        after: float | None = usage_total(root_v1, key)
    except Exception as e:
        after, out["usage_after_error"] = None, err(e, scrub)
    good = [x for x in calls if "error" not in x]

    def tok(k: str) -> Any:
        return sum((x["usage"] or {}).get(k) or 0 for x in good)

    out.update(
        {
            "response_ids": [x["response_id"] for x in good],
            "echoed_models": [x["echoed_model"] for x in good],
            "prompt_tokens": tok("prompt_tokens"),
            "completion_tokens": tok("completion_tokens"),
            "usage_before": before,
            "usage_after": after,
            "usage_delta": round(after - before, 6) if after is not None else None,
            "started_utc": started,
            "finished_utc": utc(),
            "per_call": calls,
            "note": COST_NOTE,
        }
    )
    return out


def followup(root_v1: str, root: str, key: str, scrub: Scrub) -> dict[str, Any]:
    out: dict[str, Any] = {}

    def guard(name: str, fn: Any) -> None:
        try:
            out[name] = fn()
        except Exception as e:
            out[name] = err(e, scrub)

    for m in ("gemini-3.6-flash", "gemini-3.5-flash"):
        guard(
            f"gemini_native_structured:{m}",
            lambda m=m: gemini_native_structured(root, key, m),
        )
    c = oai_client(root_v1, key)
    for m in ("claude-sonnet-5", "gemini-3.6-flash"):
        guard(f"json_object:{m}", lambda m=m: oai_json_object(c, m))
    guard(
        "haiku_dated:claude-haiku-4-5-20251001",
        lambda: probe_model(root_v1, root, key, "claude-haiku-4-5-20251001", scrub),
    )
    if "error" not in out["haiku_dated:claude-haiku-4-5-20251001"]:
        out["haiku_dated_summary"] = summarise(
            out["haiku_dated:claude-haiku-4-5-20251001"]
        )
    for m in (
        "claude-sonnet-5",
        "claude-haiku-4-5-20251001",
        "gemini-3.6-flash",
        "claude-opus-4-8",
        "gemini-3.5-flash",
    ):
        guard(f"cost:{m}", lambda m=m: cost_probe(root_v1, key, m, scrub))
    return out


def cost_input(
    root_v1: str, key: str, models: list[str], scrub: Scrub
) -> dict[str, Any]:
    """Input-heavy cost pass.

    3 calls x max_tokens=5 per model, sequential so usage deltas attribute.
    """
    params = {"repeats": 3, "max_tokens": 5, "sleep_s": 8}
    started = utc()
    results: dict[str, Any] = {}
    for m in models:
        try:
            results[m] = cost_probe(
                root_v1,
                key,
                m,
                scrub,
                n=params["repeats"],
                max_tokens=params["max_tokens"],
                prompt=COST_INPUT_PROMPT,
                sleep_s=params["sleep_s"],
            )
        except Exception as e:
            results[m] = err(e, scrub)
    return {
        "schema": "pl.relay_cost_input_heavy/2",
        "task": "S0-ROOT-04",
        "started_utc": started,
        "finished_utc": utc(),
        "models": models,
        "params": {
            **params,
            "prompt_unit": COST_INPUT_UNIT,
            "prompt_repeat": COST_INPUT_REPEAT,
            "prompt_suffix": COST_INPUT_SUFFIX,
            "prompt_chars": len(COST_INPUT_PROMPT),
        },
        "note": COST_NOTE,
        "results": results,
    }


def run_parallel(models: list[str], fn: Any, scrub: Scrub) -> dict[str, Any]:
    """One worker per model; a crashed worker is recorded, never dropped."""
    results: dict[str, Any] = {}
    with cf.ThreadPoolExecutor(max(1, len(models))) as ex:
        futs = {m: ex.submit(fn, m) for m in models}
        for m, f in futs.items():
            try:
                results[m] = f.result()
            except Exception:
                results[m] = {"model": m, "crash": scrub(traceback.format_exc())[-800:]}
    return results


def summary_of(results: dict[str, Any], fn: Any) -> dict[str, Any]:
    return {m: {"crashed": True} if "crash" in r else fn(r) for m, r in results.items()}


RELAY_NOTE = (
    "OpenAI-compatible third-party relay (host redacted; see the git-ignored .env)"
)


def main_part(
    root_v1: str,
    root: str,
    key: str,
    scrub: Scrub,
    models: list[str],
    ttft_n: int,
    relay: str = RELAY_NOTE,
    stream_max_tokens: int = 48,
    relay_extras: bool = True,
) -> dict[str, Any]:
    """`relay_extras`: the billing balance and native routes of the original relay."""
    started = utc()
    bal0 = balance(root_v1, key, scrub) if relay_extras else dict(SKIPPED)
    results = run_parallel(
        models,
        lambda m: probe_model(
            root_v1, root, key, m, scrub, ttft_n, stream_max_tokens, relay_extras
        ),
        scrub,
    )
    bal1 = balance(root_v1, key, scrub) if relay_extras else dict(SKIPPED)
    return {
        "schema": "pl.relay_probe/2",
        "task": "S0-ROOT-04",
        "started_utc": started,
        "finished_utc": utc(),
        "relay": relay,
        "sdk_versions": {
            "openai": openai.__version__,
            "anthropic": anthropic.__version__,
        },
        "models": models,
        "ttft_calls_per_model": ttft_n,
        "ttft_stream_max_tokens": stream_max_tokens,
        "ttft_note": (
            "wall clock from the Mac, sequential per model, "
            f"{len(models)} models in parallel"
        ),
        "balance_before": bal0,
        "balance_after": bal1,
        "summary": summary_of(results, summarise),
        "results": results,
    }


def forced_part(
    root_v1: str, key: str, scrub: Scrub, models: list[str], n: int
) -> dict[str, Any]:
    started = utc()
    results = run_parallel(
        models, lambda m: forced_model(root_v1, key, m, n, scrub), scrub
    )
    return {
        "schema": "pl.relay_forced_tool/1",
        "task": "S0-ROOT-04",
        "started_utc": started,
        "finished_utc": utc(),
        "models": models,
        "calls_per_model": n,
        "tool": CLASSIFY,
        "tool_choice": FORCED_CHOICE,
        "utterances": FORCED_UTTERANCES,
        "latency_note": (
            "wall clock from the Mac, sequential per model, "
            f"{len(models)} models in parallel"
        ),
        "summary": summary_of(results, summarise_forced),
        "results": results,
    }


def write(path: str, report: dict[str, Any], scrub: Scrub) -> None:
    out = pathlib.Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        scrub(json.dumps(report, indent=2, ensure_ascii=False, default=str)) + "\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=".env")
    ap.add_argument(
        "--env-format",
        choices=sorted(ENV_VARS),
        default="keyvalue",
        help=(
            "keyvalue: `name: value` lines, base_url ends in /v1 (the relay .env); "
            "dotenv: `NAME=value` lines, the API is at BASE_URL + /v1 (TeamRouter)"
        ),
    )
    ap.add_argument(
        "--base-var",
        help="env variable holding the base URL (default: base_url | "
        "TEAMOROUTER_BASE_URL by format)",
    )
    ap.add_argument(
        "--key-var",
        help="env variable holding the key (default: 备用key2 | "
        "TEAMOROUTER_API_KEY by format)",
    )
    ap.add_argument(
        "--task",
        default="S0-ROOT-04",
        help="task id written into the report (--part main|forced|cost-input)",
    )
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--part", choices=["main", "followup", "forced", "cost-input"], default="main"
    )
    ap.add_argument(
        "--models",
        help="comma-separated; overrides MODELS for --part main|forced|cost-input",
    )
    ap.add_argument(
        "--ttft-n",
        type=int,
        default=TTFT_N,
        help="TTFT streams per model (--part main)",
    )
    ap.add_argument(
        "--stream-max-tokens",
        type=int,
        default=48,
        help="max_tokens of each TTFT stream (--part main)",
    )
    ap.add_argument(
        "--forced-n",
        type=int,
        default=10,
        help="forced tool calls per model (--part forced)",
    )
    args = ap.parse_args()
    models = (
        [m.strip() for m in args.models.split(",") if m.strip()]
        if args.models is not None
        else list(MODELS)
    )
    if not models:
        ap.error("--models is empty")
    env_path = pathlib.Path(args.env)
    root_v1, key = load_env(env_path, args.env_format, args.base_var, args.key_var)
    root = root_v1.removesuffix("/v1")
    relay = (
        RELAY_NOTE
        if args.env_format == "keyvalue"
        else f"OpenAI-compatible endpoint (host redacted; see the git-ignored "
        f"{env_path.name})"
    )
    host = httpx.URL(root).host
    scrub = Scrub(key, root_v1, root, host)
    if args.part == "followup":
        started = utc()
        res = followup(root_v1, root, key, scrub)
        write(
            args.out,
            {
                "schema": "pl.relay_probe_followup/1",
                "task": "S0-ROOT-04",
                "started_utc": started,
                "finished_utc": utc(),
                "results": res,
            },
            scrub,
        )
        print(
            scrub(
                json.dumps(
                    {k: v for k, v in res.items() if not k.startswith("haiku_dated:")},
                    indent=1,
                    default=str,
                )
            )[:6000]
        )
        return
    if args.part == "forced":
        report = forced_part(root_v1, key, scrub, models, args.forced_n)
    elif args.part == "cost-input":
        report = cost_input(root_v1, key, models, scrub)
        report["summary"] = {
            m: {
                k: r.get(k)
                for k in (
                    "calls_ok",
                    "prompt_tokens",
                    "completion_tokens",
                    "usage_delta",
                )
            }
            if "error" not in r
            else r
            for m, r in report["results"].items()
        }
    else:
        report = main_part(
            root_v1,
            root,
            key,
            scrub,
            models,
            args.ttft_n,
            relay,
            args.stream_max_tokens,
            relay_extras=args.env_format == "keyvalue",
        )
    report["task"] = args.task
    write(args.out, report, scrub)
    print(scrub(json.dumps(report["summary"], indent=2, default=str)))


if __name__ == "__main__":
    main()
