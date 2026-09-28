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
