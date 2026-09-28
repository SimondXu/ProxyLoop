"""World-model selection, PR2b-2 (S1-MOD-09): the CLI of the scores, the blind Mouth
judge batches and the report. Offline: no key, no model call (ADR-0024).

    python -m scripts.mod.world_select score --gold-sha <sha256> --rows <jsonl>... \
        [--runs runs] [--prices <json>] [--judge-dir <dir> --judge-key <json>] [--out]
    python -m scripts.mod.world_select report ...  (score's options; the report files)
    python -m scripts.mod.world_select judge-export --rows <jsonl>... --out-dir <dir> \
        --key-out <json outside the out dir> --seed N

``score`` prints (or writes ``--out``) the scores of ``world_select_score``. ``report``
writes them with the git sha to ``docs/decisions/data/world-select-report.json`` and
renders ``world-select-report.md`` from that JSON (every number read from it).

``judge-export`` writes blind Mouth batches: every arm's Mouth model output (not a
fallback template, not an error), one per record with what the Mouth was asked to say
(``intent``, ``say``, ``ask``) and the ``heard`` text, shuffled with ``--seed`` into
batches of at most 25, with no arm, model or item id. Each batch header carries the
rubric, ``docs/decisions/data/world-select-mouth-rubric.md`` (refused unless its
sha256 is ``RUBRIC_SHA``). The key (record -> arm, item id) goes to ``--key-out``,
outside ``--out-dir``. The judge's labels come back in the rubric's output format:
arrays of {record, M1..M5: bool, note}, one or more JSON files in ``--judge-dir``.
No SimUser judge (ADR-0024).
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from scripts.mod import world_select as ws
from scripts.mod import world_select_run as wsr
from scripts.mod import world_select_score as sc

Obj = sc.Obj
DATA = ws.REPO / "docs/decisions/data"
REPORT, REPORT_MD = DATA / "world-select-report.json", DATA / "world-select-report.md"
RUBRIC = DATA / "world-select-mouth-rubric.md"
RUBRIC_SHA = "38e858bb40ca275e0b05a9555e74c26c5084d76b6fa88ac596928812f9b48b88"
SHOWN = ("record", "intent", "say", "ask", "heard", "output")  # a record, and no more


def dump(path: Path, doc: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, "utf-8")


def rubric(path: Path) -> str:
    if (sha := sc.sha256_file(path)) != RUBRIC_SHA:
        raise SystemExit(f"{path}: sha256 {sha}, not the rubric's {RUBRIC_SHA}")
    return path.read_text("utf-8")


def asked(item: Obj) -> Obj:
    """What the Mouth was asked to say: the intent kind, its say and ask terms."""
    made = bool(item.get("constructed"))
    i = cast(Obj, item | {"kind": item["intent"]} if made else item["intent"])
    say = sorted(i["say"].items()) if made else i.get("say", [])
    terms = {"say": [list(kv) for kv in say], "ask": list(i.get("ask", []))}
    return {"intent": i["kind"]} | terms


def judge_export(doc: Obj, arms: dict[str, sc.Arm], args: argparse.Namespace) -> Obj:
    """``args``: out_dir, key_out, seed, batch, rubric."""
    out_dir, size = cast(Path, args.out_dir), cast(int, args.batch)
    if not 1 <= size <= ws.MAX_BATCH:
        raise SystemExit(f"--batch must be 1..{ws.MAX_BATCH}, got {size}")
    if args.key_out.resolve().is_relative_to(out_dir.resolve()):
        raise SystemExit(f"--key-out {args.key_out} is inside --out-dir {out_dir}")
    text = rubric(args.rubric)
    records: list[tuple[Obj, Obj]] = []
    left = Counter[str]()
    for name, arm in sorted(arms.items()):
        for item in sc.role_items(doc, "mouth") if "mouth" in arm.roles else ():
            if (r := arm.row(item, "mouth"))["status"] != "ok" or r["result"][
                "fallback"
            ]:
                left["fallback" if r["status"] == "ok" else r["status"]] += 1
                continue
            shown = asked(item) | {
                "heard": item["heard"],
                "output": r["result"]["text"],
            }
            records.append(({"arm": name, "item_id": item["item_id"]}, shown))
    random.Random(args.seed).shuffle(records)
    key: Obj = {"seed": args.seed, "batch_size": size, "root_hash": doc["root_hash"]}
    key |= {"rubric_sha256": RUBRIC_SHA, "not_exported": dict(sorted(left.items()))}
    key |= {"batches": {}, "records": {}}
    for k, at in enumerate(range(0, len(records), size), 1):
        name, chunk = f"judge-{k:03d}", records[at : at + size]
        ids = [f"{name}-{p:02d}" for p in range(len(chunk))]
        shown = [{"record": i} | s for i, (_, s) in zip(ids, chunk, strict=True)]
        head = {"batch": name, "rubric": text, "rubric_sha256": RUBRIC_SHA}
        dump(out_dir / f"{name}.json", head | {"records": shown})
        key["batches"][name] = ids
        key["records"] |= {i: m for i, (m, _) in zip(ids, chunk, strict=True)}
    dump(args.key_out, key)
    return key


def judged_labels(key_path: Path, labels: Path) -> dict[str, Obj]:
    """Arm -> item id -> {M1..M5}, from the judge's label arrays and the export key."""
    records = cast(Obj, sc.load_json(key_path))["records"]
    out: dict[str, Obj] = {}
    seen: set[str] = set()
    for f in sorted(labels.glob("*.json")):
        for r in cast(list[Obj], sc.load_json(f)):
            if (rid := str(r.get("record"))) not in records or rid in seen:
                raise SystemExit(f"{f}: record {rid!r} unknown or labelled twice")
            if not all(isinstance(r.get(m), bool) for m in sc.JUDGED):
                raise SystemExit(f"{f}: record {rid}: M1..M5 must be true or false")
            seen.add(rid)
            meta = records[rid]
            out.setdefault(meta["arm"], {})[meta["item_id"]] = {
                m: r[m] for m in sc.JUDGED
            }
    return out


