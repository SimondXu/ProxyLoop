"""Same-state Fast probe (S1-MOD-08): at exactly the recorded Fast states, what would
other Fast candidates have said? Root-run (L+G); ``--plan`` makes no call, needs no key.

Diagnostic only, open-loop (``ABOUT``). Views: the recorded Fast turns (both lanes) of
the train bundles on the current fingerprints, whole runs newest first, up to
``--max-views`` (``collect``), with the recorded answer as the reference. Calls go
through the production adapter (``make_client``, live) in the kernel's request shape
(``build_request``), after the kernel's P3 (``parity``). No session, kernel, world or
Slow runs, and no retry here: the adapter's own rule (one retry of a connection failure
before the first token) shows under ``failed_attempts``. A failed call raises
``LLMUnavailable``: its row is written with the partial report, and the run aborts
(AGENTS rule 6). Keys and URLs stay in ``PL_<ENDPOINT>_*`` and are never written.
Numbers: see ``NUMBER_RULE``; number words are not seen. p90: nearest rank.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import re
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

import httpx

from proxyloop.contract import llm
from proxyloop.contract import protocol as fp
from proxyloop.contract.base import Lane
from proxyloop.contract.bundle import Bundle
from proxyloop.contract.config import Sampling
from proxyloop.contract.views import FastView
from proxyloop.core.clock import WallClock
from proxyloop.kernel.lanes import load_tokenizer, p3  # the kernel's pin and P3
from proxyloop.llm.factory import make_client
from proxyloop.llm.http import HTTPAdapter
from proxyloop.llm.vllm import VLLMClient
from proxyloop.training import pull_through as pt

Json = dict[str, Any]
Tok = fp.ChatTokenizer | None
Rec = llm.LLMCallRecord
REAL = llm.AdapterKind.REAL_HTTP
ABOUT = "Diagnostic only, open-loop: no outcomes, compounding errors or timing effects"
NUMBER_RULE = (  # the same for every model: 1,200.50 -> 1200.5, 75.00 -> 75
    "digit runs with ,/. separators, commas and decimal trailing zeros dropped; "
    "unsupported: spoken, but not among the rendered messages' numbers"
)
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
SLOW = tuple(f"slow:{t}" for t in get_args(fp.RelayType))
DIRECTIVES = ("hold", "wait", "end_call", *SLOW)
REFERENCE = "reference"
LANES: tuple[Lane, ...] = ("user", "cp")


@dataclass(frozen=True)
class View:
    run_id: str
    turn: str  # the fast.turn event id
    lane: Lane
    profile: str
    view: FastView
    sampling: Sampling  # the session's fast_sampling
    seed: int  # the seed the recorded call sent
    reference: Rec  # the recorded call
    raw: str  # its response text


def collect(
    bundles: Sequence[Bundle], fps: dict[str, str], cap: int
) -> tuple[list[View], Json]:
    """The recorded Fast turns of the train bundles on ``fps``: whole bundles, newest
    first (as ``pull_through.select``), each bundle's turns in their recorded order, cut
    at ``cap``. The funnel's ``composition``: per run, turns taken of those available,
    and taken per lane."""
    funnel, found, composition = Counter[str](), list[View](), dict[str, Json]()
    newest = sorted(bundles, key=lambda b: (b.events[0].wall, b.manifest.run_id))
    for b in reversed(newest):
        why = "not_train" if b.manifest.split != "train" else "stale_fingerprint"
        if b.manifest.split != "train" or b.manifest.fingerprints != fps:
            funnel[f"bundle_{why}"] += 1
            continue
        asked = {
            e.payload["gen_id"]: e.payload for e in b.events if e.type == "fast.request"
        }
        calls = {c.call_id: c for c in pt.fast_calls(b) if c.error is None}
        mine = list[View]()
        for e in (e for e in b.events if e.type == "fast.turn"):
            req, rec = asked[e.payload["gen_id"]], calls.get(str(e.payload["call_id"]))
            if rec is None or rec.response_sha is None:
                funnel["no_reference_answer"] += 1
                continue
            if (seed := (rec.sampling_sent or {}).get("seed")) is None:
                funnel["seed_not_recorded"] += 1
                continue
            view = FastView.model_validate_json(b.prompts[str(req["view_sha"])].content)
            lane: Lane = "user" if req["lane"] == "user" else "cp"
            args = (b.manifest.run_id, e.event_id, lane, str(req["profile"]), view)
            args += (b.manifest.cfg.fast_sampling, int(seed), rec)
            mine.append(View(*args, b.prompts[rec.response_sha].content))
        taken = mine[: max(cap - len(found), 0)]
        comp: Json = {"taken": len(taken), "available": len(mine)}
        comp |= {lane: sum(v.lane == lane for v in taken) for lane in LANES}
        composition[b.manifest.run_id] = comp
        found += taken
        funnel["dropped_over_cap"] += len(mine) - len(taken)
    seen = len(found) + funnel["dropped_over_cap"]
    counts = {"bundles": len(bundles), "views_found": seen, "selected": len(found)}
    return found, counts | {**funnel, "composition": composition}


def parse_model(spec: str) -> llm.ModelRef:
    """<endpoint>:<model_id>[@<reasoning_effort>]; ModelRef refuses a bad one."""
    endpoint, _, rest = spec.partition(":")
    model_id, _, effort = rest.partition("@")
    ref = {"kind": REAL, "endpoint": endpoint, "model_id": model_id}
    return llm.ModelRef.model_validate(ref | {"reasoning_effort": effort or None})


def build_request(v: View, ref: llm.ModelRef, tok: Tok) -> llm.TextRequest:
    """The kernel's Fast request (``kernel.lanes.FastLane._request``): vLLM gets the
    pinned tokenizer's prompt, other endpoints the messages; the session's sampling."""
    args: Json = v.sampling.model_dump() | {"seed": v.seed}  # + max_tokens
    args |= {"call_id": v.reference.call_id, "role": v.reference.role}
    if ref.endpoint != "vllm":
        args["messages"] = fp.render_messages(v.view, v.profile)
    elif tok is None:
        raise RuntimeError("a vLLM candidate needs the pinned tokenizer")
    else:
        args["prompt"] = fp.render_prompt(v.view, v.profile, tok)
    return llm.TextRequest(**args)


def view_text(v: View) -> str:
    return "\n".join(m.content for m in fp.render_messages(v.view, v.profile))


def numbers(text: str) -> list[str]:
    out = [str(n).replace(",", "") for n in NUMBER.findall(text)]
    return [n.rstrip("0").rstrip(".") if "." in n else n for n in out]


def directives(items: Sequence[fp.TurnItem]) -> list[str]:
    out = {i.kind for i in items if isinstance(i, fp.Hold | fp.Wait | fp.EndCall)}
    return sorted(out | {f"slow:{i.type}" for i in items if isinstance(i, fp.Relay)})


def analyse(raw: str, v: View) -> Json:
    items = fp.parse_turn(raw, v.lane, v.profile)
    spoken = " ".join(i.text for i in items if isinstance(i, fp.Speech))
    known = set(numbers(view_text(v)))
    return {
        "items": [i.model_dump(mode="json") for i in items],
        "issues": [i.reason for i in items if isinstance(i, fp.ParseIssue)],
        "directives": directives(items),
        "sentences": sum(isinstance(i, fp.Speech) for i in items),
        "spoken_words": len(spoken.split()),
        "unsupported_numbers": [n for n in numbers(spoken) if n not in known],
    }


def row(label: str, v: View, raw: str, rec: Rec, failed: Sequence[Rec]) -> Json:
    first = rec.t_first_token
    out: Json = {"model": label, "run_id": v.run_id, "turn": v.turn, "lane": v.lane}
    out |= {"raw": raw, "error": rec.error, "record": rec.model_dump(mode="json")}
    out["failed_attempts"] = [r.model_dump(mode="json") for r in failed]
    out["ttft_ms"] = None if first is None else first - rec.t_start
    if rec.error is None:
        out |= analyse(raw, v)
        out["agrees"] = out["directives"] == analyse(v.raw, v)["directives"]
    return out


def arm_order(v: View, labels: Sequence[str]) -> list[str]:
    """A per-view shuffle, seeded by the view: deterministic, and no arm always goes
    first (prefix-cache bias)."""
    order = list(labels)
    random.Random(f"{v.run_id}:{v.turn}").shuffle(order)
    return order


def rate(rows: Sequence[Json], pred: Callable[[Json], bool]) -> float | None:
    return sum(map(pred, rows)) / len(rows) if rows else None


def summarise(rows: Sequence[Json]) -> Json:
    """Rates are over answered calls unless named ``_all``; None when there are none."""
    ok = [r for r in rows if r["error"] is None]
    words = sorted(r["spoken_words"] for r in ok)
    usage = [r["record"]["usage"] for r in ok if r["record"]["usage"] is not None]
    out: Json = {"n": len(rows), "errors": len(rows) - len(ok)}
    out["failed_attempts"] = sum(len(r["failed_attempts"]) for r in rows)
    out["parse_issue_rate_all"] = rate(rows, lambda r: bool(r.get("issues")))
    out["parse_issue_rate_answered"] = rate(ok, lambda r: bool(r["issues"]))
    out["directive_rate"] = {
        d: rate(ok, lambda r, d=d: d in r["directives"]) for d in DIRECTIVES
    }
    out["spoken_words_mean"] = statistics.fmean(words) if words else None
    out["spoken_words_p90"] = words[math.ceil(0.9 * len(words)) - 1] if words else None
    out["unsupported_number_share"] = rate(ok, lambda r: bool(r["unsupported_numbers"]))
    out["directive_agreement"] = rate(ok, lambda r: r["agrees"])
    # Unknown usage stays unknown: summed only over the calls that reported it.
    out["usage_unknown"] = len(ok) - len(usage)
    for k in ("prompt_tokens", "completion_tokens"):
        out[k] = sum(u[k] for u in usage) if usage else None
    return out


def summary(rows: Sequence[Json], labels: Sequence[str]) -> Json:
    """Per model (the recorded reference first), per lane."""
    out: Json = {}
    for m in (REFERENCE, *labels):
        mine = [r for r in rows if r["model"] == m]
        out[m] = {ln: summarise([r for r in mine if r["lane"] == ln]) for ln in LANES}
    return out


def plan(views: Sequence[View], labels: Sequence[str], funnel: Json) -> Json:
    chars = sum(len(view_text(v)) for v in views)
    out: Json = {"views": len(views), "by_lane": dict(Counter(v.lane for v in views))}
    out |= {"funnel": funnel, "calls": {m: len(views) for m in labels}}
    out["est_prompt_tokens"] = {m: chars // 4 for m in labels}
    out["est_rule"] = "chars/4 of the rendered messages, the same for every model"
    return out


async def probe(
    views: Sequence[View],
    models: dict[str, llm.ModelRef],
    tok: Tok,
    report: Json,
    transports: Mapping[str, httpx.AsyncBaseTransport] | None = None,
) -> Json:
    """P3 once per vLLM candidate, then every (view, model) call, one at a time;
    ``report`` keeps the rows even when a dead endpoint or P3 aborts the run.
    ``transports``: per endpoint, a test seam."""
    sunk: list[Rec] = []  # every attempt's record, as the adapter sinks it
    rows = [row(REFERENCE, v, v.raw, v.reference, []) for v in views]
    report |= {"rows": rows}
    clients: dict[str, llm.LLMClient] = {}
    ms, sink, seams = WallClock().monotonic_ms, sunk.append, transports or {}
    for m, ref in models.items():
        t = seams.get(str(ref.endpoint))
        clients[m] = make_client(ref, live=True, clock=ms, on_record=sink, transport=t)
    try:
        await parity(clients, views, tok, report)
        for v in views:
            for m in arm_order(v, list(models)):
                request, text = build_request(v, clients[m].ref, tok), ""
                sunk.clear()
                try:
                    async for delta in clients[m].stream_text(request):
                        text += delta if isinstance(delta, str) else ""
                except llm.LLMUnavailable as dead:  # recorded, then abort (rule 6)
                    rows.append(row(m, v, text, dead.record, sunk[:-1]))
                    report["aborted"] = str(dead)
                    raise
                rows.append(row(m, v, text, sunk[-1], sunk[:-1]))
    finally:
        report["summary"] = summary(rows, list(models))
        for c in clients.values():
            if isinstance(c, HTTPAdapter):
                await c.aclose()
    return report


async def parity(
    clients: Mapping[str, llm.LLMClient], views: Sequence[View], tok: Tok, report: Json
) -> None:
    """The kernel's session-start P3 (``kernel.lanes.p3``: vLLM /tokenize of the
    messages and of the prompt == the pinned tokenizer's ids) on the sample's first
    view, before any call; a failure aborts (§12). Its result goes into the report."""
    report["p3"] = checks = dict[str, Json]()
    for m, client in clients.items():
        if not isinstance(client, VLLMClient) or not views:
            continue
        if tok is None:
            raise RuntimeError("P3 needs the pinned tokenizer")
        checks[m] = {"run_id": views[0].run_id, "turn": views[0].turn, "passed": False}
        try:
            checks[m]["passed"] = await p3(client, views[0].view, tok)
        except Exception as err:  # /tokenize cannot answer: dead, never skipped
            checks[m]["error"] = type(err).__name__  # its text may name the host
            report["aborted"] = f"P3 for {m}: {type(err).__name__}"
            raise
        if not checks[m]["passed"]:
            report["aborted"] = f"P3 failed for {m}: /tokenize != the pinned tokenizer"
            raise RuntimeError(report["aborted"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.mod.probe_same_state")
    parser.add_argument("--evidence", required=True, help="a dir of train bundles")
    parser.add_argument(
        "--model", action="append", required=True, help=parse_model.__doc__
    )
    parser.add_argument("--max-views", type=int, required=True, help="a hard cap")
    parser.add_argument("--out", help="the report JSON (required without --plan)")
    parser.add_argument("--plan", action="store_true", help="counts only; no call")
    args = parser.parse_args(argv)
    models = {spec: parse_model(spec) for spec in args.model}
    fps = pt.current_fingerprints()
    views, funnel = collect(pt.load_bundles(Path(args.evidence)), fps, args.max_views)
    if args.plan:
        print(json.dumps(plan(views, list(models), funnel), indent=1))
        return 0
    if not args.out:
        raise SystemExit("--out is required without --plan")
    vllm = any(ref.endpoint == "vllm" for ref in models.values())
    tok = load_tokenizer() if vllm else None
    report: Json = {"about": ABOUT, "measured_at": time.time(), "models": list(models)}
    report |= {"fingerprints": fps, "funnel": funnel, "number_rule": NUMBER_RULE}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(probe(views, models, tok, report))
    finally:  # a paid run is never lost, an aborted one included
        out.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", "utf-8")
    print(json.dumps(report["summary"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
