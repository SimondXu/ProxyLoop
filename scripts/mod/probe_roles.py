"""S0-ROOT-12 model role probe (root-run, flag L): recorded requests, new models.

Replays requests of one run bundle through production code only (``make_client`` on
``teamrouter``, the contract renderer and parser, Slow's ``act``, the Ear's recorded
``classify`` tool and ``check_act``): Slow and Ear on ``gemini-3.8-flash``, the
integration Fast on ``gpt-6-luna``. One part per run, so the TeamRouter balance can
be read between parts (ADR-0001's usage-delta method):

    uv run python scripts/mod/probe_roles.py --run runs/<id> --part slow --plan
    uv run python scripts/mod/probe_roles.py --run runs/<id> --part slow --out <json>

The adapter reads ``PL_TEAMROUTER_BASE_URL``/``_API_KEY`` from the environment;
nothing reads ``.env``. ``--plan`` calls nothing and projects tokens from the
recorded usage. Calls run one at a time, never retried beyond the adapter's rule:
an HTTP 400/422 is a rejection recorded for that call, any other failure is
recorded and aborts the part (exit 1). The summary is rewritten after every call.
Percentiles are nearest-rank; latencies are measured here, through the relay.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

from proxyloop.cli import WORLD_EFFORT, live_config
from proxyloop.contract import llm
from proxyloop.contract.base import Lane, sha256_text
from proxyloop.contract.bundle import Bundle, read_bundle
from proxyloop.contract.protocol import ParseIssue, Speech, parse_turn, render_messages
from proxyloop.contract.views import FastView
from proxyloop.env import world
from proxyloop.env.counterparty.ear import check_act
from proxyloop.env.tasks.loader import load_task
from proxyloop.llm.factory import make_client
from proxyloop.llm.http import HTTPAdapter
from proxyloop.slow import prompt as slow_prompt

Json = dict[str, Any]
Effort = llm.ReasoningEffort | None  # None: the provider default
MODELS = {"slow": "gemini-3.8-flash", "ear": "gemini-3.8-flash", "fast": "gpt-6-luna"}
ARMS: dict[str, tuple[Effort, ...]] = {"slow": ("low", None), "fast": (None,)}
ARMS["ear"] = ("none", "minimal", "low", None)
N = {"slow": 24, "fast": 20, "ear": 20}
REJECTED = {400, 422}
RULE = (
    "evenly spaced in log order, index floor((2i+1)N/2n); fast: n/2 per lane;"
    " arms run in listed order on even items, reversed on odd ones"
)
FAST_ROLE: dict[Lane, llm.LLMRole] = {"user": "fast_user", "cp": "fast_cp"}
SAMPLING = live_config(MODELS["fast"], WORLD_EFFORT, 0).fast_sampling  # the CLI's


@dataclass(frozen=True)
class Item:
    source: str  # the recorded call_id
    t_ms: int
    usage: llm.Usage | None  # as recorded
    request: llm.TextRequest | llm.ToolRequest
    lane: Lane = "user"
    heard: str = ""
    offers: tuple[str, ...] = ()
    keys: tuple[str, ...] = ()


def label(effort: Effort) -> str:
    return effort or "default"


def spread[T](xs: list[T], n: int) -> list[T]:
    if n >= len(xs):
        return xs
    return [xs[(2 * i + 1) * len(xs) // (2 * n)] for i in range(n)]


Call = tuple[int, llm.LLMCallRecord, tuple[str, ...]]  # (t_ms, last record, causes)


def calls_of(bundle: Bundle, role: str) -> list[Call]:
    """Each call's last record, in first-appearance order."""
    out: dict[str, Call] = {}
    for e in bundle.events:
        if e.type == "llm.call" and e.payload["role"] == role:
            rec = llm.LLMCallRecord.model_validate(e.payload)
            t = out[rec.call_id][0] if rec.call_id in out else e.t_ms
            out[rec.call_id] = (t, rec, e.cause_ids)
    return list(out.values())


def recorded(bundle: Bundle, rec: llm.LLMCallRecord) -> tuple[Json, Json]:
    """The recorded request body, and the request fields it gives back."""
    body: Json = json.loads(bundle.prompts[rec.prompt_sha].content)
    msgs = tuple(llm.ChatMessage.model_validate(m) for m in body["messages"])
    return body, {"call_id": "-", "role": rec.role, "messages": msgs}


