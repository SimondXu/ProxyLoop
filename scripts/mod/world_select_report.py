"""World-model selection, PR2b-2 (S1-MOD-09): the CLI of the scores, the blind Mouth
judge batches and the report. Offline: no key, no model call (ADR-0024).

    python -m scripts.mod.world_select score --gold-sha <sha256> --rows <jsonl>... \
        [--runs runs] [--prices <json>] [--judge-dir <dir> --judge-key <json>] [--out]
    python -m scripts.mod.world_select report ...  (score's options; the report files)
    python -m scripts.mod.world_select judge-export --rows <jsonl>... --out-dir <dir> \
        --key-out <json outside the out dir> --seed N

``score`` prints (or writes ``--out``) the scores: the Ear's (``world_select_score``),
the Mouth's (fidelity_ok, fallback, timeout, the judged M1..M5 and no-violation rates
with judge labels; an exhausted Mouth returns its template, ``world.bounded``, so
exhaustion is the fallback rate), the SimUser's (full-check validity, partial checks,
exhausted, timeout; invented numbers: digits, ``world.numbers``, in a reply that appear
nowhere in the request the SimUser saw, read from the bundles under ``--runs``, else
null; undeclared reveals null: the row does not carry them), latency (the HTTP records
without error, nearest-rank p50/p95), tokens, cost (only with ``--prices``: {model_id:
{"in": $/M, "out": $/M}} on prompt and completion tokens) and the served echoes; and
paired, X - incumbent per segment, Ear consequence-class accuracy and Mouth fidelity_ok
rate (one seed for every comparison). No decision rule: the user decides. ``report``
writes them with the git sha to ``docs/decisions/data/world-select-report.json`` and
renders ``world-select-report.md`` from that JSON (every number read from it).

``judge-export`` writes blind Mouth batches: every arm's Mouth model output (not a
fallback template, not an error), one per record with what the Mouth was asked to say
(``intent``, ``say``, ``ask``) and the ``heard`` text, shuffled with ``--seed`` into
batches of at most 25, with no arm, model or item id. Each batch header carries the
rubric, ``docs/decisions/data/world-select-mouth-rubric.md`` (refused unless its
sha256 is ``RUBRIC_SHA``) and the export id (``export_id``: seed, rows, rubric), which
every record id carries. The key (record -> arm, item id) goes to ``--key-out``,
outside ``--out-dir``; scoring refuses a key of other items, rows or rubric. The
judge's labels come back in the rubric's output format: arrays of {record, M1..M5:
bool, note}, in one or more JSON files in ``--judge-dir``.
No SimUser judge (ADR-0024).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, cast

from proxyloop.contract.base import canonical_json, sha256_text
from proxyloop.env import world
from scripts.mod import world_select as ws
from scripts.mod import world_select_run as wsr
from scripts.mod import world_select_score as sc

Obj = sc.Obj
DATA = ws.REPO / "docs/decisions/data"
REPORT, REPORT_MD = DATA / "world-select-report.json", DATA / "world-select-report.md"
RUBRIC = DATA / "world-select-mouth-rubric.md"
RUBRIC_SHA = "38e858bb40ca275e0b05a9555e74c26c5084d76b6fa88ac596928812f9b48b88"
SHOWN = ("record", "intent", "say", "ask", "heard", "output")  # a record, and no more


def fidelity(row: Obj) -> bool:
    return row["status"] == "ok" and row["result"]["fidelity_ok"] is True


def mouth_metrics(items: Sequence[Obj], arm: sc.Arm, judged: Obj | None) -> Obj:
    rows = [arm.row(i, "mouth") for i in items]
    fallback = [r["status"] == "ok" and r["result"]["fallback"] is True for r in rows]
    status = Counter(r["status"] for r in rows)
    out: Obj = {
        "items": len(rows),
        "fidelity_ok": sc.rate(sum(map(fidelity, rows)), len(rows)),
    }
    out |= {"fallback": sc.rate(sum(fallback), len(rows)), "timeout": status["timeout"]}
    out["exhausted"] = status["exhausted"]
    if judged is not None:
        got = [judged[i["item_id"]] for i in items if i["item_id"] in judged]
        out["judged"] = {
            m: sc.rate(sum(j[m] for j in got), len(got)) for m in sc.JUDGED
        }
        clean = sum(all(j[m] for m in sc.JUDGED) for j in got)
        out["judged"]["no_violation"] = sc.rate(clean, len(got))
    return out


def simuser_metrics(items: Sequence[Obj], arm: sc.Arm, prompts: Obj | None) -> Obj:
    rows = [(i, arm.row(i, "simuser")) for i in items]
    live = [(i, r) for i, r in rows if r["status"] != "not_replayable"]
    full = [r["status"] == "ok" for _, r in live if r.get("check") == "full"]
    status = Counter(r["status"] for _, r in rows)
    out: Obj = {"items": len(rows), "not_replayable": status["not_replayable"]}
    out["valid_full_check"] = sc.rate(sum(full), len(full))
    out["partial_check"] = sum(r.get("check") == "partial" for _, r in live)
    out |= {"exhausted": status["exhausted"], "timeout": status["timeout"]}
    out |= {"undeclared_reveals": None, "invented_numbers": None}
    if prompts is not None:
        ok = [
            (i, r) for i, r in live if r["status"] == "ok" and i["item_id"] in prompts
        ]
        texts = [
            (prompts[i["item_id"]], r["result"]["reply"].get("text")) for i, r in ok
        ]
        new = [world.numbers(t) - world.numbers(p) for p, t in texts if t]
        out["invented_numbers"] = sc.rate(sum(bool(x) for x in new), len(new))
        out["invented_numbers"]["numbers"] = sum(len(x) for x in new)
    return out


def simuser_prompts(doc: Obj, runs: Path) -> Obj:
    """Item id -> the request text the SimUser saw (its frozen prompt sha's)."""
    rec, out = wsr.Recorded(doc, runs), dict[str, str]()
    for item in doc["items"]["simuser"]:
        for o in item["occurrences"]:
            if (b := rec.bundles.get(o["run_id"])) and item["prompt_sha"] in b.prompts:
                body = json.loads(b.prompts[item["prompt_sha"]].content)
                out[item["item_id"]] = "\n".join(m["content"] for m in body["messages"])
                break
    return out


def pct(values: Sequence[int], q: float) -> int | None:
    s = sorted(values)
    return s[max(math.ceil(q * len(s)) - 1, 0)] if s else None


def usage(arm: sc.Arm, prices: Obj | None) -> Obj:
    out: Obj = {"latency_ms": {}, "tokens": {}, "cost_usd": None}
    echoes: set[str] = set()
    for role in sorted(arm.roles):
        recs = [c for (_, r, _), row in sorted(arm.rows.items()) if r == role
                for a in sc.attempts(row) for c in a.get("records", [])]  # fmt: skip
        ms = [c["latency_ms"] for c in recs if c.get("error") is None]
        out["latency_ms"][role] = {
            "n": len(ms),
            "p50": pct(ms, 0.5),
            "p95": pct(ms, 0.95),
        }
        kinds = ("prompt_tokens", "completion_tokens", "reasoning_tokens")
        use = [cast(Obj, c.get("usage") or {}) for c in recs]
        tok = out["tokens"][role] = {k: sum(u.get(k) or 0 for u in use) for k in kinds}
        echoes |= {c["echo"] for c in recs if c.get("echo")}
        if prices is not None:
            if (p := prices.get(model := arm.model_ref["model_id"])) is None:
                raise SystemExit(f"--prices has no {model}")
            cost = tok["prompt_tokens"] * p["in"] + tok["completion_tokens"] * p["out"]
            out["cost_usd"] = (out["cost_usd"] or {}) | {role: round(cost / 1e6, 6)}
    return out | {"echoes": sorted(echoes)}


def by_segment[T](items: Iterable[T], of: Callable[[T], Obj]) -> dict[str, list[T]]:
    out: dict[str, list[T]] = {}
    for x in items:
        out.setdefault(sc.segment(of(x)), []).append(x)
    return {s: out[s] for s in sc.SEGMENTS if s in out}


def load_rows(paths: Iterable[Path], root: str) -> dict[str, sc.Arm]:
    """Per arm, the one final row per key (item_id, role, repeat), across all files;
    refused: a second final row, or a key whose last row is not final (unavailable or
    capped: re-run it). ``left`` counts the unavailable and capped rows."""
    arms: dict[str, sc.Arm] = {}
    last: dict[tuple[str, sc.RowKey], str] = {}
    for path in paths:
        torn, seen = 0, set[str]()
        for line in path.read_text("utf-8").splitlines():
            try:
                r = cast(Obj, json.loads(line))
            except ValueError:
                torn += 1  # a line cut by a crash: --resume re-ran its item
                continue
            if r.get("schema") != wsr.ROW_SCHEMA or r.get("items_root_hash") != root:
                raise SystemExit(f"{path}: a row of another schema or items")
            arm = arms.setdefault(r["arm"], sc.Arm(r["arm"], r["model_ref"], {}))
            seen.add(arm.label)
            key = (r["item_id"], r["role"], r["repeat"])
            last[(arm.label, key)] = r["status"]
            if r["status"] in wsr.FINAL and key in arm.rows:  # no best-of-N (rule 12)
                raise SystemExit(f"{path}: a second final row for {arm.label} {key}")
            if r["status"] in wsr.FINAL:
                arm.rows[key] = r
            else:
                arm.left[r["status"]] += 1
        if torn and len(seen) != 1:
            raise SystemExit(f"{path}: {torn} torn lines, arms {sorted(seen)}")
        for name in seen:
            arms[name].torn += torn
    if open_ := sorted(k for k, status in last.items() if status not in wsr.FINAL):
        raise SystemExit(f"{len(open_)} keys end unavailable or capped: {open_[0]}")
    return arms


def complete(doc: Obj, arm: sc.Arm) -> None:
    for role in arm.roles:
        ids = {i["item_id"] for i in sc.role_items(doc, role)}
        if missing := ids - {i for i, r, n in arm.rows if r == role and n == 1}:
            raise SystemExit(f"{arm.label}: {len(missing)} {role} items have no row")


def score(args: argparse.Namespace, judged: dict[str, Obj] | None = None) -> Obj:
    """``args``: items, codebook, gold, gold_sha, rows, runs, prices, incumbent,
    roles (every arm's scored roles; default: the incumbent's), seed, resamples.
    ``judged``: arm -> item id -> {M1..M5}."""
    gold, labels = sc.gold_labels(args.gold, args.gold_sha)
    doc = sc.checked_items(args.items, gold["items_root_hash"])
    if (sha := sc.sha256_file(args.codebook)) != gold["codebook_sha256"]:
        raise SystemExit(f"{args.codebook}: sha256 {sha}, not the gold's")
    ears = sc.role_items(doc, "ear")
    need = {
        (i["item_id"], n) for i in ears for n in range(1, len(sc.utterances(i)) + 1)
    }
    if missing := need - labels.keys():
        raise SystemExit(f"the gold lacks {len(missing)} labels, e.g. {min(missing)}")
    arms = load_rows(args.rows, doc["root_hash"])
    if args.incumbent not in arms:
        raise SystemExit(f"no rows of the incumbent {args.incumbent}")
    want = set(args.roles or ()) or arms[args.incumbent].roles
    if odd := {a.label: sorted(a.roles) for a in arms.values() if a.roles != want}:
        raise SystemExit(f"arms not on the roles {sorted(want)}: {odd}")
    for arm in arms.values():
        complete(doc, arm)
    prices = sc.load_json(args.prices) if args.prices else None
    prompts = simuser_prompts(doc, args.runs) if args.runs else None
    out: Obj = {"note": sc.NOTE, "incumbent": args.incumbent, "arms": {}}
    out |= {"items_root_hash": doc["root_hash"], "codebook_sha256": sha}
    out |= {"gold_sha256": args.gold_sha, "gold_counts": gold.get("counts")}
    out |= {"bootstrap": {"seed": args.seed, "resamples": args.resamples}}
    units: dict[str, list[sc.Unit]] = {}
    for name, arm in sorted(arms.items()):
        res = {"model_ref": arm.model_ref, "torn_lines": arm.torn} | usage(arm, prices)
        res["not_final_rows"] = {k: arm.left[k] for k in ("unavailable", "capped")}
        if "ear" in arm.roles:
            units[name] = sc.ear_units(doc, labels, arm)
            segs = by_segment(units[name], lambda u: u.item)
            res["ear"] = {s: sc.ear_metrics(v, arm) for s, v in segs.items()}
        if "mouth" in arm.roles:
            j = None if judged is None else judged.get(name, {})
            segs = by_segment(sc.role_items(doc, "mouth"), lambda i: i)
            res["mouth"] = {s: mouth_metrics(v, arm, j) for s, v in segs.items()}
        if "simuser" in arm.roles:
            segs = by_segment(sc.role_items(doc, "simuser"), lambda i: i)
            res["simuser"] = {
                s: simuser_metrics(v, arm, prompts) for s, v in segs.items()
            }
        out["arms"][name] = res
    return out | {"paired": paired(doc, arms, units, args)}


def paired(
    doc: Obj,
    arms: dict[str, sc.Arm],
    ears: dict[str, list[sc.Unit]],
    args: argparse.Namespace,
) -> Obj:
    """X - incumbent: Ear consequence-class accuracy and Mouth fidelity_ok rate."""
    inc, out = arms[args.incumbent], dict[str, Obj]()

    def boot(units: Iterable[tuple[Obj, float, int]]) -> Obj:
        clustered = [(sc.cluster(i), d, n) for i, d, n in units]
        return sc.bootstrap(clustered, args.seed, args.resamples)

    for name, arm in sorted(arms.items()):
        if arm is inc:
            continue
        res: Obj = out.setdefault(name, {})
        if name in ears and inc.label in ears:
            ear = zip(ears[name], ears[inc.label], strict=True)
            units = [
                (x.item, sum(x.correct) - sum(y.correct), len(x.pairs)) for x, y in ear
            ]
            segs = by_segment(units, lambda t: t[0])
            res["ear_cc_accuracy"] = {s: boot(v) for s, v in segs.items()}
        if "mouth" in arm.roles & inc.roles:
            mouth = [(i, fidelity(arm.row(i, "mouth")) - fidelity(inc.row(i, "mouth")),
                      1) for i in sc.role_items(doc, "mouth")]  # fmt: skip
            segs = by_segment(mouth, lambda t: t[0])
            res["mouth_fidelity_ok"] = {s: boot(v) for s, v in segs.items()}
    return out


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
    eid, records, left = (
        export_id(args.seed, args.rows),
        list[tuple[Obj, Obj]](),
        Counter[str](),
    )
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
    key["export_id"] = eid
    key |= {"rubric_sha256": RUBRIC_SHA, "not_exported": dict(sorted(left.items()))}
    key |= {"batches": {}, "records": {}}
    for k, at in enumerate(range(0, len(records), size), 1):
        name, chunk = f"judge-{eid[:8]}-{k:03d}", records[at : at + size]
        ids = [f"{name}-{p:02d}" for p in range(len(chunk))]
        shown = [{"record": i} | s for i, (_, s) in zip(ids, chunk, strict=True)]
        head = {"batch": name, "export_id": eid, "rubric": text}
        head["rubric_sha256"] = RUBRIC_SHA
        dump(out_dir / f"{name}.json", head | {"records": shown})
        key["batches"][name] = ids
        key["records"] |= {i: m for i, (m, _) in zip(ids, chunk, strict=True)}
    dump(args.key_out, key)
    return key


def export_id(seed: int, rows: Sequence[Path]) -> str:
    """An export's id: the sha256 of its seed, its rows files' sha256 set and the
    rubric's sha256."""
    shas = sorted(sc.sha256_file(p) for p in rows)
    return sha256_text(
        canonical_json({"seed": seed, "rows": shas, "rubric": RUBRIC_SHA})
    )


def judged_labels(
    key_path: Path, labels: Path, root: str, rows: Sequence[Path]
) -> dict[str, Obj]:
    """Arm -> item id -> {M1..M5}, from the judge's label arrays and the export key,
    which must be this rubric's and, by its export id, these items' and rows' (every
    record id carries the id): every exported record labelled exactly once."""
    key = cast(Obj, sc.load_json(key_path))
    eid, records = key["export_id"], cast(Obj, key["records"])
    same = (key["root_hash"], key["rubric_sha256"]) == (root, RUBRIC_SHA)
    if not same or eid != export_id(key["seed"], rows):
        raise SystemExit(f"{key_path}: an export of other items, rows or rubric")
    if any(not i.startswith(f"judge-{eid[:8]}-") for i in records):
        raise SystemExit(f"{key_path}: a record id without the export id {eid[:8]}")
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
    if unlabelled := len(records.keys() - seen):
        raise SystemExit(f"{unlabelled} of {len(records)} exported records unlabelled")
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
    keys = (
        "latency_ms",
        "tokens",
        "cost_usd",
        "echoes",
        "torn_lines",
        "not_final_rows",
    )
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
        p.add_argument("--roles", type=wsr.roles_arg, help="every arm's, exactly")
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
        key = judge_export(doc, load_rows(args.rows, doc["root_hash"]), args)
        summary: Obj = {"batches": len(key["batches"]), "records": len(key["records"])}
        summary["not_exported"] = key["not_exported"]
    else:
        if (args.judge_dir is None) != (args.judge_key is None):
            raise SystemExit("--judge-dir and --judge-key go together")
        root = sc.load_json(args.items)["root_hash"]  # score() checks the items
        judged = (
            judged_labels(args.judge_key, args.judge_dir, root, args.rows)
            if args.judge_dir
            else None
        )
        doc = score(args, judged)
        if args.cmd == "report":
            dump(args.out, doc | {"git_sha": git_sha()})
            args.out_md.write_text(render(sc.load_json(args.out)) + "\n", "utf-8")
        elif args.out is not None:
            dump(args.out, doc)
        summary = doc if args.out is None else {"out": str(args.out)}
    json.dump(summary, sys.stdout, indent=1, sort_keys=True)
    print()
