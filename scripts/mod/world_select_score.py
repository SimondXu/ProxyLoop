"""World-model selection, PR2b (S1-MOD-09): the Ear gold, the scores, the blind judge
batches and the report. Offline: no key, no model call (ADR-0024).

    python -m scripts.mod.world_select gold --labels-dir <dir> --batch-key <json> \
        --adj-key <json> --annotator-codebook <v> [--user <json> --review <json>]
    python -m scripts.mod.world_select score --gold-sha <sha256> --rows <jsonl>... \
        [--runs runs] [--prices <json>] [--judge-dir <dir> --judge-key <json>]
    python -m scripts.mod.world_select report ...  (score's options; the report files)
    python -m scripts.mod.world_select judge-export --rows <jsonl>... --out-dir <dir> \
        --key-out <json outside the out dir> --seed N

Every command refuses items that do not hash to the frozen root; ``gold``, ``score``
and ``report`` a codebook that is not the frozen one; ``score`` a gold file whose
sha256 is not ``--gold-sha`` or that names other items or another codebook.

``gold``, per (item, utterance): the user's decision (``--user``: [{review_id, act,
offer_ref?, price_usd?, facts?}], located by the ``--review`` sheet's {id, adj, pos,
idx} or {id, check: [batch, pos, idx]}, whose ``text`` must be the item's) over the
adjudication (``adj-*.json``; ``--adj-key``: adj batch -> [[batch, pos]...]) over the
first pass (``batch-*.json``; ``--batch-key``: batch -> [item_id...]). A user act
equal to the act it replaces keeps that label's arguments unless given; another act
takes only the given ones. Constructed Ear items keep their constructed ``gold``
(source ``constructed``) unless the user decides. ``excluded`` labels stay, marked,
and are never scored.

``score`` takes each arm's last final row per (item_id, role, repeat) and refuses an
arm missing an item of a role it ran. Segments: recorded, constructed, and
off_distribution (the Ear items flagged so). Ear: the prediction is the row's acts
(the first valid attempt's); an exhausted or timed-out item is wrong in every
accuracy and also counted. The consequence class merges smalltalk, other, injection
and refuse_fact into ``clarify``. Rates carry Wilson 95 % CIs. Argument accuracy is
on the utterances whose gold act uses the argument and whose predicted act is that
act (prices as decimals; facts as sets, values case- and space-folded). Frequency
weights are each recorded item's occurrence count (constructed: 1). Stability: the
repeat-2 act equals repeat 1's, per utterance (an error disagrees). Paired: X -
incumbent per segment, a percentile bootstrap resampling clusters (one seed for every
comparison): a recorded item's cluster is its first occurrence's run_id; a
constructed item is its own. No decision rule: the user decides. SimUser invented
numbers: digits (``world.numbers``) in a reply that appear nowhere in the request the
SimUser saw (persona, goal, facts, chat, stop), read from the bundles under
``--runs`` (without it: null). Latency: the HTTP records without error, nearest-rank
p50/p95. Cost only with ``--prices`` ({model_id: {"in": $/M, "out": $/M}}), on the
prompt and completion tokens.

``judge-export``: every arm's Mouth model outputs (not a fallback template, not an
error), one per record with the intent, its say/ask terms and the heard text, shuffled
with ``--seed`` into batches of at most 25, with no arm or model; the key goes to
``--key-out``. Judge labels come back as arrays of {batch, pos, M1..M5: bool}.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from proxyloop.contract.base import sha256_text
from proxyloop.env import world
from scripts.mod import world_select as ws
from scripts.mod import world_select_run as wsr

Json = dict[str, Any]
Key = tuple[str, str, int]  # (item_id, role, repeat)
Units = Sequence[tuple[str, float, int]]  # (cluster, X - incumbent, count)
DATA = ws.REPO / "docs/decisions/data"
ITEMS, CODEBOOK = wsr.ITEMS, DATA / "world-select-codebook.md"
GOLD, REPORT = DATA / "world-select-gold.json", DATA / "world-select-report.json"
REPORT_MD = DATA / "world-select-report.md"
ITEMS_ROOT = "471a0a9151af0c85204b6d49d2977fc14fae50fdfcd77cc2c2401246d61a41cc"
CODEBOOK_SHA = "892c8f686dfcb27d6a4c81a0f672c44226e2e306f625cf895da427534b4b7a38"
INCUMBENT = "teamrouter:gemini-3.8-flash@low"
LABEL_ACTS = (*ws.ACTS, "excluded")
CLARIFY = frozenset({"smalltalk", "other", "injection", "refuse_fact"})
HARM = ("accept", "cancel_intent", "cite_competitor")
ARGS = {
    "offer_ref": ("accept", "ask_readback"),
    "price_usd": ("cite_competitor", "accept"),
    "facts": ("provide_fact",),
}
SEGMENTS = ("recorded", "constructed", "off_distribution")
JUDGE = ("M1", "M2", "M3", "M4", "M5")
Z = 1.959963984540054  # the normal 97.5 % quantile
NOTE = "Internal instrument choice, not a claim; the user decides (ADR-0024)."


def r4(x: float) -> float:
    return round(x, 4)


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


def role_items(doc: Json, role: str) -> list[Json]:
    return [*doc["items"][role], *doc["constructed"][role]]


def said(item: Json) -> list[str]:
    return list(item["block"] if item.get("constructed") else item["utterances"])


def segment(item: Json) -> str:
    if item.get("off_distribution"):
        return "off_distribution"
    return "constructed" if item.get("constructed") else "recorded"


def cluster(item: Json) -> str:
    """A recorded item's first occurrence's run; a constructed item is its own."""
    if item.get("constructed"):
        return cast(str, item["item_id"])
    return cast(str, item["occurrences"][0]["run_id"])


def label(r: Json, source: str, version: str | None) -> Json:
    if r["act"] not in LABEL_ACTS:
        raise SystemExit(f"unknown act {r['act']!r} ({source})")
    out = {k: r.get(k) for k in ("act", "offer_ref", "price_usd", "confidence")}
    out |= {"facts": list(r.get("facts") or []), "codebook": version}
    out |= {"alternates": list(r.get("alternates") or []), "source": source}
    return out | {"excluded": r["act"] == "excluded"}


def read_labels(root: Path, prefix: str) -> dict[tuple[str, int, int], Json]:
    out: dict[tuple[str, int, int], Json] = {}
    for f in sorted(root.glob(f"{prefix}-*.json")):
        for r in cast(list[Json], read(f)):
            if r["batch"] != f.stem:
                raise SystemExit(f"{f}: a label of batch {r['batch']}")
            if (at := (r["batch"], r["pos"], r["idx"])) in out:
                raise SystemExit(f"{f}: two labels for {at}")
            out[at] = r
    return out


def gold(
    doc: Json,
    labels: Path,
    key: Json,
    adj_key: Json,
    annotator_codebook: str,
    book: Path,
    decisions: Sequence[Json] = (),
    sheet: Sequence[Json] = (),
) -> Json:
    """The gold file (the module docstring)."""
    sha, version = codebook(book)
    if key["root_hash"] != doc["root_hash"]:
        raise SystemExit(f"--batch-key is for the items {key['root_hash']}")
    by_id = {i["item_id"]: i for i in role_items(doc, "ear")}

    def at(batch: str, pos: int) -> str:
        try:
            return cast(str, key["batches"][batch][pos])
        except (KeyError, IndexError):
            raise SystemExit(f"--batch-key has no item at {batch} {pos}") from None

    def adj(batch: str, pos: int) -> str:
        try:
            return at(*adj_key[batch][pos])
        except (KeyError, IndexError):
            raise SystemExit(f"--adj-key has no item at {batch} {pos}") from None

    out: dict[tuple[str, int], Json] = {}
    for item in doc["constructed"]["ear"]:
        for n, g in enumerate(item["gold"], 1):
            out[(item["item_id"], n)] = label(g, "constructed", None)
    for (b, pos, n), r in read_labels(labels, "batch").items():
        if by_id.get(iid := at(b, pos), {"constructed": True}).get("constructed"):
            raise SystemExit(f"{b} {pos}: not a recorded Ear item")
        out[(iid, n)] = label(r, "annotator", annotator_codebook)
    for (b, pos, n), r in read_labels(labels, "adj").items():
        if out.get(k := (adj(b, pos), n), {}).get("source") != "annotator":
            raise SystemExit(f"{b} {pos} {n}: adjudicates no first-pass label")
        out[k] = label(r, "adjudicated", version)
    need = {(i, n) for i, it in by_id.items() for n in range(1, len(said(it)) + 1)}
    if bad := need ^ out.keys():
        raise SystemExit(f"{len(bad)} labels missing or extra, e.g. {min(bad)}")
    rows, decided = {e["id"]: e for e in sheet}, set[tuple[str, int]]()
    for d in decisions:
        if (e := rows.get(d["review_id"])) is None:
            raise SystemExit(f"review_id {d['review_id']} is not on the sheet")
        if "check" in e:
            k = (at(*e["check"][:2]), e["check"][2])
        else:
            k = (adj(e["adj"], e["pos"]), e["idx"])
        if said(by_id[k[0]])[k[1] - 1] != e["text"] or k in decided:
            raise SystemExit(f"review_id {d['review_id']}: not its text, or twice")
        decided.add(k)
        act, base = d["act"], out[k]
        new = {a: d.get(a, base[a] if act == base["act"] else None) for a in ARGS}
        new["facts"] = new["facts"] or []
        if (act, bool(new["facts"])) == ("provide_fact", False) or (
            act == "cite_competitor" and new["price_usd"] is None
        ):
            raise SystemExit(f"review_id {d['review_id']}: {act} needs its argument")
        out[k] = label(new | {"act": act}, "user", version)
    listed = [{"item_id": i, "idx": n} | v for (i, n), v in sorted(out.items())]
    counts: Json = {"labels": len(listed), "items": len({i for i, _ in out})}
    counts["by_source"] = dict(Counter(v["source"] for v in listed))
    counts["excluded"] = sum(1 for v in listed if v["excluded"])
    head = {"version": 1, "items_root_hash": doc["root_hash"], "codebook_sha256": sha}
    return head | {"codebook_version": version, "labels": listed, "counts": counts}


def load_gold(
    path: Path, sha: str, doc: Json, book: Path
) -> dict[tuple[str, int], Json]:
    if (got := file_sha(path)) != sha:
        raise SystemExit(f"{path}: sha256 {got}, not --gold-sha {sha}")
    g = cast(Json, read(path))
    made_for = (g["items_root_hash"], g["codebook_sha256"])
    if made_for != (doc["root_hash"], codebook(book)[0]):
        raise SystemExit(f"{path}: made for other items or another codebook")
    return {(x["item_id"], x["idx"]): x for x in g["labels"]}


@dataclass
class Arm:
    label: str
    model_ref: Json
    rows: dict[Key, Json]
    torn: int = 0

    def row(self, item: Json, role: str, repeat: int = 1) -> Json:
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
                r = cast(Json, json.loads(line))
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


def complete(doc: Json, arm: Arm) -> None:
    for role in arm.roles:
        ids = {i["item_id"] for i in role_items(doc, role)}
        if missing := ids - {i for i, r, n in arm.rows if r == role and n == 1}:
            raise SystemExit(f"{arm.label}: {len(missing)} {role} items have no row")


def attempts(row: Json) -> list[Json]:
    return list(row.get("attempts") or [])


def rate(k: int, n: int) -> Json:
    """k of n with a Wilson 95 % CI (rate and CI null when n is 0)."""
    if n == 0:
        return {"k": k, "n": 0, "rate": None, "ci95": None}
    p, z2 = k / n, Z * Z
    half = Z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    lo, hi = [(p + z2 / (2 * n) + s * half) / (1 + z2 / n) for s in (-1, 1)]
    return {"k": k, "n": n, "rate": r4(p), "ci95": [r4(max(lo, 0)), r4(min(hi, 1))]}


def weighted(weights: Sequence[float], hits: Sequence[bool]) -> float | None:
    total = sum(weights)
    return (
        r4(sum(w for w, h in zip(weights, hits, strict=True) if h) / total)
        if total
        else None
    )


def bootstrap(units: Units, seed: int, resamples: int) -> Json:
    """Clusters resampled with replacement: the ratio sum(X - incumbent) / count,
    its estimate and the 2.5 % and 97.5 % percentiles."""
    sums: dict[str, list[float]] = {}
    for c, d, n in units:
        t = sums.setdefault(c, [0.0, 0.0])
        t[0], t[1] = t[0] + d, t[1] + n
    groups = [sums[c] for c in sorted(sums) if sums[c][1]]
    out: Json = {"units": len(units), "clusters": len(groups)}
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


def facts(value: Any) -> set[tuple[str, str]]:
    said = cast(list[dict[str, str]], value or [])
    return {(f["key"], " ".join(f["value"].split()).casefold()) for f in said}


def same_arg(arg: str, g: Any, p: Any) -> bool:
    if arg == "facts":
        return facts(g) == facts(p)
    if arg == "price_usd" and g is not None and p is not None:
        return Decimal(str(g)) == Decimal(str(p))
    return g == p


@dataclass
class Unit:
    item: Json
    row: Json
    pairs: list[tuple[Json, Json | None]]  # (gold, predicted), excluded left out

    @property
    def correct(self) -> list[bool]:
        return [p is not None and cls(p["act"]) == cls(g["act"]) for g, p in self.pairs]


def predicted(row: Json | None) -> list[Json] | None:
    if row is None or row["status"] != "ok":
        return None
    return cast(list[Json], row["result"]["acts"])


def ear_units(doc: Json, labels: dict[tuple[str, int], Json], arm: Arm) -> list[Unit]:
    out: list[Unit] = []
    for item in role_items(doc, "ear"):
        acts, row = predicted(arm.row(item, "ear")), arm.row(item, "ear")
        pairs = [(labels[(item["item_id"], n)], acts[n - 1] if acts else None)
                 for n in range(1, len(said(item)) + 1)]  # fmt: skip
        out.append(Unit(item, row, [(g, p) for g, p in pairs if not g["excluded"]]))
    return out


def first_size(row: Json, n: int) -> bool:
    """The first attempt made exactly one call, holding exactly ``n`` acts."""
    try:
        raw = attempts(row)[0]["raw"]
        return len(raw) == 1 and len(json.loads(raw[0]["arguments"])["acts"]) == n
    except (ValueError, KeyError, TypeError, IndexError):
        return False


def per_class(acts: Sequence[tuple[str, str | None]], a: str) -> Json:
    tp = sum(g == p == a for g, p in acts)
    recall = rate(tp, sum(g == a for g, _ in acts))
    return {"recall": recall, "precision": rate(tp, sum(p == a for _, p in acts))}


def harm(acts: Sequence[tuple[str, str | None]], h: str) -> Json:
    """False positives and negatives on a harm class (an error is a negative)."""
    fp = sum(p == h != g for g, p in acts)
    return {"fp": fp, "fn": sum(g == h != p for g, p in acts)}


def ear_metrics(units: Sequence[Unit], arm: Arm) -> Json:
    pairs = [(u, g, p) for u in units for g, p in u.pairs]
    acts = [(g["act"], p["act"] if p else None) for _, g, p in pairs]
    cc, exact = [c for u in units for c in u.correct], [g == p for g, p in acts]
    w = [float(u.item.get("count", 1)) for u, _, _ in pairs]
    out: Json = {"items": len(units), "utterances": len(pairs)}
    out["excluded"] = sum(len(said(u.item)) - len(u.pairs) for u in units)
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
    blocks = [u for u in units if len(said(u.item)) > 1]
    sizes = [first_size(u.row, len(said(u.item))) for u in blocks]
    out["block_size_first_attempt"] = rate(sum(sizes), len(sizes))
    out["arguments"] = {}
    for arg, uses in ARGS.items():
        on = [(g, p) for _, g, p in pairs
              if g["act"] in uses and p and p["act"] == g["act"]]  # fmt: skip
        hits = sum(same_arg(arg, g.get(arg), p.get(arg)) for g, p in on)
        out["arguments"][arg] = rate(hits, len(on))
    agree: list[bool] = []
    for u in units:
        if (again := arm.rows.get((u.item["item_id"], "ear", 2))) is not None:
            one, two = predicted(u.row), predicted(again)
            both = zip(one or [], two or [], strict=False)
            same = [a["act"] == b["act"] for a, b in both]
            agree += same or [False] * len(said(u.item))
    out["stability"] = rate(sum(agree), len(agree))
    return out


def fidelity(row: Json) -> bool:
    return row["status"] == "ok" and row["result"]["fidelity_ok"] is True


def mouth_metrics(items: Sequence[Json], arm: Arm, judged: Json | None) -> Json:
    rows = [arm.row(i, "mouth") for i in items]
    fallback = [r["status"] == "ok" and r["result"]["fallback"] is True for r in rows]
    status = Counter(r["status"] for r in rows)
    out: Json = {
        "items": len(rows),
        "fidelity_ok": rate(sum(map(fidelity, rows)), len(rows)),
    }
    out |= {"fallback": rate(sum(fallback), len(rows)), "timeout": status["timeout"]}
    out["exhausted"] = status["exhausted"]
    if judged is not None:
        got = [judged[i["item_id"]] for i in items if i["item_id"] in judged]
        out["judged"] = {
            m: rate(sum(j[m] is True for j in got), len(got)) for m in JUDGE
        }
    return out


def simuser_metrics(items: Sequence[Json], arm: Arm, prompts: Json | None) -> Json:
    rows = [(i, arm.row(i, "simuser")) for i in items]
    live = [(i, r) for i, r in rows if r["status"] != "not_replayable"]
    full = [r["status"] == "ok" for _, r in live if r.get("check") == "full"]
    status = Counter(r["status"] for _, r in rows)
    out: Json = {"items": len(rows), "not_replayable": status["not_replayable"]}
    out["valid_full_check"] = rate(sum(full), len(full))
    out["partial_check"] = sum(r.get("check") == "partial" for _, r in live)
    out |= {"exhausted": status["exhausted"], "timeout": status["timeout"]}
    # undeclared reveals: the row does not carry them
    out |= {"undeclared_reveals": None, "invented_numbers": None}
    if prompts is not None:
        ok = [
            (i, r) for i, r in live if r["status"] == "ok" and i["item_id"] in prompts
        ]
        texts = [
            (prompts[i["item_id"]], r["result"]["reply"].get("text")) for i, r in ok
        ]
        new = [world.numbers(t) - world.numbers(p) for p, t in texts if t]
        out["invented_numbers"] = rate(sum(bool(x) for x in new), len(new))
        out["invented_numbers"]["numbers"] = sum(len(x) for x in new)
    return out


def simuser_prompts(doc: Json, runs: Path) -> Json:
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


def usage(arm: Arm, prices: Json | None) -> Json:
    out: Json = {"latency_ms": {}, "tokens": {}, "cost_usd": None}
    echoes: set[str] = set()
    for role in sorted(arm.roles):
        recs = [c for (_, r, _), row in sorted(arm.rows.items()) if r == role
                for a in attempts(row) for c in a.get("records", [])]  # fmt: skip
        ms = [c["latency_ms"] for c in recs if c.get("error") is None]
        out["latency_ms"][role] = {
            "n": len(ms),
            "p50": pct(ms, 0.5),
            "p95": pct(ms, 0.95),
        }
        kinds = ("prompt_tokens", "completion_tokens", "reasoning_tokens")
        use = [cast(Json, c.get("usage") or {}) for c in recs]
        tok = out["tokens"][role] = {k: sum(u.get(k) or 0 for u in use) for k in kinds}
        echoes |= {c["echo"] for c in recs if c.get("echo")}
        if prices is not None:
            if (p := prices.get(model := arm.model_ref["model_id"])) is None:
                raise SystemExit(f"--prices has no {model}")
            cost = tok["prompt_tokens"] * p["in"] + tok["completion_tokens"] * p["out"]
            out["cost_usd"] = (out["cost_usd"] or {}) | {role: round(cost / 1e6, 6)}
    return out | {"echoes": sorted(echoes)}


def judged_labels(key_path: Path, root: Path) -> dict[str, Json]:
    """Arm -> item id -> {M1..M5}, from the judge's label arrays and the export key."""
    key, out = cast(Json, read(key_path)), dict[str, Json]()
    for (batch, pos, _), r in read_labels(root, "judge").items():
        meta = key["batches"][batch][pos]
        out.setdefault(meta["arm"], {})[meta["item_id"]] = {m: r[m] for m in JUDGE}
    return out


