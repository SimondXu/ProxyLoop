"""Same-state Fast probe (S1-MOD-08): at exactly the recorded Fast states, what would
other Fast candidates have said? Root-run (L+G); ``--plan`` makes no call, needs no key.

Diagnostic only, open-loop (``ABOUT``). Views: the recorded Fast turns (both lanes) of
the train bundles on the current fingerprints, whole runs newest first, up to
``--max-views`` (``collect``), with the recorded answer as the reference. Calls go
through the production adapter (``make_client``, live) in the kernel's request shape
(``build_request``), after the kernel's P3 (``parity``). ``--max-tokens`` overrides
only the request's max_tokens, for reasoning models whose max_tokens counts reasoning;
the default is the kernel's request. No session, kernel, world or
Slow runs, and no retry here: the adapter's own rule (one retry of a connection failure
before the first token) shows under ``failed_attempts``. A failed call raises
``LLMUnavailable``: its row is written with the partial report, and the run aborts
(AGENTS rule 6). Keys and URLs stay in ``PL_<ENDPOINT>_*`` and are never written.
Numbers: see ``NUMBER_RULE``; number words are not seen. p90: nearest rank.

S1-MOD-10 (a revised profile, re-tested): ``--profile <lane>=<name>`` renders every view
of that lane with that profile (``View.rendered``; rows record ``profile_rendered``,
the reference's being the recorded one); ``--any-fingerprint`` (only with an override
for every lane present) also takes stale-fingerprint bundles; ``--family-include`` /
``--family-exclude`` filter on ``manifest.task_ref``; ``--seed-missing`` seeds a turn
that recorded none (rows record ``seed_source``); ``--views-manifest`` takes exactly
a ``profile_check select-b`` manifest's views; ``--views-file`` probes the views
``profile_check build-c`` wrote, which have no recorded answer: no reference rows.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
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
HUGE = 10**9  # "no cap"


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
    seed_source: str = "recorded"  # "default": none recorded, --seed-missing's seed
    render_as: str | None = None  # a --profile override; None: ``profile``
    # A --views-file view: ``reference`` is its source turn's call, kept only for the
    # request's call_id and role; it has no recorded answer and no reference row.
    counterfactual: bool = False

    @property
    def rendered(self) -> str:
        """The profile its requests are rendered with."""
        return self.render_as or self.profile


def family_ok(task_ref: str, include: Sequence[str], exclude: Sequence[str]) -> bool:
    """Substrings of ``manifest.task_ref``: any include (none: all), no exclude."""
    taken = not include or any(s in task_ref for s in include)
    return taken and not any(s in task_ref for s in exclude)


def collect(
    bundles: Sequence[Bundle],
    fps: dict[str, str],
    cap: int,
    *,
    any_fingerprint: bool = False,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    seed_missing: int | None = None,
) -> tuple[list[View], Json]:
    """The recorded Fast turns of the train bundles on ``fps`` (any fingerprint with
    ``any_fingerprint``; ``family_ok``): whole bundles, newest first (as
    ``pull_through.select``), each bundle's turns in their recorded order, cut at
    ``cap``. A turn with no recorded seed is dropped, or given ``seed_missing``. The
    funnel's ``composition``: per run, turns taken of those available, and taken per
    lane; the new funnel keys appear only when their option acts."""
    funnel, found, composition = Counter[str](), list[View](), dict[str, Json]()
    newest = sorted(bundles, key=lambda b: (b.events[0].wall, b.manifest.run_id))
    for b in reversed(newest):
        stale = b.manifest.fingerprints != fps
        if b.manifest.split != "train":
            funnel["bundle_not_train"] += 1
            continue
        if not family_ok(b.manifest.task_ref, include, exclude):
            funnel["bundle_family_filtered"] += 1
            continue
        if stale and not any_fingerprint:
            funnel["bundle_stale_fingerprint"] += 1
            continue
        if stale:
            funnel["bundle_stale_fingerprint_taken"] += 1
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
            source, seed = "recorded", (rec.sampling_sent or {}).get("seed")
            if seed is None:
                if seed_missing is None:
                    funnel["seed_not_recorded"] += 1
                    continue
                source, seed = "default", seed_missing
                funnel["seed_defaulted"] += 1
            view = FastView.model_validate_json(b.prompts[str(req["view_sha"])].content)
            lane: Lane = "user" if req["lane"] == "user" else "cp"
            args = (b.manifest.run_id, e.event_id, lane, str(req["profile"]), view)
            args += (b.manifest.cfg.fast_sampling, int(seed), rec)
            raw = b.prompts[rec.response_sha].content
            mine.append(View(*args, raw, seed_source=source))
        taken = mine[: max(cap - len(found), 0)]
        comp: Json = {"taken": len(taken), "available": len(mine)}
        comp |= {lane: sum(v.lane == lane for v in taken) for lane in LANES}
        composition[b.manifest.run_id] = comp
        found += taken
        funnel["dropped_over_cap"] += len(mine) - len(taken)
    seen = len(found) + funnel["dropped_over_cap"]
    counts = {"bundles": len(bundles), "views_found": seen, "selected": len(found)}
    return found, counts | {**funnel, "composition": composition}


def read_views(path: Path) -> list[View]:
    """The views of a ``profile_check build-c`` file (``counterfactual``)."""
    out = list[View]()
    for x in json.loads(path.read_text("utf-8"))["views"]:
        lane: Lane = "user" if x["lane"] == "user" else "cp"
        args = (x["run_id"], x["turn"], lane, x["profile"])
        args += (FastView.model_validate(x["view"]), Sampling(**x["sampling"]))
        args += (int(x["seed"]), Rec.model_validate(x["source_call"]), "")
        out.append(View(*args, seed_source=x["seed_source"], counterfactual=True))
    return out


def manifest_views(bundles: Sequence[Bundle], manifest: Json) -> list[View]:
    """A ``profile_check select-b`` manifest's views, in its order, collected with its
    selection (any fingerprint, its seed for a seedless turn); all found, or refused."""
    s = manifest["selection"]
    views, _ = collect(
        bundles, pt.current_fingerprints(), HUGE, any_fingerprint=True,
        include=s["include"], exclude=s["exclude"], seed_missing=s["seed_missing"],
    )  # fmt: skip
    at = {(v.run_id, v.turn): v for v in views}
    want = [(str(r["run_id"]), str(r["turn"])) for r in manifest["views"]]
    if lost := [k for k in want if k not in at]:
        raise SystemExit(f"{len(lost)} manifest views not found (bundles changed?)")
    return [at[k] for k in want]


def overrides(specs: Sequence[str]) -> dict[str, str]:
    """``<lane>=<profile>`` pairs: a known profile of that lane, one per lane."""
    out: dict[str, str] = {}
    for spec in specs:
        lane, _, name = spec.partition("=")
        if lane not in LANES or lane in out:
            raise SystemExit(f"--profile {spec}: not <user|cp>=<name>, once per lane")
        if name not in fp.PROFILES or fp.PROFILES[name].lane != lane:
            raise SystemExit(f"--profile {spec}: no {lane}-lane profile {name!r}")
        out[lane] = name
    return out


def parse_model(spec: str) -> llm.ModelRef:
    """<endpoint>:<model_id>[@<reasoning_effort>]; ModelRef refuses a bad one."""
    endpoint, _, rest = spec.partition(":")
    model_id, _, effort = rest.partition("@")
    ref = {"kind": REAL, "endpoint": endpoint, "model_id": model_id}
    return llm.ModelRef.model_validate(ref | {"reasoning_effort": effort or None})


def build_request(
    v: View, ref: llm.ModelRef, tok: Tok, max_tokens: int | None = None
) -> llm.TextRequest:
    """The kernel's Fast request (``kernel.lanes.FastLane._request``): vLLM gets the
    pinned tokenizer's prompt, other endpoints the messages; the session's sampling,
    with ``max_tokens`` replaced by the override when one is given."""
    args: Json = v.sampling.model_dump() | {"seed": v.seed}  # + max_tokens
    if max_tokens is not None:
        args["max_tokens"] = max_tokens
    args |= {"call_id": v.reference.call_id, "role": v.reference.role}
    if ref.endpoint != "vllm":
        args["messages"] = fp.render_messages(v.view, v.rendered)
    elif tok is None:
        raise RuntimeError("a vLLM candidate needs the pinned tokenizer")
    else:
        args["prompt"] = fp.render_prompt(v.view, v.rendered, tok)
    return llm.TextRequest(**args)


def view_text(v: View, profile: str | None = None) -> str:
    """The rendered messages' text (default: as its requests are rendered)."""
    msgs = fp.render_messages(v.view, profile or v.rendered)
    return "\n".join(m.content for m in msgs)


