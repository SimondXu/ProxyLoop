"""The spend report ``pl.spend/1`` (PLAN §0.8), generated from the
``spend.charged`` events of indexed bundles and a Modal usage export.

Money is integer micro-USD until it is formatted. Nothing is estimated:
``unpriced`` calls are counted with their tokens, ``gpu_time`` calls get their $
only from the Modal input, and a missing usage is counted, never read as zero.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from proxyloop.obs.runs import Run, index

SCHEMA = "pl.spend/1"
FIELDS = (  # one row per (role, endpoint, model_id); every value an int
    "calls_tokens",
    "calls_gpu_time",
    "calls_unpriced",
    "priced_micro_usd",
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "reasoning_unreported",
    "usage_missing",
    "charge_without_call",
    "call_without_charge",
    "episodes",
)
_EXCLUDED = ("incomplete", "invalid", "sealed")
Key = tuple[str, str, str]  # role, endpoint ("" for none), model_id
Tally = dict[Key, Counter[str]]


class GpuUsage(BaseModel):
    """One line of the Modal usage export, as the root hand-copies it."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    job: str = Field(min_length=1)
    app_id: str | None
    usd: str = Field(pattern=r"^\d+(\.\d{1,6})?$")  # at most whole micro-USD
    source: str
    period: str | None

    @property
    def micro_usd(self) -> int:
        return int(Decimal(self.usd) * 1_000_000)  # exact: at most 6 decimals


def load_gpu(path: Path) -> list[GpuUsage]:
    return TypeAdapter(list[GpuUsage]).validate_json(path.read_bytes())


def _usd(micro: Decimal | int, places: int = 6) -> str:
    step = Decimal(1) / 10**places
    return f"{(Decimal(micro) / 1_000_000).quantize(step, ROUND_HALF_EVEN):f}"


def _whole(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), ROUND_HALF_EVEN))


def _tally(episodes: Sequence[Run], real_only: bool = False) -> Tally:
    acc: Tally = defaultdict(Counter)
    for run in episodes:
        ran: set[Key] = set()
        for cost in run.costs:
            c = cost.charge
            if real_only and run.reality.get(c.role) != "real_http":
                continue
            ran.add(key := (c.role, c.endpoint or "", c.model_id))
            n = acc[key]
            n[f"calls_{c.basis}"] += 1
            if c.micro_usd is not None:  # set iff the basis is tokens
                n["priced_micro_usd"] += c.micro_usd
            usage = None if cost.record is None else cost.record.usage
            if cost.record is None:
                n["charge_without_call"] += 1
            elif usage is None:
                n["usage_missing"] += 1
            else:
                n["prompt_tokens"] += usage.prompt_tokens
                n["completion_tokens"] += usage.completion_tokens
                if usage.reasoning_tokens is None:
                    n["reasoning_unreported"] += 1
                else:
                    n["reasoning_tokens"] += usage.reasoning_tokens
                if c.basis == "unpriced":
                    n["unpriced_prompt"] += usage.prompt_tokens
                    n["unpriced_completion"] += usage.completion_tokens
        for r in run.uncharged:
            if not real_only or run.reality.get(r.role) == "real_http":
                ref = r.model_ref
                ran.add(key := (r.role, ref.endpoint or "", ref.model_id))
                acc[key]["call_without_charge"] += 1
        for key in ran:
            acc[key]["episodes"] += 1
    return acc


def _unknown(n: Counter[str]) -> bool:
    """Whether some of this key's $ is not in its priced calls."""
    gaps = ("calls_unpriced", "calls_gpu_time", "usage_missing", "call_without_charge")
    return any(n[g] for g in gaps)