def by_segment[T](items: Iterable[T], of: Callable[[T], Json]) -> dict[str, list[T]]:
    out: dict[str, list[T]] = {}
    for x in items:
        out.setdefault(segment(of(x)), []).append(x)
    return {s: out[s] for s in SEGMENTS if s in out}


def score(args: argparse.Namespace) -> Json:
    doc = load_items(args.items)
    labels = load_gold(args.gold, args.gold_sha, doc, args.codebook)
    arms = load_rows(args.rows, doc["root_hash"])
    if args.incumbent not in arms:
        raise SystemExit(f"no rows of the incumbent {args.incumbent}")
    for arm in arms.values():
        complete(doc, arm)
    prices = read(args.prices) if args.prices else None
    prompts = simuser_prompts(doc, args.runs) if args.runs else None
    judge = judged_labels(args.judge_key, args.judge_dir) if args.judge_dir else None
    out: Json = {"note": NOTE, "incumbent": args.incumbent, "arms": {}}
    out |= {"items_root_hash": doc["root_hash"], "codebook_sha256": CODEBOOK_SHA}
    out |= {"gold_sha256": args.gold_sha, "seed": args.seed}
    out["resamples"] = args.resamples
    ears: dict[str, list[Unit]] = {}
    for name, arm in sorted(arms.items()):
        res = {"model_ref": arm.model_ref, "torn_lines": arm.torn} | usage(arm, prices)
        if "ear" in arm.roles:
            ears[name] = ear_units(doc, labels, arm)
            segs = by_segment(ears[name], lambda u: u.item)
            res["ear"] = {s: ear_metrics(v, arm) for s, v in segs.items()}
        if "mouth" in arm.roles:
            j = None if judge is None else judge.get(name, {})
            segs = by_segment(role_items(doc, "mouth"), lambda i: i)
            res["mouth"] = {s: mouth_metrics(v, arm, j) for s, v in segs.items()}
        if "simuser" in arm.roles:
            segs = by_segment(role_items(doc, "simuser"), lambda i: i)
            res["simuser"] = {
                s: simuser_metrics(v, arm, prompts) for s, v in segs.items()
            }
        out["arms"][name] = res
    return out | {"paired": paired(doc, arms, ears, args)}


