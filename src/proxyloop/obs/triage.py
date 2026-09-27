"""One bundle's triage report: a header, a timeline and counters, offline.

``python -m proxyloop.obs.triage RUN [--json] [--content]`` reads
``events.jsonl`` and ``prompts.jsonl`` only, after ``trace.check`` refuses sealed
and test-split bundles (AGENTS rule 11). Timeline rows are built from codes,
enums, ids and numbers (default deny, as in ``obs.trace``); ``--content`` adds
the user-lane, relay and tool-result text for local triage.

Counters are a registry of pure functions (``COUNTERS``: name → fn(Inputs)),
so a failure-class set can add some without touching the CLI. A counter never
turns an unknown into 0: it reports ``None`` or counts the unknowns apart.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import cast

from proxyloop.contract import protocol as fp
from proxyloop.contract.bundle import EVENTS, MANIFEST
from proxyloop.contract.events import Event
from proxyloop.contract.llm import LLMCallRecord
from proxyloop.obs.runs import Seal
from proxyloop.obs.trace import (
    _TOOLS,  # pyright: ignore[reportPrivateUsage]
    Prompts,
    Refused,
    check,
    lines,
    unseal,
)
from proxyloop.obs.trace import (
    _identifier as _is_code,  # pyright: ignore[reportPrivateUsage]
)

SCHEMA = "pl.triage/1"
Row = dict[str, object]
_LEAD = ("seq", "t_ms", "type")  # every timeline row's first columns
_DIRECTIVES = (fp.Relay, fp.Hold, fp.Wait, fp.EndCall)  # @slow @hold @wait @end_call


@dataclass(frozen=True)
class Inputs:
    """What a counter may read: the events, prompt records by sha, and the
    relay window (ms) for the user-fact counter."""

    events: tuple[Event, ...]
    prompt: Callable[[str], str | None]
    relay_window_ms: int = 10_000


CounterFn = Callable[[Inputs], object]
COUNTERS: dict[str, CounterFn] = {}


def counter(name: str) -> Callable[[CounterFn], CounterFn]:
    def register(fn: CounterFn) -> CounterFn:
        COUNTERS[name] = fn
        return fn

    return register


def _of(events: Sequence[Event], *types: str) -> list[Event]:
    return [e for e in events if e.type in types]


def _calls(events: Sequence[Event]) -> list[LLMCallRecord]:
    return [LLMCallRecord.model_validate(e.payload) for e in _of(events, "llm.call")]


def _code(value: object) -> object:
    """An identifier, number or bool as is; any other value is withheld."""
    return value if value is None or _is_code(value) else "?"


def _dict(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


@counter("slow_steps")
def _slow_steps(x: Inputs) -> int:
    return len(_of(x.events, "slow.step.started"))


@counter("slow_step_max_gap_ms")
def _slow_gap(x: Inputs) -> int | None:
    """From session.started to the first step, then step to step; None: no step."""
    ts = [e.t_ms for e in _of(x.events, "session.started", "slow.step.started")]
    return max((b - a for a, b in pairwise(ts)), default=None)


def _per_role(keep: Callable[[LLMCallRecord], bool]) -> CounterFn:
    return lambda x: dict(Counter(r.role for r in _calls(x.events) if keep(r)))


COUNTERS["llm_errors"] = _per_role(lambda r: r.error is not None)
COUNTERS["finish_length"] = _per_role(lambda r: r.finish_reason == "length")
COUNTERS["finish_reason_null"] = _per_role(lambda r: r.finish_reason is None)


@counter("speech_after_directive")
def _after_directive(x: Inputs) -> dict[str, object]:
    """Speech items after the first directive item, per generation (fast.turn),
    parsed from the raw response by the contract parser: the total, the
    generations with any, and those whose response is missing (``unknown``)."""
    last = {r.call_id: r for r in _calls(x.events)}  # the final attempt wins
    counts: dict[str, int] = {}
    unknown: list[str] = []
    for turn in _of(x.events, "fast.turn"):
        gen = str(turn.payload["gen_id"])
        record = last.get(str(turn.payload["call_id"]))
        sha = record.response_sha if record else None
        text = x.prompt(sha) if sha else None
        if text is None:
            unknown.append(gen)
            continue
        lane = "cp" if turn.payload["lane"] == "cp" else "user"
        n, seen = 0, False
        for item in fp.parse_turn(text, lane):
            seen = seen or isinstance(item, _DIRECTIVES)
            if seen and isinstance(item, fp.Speech):
                n += 1
        counts[gen] = n
    gens = {g: n for g, n in counts.items() if n > 0}
    return {"total": sum(gens.values()), "gens": gens, "unknown": unknown}


@counter("hold_repeats")
def _holds(x: Inputs) -> int | None:
    """The kernel's own count (session.ended ``counts.hold_repeat``); None: the
    session has no end record. A Counter omits zeros, so a missing key is 0."""
    ends = _of(x.events, "session.ended")
    if not ends or not isinstance(ends[-1].payload.get("counts"), dict):
        return None
    return cast(int, _dict(ends[-1].payload["counts"]).get("hold_repeat", 0))


@counter("user_facts_unrelayed")
def _fact_msgs(x: Inputs) -> dict[str, list[str]]:
    """user.msg whose cause is a ``user.sim`` with non-empty ``revealed`` and
    that no user-lane ``f2s.msg`` cites (``utt_ref``) within the window.
    ``unknown``: messages with no ``user.sim`` cause (e.g. a human), or whose
    window outlives the log; neither can be judged."""
    by_id = {e.event_id: e for e in x.events}
    end = x.events[-1].t_ms if x.events else 0
    relayed: dict[str, list[int]] = {}
    for f in _of(x.events, "f2s.msg"):
        if f.payload.get("lane") == "user":
            relayed.setdefault(str(f.payload.get("utt_ref")), []).append(f.t_ms)
    flagged: list[str] = []
    unknown: list[str] = []
    for msg in _of(x.events, "user.msg"):
        sims = [by_id[c] for c in msg.cause_ids if by_id[c].type == "user.sim"]
        if not sims:
            unknown.append(msg.event_id)
            continue
        if not _dict(sims[0].payload.get("revealed")):
            continue
        close = msg.t_ms + x.relay_window_ms
        if any(t <= close for t in relayed.get(msg.event_id, [])):
            continue
        (flagged if end >= close else unknown).append(msg.event_id)
    return {"flagged": flagged, "unknown": unknown}


def header(events: Sequence[Event]) -> Row:
    start = events[0].payload
    models = {r: _dict(_dict(m).get("ref")) for r, m in _dict(start["models"]).items()}
    ends = _of(events, "session.ended")
    return {
        "run_id": events[0].run_id,
        "git_sha": start.get("git_sha"),
        "task_ref": start.get("task_ref"),
        "split": start.get("split"),
        "mode": "+".join(sorted({str(m.get("kind")) for m in models.values()})) or None,
        "models": {
            r: f"{m.get('endpoint')}/{m.get('model_id')}"
            for r, m in sorted(models.items())
        },
        "ended": _code(ends[-1].payload.get("reason")) if ends else None,
        "duration_ms": events[-1].t_ms,
    }


def _row(e: Event, content: bool) -> Row | None:
    p, t = e.payload, e.type
    row: Row = {}
    text: dict[str, object] = {}
    if t == "rep.policy":
        intent = _dict(p.get("intent"))
        row = {"from": p.get("from"), "to": p.get("to"), "intent": intent.get("kind")}
    elif t == "slow.tool":
        name = p.get("name") if p.get("name") in _TOOLS else "unknown"
        result = str(p.get("result_text", ""))
        row = {"name": name, "ok": p.get("ok"), "result_len": len(result)}
        text = {"result_text": result[:100]}
    elif t == "action.denied":
        row = {"intent": p.get("intent"), "reason": p.get("reason")}
    elif t in ("s2f.msg", "f2s.msg"):
        guide = _dict(p.get("guide"))
        row = {k: p.get(k) for k in ("msg_id", "lane", "utt_ref")}
        row |= {"msg_type": p.get("type"), "move": guide.get("move")}
        row["n_facts"] = len(cast(list[object], p.get("facts") or []))
        text = {"text": p.get("text"), "facts": p.get("facts")}
    elif t == "status.changed":
        row = {"previous": p.get("previous"), "status": p.get("status")}
    elif t == "authority.fence":
        row = {k: p.get(k) for k in ("op", "fence_id", "utt_id")}
    elif t == "approval.post":
        row = {k: p.get(k) for k in ("subject", "subject_id", "decision")}
    elif t == "approval.requested":
        row = {k: p.get(k) for k in ("approval_id", "offer_ref", "revision")}
    elif t == "approval.decided":
        row = {k: p.get(k) for k in ("approval_id", "decision", "by")}
    elif t == "user.msg":
        row = {"text_len": len(str(p.get("text", "")))}
        text = {"text": p.get("text")}
    else:
        return None
    out: Row = {"seq": e.seq, "t_ms": e.t_ms, "type": t}
    out |= {k: _code(v) for k, v in row.items() if v is not None}
    return out | (text if content else {})


def triage(run: Path, content: bool = False, relay_window_s: float = 10) -> Row:
    seal = Seal()
    check(run, seal)  # refuses sealed and non-open splits (rule 11)
    unseal(run, seal)
    strict = (run / MANIFEST).is_file()
    raw = lines(run / EVENTS, follow=False, strict=strict)
    events = tuple(Event.model_validate_json(x) for x in raw)
    if not events or events[0].type != "session.started":
        raise Refused(f"{run}: the first event is not session.started")
    x = Inputs(events, Prompts(run, seal).get, round(relay_window_s * 1000))
    rows = [r for e in events if (r := _row(e, content)) is not None]
    return {
        "schema": SCHEMA,
        "header": header(events),
        "timeline": rows,
        "counters": {name: fn(x) for name, fn in sorted(COUNTERS.items())},
        "relay_window_ms": x.relay_window_ms,
    }


def text_report(report: Row) -> str:
    out = [f"{k}: {v}" for k, v in _dict(report["header"]).items()]
    out.append("-- timeline")
    for row in cast(list[Row], report["timeline"]):
        rest = " ".join(f"{k}={v}" for k, v in row.items() if k not in _LEAD)
        out.append(f"{row['t_ms']:>8} #{row['seq']:<5} {row['type']:<19} {rest}")
    out.append(f"-- counters (relay window {report['relay_window_ms']} ms)")
    out += [f"{k}: {v}" for k, v in _dict(report["counters"]).items()]
    return "\n".join(out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m proxyloop.obs.triage")
    parser.add_argument("run", type=Path, metavar="RUN")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--content", action="store_true", help="add user-lane and relay text"
    )
    parser.add_argument("--relay-window", type=float, default=10, metavar="S")
    args = parser.parse_args(argv)
    try:
        report = triage(args.run, args.content, args.relay_window)
    except Refused as err:
        print(f"refused: {err}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False))
    else:
        print(text_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
