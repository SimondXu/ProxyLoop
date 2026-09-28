"""One bundle's triage report: a header row, a timeline and the detectors.

ADVISORY ONLY: triage signals, never a metric, a claim or a merge gate.

``python -m proxyloop.obs.triage RUN [--json] [--content] [--relay-window S]``
reads ``events.jsonl``, ``manifest.json`` and ``prompts.jsonl`` only. The bundle
goes through ``runs.load`` first: sealed and test-split bundles are refused
(AGENTS rule 11) and an invalid one is reported, never a traceback. Timeline
rows carry codes, enums, ids and numbers (default deny, as in ``obs.trace``);
``--content`` adds user-lane, relay and tool-result text for local triage.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from proxyloop.contract.bundle import MANIFEST, Manifest
from proxyloop.contract.events import Event
from proxyloop.obs import runs
from proxyloop.obs.detectors import BANNER, Inputs, as_dict, run_all, safe
from proxyloop.obs.trace import TOOL_NAMES, Prompts, Refused, unseal

SCHEMA = "pl.triage/1"
Row = dict[str, object]
_LEAD = ("seq", "t_ms", "type")  # every timeline row's first columns


class Unreadable(Exception):
    """runs.load found the bundle invalid, or without a split to check."""


def read(
    path: Path, seal: runs.Seal, window_s: float = 10, content: bool = False
) -> tuple[runs.Run, Inputs]:
    """The bundle's index row and its detector inputs. ``incomplete`` (no
    manifest: e.g. a crashed run) is read; ``sealed`` and ``invalid`` are not.
    The events are the ones ``runs.load`` parsed (once)."""
    path = path.resolve()  # runs.load places it relative to its parent
    unseal(path, seal)
    run = runs.load(path, path.parent, seal)
    if run.status == "sealed":
        raise Refused(f"{path} is sealed held-out data (AGENTS rule 11)")
    if run.status == "invalid" or run.events is None:
        raise Unreadable(f"{path}: {run.status}: {run.error}")
    unseal(path, seal)
    events, man = run.log, None
    if (path / MANIFEST).is_file():
        man = Manifest.model_validate_json((path / MANIFEST).read_text("utf-8"))
    if not events or events[0].type != "session.started":
        raise Unreadable(f"{path}: no complete session.started line to start from")
    window_ms = round(window_s * 1000)
    return run, Inputs(events, man, Prompts(path, seal).get, window_ms, content)


def row(run: runs.Run, x: Inputs) -> Row:
    """One run: what it ran (sha, slow_fp, task, mode, models, slow_view) and
    every detector's value. Header strings are codes (``_ref``), else "?"."""
    start = x.events[0].payload
    models = {
        r: as_dict(as_dict(m).get("ref")) for r, m in as_dict(start["models"]).items()
    }
    keys = ("endpoint", "model_id", "reasoning_effort")
    if x.manifest is not None:
        mode = "live" if x.manifest.cfg.live else "not_live"
        slow_view: object = x.manifest.cfg.slow_view.value
    else:  # no manifest: the adapter kinds session.started names, labelled
        mode = "kinds:" + "+".join(
            sorted({str(m.get("kind")) for m in models.values()})
        )
        slow_view = start.get("slow_view")  # S1-SYS-43; None before it
    return {
        "schema": SCHEMA,
        "advisory": BANNER,
        "run_id": run.run_id,
        "path": run.path,
        "status": run.status,
        "started": run.started,
        "git_sha": _ref(start.get("git_sha")),
        "slow_fp": _ref(start.get("slow_fp")),  # S1-SYS-43; None before it
        "task_ref": _ref(start.get("task_ref")),
        "split": _ref(start.get("split")),
        "mode": _ref(mode),
        "models": {
            str(_ref(r)): {k: _ref(m.get(k)) for k in keys}
            for r, m in sorted(models.items())
        },
        "slow_view": _ref(slow_view),
        "duration_ms": x.events[-1].t_ms,
        "detectors": run_all(x),
    }


_REF = re.compile(r"[A-Za-z0-9_.:@/+-]{1,128}")


def _ref(value: object) -> object:
    """A header string: an identifier, or a ref with ``@`` (``task@version``),
    ``/`` (``org/model``) or ``+`` (``kinds:a+b``); any other value is "?"."""
    if isinstance(value, str):
        return value if _REF.fullmatch(value) else "?"
    return safe(value)


def _timeline(e: Event, content: bool) -> Row | None:
    p, t = e.payload, e.type
    row: Row = {}
    text: dict[str, object] = {}
    if t == "rep.policy":
        intent = as_dict(p.get("intent"))
        row = {"from": p.get("from"), "to": p.get("to"), "intent": intent.get("kind")}
    elif t == "slow.tool":
        name = p.get("name") if p.get("name") in TOOL_NAMES else "unknown"
        result = str(p.get("result_text", ""))
        row = {"name": name, "ok": p.get("ok"), "result_len": len(result)}
        text = {"result_text": result[:100]}
    elif t == "action.denied":
        row = {"intent": p.get("intent"), "reason": p.get("reason")}
    elif t in ("s2f.msg", "f2s.msg"):
        guide = as_dict(p.get("guide"))
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
    out |= {k: safe(v) for k, v in row.items() if v is not None}
    return out | (text if content else {})


def triage(run: Path, content: bool = False, relay_window_s: float = 10) -> Row:
    """The run's row plus its timeline (``relay_window_ms`` travels with it)."""
    index_row, x = read(run, runs.Seal(), relay_window_s, content)
    rows = [r for e in x.events if (r := _timeline(e, content)) is not None]
    return row(index_row, x) | {"relay_window_ms": x.relay_window_ms, "timeline": rows}


def text_report(report: Row) -> str:
    skip = ("schema", "advisory", "detectors", "timeline")
    out = [f"# {BANNER}"]
    out += [f"{k}: {v}" for k, v in report.items() if k not in skip]
    out.append("-- timeline")
    for r in cast(list[Row], report["timeline"]):
        rest = " ".join(f"{k}={v}" for k, v in r.items() if k not in _LEAD)
        out.append(f"{r['t_ms']:>8} #{r['seq']:<5} {r['type']:<19} {rest}")
    out.append("-- detectors")
    out += [f"{k}: {v}" for k, v in as_dict(report["detectors"]).items()]
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
    except Unreadable as err:
        print(f"unreadable: {err}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False))
    else:
        print(text_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
