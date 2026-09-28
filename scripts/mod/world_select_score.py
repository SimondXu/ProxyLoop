"""World-model selection, PR2b-1 (S1-MOD-09): the Ear gold file. Offline: no key, no
model call (ADR-0024).

    python -m scripts.mod.world_select gold --labels-dir <dir> --batch-key <json> \
        --adj-key <json> (--user <json> --review <json> | --draft --out <scratch>) \
        [--out docs/decisions/data/world-select-gold.json]

It refuses items that do not hash to the frozen root, a codebook whose sha256 is not
the frozen one, and a ``--batch-key`` made for other items. Coverage is complete or
refused: every utterance of every Ear item has one label, every ``--adj-key`` item is
adjudicated on every utterance, and every review id on the sheet is decided exactly
once. Only ``--draft`` writes without the user's decisions, never to the default
``--out``, and it marks the file ``draft: true``.

Per (item_id, idx), the label with the highest precedence wins:

1. the user's decision (``--user``: [{review_id, act, offer_ref?, price_usd?,
   facts?}]), located by the ``--review`` sheet's {id, adj, pos, idx} (through
   ``--adj-key``) or {id, check: [batch, pos, idx]} (through ``--batch-key``), whose
   ``text`` must be the utterance's;
2. the adjudication (``adj-*.json``; ``--adj-key``: adj batch -> [[batch, pos]...]);
3. the first pass (``batch-*.json``; ``--batch-key``: batch -> [item_id...] by pos).

Constructed Ear items keep their constructed ``gold`` (source ``constructed``, no
codebook version) unless the user decides. Every label records its ``source`` and
``codebook_version``: the first pass's per batch (``FIRST_PASS``), the adjudication's
and the user's the committed codebook's (its title). A user decision's arguments: the
ones it gives (all of them: given any, the others are empty); else, when its act is
the replaced label's, that label's; else those of the alternate with its act (on the
sheet entry, then on the replaced label); else none. Its ``args_from`` says which:
``decision``, the replaced label's source (``adjudicated``, ``annotator`` or
``constructed``), ``alternate`` or ``none``. An adj entry's ``orig`` must be the
``--adj-key``'s [batch, pos]. The head records the sha256 of every input file. A
``provide_fact`` without facts or a ``cite_competitor`` without a price is refused,
every such item listed. ``excluded`` labels stay, marked ``excluded: true``; scoring
leaves them out. The output is deterministic, with sorted keys.

PR2b-2: the scoring core (the gold as read, rows, statistics, Ear metrics);
``world_select_report`` runs it and adds the Mouth, SimUser, calls and paired parts.
The gold file is read by its schema, never rebuilt: its sha256 must be ``--gold-sha``
(as ADR-0024 records it), not a ``draft``, the items must hash to the root it names
and the codebook to the sha256 it names, and every Ear utterance must have a label.

Rows: each arm's last final row per (item_id, role, repeat); an arm missing a row for
an item of a role it ran is refused. Segments: recorded, constructed, and
off_distribution (the Ear items flagged so). Ear: the prediction is the row's acts
(the first valid attempt's); an exhausted or timed-out item is wrong in every accuracy
and also counted; ``excluded`` gold is left out. The consequence class merges
smalltalk, other, injection and refuse_fact into ``clarify``; the harm classes are
accept, cancel_intent and cite_competitor (an error is a negative). Only the gold act
is right: alternates earn nothing. Rates carry Wilson 95 % CIs. Argument accuracy is on
the utterances whose gold act uses the argument and whose predicted act is that act
(prices as decimals; facts as sets, values case- and space-folded). Frequency weights
are each recorded item's occurrence count (constructed: 1). Stability: the repeat-2
act equals repeat 1's, per utterance (an error disagrees). The paired bootstrap
resamples clusters (a recorded item's cluster is its first occurrence's run_id; a
constructed item is its own) and reports the 2.5 % point at index floor(0.025 (B - 1))
and the 97.5 % point at ceil(0.975 (B - 1)).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from proxyloop.contract.base import sha256_text
from scripts.mod import world_select as ws

Json = dict[str, Any]
Label = tuple[str, int]  # (item_id, idx)
DATA = ws.REPO / "docs/decisions/data"
ITEMS, CODEBOOK = DATA / "world-select-items.json", DATA / "world-select-codebook.md"
GOLD = DATA / "world-select-gold.json"
ITEMS_ROOT = "471a0a9151af0c85204b6d49d2977fc14fae50fdfcd77cc2c2401246d61a41cc"
CODEBOOK_SHA = "892c8f686dfcb27d6a4c81a0f672c44226e2e306f625cf895da427534b4b7a38"
# The codebook each first-pass batch was labelled under (model root, 2026-09-28).
FIRST_PASS = {f"batch-{n:03d}": "v1.0" if n <= 6 else "v1.1" for n in range(1, 18)}
LABEL_ACTS = (*ws.ACTS, "excluded")
ARGS = ("offer_ref", "price_usd", "facts")
NEEDS = {"provide_fact": "facts", "cite_competitor": "price_usd"}


def read(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def write(path: Path, doc: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, "utf-8")


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_items(path: Path) -> Json:
    doc = cast(Json, read(path))
    ids = [i["item_id"] for k in ("items", "constructed") for r in ws.ROLES
           for i in doc[k][r]]  # fmt: skip
    root = sha256_text("\n".join(sorted(ids)))
    if root != doc["root_hash"] or root != ITEMS_ROOT:
        raise SystemExit(f"{path}: the items hash to {root}, not {ITEMS_ROOT}")
    return doc


def codebook(path: Path) -> tuple[str, str]:
    """The codebook's sha256 (the frozen one) and version (its title's)."""
    if (sha := file_sha(path)) != CODEBOOK_SHA:
        raise SystemExit(f"{path}: sha256 {sha}, not the frozen {CODEBOOK_SHA}")
    found = re.search(r"codebook (v[\d.]+)", path.read_text("utf-8"))
    if found is None:
        raise SystemExit(f"{path}: no version in its title")
    return sha, found.group(1)


def said(item: Json) -> list[str]:
    return list(item["block"] if item.get("constructed") else item["utterances"])


def label(r: Json, source: str, version: str | None) -> Json:
    if r["act"] not in LABEL_ACTS:
        raise SystemExit(f"unknown act {r['act']!r} ({source})")
    out = {k: r.get(k) for k in ("act", "offer_ref", "price_usd", "confidence")}
    out |= {"facts": list(r.get("facts") or []), "codebook_version": version}
    out |= {"alternates": list(r.get("alternates") or []), "source": source}
    return out | {"excluded": r["act"] == "excluded"}


def index(v: object, low: int, what: str) -> int:
    """``v`` as a position: a non-bool int ``>= low`` (no negative indexing)."""
    if isinstance(v, bool) or not isinstance(v, int) or v < low:
        raise SystemExit(f"{what} {v!r}: not an int >= {low}")
    return v


def read_labels(root: Path, prefix: str) -> dict[tuple[str, int, int], Json]:
    out: dict[tuple[str, int, int], Json] = {}
    for f in sorted(root.glob(f"{prefix}-*.json")):
        for r in cast(list[Json], read(f)):
            if r["batch"] != f.stem:
                raise SystemExit(f"{f}: a label of batch {r['batch']}")
            pos, idx = index(r["pos"], 0, f"{f}: pos"), index(r["idx"], 1, f"{f}: idx")
            if (at := (r["batch"], pos, idx)) in out:
                raise SystemExit(f"{f}: two labels for {at}")
            out[at] = r
    return out


def decided(d: Json, entry: Json, base: Json) -> Json:
    """A user decision's label content and ``args_from`` (the module docstring)."""
    act = d["act"]
    seen = [*entry.get("alternates", []), *base["alternates"]]
    alts = [cast(Json, a) for a in seen if isinstance(a, dict)]
    alts = [a for a in alts if a.get("act") == act]
    src, since = (
        (d, "decision") if any(a in d for a in ARGS)
        else (base, base["source"]) if act == base["act"]
        else (alts[0], "alternate") if alts
        else ({}, "none")
    )  # fmt: skip
    new: Json = {a: src.get(a) for a in ARGS}
    return new | {"act": act, "facts": new["facts"] or [], "args_from": since}