def _rows(tally: Tally, per_episode: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for k, n in sorted(tally.items()):
        row = {"role": k[0], "endpoint": k[1] or None, "model_id": k[2]}
        row |= {f: n[f] for f in FIELDS}
        if per_episode:
            per = Decimal(n["priced_micro_usd"]) / n["episodes"]
            row["usd_per_episode"] = None if _unknown(n) else _usd(per, 8)
            row["priced_lower_bound_micro_usd_per_episode"] = _whole(per)
            row["priced_lower_bound_usd_per_episode"] = _usd(per, 8)
            row["lower_bound"] = _unknown(n)  # the priced calls only: not the cost
        rows.append(row)
    return rows


def _projection(live: Tally, n: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for k, c in sorted(live.items()):
        per = n / Decimal(c["episodes"])
        micro = None if _unknown(c) else _whole(c["priced_micro_usd"] * per)
        rows.append(
            {"role": k[0], "endpoint": k[1] or None, "model_id": k[2]}
            | {
                "episodes_basis": c["episodes"],
                "micro_usd": micro,
                "usd": None if micro is None else _usd(micro),
                "priced_lower_bound_micro_usd": (
                    low := _whole(c["priced_micro_usd"] * per)
                ),
                "priced_lower_bound_usd": _usd(low),
                "lower_bound": _unknown(c),
                "calls_unpriced": c["calls_unpriced"],
                "calls_gpu_time": c["calls_gpu_time"],
                "usage_missing": c["usage_missing"],
                "unpriced_prompt_tokens": _whole(c["unpriced_prompt"] * per),
                "unpriced_completion_tokens": _whole(c["unpriced_completion"] * per),
            }
        )
    return {
        "episodes": n,
        "by_model": rows,
        "note": "N x total / the live episodes each key ran in; null $ where any"
        " call of the key is unpriced, gpu_time, without usage or uncharged."
        " priced_lower_bound_* sums the priced calls only: with lower_bound true"
        " it is a floor, never the full cost",
        "gpu": None,
        "gpu_note": "GPU $ are not projected; see Modal usage",
    }


def report(
    runs: Sequence[Run],
    gpu: Sequence[GpuUsage] | None,
    project: int | None,
    inputs: dict[str, object],
) -> dict[str, Any]:
    ok = sorted(
        (r for r in runs if r.status == "ok"),
        key=lambda r: (r.kind != "evidence", r.path),
    )
    chosen: dict[str, Run] = {}
    for run in ok:  # identical copies of a run_id (runs.index); the evidence one
        chosen.setdefault(run.run_id, run)
    episodes = sorted(chosen.values(), key=lambda r: r.run_id)
    live = [
        r for r in episodes if r.reality and set(r.reality.values()) == {"real_http"}
    ]
    non_live = [r for r in episodes if r not in live]
    live_tally, all_real = _tally(live), _tally(episodes, real_only=True)
    gpu_section: dict[str, object] = {"input": None, "note": "no Modal usage input"}
    gpu_micro: int | None = None
    if gpu is not None:
        jobs: dict[str, Counter[str]] = defaultdict(Counter)
        for line in gpu:
            jobs[line.job].update({"entries": 1, "micro_usd": line.micro_usd})
        gpu_micro = sum(c["micro_usd"] for c in jobs.values())
        rows = [
            {
                "job": job,
                "entries": c["entries"],
                "micro_usd": c["micro_usd"],
                "usd": _usd(c["micro_usd"]),
            }
            for job, c in sorted(jobs.items())
        ]
        gpu_section = {
            "input": inputs["gpu_usage"],
            "jobs": rows,
            "micro_usd": gpu_micro,
        }
    total = sum(all_real.values(), Counter[str]())
    llm = total["priced_micro_usd"]
    micro = llm if gpu_micro is None else llm + gpu_micro
    mismatches = total["charge_without_call"] + total["call_without_charge"]
    gaps = total["calls_unpriced"] + total["usage_missing"] + mismatches
    excluded = {s: sum(r.status == s for r in runs) for s in _EXCLUDED}
    unindexed = sum(
        c.charge.micro_usd or 0
        for r in runs
        if r.status == "incomplete"
        for c in r.costs
    )  # tokens basis only; None is every other basis
    return {
        "schema": SCHEMA,
        "inputs": inputs,
        "bundles": {
            "ok": len(ok),
            **excluded,
            "duplicates_collapsed": len(ok) - len(chosen),
            "episodes": len(episodes),
            "not_counted": sorted(r.run_id for r in runs if r.status != "ok"),
        },
        "live": {
            "episodes": len(live),
            "run_ids": [r.run_id for r in live],
            "denominator": "per row: the live episodes in which that"
            " (role, endpoint, model_id) ran; null where any of its calls is"
            " unpriced, gpu_time, without usage or without a charge."
            " priced_lower_bound_* sums the priced calls only: with lower_bound"
            " true it is a floor, never the full cost",
            "models": _rows(live_tally, per_episode=True),
        },
        "non_live": {
            "episodes": len(non_live),
            "run_ids": [r.run_id for r in non_live],
            "models": _rows(_tally(non_live)),
        },
        "gpu": gpu_section,
        "cumulative": {
            "llm_priced_micro_usd": llm,  # real_http roles only, over every episode
            "gpu_micro_usd": gpu_micro,
            "micro_usd": micro,
            "usd": _usd(micro),
            "calls_unpriced": total["calls_unpriced"],
            "unpriced_prompt_tokens": total["unpriced_prompt"],
            "unpriced_completion_tokens": total["unpriced_completion"],
            "usage_missing": total["usage_missing"],
            "mismatches": mismatches,
            "excluded_bundles": excluded,
            "unindexed_priced_micro_usd": unindexed,  # never in micro_usd
            "complete": gpu_micro is not None
            and not gaps
            and not any(excluded.values()),
        },
        "projection": None if project is None else _projection(live_tally, project),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m proxyloop.obs.spend")
    parser.add_argument("--root", type=Path, action="append")
    parser.add_argument("--gpu-usage", type=Path)
    parser.add_argument("--project-episodes", type=int)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.project_episodes is not None and args.project_episodes <= 0:
        parser.error("--project-episodes must be positive")
    roots = args.root or [p for p in (Path("runs"), Path("evidence")) if p.is_dir()]
    gpu = None if args.gpu_usage is None else load_gpu(args.gpu_usage)
    inputs: dict[str, object] = {
        "roots": [str(r) for r in roots],
        "gpu_usage": None if args.gpu_usage is None else str(args.gpu_usage),
        "project_episodes": args.project_episodes,
    }
    out = report(index(roots), gpu, args.project_episodes, inputs)
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", "utf-8")
    b, c = out["bundles"], out["cumulative"]
    print(" ".join(f"{k}={v}" for k, v in b.items() if k != "not_counted"))
    print(f"live={out['live']['episodes']} non_live={out['non_live']['episodes']}")
    print(" ".join(f"{k}={v}" for k, v in c.items()))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
