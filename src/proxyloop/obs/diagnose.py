"""The detectors across runs, grouped by slow_fp (else git_sha), newest first.

ADVISORY ONLY: triage signals, never a metric, a claim or a merge gate.

``python -m proxyloop.obs.diagnose [--root DIR ...] [--json] [--content]``
takes every ``ok`` bundle ``runs.index`` finds (sealed data is never listed or
read), one copy per run_id, and groups them by the Slow fingerprint they ran
with (``session.started.slow_fp``, S1-SYS-43), or by git_sha for a run without
one, then task_ref: an issue fixed later shows under its old group, not as
current, and bundles across agent harness v2 are never pooled (ADR-0018).
slow_fp changes with any edit under slow/ or guard/, so the groups are
fine-grained by design.
After the table, the outcome tiers per family (``obs.tiers``), per group;
``--json`` prints ``{"runs": [...], "tiers": {<group>: {...}}}``.
``--content`` lets the text-reading detectors run; their values stay codes,
but the rows (``--json``) then also carry the kernel-authored world_error
message.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from proxyloop.obs import runs, tiers
from proxyloop.obs.detectors import BANNER, as_dict, scalar
from proxyloop.obs.trace import Refused
from proxyloop.obs.triage import Row, Unreadable, read, row


def group(r: Row) -> str:
    """``slow_fp:<fp>`` when the run carries one, else ``git_sha:<sha>``."""
    fp = r.get("slow_fp")
    return f"slow_fp:{fp}" if fp is not None else f"git_sha:{r['git_sha']}"


def rows(
    roots: Sequence[Path], window_s: float = 10, content: bool = False
) -> tuple[list[Row], list[str]]:
    """One row per ok run, newest group first (by its newest run), then
    task_ref and start time within a group; and why each skipped run was."""
    seal, seen = runs.Seal(), set[str]()
    out, skipped = list[Row](), list[str]()
    for run in runs.index(roots):
        if run.status != "ok" or run.run_id in seen:
            continue
        seen.add(run.run_id)
        try:
            out.append(row(*read(Path(run.path), seal, window_s, content)))
        except (Unreadable, Refused) as err:  # one bad bundle never ends the table
            skipped.append(str(err))
    newest: dict[str, str] = {}
    for r in out:
        g, at = group(r), str(r["started"])
        newest[g] = max(newest.get(g, ""), at)
    out.sort(key=lambda r: (str(r["task_ref"]), str(r["started"])))
    out.sort(key=lambda r: newest[group(r)], reverse=True)
    return out, skipped


_TEXT = {  # shown, not summed
    "end_reason": "end", "first_llm_error": "err", "end.status": "status",
    "approval.path": "approval", "end_world_error": "world", "tier": "tier",
}  # fmt: skip
# The max, not the sum; guide_to_heard_ms shows its p50 (ms), not its count.
_MAX = frozenset(
    {"slow_max_step_gap_ms", "slow_last_step_to_end_ms", "max_consecutive_ok_hold",
     "guide_to_heard_ms", "identity.ask_user_per_key",
     "slow.readback_asks_max_per_revision", "close.reply_to_finish_steps",
     "rungs_reached", "levers_heard"}
)  # fmt: skip


def _brief(value: object) -> str:
    if isinstance(value, dict):
        d = cast(dict[str, object], value)
        keys = ("role", "type", "http", "h5_pass", "world_error_type", "tier", "reason")
        return ":".join(str(d[k]) for k in keys if k in d) or "-"
    return str(value)


def _extra(d: dict[str, object]) -> list[tuple[str, object]]:
    """``unasked_n`` as is; ``unknown_n``: the length of an ``unknown`` list."""
    out = [("unasked_n", d["unasked_n"])] if "unasked_n" in d else []
    unknown = d.get("unknown")
    if isinstance(unknown, list) and unknown:
        out.append(("unknown_n", len(cast(list[object], unknown))))
    return out


def table(all_rows: Sequence[Row]) -> str:
    """Per group: one line per run with its nonzero or unknown (``?``)
    detector scalars, then the group's totals: ``sum`` (``max`` for ``_MAX``;
    unknowns are counted, not summed)."""
    out = [f"# {BANNER}"]
    groups: dict[str, list[Row]] = {}
    for r in all_rows:
        groups.setdefault(group(r), []).append(r)
    for key, members in groups.items():
        kind, _, value = key.partition(":")
        out.append(f"== {kind} {value[:12]}  runs={len(members)}")
        sums: dict[str, float] = {}
        unknown: dict[str, int] = {}
        for r in members:
            cells: list[str] = []
            items = list(cast(dict[str, object], r["detectors"]).items())
            items += [  # second scalars, shown on their own
                (f"{k}.{n}", m) for k, v in list(items) for n, m in _extra(as_dict(v))
            ]
            for name, value in items:
                if name in _TEXT:
                    cells.insert(0, f"{_TEXT[name]}={_brief(value)}")
                    continue
                n = scalar(value)
                if name == "guide_to_heard_ms":
                    n = cast(dict[str, int | None], value)["p50"]
                if n is None:
                    unknown[name] = unknown.get(name, 0) + 1
                    cells.append(f"{name}=?")
                elif n:
                    was = sums.get(name, 0)
                    sums[name] = max(was, n) if name in _MAX else was + n
                    cells.append(f"{name}={n}")
            head = f"  {r['run_id']} {r['task_ref']} {r['mode']}"
            out.append(" ".join([head, *cells]))
        total = ["sum", *(f"{k}={v:g}" for k, v in sorted(sums.items())
                          if k not in _MAX)]  # fmt: skip
        maxima = [f"{k}={v:g}" for k, v in sorted(sums.items()) if k in _MAX]
        total += ["max", *maxima] if maxima else []
        total += [f"{k}:?x{v}" for k, v in sorted(unknown.items())]
        out.append("  " + " ".join(total))
    return "\n".join(out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m proxyloop.obs.diagnose")
    parser.add_argument("--root", type=Path, action="append")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--relay-window", type=float, default=10, metavar="S")
    parser.add_argument(
        "--content", action="store_true", help="run the text-reading detectors"
    )
    args = parser.parse_args(argv)
    roots = args.root or [p for p in (Path("runs"), Path("evidence")) if p.is_dir()]
    if sealed := [str(r) for r in roots if runs.Seal().covers(r)]:
        why = ", ".join(sealed)
        print(f"refused: {why} is sealed (AGENTS rule 11)", file=sys.stderr)
        return 2
    found, skipped = rows(roots, args.relay_window, args.content)
    notes = [f"skipped: {why}" for why in skipped] + [f"skipped={len(skipped)}"]
    print("\n".join(notes), file=sys.stderr)
    groups: dict[str, list[Row]] = {}
    for r in found:  # the table's groups, in its order
        groups.setdefault(group(r), []).append(r)
    graded = {g: tiers.summary(members) for g, members in groups.items()}
    if args.json:
        doc = {"runs": found, "tiers": graded}
        print(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False))
    else:
        print(
            "\n".join([table(found), *(tiers.block(s, g) for g, s in graded.items())])
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