def gold(
    doc: Json,
    labels: Path,
    key: Json,
    adj_key: Json,
    book: Path,
    decisions: Sequence[Json] = (),
    sheet: Sequence[Json] = (),
) -> Json:
    """The gold file (the module docstring)."""
    sha, version = codebook(book)
    if key["root_hash"] != doc["root_hash"]:
        raise SystemExit(f"--batch-key is for the items {key['root_hash']}")
    listed = Counter(i for b in key["batches"].values() for i in b)
    if twice := sorted(i for i, c in listed.items() if c > 1):
        raise SystemExit(f"--batch-key lists {len(twice)} items twice, e.g. {twice[0]}")
    by_id = {
        i["item_id"]: i for i in (*doc["items"]["ear"], *doc["constructed"]["ear"])
    }

    def at(batch: str, pos: object) -> str:
        n = index(pos, 0, f"--batch-key {batch} pos")
        try:
            return cast(str, key["batches"][batch][n])
        except (KeyError, IndexError):
            raise SystemExit(f"--batch-key has no item at {batch} {n}") from None

    def adj(batch: str, pos: object) -> str:
        n = index(pos, 0, f"--adj-key {batch} pos")
        try:
            orig = adj_key[batch][n]
        except (KeyError, IndexError):
            raise SystemExit(f"--adj-key has no item at {batch} {n}") from None
        return at(*orig)

    out: dict[Label, Json] = {}
    for item in doc["constructed"]["ear"]:
        for n, g in enumerate(item["gold"], 1):
            out[(item["item_id"], n)] = label(g, "constructed", None)
    for (b, pos, n), r in read_labels(labels, "batch").items():
        if by_id.get(iid := at(b, pos), {"constructed": True}).get("constructed"):
            raise SystemExit(f"{b} {pos}: not a recorded Ear item")
        if b not in FIRST_PASS:
            raise SystemExit(f"{b}: no first-pass codebook version")
        if (iid, n) in out:
            raise SystemExit(f"{b} {pos} {n}: a second first-pass label for {iid} {n}")
        out[(iid, n)] = label(r, "annotator", FIRST_PASS[b])
    for (b, pos, n), r in read_labels(labels, "adj").items():
        if out.get(k := (adj(b, pos), n), {}).get("source") != "annotator":
            raise SystemExit(f"{b} {pos} {n}: adjudicates no first-pass label")
        out[k] = label(r, "adjudicated", version)
    short: list[str] = []  # every --adj-key utterance, a missing adj file's too
    for b, pairs in sorted(adj_key.items()):
        for pos in range(len(pairs)):
            iid = adj(b, pos)
            for n in range(1, (len(said(by_id[iid])) if iid in by_id else 1) + 1):
                if out.get((iid, n), {}).get("source") != "adjudicated":
                    short.append(f"{b} {pos} {n}")
    if short:
        raise SystemExit(f"{len(short)} --adj-key utterances unadjudicated: {short[0]}")
    need = {(i, n) for i, it in by_id.items() for n in range(1, len(said(it)) + 1)}
    if bad := need ^ out.keys():
        raise SystemExit(f"{len(bad)} labels missing or extra, e.g. {min(bad)}")
    ids, given = [e["id"] for e in sheet], Counter(d["review_id"] for d in decisions)
    if len(set(ids)) != len(ids):
        raise SystemExit("the review sheet lists an id twice")
    if extra := [i for i in given if i not in ids]:
        raise SystemExit(f"review_id {extra[0]} is not on the sheet")
    if odd := [i for i in ids if given[i] != 1]:
        raise SystemExit(f"{len(odd)} review ids not decided exactly once: {odd[0]}")
    entries, done, lacking = {e["id"]: e for e in sheet}, set[Label](), list[str]()
    for d in decisions:
        e = entries[d["review_id"]]
        where = f"review_id {d['review_id']}"
        if "check" in e:
            batch, at_pos, at_idx = e["check"]
            k = (at(batch, at_pos), index(at_idx, 1, f"{where}: check idx"))
        else:
            k = (adj(e["adj"], e["pos"]), index(e["idx"], 1, f"{where}: idx"))
            if e.get("orig") != (orig := adj_key[e["adj"]][e["pos"]]):
                raise SystemExit(f"{where}: orig {e.get('orig')}, --adj-key {orig}")
        heard = said(by_id[k[0]])
        if k[1] > len(heard) or heard[k[1] - 1] != e["text"] or k in done:
            raise SystemExit(f"review_id {d['review_id']}: not its text, or twice")
        done.add(k)
        new = decided(d, e, out[k])
        if (arg := NEEDS.get(new["act"])) and new[arg] in (None, []):
            lacking.append(f"review_id {d['review_id']} ({k[0]} {k[1]}): {arg}")
        out[k] = label(new, "user", version) | {"args_from": new["args_from"]}
    if lacking:
        raise SystemExit("decisions without their argument: " + "; ".join(lacking))
    listed = [{"item_id": i, "idx": n} | v for (i, n), v in sorted(out.items())]
    counts: Json = {"labels": len(listed), "items": len({i for i, _ in out})}
    counts["by_source"] = dict(Counter(v["source"] for v in listed))
    counts["excluded"] = sum(1 for v in listed if v["excluded"])
    head = {"version": 1, "items_root_hash": doc["root_hash"], "codebook_sha256": sha}
    return head | {"codebook_version": version, "labels": listed, "counts": counts}


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m scripts.mod.world_select gold")
    ap.add_argument("--items", type=Path, default=ITEMS)
    ap.add_argument("--codebook", type=Path, default=CODEBOOK)
    for flag in ("--labels-dir", "--batch-key", "--adj-key"):
        ap.add_argument(flag, type=Path, required=True, help="read-only")
    ap.add_argument("--user", type=Path, help="the user's decisions, with --review")
    ap.add_argument("--review", type=Path, help="the review sheet")
    ap.add_argument("--out", type=Path, default=GOLD)
    ap.add_argument(
        "--draft",
        action="store_true",
        help="without the user's decisions, not --out's default",
    )
    return ap


