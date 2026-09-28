"""World-model selection, PR2b-2 (S1-MOD-09): the scoring core (the gold as read, the
rows, the statistics, the Ear metrics). Offline: no key, no model call (ADR-0024).
``world_select_report`` runs it (``score``, ``report``) and adds the Mouth, SimUser,
latency, cost and paired parts.

The gold file is read by its schema (version 1; labels with item_id, idx, act,
offer_ref, price_usd, facts, source, codebook_version, excluded), never rebuilt: its
sha256 must be ``--gold-sha`` (the value ADR-0024 records), the items must hash to the
root it names and the codebook to the sha256 it names (the gold builder checked both
against the frozen values), and every scored Ear utterance must have a label.

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

import hashlib
import json
import math
import random
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from proxyloop.contract.base import sha256_text
from scripts.mod import world_select as ws
from scripts.mod import world_select_run as wsr

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
    if doc.get("version") != 1:
        raise SystemExit(f"{path}: gold version {doc.get('version')}, not 1")
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

    def row(self, item: Obj, role: str, repeat: int = 1) -> Obj:
        return self.rows[(item["item_id"], role, repeat)]

    @property
    def roles(self) -> set[str]:
        return {role for _, role, _ in self.rows}


def load_rows(paths: Iterable[Path], root: str) -> dict[str, Arm]:
    """Per arm, the last final row per key (unavailable and capped rows re-ran)."""
    arms: dict[str, Arm] = {}
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
            arm = arms.setdefault(r["arm"], Arm(r["arm"], r["model_ref"], {}))
            seen.add(arm.label)
            if r["status"] in wsr.FINAL:
                arm.rows[(r["item_id"], r["role"], r["repeat"])] = r
        if torn and len(seen) != 1:
            raise SystemExit(f"{path}: {torn} torn lines, arms {sorted(seen)}")
        for name in seen:
            arms[name].torn += torn
    return arms


def complete(doc: Obj, arm: Arm) -> None:
    for role in arm.roles:
        ids = {i["item_id"] for i in role_items(doc, role)}
        if missing := ids - {i for i, r, n in arm.rows if r == role and n == 1}:
            raise SystemExit(f"{arm.label}: {len(missing)} {role} items have no row")


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


def by_segment[T](items: Iterable[T], of: Callable[[T], Obj]) -> dict[str, list[T]]:
    out: dict[str, list[T]] = {}
    for x in items:
        out.setdefault(segment(of(x)), []).append(x)
    return {s: out[s] for s in SEGMENTS if s in out}
