"""The detectors across runs, grouped by git_sha, newest first.

ADVISORY ONLY: triage signals, never a metric, a claim or a merge gate.

``python -m proxyloop.obs.diagnose [--root DIR ...] [--json]`` takes every
``ok`` bundle ``runs.index`` finds (sealed data is never listed or read), one
copy per run_id, and groups them by the git_sha they ran on, then task_ref, so
an issue fixed on a newer sha shows under its old sha, not as current.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from proxyloop.obs import runs
from proxyloop.obs.detectors import BANNER, scalar
from proxyloop.obs.triage import Row, read, row


def rows(roots: Sequence[Path], window_s: float = 10) -> list[Row]:
    """One row per ok run, newest sha group first (by its newest run), then
    task_ref and start time within a group."""
    seal, seen = runs.Seal(), set[str]()
    out: list[Row] = []
    for run in runs.index(roots):
        if run.status != "ok" or run.run_id in seen:
            continue
        seen.add(run.run_id)
        out.append(row(*read(Path(run.path), seal, window_s)))
    newest: dict[str, str] = {}
    for r in out:
        sha, at = str(r["git_sha"]), str(r["started"])
        newest[sha] = max(newest.get(sha, ""), at)
    out.sort(key=lambda r: (str(r["task_ref"]), str(r["started"])))
    out.sort(key=lambda r: newest[str(r["git_sha"])], reverse=True)
    return out


_TEXT = {"end_reason": "end", "first_llm_error": "err"}  # shown, not summed
_MAX = frozenset({"slow_max_step_gap_ms", "max_consecutive_ok_hold"})  # max, not sum


def _brief(value: object) -> str:
    if isinstance(value, dict):
        d = cast(dict[str, object], value)
        return ":".join(str(d[k]) for k in ("role", "type", "http") if k in d) or "-"
    return str(value)


def table(all_rows: Sequence[Row]) -> str:
    """Per sha: one line per run with its nonzero or unknown (``?``) detector
    scalars, then the group's sums (maxima for ``_MAX``; unknowns are counted,
    not summed)."""
    out = [f"# {BANNER}"]
    groups: dict[str, list[Row]] = {}
    for r in all_rows:
        groups.setdefault(str(r["git_sha"]), []).append(r)
    for sha, group in groups.items():
        out.append(f"== {sha[:12]}  runs={len(group)}")
        sums: dict[str, float] = {}
        unknown: dict[str, int] = {}
        for r in group:
            cells: list[str] = []
            for name, value in cast(dict[str, object], r["detectors"]).items():
                if name in _TEXT:
                    cells.insert(0, f"{_TEXT[name]}={_brief(value)}")
                    continue
                n = scalar(value)
                if n is None:
                    unknown[name] = unknown.get(name, 0) + 1
                    cells.append(f"{name}=?")
                elif n:
                    was = sums.get(name, 0)
                    sums[name] = max(was, n) if name in _MAX else was + n
                    cells.append(f"{name}={n}")
            out.append(
                f"  {r['run_id']} {r['task_ref']} {r['mode']} " + " ".join(cells)
            )
        total = [f"{k}={v:g}" for k, v in sorted(sums.items())]
        total += [f"{k}:?x{v}" for k, v in sorted(unknown.items())]
        out.append("  sum " + " ".join(total))
    return "\n".join(out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m proxyloop.obs.diagnose")
    parser.add_argument("--root", type=Path, action="append")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--relay-window", type=float, default=10, metavar="S")
    args = parser.parse_args(argv)
    roots = args.root or [p for p in (Path("runs"), Path("evidence")) if p.is_dir()]
    found = rows(roots, args.relay_window)
    if args.json:
        print(json.dumps(found, indent=1, sort_keys=True, ensure_ascii=False))
    else:
        print(table(found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