def select_slow(bundle: Bundle) -> list[Item]:
    """As ``SlowLoop.step`` builds the request: ``act`` forced, no temperature."""
    act: Json = {"tools": (slow_prompt.ACT,), "tool_choice": slow_prompt.ACT.name}
    act["max_tokens"] = slow_prompt.MAX_TOKENS
    return [
        Item(
            rec.call_id,
            t,
            rec.usage,
            llm.ToolRequest(**recorded(bundle, rec)[1], **act),
        )
        for t, rec, _ in calls_of(bundle, "slow")
    ]


def select_ear(bundle: Bundle) -> list[Item]:
    """As ``Ear.classify`` builds it, with its recorded tool; first attempts only."""
    task = load_task(bundle.manifest.task_ref.split("@")[0])
    keys = tuple(task.counterparty.identity)
    by_id = {e.event_id: e for e in bundle.events}
    items: list[Item] = []
    for t, rec, causes in calls_of(bundle, "ear"):
        if not rec.call_id.endswith(":0"):
            continue
        body, args = recorded(bundle, rec)
        (tool,) = (llm.ToolSpec.model_validate(x) for x in body["tools"])
        args |= {"tools": (tool,), "tool_choice": "classify", "temperature": 0}
        request = llm.ToolRequest(**args, max_tokens=world.MAX_TOKENS)
        offer = cast(Json, tool.parameters["properties"]).get("offer_ref", {})
        heard = str(by_id[causes[0]].payload["text_heard"])  # the utt.delivered
        offers = tuple(offer.get("enum", ()))
        items.append(
            Item(rec.call_id, t, rec.usage, request, "cp", heard, offers, keys)
        )
    return items


def select_fast(bundle: Bundle, lane: Lane) -> list[Item]:
    """As ``FastLane._request`` builds it for a chat endpoint, with CLI sampling."""
    usage = {r.call_id: r.usage for _, r, _ in calls_of(bundle, FAST_ROLE[lane])}
    sampling = SAMPLING.model_dump(include={"max_tokens", "temperature", "top_p"})
    items: list[Item] = []
    for e in bundle.events:
        if e.type != "fast.request" or e.payload["lane"] != lane:
            continue
        p, k = e.payload, int(str(e.payload["gen_id"]).split("-g")[1])
        view = FastView.model_validate_json(bundle.prompts[str(p["view_sha"])].content)
        seed = int(sha256_text(f"{bundle.manifest.cfg.seed}:{lane}:{k}")[:8], 16)
        messages = render_messages(view, str(p["profile"]))
        args: Json = {"call_id": "-", "role": FAST_ROLE[lane], "seed": seed}
        request = llm.TextRequest(**args, messages=messages, **sampling)
        source = f"{FAST_ROLE[lane]}:{k}"
        items.append(Item(source, e.t_ms, usage.get(source), request, lane))
    return items


