"""World-model selection, PR2b-1 (S1-MOD-09): the Ear gold file. Offline: no key, no
model call (ADR-0024).

    python -m scripts.mod.world_select gold --labels-dir <dir> --batch-key <json> \
        --adj-key <json> [--user <json> --review <json>] \
        [--out docs/decisions/data/world-select-gold.json]

It refuses items that do not hash to the frozen root, a codebook whose sha256 is not
the frozen one, and a ``--batch-key`` made for other items.

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
ones it gives; else, when its act is the replaced label's, that label's; else those of
the alternate with its act (on the sheet entry, then on the replaced label). A
``provide_fact`` without facts or a ``cite_competitor`` without a price is refused,
every such item listed. ``excluded`` labels stay, marked ``excluded: true``; scoring
leaves them out. The output is deterministic, with sorted keys.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Sequence
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
FIRST_PASS = {f"batch-{n:03d}": "v1.0" if n <= 6 else "v1.1" for n in range(1, 18)} | {
    f"check-{n:03d}": "v1.1" for n in range(1, 8)
}
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


def decided(d: Json, entry: Json, base: Json) -> Json:
    """A user decision's label content (its arguments: the module docstring)."""
    act = d["act"]
    seen = [*entry.get("alternates", []), *base["alternates"]]
    alts = [cast(Json, a) for a in seen if isinstance(a, dict)]
    alts = [a for a in alts if a.get("act") == act]
    src = base if act == base["act"] else (alts[0] if alts else {})
    new: Json = {a: d.get(a, src.get(a)) for a in ARGS}
    return new | {"act": act, "facts": new["facts"] or []}


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
    by_id = {
        i["item_id"]: i for i in (*doc["items"]["ear"], *doc["constructed"]["ear"])
    }

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

    out: dict[Label, Json] = {}
    for item in doc["constructed"]["ear"]:
        for n, g in enumerate(item["gold"], 1):
            out[(item["item_id"], n)] = label(g, "constructed", None)
    for (b, pos, n), r in read_labels(labels, "batch").items():
        if by_id.get(iid := at(b, pos), {"constructed": True}).get("constructed"):
            raise SystemExit(f"{b} {pos}: not a recorded Ear item")
        if b not in FIRST_PASS:
            raise SystemExit(f"{b}: no first-pass codebook version")
        out[(iid, n)] = label(r, "annotator", FIRST_PASS[b])
    for (b, pos, n), r in read_labels(labels, "adj").items():
        if out.get(k := (adj(b, pos), n), {}).get("source") != "annotator":
            raise SystemExit(f"{b} {pos} {n}: adjudicates no first-pass label")
        out[k] = label(r, "adjudicated", version)
    need = {(i, n) for i, it in by_id.items() for n in range(1, len(said(it)) + 1)}
    if bad := need ^ out.keys():
        raise SystemExit(f"{len(bad)} labels missing or extra, e.g. {min(bad)}")
    entries, done, lacking = {e["id"]: e for e in sheet}, set[Label](), list[str]()
    for d in decisions:
        if (e := entries.get(d["review_id"])) is None:
            raise SystemExit(f"review_id {d['review_id']} is not on the sheet")
        if "check" in e:
            k = (at(*e["check"][:2]), e["check"][2])
        else:
            k = (adj(e["adj"], e["pos"]), e["idx"])
        if said(by_id[k[0]])[k[1] - 1] != e["text"] or k in done:
            raise SystemExit(f"review_id {d['review_id']}: not its text, or twice")
        done.add(k)
        new = decided(d, e, out[k])
        if (arg := NEEDS.get(new["act"])) and new[arg] in (None, []):
            lacking.append(f"review_id {d['review_id']} ({k[0]} {k[1]}): {arg}")
        out[k] = label(new, "user", version)
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
    return ap


def main(argv: Sequence[str]) -> None:
    """``argv`` after ``gold``."""
    args = parser().parse_args(argv)
    if (args.user is None) != (args.review is None):
        raise SystemExit("--user and --review go together")
    user = (read(args.user), read(args.review)) if args.user else ((), ())
    keys = read(args.batch_key), read(args.adj_key)
    doc = gold(load_items(args.items), args.labels_dir, *keys, args.codebook, *user)
    write(args.out, doc)
    summary = doc["counts"] | {"sha256": file_sha(args.out)}
    json.dump(summary, sys.stdout, indent=1, sort_keys=True)
    print()