def paired(
    doc: Json,
    arms: dict[str, Arm],
    ears: dict[str, list[Unit]],
    args: argparse.Namespace,
) -> Json:
    """X - incumbent: Ear consequence-class accuracy and Mouth fidelity_ok rate."""
    inc, out = arms[args.incumbent], dict[str, Json]()

    def boot(units: Iterable[tuple[Json, float, int]]) -> Json:
        return bootstrap(
            [(cluster(i), d, n) for i, d, n in units], args.seed, args.resamples
        )

    for name, arm in sorted(arms.items()):
        if arm is inc:
            continue
        res: Json = out.setdefault(name, {})
        if name in ears and inc.label in ears:
            ear = zip(ears[name], ears[inc.label], strict=True)
            units = [
                (x.item, sum(x.correct) - sum(y.correct), len(x.pairs)) for x, y in ear
            ]
            segs = by_segment(units, lambda t: t[0])
            res["ear_cc_accuracy"] = {s: boot(v) for s, v in segs.items()}
        if "mouth" in arm.roles & inc.roles:
            mouth = [(i, fidelity(arm.row(i, "mouth")) - fidelity(inc.row(i, "mouth")),
                      1) for i in role_items(doc, "mouth")]  # fmt: skip
            segs = by_segment(mouth, lambda t: t[0])
            res["mouth_fidelity_ok"] = {s: boot(v) for s, v in segs.items()}
    return out