def select(bundle: Bundle, part: str, n: int) -> list[Item]:
    if part != "fast":
        return spread((select_slow if part == "slow" else select_ear)(bundle), n)
    lanes: tuple[Lane, ...] = ("user", "cp")
    return [x for lane in lanes for x in spread(select_fast(bundle, lane), n // 2)]


_KEYS = {"type", "properties", "required", "enum", "items", "description"}
SCHEMA_KEYS = _KEYS | {"maxLength", "minimum", "maximum", "additionalProperties"}
_TYPES: dict[str, type | tuple[type, ...]] = {"object": dict, "array": list}
TYPES = _TYPES | {
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
}


def violations(value: object, schema: Json, path: str = "$") -> list[str]:
    """The JSON-schema subset ACT uses; any other keyword raises, never passes."""
    if unknown := set(schema) - SCHEMA_KEYS:
        raise ValueError(f"unsupported schema keywords {sorted(unknown)}")
    out = [f"{path}: not in enum"] if value not in schema.get("enum", [value]) else []
    kind = schema.get("type")
    numeric_bool = kind in ("integer", "number") and isinstance(value, bool)
    if kind and (not isinstance(value, TYPES[kind]) or numeric_bool):
        return [*out, f"{path}: not {kind}"]
    if isinstance(value, dict):
        obj, props = cast(Json, value), cast(Json, schema.get("properties", {}))
        out += [
            f"{path}.{k}: missing" for k in schema.get("required", ()) if k not in obj
        ]
        for k, v in obj.items():
            if k in props:
                out += violations(v, props[k], f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                out.append(f"{path}.{k}: not allowed")
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(cast(list[object], value)):
            out += violations(v, schema["items"], f"{path}[{i}]")
    if isinstance(value, str) and len(value) > schema.get("maxLength", math.inf):
        out.append(f"{path}: longer than {schema['maxLength']}")
    low, high = schema.get("minimum", -math.inf), schema.get("maximum", math.inf)
    if isinstance(value, int) and not low <= value <= high:
        out.append(f"{path}: out of range")
    return out


def judge_slow(calls: tuple[llm.ToolCall, ...]) -> Json:
    """Valid: at least one call, and every call is ``act`` with schema-valid args."""
    bad, n_valid = [] if calls else ["no tool call"], 0
    for i, c in enumerate(calls):
        v = [] if c.name == slow_prompt.ACT.name else [f"name {c.name[:40]!r}"]
        try:
            v += violations(json.loads(c.arguments), slow_prompt.ACT.parameters)
        except json.JSONDecodeError:
            v.append("arguments are not JSON")
        n_valid += not v
        bad += [f"call {i}: {x}" for x in v]
    out: Json = {"n_calls": len(calls), "n_valid_calls": n_valid}
    return out | {"valid": not bad, "invalid": bad[:5]}


def judge_ear(item: Item, calls: tuple[llm.ToolCall, ...]) -> Json:
    try:
        act = check_act(calls, item.heard, item.offers, item.keys)
    except world.Invalid as err:
        return {"valid": False, "act": None, "invalid": str(err)[:200]}
    return {"valid": True, "act": act.act}


async def one(part: str, client: llm.LLMClient, item: Item, call_id: str) -> Json:
    """One call and its row; ``fatal`` marks a failure that aborts the part."""
    request = item.request.model_copy(update={"call_id": call_id})
    out: Json = {"source": item.source, "t_ms": item.t_ms}
    try:
        if isinstance(request, llm.TextRequest):
            text, rec = "", None
            async for delta in client.stream_text(request):
                if isinstance(delta, llm.LLMCallRecord):
                    rec = delta
                else:
                    text += delta
            assert rec is not None, "every call ends with its record"
            turn = parse_turn(text, item.lane)
            out |= {"lane": item.lane, "text_chars": len(text), "relay_measured": True}
            out["n_speech"] = sum(isinstance(i, Speech) for i in turn)
            out["issues"] = [i.reason for i in turn if isinstance(i, ParseIssue)]
        else:
            resp = await client.chat_tools(request)
            rec, calls = resp.record, resp.tool_calls
            out |= judge_slow(calls) if part == "slow" else judge_ear(item, calls)
    except llm.LLMUnavailable as exc:
        rec = exc.record
        status = re.match(r"EndpointError: HTTP (\d{3})", rec.error or "")
        rejected = status is not None and int(status.group(1)) in REJECTED
        out |= {"rejected": rejected, "fatal": not rejected}
    first, usage = rec.t_first_token, rec.usage
    out |= {"call_id": call_id, "served_model_echo": rec.served_model_echo}
    out |= {"request_id": rec.request_id, "finish_reason": rec.finish_reason}
    out |= {
        "error": rec.error and rec.error[:300],
        "latency_ms": rec.t_end - rec.t_start,
    }
    out["ttft_ms"] = None if first is None else first - rec.t_start
    return out | {"usage": usage and usage.model_dump(mode="json")}


def pct(values: list[int], q: float) -> int | None:
    xs = sorted(values)
    return xs[max(0, math.ceil(q * len(xs)) - 1)] if xs else None


def rate(num: int, den: int) -> float | None:
    return num / den if den else None


def tokens(usages: list[llm.Usage | None]) -> Json:
    """Exact totals over the records that report usage; ``records_without_usage``
    counts the others. Unknown is never 0: every total is null when no record
    reports usage, and ``reasoning`` is null when any usage lacks it."""
    known = [u for u in usages if u]
    unknown = sum(u.reasoning_tokens is None for u in known)
    none = bool(usages) and not known
    out: Json = {"prompt": None if none else sum(u.prompt_tokens for u in known)}
    out["completion"] = None if none else sum(u.completion_tokens for u in known)
    reasoning = sum(u.reasoning_tokens or 0 for u in known)
    out |= {"reasoning": None if none or unknown else reasoning}
    out["reasoning_unknown"] = unknown
    return out | {"records_without_usage": len(usages) - len(known)}


def arm_metrics(part: str, mine: list[Json], default: dict[str, str]) -> Json:
    """One arm's metrics. Rates are over every call (n): a rejected or failed call
    counts as not valid and not parsed; ``*_answered`` rates are over answered
    calls only. ``default``: the default arm's valid Ear act per source."""
    ok = [r for r in mine if not r["error"]]
    n, lat = len(mine), [r["latency_ms"] for r in ok]
    think = [r["usage"]["reasoning_tokens"] for r in ok if r["usage"]]
    think = [x for x in think if x is not None]
    arm: Json = {"n": n, "n_ok": len(ok), "n_error": n - len(ok)}
    arm |= {"n_rejected": sum(bool(r.get("rejected")) for r in mine)}
    arm["finish_reasons"] = dict(Counter(str(r["finish_reason"]) for r in mine))
    echoes = {r["served_model_echo"] for r in mine if r["served_model_echo"]}
    arm["served_model_echo"] = sorted(echoes)
    arm |= {"latency_ms_p50": pct(lat, 0.5), "latency_ms_p95": pct(lat, 0.95)}
    arm |= {"reasoning_tokens_p50": pct(think, 0.5), "reasoning_n": len(think)}
    arm |= {"reasoning_tokens_p95": pct(think, 0.95)}
    if part != "fast":
        n_valid = sum(bool(r["valid"]) for r in ok)
        arm |= {"valid_rate": rate(n_valid, n)}
        arm["valid_rate_answered"] = rate(n_valid, len(ok))
    if part == "slow":
        per_response = Counter(r["n_calls"] for r in ok)
        arm["calls_per_response"] = dict(sorted(per_response.items()))
        n_calls = sum(r["n_calls"] for r in ok)
        valid_calls = sum(r["n_valid_calls"] for r in ok)
        arm["tool_call_valid_rate_answered"] = rate(valid_calls, n_calls)
    if part == "ear":  # over requests both this arm and the default answered validly
        both = [r for r in ok if r["valid"] and r["source"] in default]
        agree = sum(r["act"] == default[r["source"]] for r in both)
        arm |= {"agreement_with_default": rate(agree, len(both))}
        arm["agreement_n"] = len(both)
    if part == "fast":
        ttft = [r["ttft_ms"] for r in ok if r["ttft_ms"] is not None]
        arm["latency"] = {"relay_measured": True, "ttft_includes_reasoning": True}
        arm["latency"] |= {"ttft_ms_p50": pct(ttft, 0.5), "ttft_n": len(ttft)}
        arm["latency"] |= {"ttft_ms_p95": pct(ttft, 0.95)}
        arm["latency"] |= {"total_ms_p50": pct(lat, 0.5)}
        arm["latency"] |= {"total_ms_p95": pct(lat, 0.95)}
        with_issue = sum(bool(r["issues"]) for r in ok)
        arm["parse_issue_rate"] = rate(with_issue + n - len(ok), n)  # unparsed: issue
        arm["parse_issue_rate_answered"] = rate(with_issue, len(ok))
        arm["issues_by_reason"] = dict(Counter(i for r in ok for i in r["issues"]))
        arm["rejections"] = [r["error"] for r in mine if r.get("rejected")]
    return arm


def summarise(part: str, rows: list[Json], records: dict[str, list[Any]]) -> Json:
    ok = [r for r in rows if part == "ear" and r["arm"] == "default" and not r["error"]]
    default = {r["source"]: r["act"] for r in ok if r["valid"]}
    arms: Json = {}
    for effort in ARMS[part]:
        name = label(effort)
        arm = arm_metrics(part, [r for r in rows if r["arm"] == name], default)
        recs: list[llm.LLMCallRecord] = records[name]  # every attempt, errors too
        arm["tokens"] = tokens([r.usage for r in recs]) | {"records": len(recs)}
        arms[name] = {"model_id": MODELS[part], "reasoning_effort": effort} | arm
    return arms


def header(bundle: Bundle, part: str, items: list[Item]) -> Json:
    git = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    m = bundle.manifest
    out: Json = {"task": "S0-ROOT-12", "part": part, "git_sha": git.stdout.strip()}
    out |= {"source_run_id": m.run_id, "source_task_ref": m.task_ref}
    out["source_models"] = {r: rm.ref.model_id for r, rm in m.models.items()}
    arms = {
        label(e): {"model_id": MODELS[part], "reasoning_effort": e} for e in ARMS[part]
    }
    out |= {"endpoint": "teamrouter", "arms": arms, "selection_rule": RULE}
    return out | {"selection": [{"source": x.source, "t_ms": x.t_ms} for x in items]}


def plan(bundle: Bundle, part: str, items: list[Item]) -> Json:
    """The paid run's shape and a token projection from the recorded usage."""
    per_arm = tokens([x.usage for x in items])
    arms, bound = len(ARMS[part]), sum(x.request.max_tokens for x in items)
    out = header(bundle, part, items) | {"calls": len(items) * arms}
    out |= {"projected_tokens_per_arm": per_arm, "completion_bound_total": bound * arms}
    total = {k: None if v is None else v * arms for k, v in per_arm.items()}
    out["projected_tokens_total"] = total
    note = "recorded usage under source_models (their tokenizers and reasoning); "
    return out | {
        "note": note + "the bound is calls x max_tokens; TeamRouter is unpriced"
    }


async def run(
    bundle: Bundle,
    part: str,
    items: list[Item],
    out: Path,
    transport: httpx.AsyncBaseTransport | None = None,  # make_client's test seam
) -> int:
    start, rows, aborted = time.monotonic(), list[Json](), None
    records: dict[str, list[Any]] = {label(e): [] for e in ARMS[part]}
    clients: dict[str, llm.LLMClient] = {}
    for e in ARMS[part]:
        ref = llm.ModelRef(
            kind=llm.AdapterKind.REAL_HTTP,
            endpoint="teamrouter",
            model_id=MODELS[part],
            reasoning_effort=e,
        )
        clients[label(e)] = make_client(
            ref,
            live=True,
            clock=lambda: int((time.monotonic() - start) * 1000),
            on_record=records[label(e)].append,
            transport=transport,
        )

    def flush(complete: bool) -> None:
        report = header(bundle, part, items) | {
            "complete": complete,
            "aborted": aborted,
        }
        report |= {"arms": summarise(part, rows, records), "calls": rows}
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.name + ".tmp")
        tmp.write_text(json.dumps(report, indent=1) + "\n", "utf-8")
        tmp.replace(out)

    try:
        for i, item in enumerate(items):
            order = list(clients.items())  # alternated: no arm always goes second
            for name, client in order[:: -1 if i % 2 else 1]:
                row = await one(part, client, item, f"probe-{part}:{i}:{name}")
                rows.append(row | {"arm": name})
                if row.get("fatal"):
                    aborted = f"{name} {item.source}: {row['error']}"
                    print(f"aborted: {aborted}", file=sys.stderr)
                    return 1
                flush(False)
    except BaseException as exc:  # recorded, saved, then raised as it was
        aborted = repr(exc)[:500]
        raise
    finally:
        flush(aborted is None and len(rows) == len(items) * len(clients))
        for c in clients.values():
            await cast(HTTPAdapter, c).aclose()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="S0-ROOT-12 model role probe")
    ap.add_argument("--run", required=True, type=Path, help="a bundle directory")
    ap.add_argument("--part", required=True, choices=tuple(ARMS))
    ap.add_argument("--n", type=int, help="requests to select (default: the block's)")
    ap.add_argument("--plan", action="store_true", help="no calls: selection, tokens")
    ap.add_argument("--out", type=Path, help="the summary JSON (unless --plan)")
    args = ap.parse_args(argv)
    bundle = read_bundle(args.run)
    items = select(bundle, args.part, args.n or N[args.part])
    if args.plan:
        print(json.dumps(plan(bundle, args.part, items), indent=1))
        return 0
    if args.out is None:
        ap.error("--out is required unless --plan")
    return asyncio.run(run(bundle, args.part, items, args.out))


if __name__ == "__main__":
    sys.exit(main())