def inputs_sha256(args: argparse.Namespace) -> Json:
    """The sha256 of every input file but the items and the codebook (in the head)."""
    labels = sorted(
        f for p in ("batch", "adj") for f in args.labels_dir.glob(f"{p}-*.json")
    )
    user = {"review": args.review, "decisions": args.user}
    out: Json = {k: file_sha(v) if v else None for k, v in user.items()}
    out |= {"batch_key": file_sha(args.batch_key), "adj_key": file_sha(args.adj_key)}
    return out | {"labels": {f.name: file_sha(f) for f in labels}}


def main(argv: Sequence[str]) -> None:
    """``argv`` after ``gold``."""
    args = parser().parse_args(argv)
    if (args.user is None) != (args.review is None):
        raise SystemExit("--user and --review go together")
    if args.user is None and not args.draft:
        raise SystemExit("the gold needs --user and --review (or --draft)")
    if args.draft and args.out.resolve() == GOLD.resolve():
        raise SystemExit(f"--draft never writes {GOLD}")
    user = (read(args.user), read(args.review)) if args.user else ((), ())
    keys = read(args.batch_key), read(args.adj_key)
    doc = gold(load_items(args.items), args.labels_dir, *keys, args.codebook, *user)
    doc |= {"draft": args.draft, "inputs_sha256": inputs_sha256(args)}
    write(args.out, doc)
    summary = doc["counts"] | {"sha256": file_sha(args.out)}
    json.dump(summary, sys.stdout, indent=1, sort_keys=True)
    print()