def numbers(text: str) -> list[str]:
    out = [str(n).replace(",", "") for n in NUMBER.findall(text)]
    return [n.rstrip("0").rstrip(".") if "." in n else n for n in out]


def directives(items: Sequence[fp.TurnItem]) -> list[str]:
    out = {i.kind for i in items if isinstance(i, fp.Hold | fp.Wait | fp.EndCall)}
    return sorted(out | {f"slow:{i.type}" for i in items if isinstance(i, fp.Relay)})


def analyse(raw: str, v: View, profile: str) -> Json:
    items = fp.parse_turn(raw, v.lane, profile)
    spoken = " ".join(i.text for i in items if isinstance(i, fp.Speech))
    known = set(numbers(view_text(v, profile)))
    return {
        "items": [i.model_dump(mode="json") for i in items],
        "issues": [i.reason for i in items if isinstance(i, fp.ParseIssue)],
        "directives": directives(items),
        "sentences": sum(isinstance(i, fp.Speech) for i in items),
        "spoken_words": len(spoken.split()),
        "unsupported_numbers": [n for n in numbers(spoken) if n not in known],
    }


def row(
    label: str,
    v: View,
    raw: str,
    rec: Rec,
    failed: Sequence[Rec],
    sent_max_tokens: int | None = None,
) -> Json:
    """``max_tokens_sent``: what the call's body carried (``sampling_sent`` has no
    max_tokens); None: the session's, which the recorded (reference) call sent.
    ``profile_rendered``: the reference's recorded profile, else ``View.rendered``."""
    first, profile = rec.t_first_token, v.profile if label == REFERENCE else v.rendered
    out: Json = {"model": label, "run_id": v.run_id, "turn": v.turn, "lane": v.lane}
    out |= {"profile_rendered": profile, "seed_source": v.seed_source}
    out["max_tokens_sent"] = (
        v.sampling.max_tokens if sent_max_tokens is None else sent_max_tokens
    )
    out |= {"raw": raw, "error": rec.error, "record": rec.model_dump(mode="json")}
    out["failed_attempts"] = [r.model_dump(mode="json") for r in failed]
    out["ttft_ms"] = None if first is None else first - rec.t_start
    if rec.error is None:
        out |= analyse(raw, v, profile)
    if rec.error is None and not v.counterfactual:
        out["reference_directives"] = analyse(v.raw, v, v.profile)["directives"]
        out["agrees"] = out["directives"] == out["reference_directives"]
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
    ok_ref = [r for r in ok if "agrees" in r]  # a --views-file view has no reference
    out["directive_agreement"] = rate(ok_ref, lambda r: r["agrees"])
    acting = [r for r in ok_ref if r["reference_directives"]]  # the reference gave one
    out["directive_agreement_acting_reference"] = rate(acting, lambda r: r["agrees"])
    out["acting_reference_n"] = len(acting)
    # Unknown usage stays unknown: summed only over the calls that reported it.
    out["usage_unknown"] = len(ok) - len(usage)
    for k in ("prompt_tokens", "completion_tokens"):
        out[k] = sum(u[k] for u in usage) if usage else None
    return out