def intent_of(item: Json) -> Json:
    """The Mouth's semantic input: intent kind, offer ref, say and ask terms."""
    made = bool(item.get("constructed"))
    i = cast(Json, item | {"kind": item["intent"]} if made else item["intent"])
    say = sorted(i["say"].items()) if made else i.get("say", [])
    terms = {"say": [list(kv) for kv in say], "ask": list(i.get("ask", []))}
    return {"kind": i["kind"], "offer_ref": i.get("offer_ref")} | terms


def judge_export(
    doc: Json, arms: dict[str, Arm], out_dir: Path, key_out: Path, seed: int, size: int
) -> Json:
    if not 1 <= size <= ws.MAX_BATCH:
        raise SystemExit(f"--batch must be 1..{ws.MAX_BATCH}, got {size}")
    if key_out.resolve().is_relative_to(out_dir.resolve()):
        raise SystemExit(f"--key-out {key_out} is inside --out-dir {out_dir}")
    records: list[tuple[Json, Json]] = []
    left = Counter[str]()
    for name, arm in sorted(arms.items()):
        for item in role_items(doc, "mouth") if "mouth" in arm.roles else ():
            if (r := arm.row(item, "mouth"))["status"] != "ok" or r["result"][
                "fallback"
            ]:
                left["fallback" if r["status"] == "ok" else r["status"]] += 1
                continue
            shown = {"intent": intent_of(item), "heard": item["heard"]}
            meta = {"arm": name, "item_id": item["item_id"], "role": "mouth"}
            records.append((meta, shown | {"output": r["result"]["text"]}))
    random.Random(seed).shuffle(records)
    key: Json = {"seed": seed, "batch_size": size, "root_hash": doc["root_hash"]}
    key |= {"not_exported": dict(sorted(left.items())), "batches": {}}
    for k, at in enumerate(range(0, len(records), size), 1):
        name, chunk = f"judge-{k:03d}", records[at : at + size]
        blank = dict.fromkeys(JUDGE)
        shown = [{"pos": p, **s, "labels": blank} for p, (_, s) in enumerate(chunk)]
        write(out_dir / f"{name}.json", {"batch": name, "items": shown})
        key["batches"][name] = [meta for meta, _ in chunk]
    write(key_out, key)
    return key