Obj = dict[str, Any]
RowKey = tuple[str, str, int]  # (item_id, role, repeat)
Units = Sequence[tuple[str, float, int]]  # (cluster, X - incumbent, count)
INCUMBENT = "teamrouter:gemini-3.8-flash@low"
CLARIFY = frozenset({"smalltalk", "other", "injection", "refuse_fact"})
HARM = ("accept", "cancel_intent", "cite_competitor")
ARG_ACTS = {
    "offer_ref": ("accept", "ask_readback"),
    "price_usd": ("cite_competitor", "accept"),
    "facts": ("provide_fact",),
}
GOLD_FIELDS = frozenset(
    {"item_id", "idx", "act", "offer_ref", "price_usd", "facts", "source"}
    | {"codebook_version", "excluded"}
)
SEGMENTS = ("recorded", "constructed", "off_distribution")
JUDGED = ("M1", "M2", "M3", "M4", "M5")
Z = 1.959963984540054  # the normal 97.5 % quantile
NOTE = "Internal instrument choice, not a claim; the user decides (ADR-0024)."


def r4(x: float) -> float:
    return round(x, 4)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gold_labels(path: Path, sha: str) -> tuple[Obj, dict[tuple[str, int], Obj]]:
    """The gold file, as ADR-0024 pins it, and its labels by (item_id, idx)."""
    if (got := sha256_file(path)) != sha:
        raise SystemExit(f"{path}: sha256 {got}, not --gold-sha {sha}")
    doc = cast(Obj, load_json(path))
    if doc.get("version") != 1 or doc.get("draft"):
        raise SystemExit(f"{path}: not a final version-1 gold")
    out: dict[tuple[str, int], Obj] = {}
    for x in cast(list[Obj], doc["labels"]):
        if missing := GOLD_FIELDS - x.keys():
            raise SystemExit(f"{path}: a label lacks {sorted(missing)}")
        out[(x["item_id"], x["idx"])] = x
    return doc, out