def cell(v: object) -> str:
    if isinstance(v, dict) and ("rate" in v or "estimate" in v):
        r = cast(Obj, v)
        if "rate" in r:
            mid, n = r["rate"], f"{r['k']}/{r['n']}"
        else:
            mid, n = r["estimate"], f"{r['clusters']} clusters"
        return "-" if mid is None else f"{mid} [{r['ci95'][0]}, {r['ci95'][1]}] ({n})"
    if isinstance(v, list):
        return ", ".join(map(str, cast(list[Any], v)))
    return "-" if v is None else str(cast(object, v))


def flat(doc: Obj, pre: str = "") -> Obj:
    """Nested metrics as dotted keys; a rate or a comparison stays one cell."""
    out: Obj = {}
    for k, v in doc.items():
        if isinstance(v, dict) and not {"rate", "estimate"} & v.keys():
            out |= flat(cast(Obj, v), f"{pre}{k}.")
        else:
            out[pre + k] = v
    return out


def table(title: str, cols: dict[str, Obj]) -> list[str]:
    """One row per metric (the primary first), one column per arm."""
    keys = {k for c in cols.values() for k in c}
    lines = [f"## {title}", "", "| metric | " + " | ".join(cols) + " |"]
    lines.append("|" + "---|" * (len(cols) + 1))
    for k in sorted(keys, key=lambda k: (k != "cc_accuracy", k)):
        lines.append(
            f"| {k} | " + " | ".join(cell(c.get(k)) for c in cols.values()) + " |"
        )
    return [*lines, ""]