def summary(rows: Sequence[Json], labels: Sequence[str]) -> Json:
    """Per model (the recorded reference first), per lane, labelled with the model
    refs its rows were served by and the served echoes they reported."""
    out: Json = {}
    for m in (REFERENCE, *labels):
        mine = [r for r in rows if r["model"] == m]
        refs = {json.dumps(r["record"]["model_ref"], sort_keys=True) for r in mine}
        echoes = {r["record"]["served_model_echo"] for r in mine} - {None}
        out[m] = {"model_refs": [json.loads(x) for x in sorted(refs)]}
        out[m]["served_echoes"] = sorted(echoes)
        out[m] |= {ln: summarise([r for r in mine if r["lane"] == ln]) for ln in LANES}
    return out


def plan(
    views: Sequence[View],
    labels: Sequence[str],
    funnel: Json,
    max_tokens: int | None = None,
) -> Json:
    chars = sum(len(view_text(v)) for v in views)
    out: Json = {"views": len(views), "by_lane": dict(Counter(v.lane for v in views))}
    out |= {"funnel": funnel, "calls": {m: len(views) for m in labels}}
    out["max_tokens_override"] = max_tokens
    out["est_prompt_tokens"] = {m: chars // 4 for m in labels}
    out["est_rule"] = "chars/4 of the rendered messages, the same for every model"
    return out


async def probe(
    views: Sequence[View],
    models: dict[str, llm.ModelRef],
    tok: Tok,
    report: Json,
    transports: Mapping[str, httpx.AsyncBaseTransport] | None = None,
    max_tokens: int | None = None,
) -> Json:
    """P3 once per vLLM candidate, then every (view, model) call, one at a time;
    ``report`` keeps the rows even when a dead endpoint or P3 aborts the run.
    ``transports``: per endpoint, a test seam. ``max_tokens``: the override, recorded
    in the report as ``max_tokens_override`` (None: the kernel's own)."""
    sunk: list[Rec] = []  # every attempt's record, as the adapter sinks it
    rows = [
        row(REFERENCE, v, v.raw, v.reference, []) for v in views if not v.counterfactual
    ]
    report |= {"rows": rows, "max_tokens_override": max_tokens}
    clients: dict[str, llm.LLMClient] = {}
    ms, sink, seams = WallClock().monotonic_ms, sunk.append, transports or {}
    for m, ref in models.items():
        t = seams.get(str(ref.endpoint))
        clients[m] = make_client(ref, live=True, clock=ms, on_record=sink, transport=t)
    try:
        await parity(clients, views, tok, report)
        for v in views:
            for m in arm_order(v, list(models)):
                request, text = build_request(v, clients[m].ref, tok, max_tokens), ""
                sunk.clear()
                try:
                    async for delta in clients[m].stream_text(request):
                        text += delta if isinstance(delta, str) else ""
                except llm.LLMUnavailable as dead:  # recorded, then abort (rule 6)
                    rows.append(
                        row(m, v, text, dead.record, sunk[:-1], request.max_tokens)
                    )
                    report["aborted"] = str(dead)
                    raise
                rows.append(row(m, v, text, sunk[-1], sunk[:-1], request.max_tokens))
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
    messages and of the prompt == the pinned tokenizer's ids), as the kernel runs it:
    one view per lane (each lane's profile renders its own system text), here the
    sample's first view of each lane present, before any call. Every lane's result goes
    into ``report["p3"][model][lane]``; any failure then aborts (§12)."""
    report["p3"] = checks = dict[str, Json]()
    firsts = {lane: next((v for v in views if v.lane == lane), None) for lane in LANES}
    for m, client in clients.items():
        if not isinstance(client, VLLMClient):
            continue
        if tok is None:
            raise RuntimeError("P3 needs the pinned tokenizer")
        checks[m] = {}
        for lane, v in ((ln, v) for ln, v in firsts.items() if v is not None):
            check: Json = {"run_id": v.run_id, "turn": v.turn}
            checks[m][lane] = check
            try:
                check["passed"] = await p3(client, v.view, tok)
            except Exception as err:  # /tokenize cannot answer: dead, never skipped
                check |= {"passed": False, "error": type(err).__name__}  # no host
                report["aborted"] = f"P3 for {m}: {type(err).__name__}"
                raise
        if failed := [ln for ln, c in checks[m].items() if not c["passed"]]:
            report["aborted"] = f"P3 failed for {m} on {failed}: /tokenize != the pin"
            raise RuntimeError(report["aborted"])


def at_least_1(text: str) -> int:
    if (n := int(text)) < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, not {n}")
    return n


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select(a: argparse.Namespace) -> tuple[list[View], Json, Json]:
    """The views (bundles, a manifest's, or a views file's) with any override,
    the funnel, and the selection the report records."""
    over, path, listed = overrides(a.profile), a.views_file, a.views_manifest
    sel: Json = {"profile_override": over or None}
    picks = (a.any_fingerprint, a.family_include, a.family_exclude)
    if (path or listed) and (any(picks) or a.seed_missing is not None):
        raise SystemExit("--views-file/-manifest take no bundle selection option")
    if listed and not a.evidence:
        raise SystemExit("--views-manifest selects from --evidence")
    if path:
        views = read_views(path)[: a.max_views]
        funnel: Json = {"views_file": str(path), "selected": len(views)}
        sel["views_file_sha256"] = file_sha(path)
    else:
        bundles, fps = pt.load_bundles(a.evidence), pt.current_fingerprints()
        if listed:
            doc = json.loads(listed.read_text("utf-8"))
            views = manifest_views(bundles, doc)[: a.max_views]
            funnel = {"views_manifest": str(listed), "selected": len(views)}
            sel["views_manifest_sha256"] = file_sha(listed)
        else:
            views, funnel = collect(
                bundles, fps, a.max_views, any_fingerprint=a.any_fingerprint,
                include=a.family_include, exclude=a.family_exclude,
                seed_missing=a.seed_missing,
            )  # fmt: skip
        refs = {b.manifest.run_id: b.manifest.task_ref for b in bundles}
        sel["families"] = dict(Counter(refs[v.run_id] for v in views))
    missing = sorted({v.lane for v in views} - over.keys())
    if (a.any_fingerprint or listed) and (missing or not over):
        raise SystemExit(f"stale views need a --profile for each lane {missing}")
    views = [dataclasses.replace(v, render_as=over.get(v.lane)) for v in views]
    return views, funnel, sel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.mod.probe_same_state")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--evidence", type=Path, help="a dir of train bundles")
    src.add_argument("--views-file", type=Path, help="profile_check build-c's views")
    parser.add_argument(
        "--views-manifest", type=Path, help="select-b's, from --evidence"
    )
    parser.add_argument(
        "--model", action="append", required=True, help=parse_model.__doc__
    )
    parser.add_argument(
        "--max-views", type=at_least_1, required=True, help="a hard cap"
    )
    parser.add_argument(
        "--max-tokens",
        type=at_least_1,
        help="override the request's max_tokens (default: the kernel's sampling)",
    )
    parser.add_argument("--profile", action="append", default=[], help="<lane>=<name>")
    parser.add_argument("--any-fingerprint", action="store_true")
    parser.add_argument("--family-include", action="append", default=[])
    parser.add_argument("--family-exclude", action="append", default=[])
    parser.add_argument("--seed-missing", type=int, help="the seed of a seedless turn")
    parser.add_argument("--out", help="the report JSON (required without --plan)")
    parser.add_argument("--plan", action="store_true", help="counts only; no call")
    args = parser.parse_args(argv)
    models = {spec: parse_model(spec) for spec in args.model}
    fps = pt.current_fingerprints()
    views, funnel, sel = select(args)
    if args.plan:
        shown = plan(views, list(models), funnel, args.max_tokens) | sel
        print(json.dumps(shown, indent=1))
        return 0
    if not args.out:
        raise SystemExit("--out is required without --plan")
    vllm = any(ref.endpoint == "vllm" for ref in models.values())
    tok = load_tokenizer() if vllm else None
    report: Json = {"about": ABOUT, "measured_at": time.time(), "models": list(models)}
    report |= {"fingerprints": fps, "funnel": funnel, "number_rule": NUMBER_RULE}
    report |= sel
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(probe(views, models, tok, report, None, args.max_tokens))
    finally:  # a paid run is never lost, an aborted one included
        out.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", "utf-8")
    print(json.dumps(report["summary"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