def cell(v: object) -> str:
    if isinstance(v, dict) and ("rate" in v or "estimate" in v):
        r = cast(Json, v)
        mid, n = (r["rate"], f"{r['k']}/{r['n']}") if "rate" in r else (
            r["estimate"], f"{r['clusters']} clusters")  # fmt: skip
        return "-" if mid is None else f"{mid} [{r['ci95'][0]}, {r['ci95'][1]}] ({n})"
    if isinstance(v, list):
        return ", ".join(map(str, cast(list[Any], v)))
    return "-" if v is None else str(cast(object, v))


def flat(doc: Json, pre: str = "") -> Json:
    """Nested metrics as dotted keys; a rate or a comparison stays one cell."""
    out: Json = {}
    for k, v in doc.items():
        if isinstance(v, dict) and not {"rate", "estimate"} & v.keys():
            out |= flat(cast(Json, v), f"{pre}{k}.")
        else:
            out[pre + k] = v
    return out


def table(title: str, cols: dict[str, Json]) -> list[str]:
    """One row per metric (the primary first), one column per arm."""
    keys = sorted(
        {k for c in cols.values() for k in c}, key=lambda k: (k != "cc_accuracy", k)
    )
    lines = [f"## {title}", "", "| metric | " + " | ".join(cols) + " |"]
    lines.append("|" + "---|" * (len(cols) + 1))
    for k in keys:
        lines.append(
            f"| {k} | " + " | ".join(cell(c.get(k)) for c in cols.values()) + " |"
        )
    return [*lines, ""]