def render(doc: Obj) -> str:
    """The md report, every number rendered from ``doc`` (the report JSON)."""
    arms: dict[str, Obj] = doc["arms"]
    out = ["# World-model selection report (S1-MOD-09, ADR-0024)", "", doc["note"], ""]
    for k in ("git_sha", "items_root_hash", "codebook_sha256", "gold_sha256"):
        out.append(f"- {k}: {doc[k]}")
    out += [f"- incumbent: {doc['incumbent']}", "- primary: Ear cc_accuracy", ""]
    for role in ws.ROLES:
        for s in sc.SEGMENTS:
            cols = {
                a: flat(r[role][s]) for a, r in arms.items() if s in r.get(role, {})
            }
            out += table(f"{role}: {s}", cols) if cols else []
    paired = {a: flat(r) for a, r in doc["paired"].items()}
    out += table("paired: X - incumbent, 95 % CI (no decision rule)", paired)
    keys = ("latency_ms", "tokens", "cost_usd", "echoes", "torn_lines")
    cols = {a: flat({k: r[k] for k in keys}) for a, r in arms.items()}
    return "\n".join(out + table("calls: latency, tokens, cost, served echoes", cols))


def git_sha() -> str:
    run = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ws.REPO, capture_output=True)
    return run.stdout.decode().strip()


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m scripts.mod.world_select")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cmds = {c: sub.add_parser(c) for c in ("score", "report", "judge-export")}
    for p in cmds.values():
        p.add_argument("--items", type=Path, default=wsr.ITEMS)
        p.add_argument("--rows", type=Path, nargs="+", required=True, help="per arm")
    for c in ("score", "report"):
        p = cmds[c]
        p.add_argument(
            "--codebook", type=Path, default=DATA / "world-select-codebook.md"
        )
        p.add_argument("--gold", type=Path, default=DATA / "world-select-gold.json")
        p.add_argument("--gold-sha", required=True, help="as ADR-0024 records it")
        for flag in ("--runs", "--prices", "--judge-dir", "--judge-key"):
            p.add_argument(flag, type=Path)
        p.add_argument("--incumbent", default=sc.INCUMBENT)
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--resamples", type=int, default=10_000)
    cmds["score"].add_argument("--out", type=Path, help="default: stdout")
    cmds["report"].add_argument("--out", type=Path, default=REPORT)
    cmds["report"].add_argument("--out-md", type=Path, default=REPORT_MD)
    j = cmds["judge-export"]
    j.add_argument("--out-dir", type=Path, required=True)
    j.add_argument("--key-out", type=Path, required=True, help="outside --out-dir")
    j.add_argument("--seed", type=int, required=True)
    j.add_argument("--batch", type=int, default=ws.MAX_BATCH)
    j.add_argument("--rubric", type=Path, default=RUBRIC)
    return ap


def main(argv: Sequence[str]) -> None:
    """``argv`` from the subcommand on."""
    args = parser().parse_args(argv)
    if args.cmd == "judge-export":
        doc = sc.checked_items(args.items, sc.load_json(args.items)["root_hash"])
        key = judge_export(doc, sc.load_rows(args.rows, doc["root_hash"]), args)
        summary: Obj = {"batches": len(key["batches"]), "records": len(key["records"])}
        summary["not_exported"] = key["not_exported"]
    else:
        if (args.judge_dir is None) != (args.judge_key is None):
            raise SystemExit("--judge-dir and --judge-key go together")
        judged = (
            judged_labels(args.judge_key, args.judge_dir) if args.judge_dir else None
        )
        doc = sc.score(args, judged)
        if args.cmd == "report":
            dump(args.out, doc | {"git_sha": git_sha()})
            args.out_md.write_text(render(sc.load_json(args.out)) + "\n", "utf-8")
        elif args.out is not None:
            dump(args.out, doc)
        summary = doc if args.out is None else {"out": str(args.out)}
    json.dump(summary, sys.stdout, indent=1, sort_keys=True)
    print()