def checked_items(path: Path, root: str) -> Obj:
    doc = cast(Obj, load_json(path))
    ids = [i["item_id"] for k in ("items", "constructed") for r in ws.ROLES
           for i in doc[k][r]]  # fmt: skip
    got = sha256_text("\n".join(sorted(ids)))
    if got != doc["root_hash"] or got != root:
        raise SystemExit(f"{path}: the items hash to {got}, not the gold's {root}")
    return doc


def role_items(doc: Obj, role: str) -> list[Obj]:
    return [*doc["items"][role], *doc["constructed"][role]]


def utterances(item: Obj) -> list[str]:
    return list(item["block"] if item.get("constructed") else item["utterances"])


def segment(item: Obj) -> str:
    if item.get("off_distribution"):
        return "off_distribution"
    return "constructed" if item.get("constructed") else "recorded"


def cluster(item: Obj) -> str:
    """A recorded item's first occurrence's run; a constructed item is its own."""
    if item.get("constructed"):
        return cast(str, item["item_id"])
    return cast(str, item["occurrences"][0]["run_id"])


@dataclass
class Arm:
    label: str
    model_ref: Obj
    rows: dict[RowKey, Obj]
    torn: int = 0
    left: Counter[str] = field(default_factory=Counter[str])  # unavailable, capped

    def row(self, item: Obj, role: str, repeat: int = 1) -> Obj:
        return self.rows[(item["item_id"], role, repeat)]

    @property
    def roles(self) -> set[str]:
        return {role for _, role, _ in self.rows}


def attempts(row: Obj) -> list[Obj]:
    return list(row.get("attempts") or [])


def rate(k: int, n: int) -> Obj:
    """k of n with a Wilson 95 % CI (rate and CI null when n is 0)."""
    if n == 0:
        return {"k": k, "n": 0, "rate": None, "ci95": None}
    p, z2 = k / n, Z * Z
    half = Z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    lo, hi = [(p + z2 / (2 * n) + s * half) / (1 + z2 / n) for s in (-1, 1)]
    ci95 = [r4(max(lo, 0.0)), r4(min(hi, 1.0))]
    return {"k": k, "n": n, "rate": r4(p), "ci95": ci95}


def weighted(weights: Sequence[float], hits: Sequence[bool]) -> float | None:
    total = sum(weights)
    hit = sum(w for w, h in zip(weights, hits, strict=True) if h)
    return r4(hit / total) if total else None


def bootstrap(units: Units, seed: int, resamples: int) -> Obj:
    """Clusters resampled with replacement: the ratio sum(X - incumbent) / count,
    its estimate and the 2.5 % and 97.5 % percentiles."""
    sums: dict[str, list[float]] = {}
    for c, d, n in units:
        t = sums.setdefault(c, [0.0, 0.0])
        t[0], t[1] = t[0] + d, t[1] + n
    groups = [sums[c] for c in sorted(sums) if sums[c][1]]
    out: Obj = {"units": len(units), "clusters": len(groups)}
    if not groups:
        return out | {"estimate": None, "ci95": None}
    est = sum(g[0] for g in groups) / sum(g[1] for g in groups)
    rng, stats = random.Random(seed), list[float]()
    for _ in range(resamples):
        pick = rng.choices(groups, k=len(groups))
        stats.append(sum(g[0] for g in pick) / sum(g[1] for g in pick))
    stats.sort()
    lo = stats[math.floor(0.025 * (resamples - 1))]
    hi = stats[math.ceil(0.975 * (resamples - 1))]
    return out | {"estimate": r4(est), "ci95": [r4(lo), r4(hi)]}


def cls(act: str) -> str:
    return "clarify" if act in CLARIFY else act


def fact_set(value: Any) -> set[tuple[str, str]]:
    said = cast(list[dict[str, str]], value or [])
    return {(f["key"], " ".join(f["value"].split()).casefold()) for f in said}