def render(doc: Json) -> str:
    """The md report, every number rendered from ``doc``."""
    arms: dict[str, Json] = doc["arms"]
    out = ["# World-model selection report (S1-MOD-09, ADR-0024)", "", doc["note"], ""]
    for k in ("git_sha", "items_root_hash", "codebook_sha256", "gold_sha256"):
        out.append(f"- {k}: {doc[k]}")
    out += [f"- incumbent: {doc['incumbent']}", "- primary: Ear cc_accuracy", ""]
    for role in ws.ROLES:
        for s in SEGMENTS:
            cols = {
                a: flat(r[role][s]) for a, r in arms.items() if s in r.get(role, {})
            }
            out += table(f"{role}: {s}", cols) if cols else []
    out += table("paired: X - incumbent, 95 % CI, no decision rule", {
        a: flat(r) for a, r in doc["paired"].items()})  # fmt: skip
    usage_keys = ("latency_ms", "tokens", "cost_usd", "echoes", "torn_lines")
    cols = {a: flat({k: r[k] for k in usage_keys}) for a, r in arms.items()}
    return "\n".join(out + table("calls: latency, tokens, cost, echoes", cols))


def git_sha() -> str:
    run = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ws.REPO, capture_output=True)
    return run.stdout.decode().strip()


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m scripts.mod.world_select")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cmds = {c: sub.add_parser(c) for c in ("gold", "score", "report", "judge-export")}
    for c, p in cmds.items():
        p.add_argument("--items", type=Path, default=ITEMS)
        p.add_argument("--codebook", type=Path, default=CODEBOOK)
        if c != "gold":
            p.add_argument("--rows", type=Path, nargs="+", required=True, help="JSONL")
    g = cmds["gold"]
    for flag in ("--labels-dir", "--batch-key", "--adj-key"):
        g.add_argument(flag, type=Path, required=True)
    g.add_argument("--annotator-codebook", required=True, help="the first pass's")
    g.add_argument("--user", type=Path, help="the user's decisions, with --review")
    g.add_argument("--review", type=Path, help="the review sheet")
    g.add_argument("--out", type=Path, default=GOLD)
    for c in ("score", "report"):
        cmds[c].add_argument("--gold", type=Path, default=GOLD)
        cmds[c].add_argument("--gold-sha", required=True)
        for flag in ("--runs", "--prices", "--judge-dir", "--judge-key"):
            cmds[c].add_argument(flag, type=Path)
        cmds[c].add_argument("--incumbent", default=INCUMBENT)
        cmds[c].add_argument("--seed", type=int, default=0)
        cmds[c].add_argument("--resamples", type=int, default=10_000)
    cmds["score"].add_argument("--out", type=Path, help="default: stdout")
    cmds["report"].add_argument("--out", type=Path, default=REPORT)
    cmds["report"].add_argument("--out-md", type=Path, default=REPORT_MD)
    j = cmds["judge-export"]
    j.add_argument("--out-dir", type=Path, required=True)
    j.add_argument("--key-out", type=Path, required=True, help="outside --out-dir")
    j.add_argument("--seed", type=int, required=True)
    j.add_argument("--batch", type=int, default=ws.MAX_BATCH)
    return ap


