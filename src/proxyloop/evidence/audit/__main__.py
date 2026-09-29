"""``python -m proxyloop.evidence.audit frame|export|label-append|disagreements``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from proxyloop.evidence.audit import export, frame, items, labels


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m proxyloop.evidence.audit")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("frame", help="draw the sampling frame from bundle dirs")
    f.add_argument("bundles", nargs="+", type=Path)
    f.add_argument("--seed", type=int, required=True)
    f.add_argument("--out", type=Path, required=True)
    for kind, n in frame.DEFAULT_SIZES.items():
        f.add_argument(f"--{kind}", type=int, default=n, help=f"items per cell ({n})")
    f.add_argument("--protected-keys", default=items.PROTECTED_KEYS, help="regex")
    e = sub.add_parser("export", help="the blinded items of a frame, shuffled")
    e.add_argument("frame", type=Path)
    e.add_argument("--seed", type=int, required=True)
    e.add_argument("--out", type=Path, required=True)
    a = sub.add_parser("label-append", help="append one label row")
    a.add_argument("store", type=Path)
    a.add_argument("--frame", type=Path, required=True, help="the item ids to accept")
    a.add_argument("--item", required=True)
    a.add_argument("--rater", required=True, choices=labels.RATERS)
    a.add_argument("--label", required=True, choices=labels.LABELS)
    d = sub.add_parser("disagreements", help="items the two raters label differently")
    d.add_argument("store", type=Path)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd == "frame":
        sizes = {k: getattr(args, k) for k in frame.DEFAULT_SIZES}
        cands = items.load(args.bundles, args.seed, args.protected_keys)
        built = frame.build(cands, args.seed, sizes)
        frame.dump(built, args.out)
        print(f"{len(built.items)} candidates, {len(built.sampled())} sampled")
    elif args.cmd == "export":
        rows = export.export(frame.load(args.frame), args.seed)
        export.write(rows, args.out)
        print(f"{len(rows)} items")
    elif args.cmd == "label-append":
        known = {i["item_id"] for i in frame.load(args.frame)["items"] if i["sampled"]}
        if args.item not in known:
            print(f"{args.item} is not a sampled item of the frame", file=sys.stderr)
            return 2
        print(labels.LabelStore(args.store).append(args.item, args.rater, args.label))
    else:
        for item in labels.LabelStore(args.store).disagreements():
            print(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