def same_arg(arg: str, g: Any, p: Any) -> bool:
    if arg == "facts":
        return fact_set(g) == fact_set(p)
    if arg == "price_usd" and g is not None and p is not None:
        return Decimal(str(g)) == Decimal(str(p))
    return g == p


@dataclass
class Unit:
    item: Obj
    row: Obj
    pairs: list[tuple[Obj, Obj | None]]  # (gold, predicted), excluded left out

    @property
    def correct(self) -> list[bool]:
        return [p is not None and cls(p["act"]) == cls(g["act"]) for g, p in self.pairs]


def predicted(row: Obj | None) -> list[Obj] | None:
    if row is None or row["status"] != "ok":
        return None
    return cast(list[Obj], row["result"]["acts"])


def ear_units(doc: Obj, labels: dict[tuple[str, int], Obj], arm: Arm) -> list[Unit]:
    out: list[Unit] = []
    for item in role_items(doc, "ear"):
        row = arm.row(item, "ear")
        acts, n = predicted(row), len(utterances(item))
        pairs = [(labels[(item["item_id"], i)], acts[i - 1] if acts else None)
                 for i in range(1, n + 1)]  # fmt: skip
        out.append(Unit(item, row, [(g, p) for g, p in pairs if not g["excluded"]]))
    return out


def first_size(row: Obj, n: int) -> bool:
    """The first attempt made exactly one call, holding exactly ``n`` acts."""
    try:
        raw = attempts(row)[0]["raw"]
        return len(raw) == 1 and len(json.loads(raw[0]["arguments"])["acts"]) == n
    except (ValueError, KeyError, TypeError, IndexError):
        return False


def per_class(acts: Sequence[tuple[str, str | None]], a: str) -> Obj:
    tp = sum(g == p == a for g, p in acts)
    recall = rate(tp, sum(g == a for g, _ in acts))
    return {"recall": recall, "precision": rate(tp, sum(p == a for _, p in acts))}


def harm(acts: Sequence[tuple[str, str | None]], h: str) -> Obj:
    fp = sum(p == h != g for g, p in acts)
    return {"fp": fp, "fn": sum(g == h != p for g, p in acts)}


def ear_metrics(units: Sequence[Unit], arm: Arm) -> Obj:
    pairs = [(u, g, p) for u in units for g, p in u.pairs]
    acts = [(g["act"], p["act"] if p else None) for _, g, p in pairs]
    cc, exact = [c for u in units for c in u.correct], [g == p for g, p in acts]
    w = [float(u.item.get("count", 1)) for u, _, _ in pairs]
    out: Obj = {"items": len(units), "utterances": len(pairs)}
    out["excluded"] = sum(len(utterances(u.item)) - len(u.pairs) for u in units)
    out["cc_accuracy"] = rate(sum(cc), len(cc))
    out["exact_accuracy"] = rate(sum(exact), len(exact))
    out["weighted"] = {"cc_accuracy": weighted(w, cc), "exact": weighted(w, exact)}
    out["per_class"] = {a: per_class(acts, a) for a in ws.ACTS}
    out["harm"] = {h: harm(acts, h) for h in HARM}
    first = [attempts(u.row)[0]["valid"] is True for u in units if attempts(u.row)]
    first += [False] * (len(units) - len(first))  # an item with no attempt
    out["first_attempt_valid"] = rate(sum(first), len(first))
    status = Counter(u.row["status"] for u in units)
    out |= {"exhausted": status["exhausted"], "timeout": status["timeout"]}
    blocks = [u for u in units if len(utterances(u.item)) > 1]
    sizes = [first_size(u.row, len(utterances(u.item))) for u in blocks]
    out["block_size_first_attempt"] = rate(sum(sizes), len(sizes))
    out["arguments"] = {}
    for arg, uses in ARG_ACTS.items():
        on = [(g, p) for _, g, p in pairs
              if g["act"] in uses and p and p["act"] == g["act"]]  # fmt: skip
        hits = sum(same_arg(arg, g.get(arg), p.get(arg)) for g, p in on)
        out["arguments"][arg] = rate(hits, len(on))
    agree: list[bool] = []
    for u in units:
        if (again := arm.rows.get((u.item["item_id"], "ear", 2))) is not None:
            both = zip(predicted(u.row) or [], predicted(again) or [], strict=False)
            same = [a["act"] == b["act"] for a, b in both]
            agree += same or [False] * len(utterances(u.item))
    out["stability"] = rate(sum(agree), len(agree))
    return out