def main(argv: Sequence[str]) -> None:
    args = parser().parse_args(argv)
    if args.cmd == "gold":
        if (args.user is None) != (args.review is None):
            raise SystemExit("--user and --review go together")
        user = (read(args.user), read(args.review)) if args.user else ((), ())
        keys = read(args.batch_key), read(args.adj_key)
        items = load_items(args.items)
        doc = gold(
            items, args.labels_dir, *keys, args.annotator_codebook, args.codebook, *user
        )
        write(args.out, doc)
        summary = doc["counts"] | {"sha256": file_sha(args.out)}
    elif args.cmd == "judge-export":
        items = load_items(args.items)
        arms = load_rows(args.rows, items["root_hash"])
        key = judge_export(
            items, arms, args.out_dir, args.key_out, args.seed, args.batch
        )
        summary = {"batches": len(key["batches"]), "not_exported": key["not_exported"]}
    else:
        if (args.judge_dir is None) != (args.judge_key is None):
            raise SystemExit("--judge-dir and --judge-key go together")
        doc = score(args)
        if args.cmd == "report":
            write(args.out, doc | {"git_sha": git_sha()})
            args.out_md.write_text(render(read(args.out)) + "\n", "utf-8")
        summary = doc if args.out is None else {"out": str(args.out)}
        if args.cmd == "score" and args.out is not None:
            write(args.out, doc)
    json.dump(summary, sys.stdout, indent=1, sort_keys=True)
    print()
