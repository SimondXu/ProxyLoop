"""``pl.report/1`` (DOCS §4.1), generated from bundles only (AGENTS rule 13):
``{report_id, git_sha, contract_version, spec_hash, prereg_hash?, bundles:
[{run_id, evidence_sha}], tables: {name: {columns, rows, n, ci}}, generated_at}``.

Rows are keyed by name (``/tables/outcome/rows/C2/error_rate``); ``ci`` holds
``[lo, hi]`` per row and column. Errored episodes stay in every denominator
(I10); a rate with any unknown episode value is ``None``, and the
``not_computable`` table says why. Latency rows name the endpoint they were
measured on: hosted latency is "relay-measured", never self-hosted.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from proxyloop.contract import CONTRACT_VERSION
from proxyloop.contract.bundle import EVENTS, MANIFEST, PROMPTS
from proxyloop.eval.metrics import episode
from proxyloop.eval.stats import cluster_bootstrap, quantile, wilson

Episode = dict[str, Any]
Table = dict[str, Any]
_POOLED = {  # metric: (hits, trials), pooled over episodes
    "relay_recall": ("recalled", "revealed"),
    "offer_capture": ("captured", "voiced"),
    "approval_c": ("complete", "cards"),
}
_PER_100 = ("unsupported_numbers", "directive_error")
_LATENCY = {"ttft": "ttft_ms", "ttfs": "ttfs_ms", "heard": "time_to_heard_ms"}


def evidence_sha(run_dir: Path) -> str:
    """sha256 over the bundle's three files (a missing file hashes as such)."""
    h = hashlib.sha256()
    for name in (MANIFEST, EVENTS, PROMPTS):
        path = run_dir / name
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "-"
        h.update(f"{name} {digest}\n".encode())
    return h.hexdigest()


def _table(columns: Sequence[str]) -> Table:
    return {"columns": list(columns), "rows": {}, "n": {}, "ci": {}}


def _put(table: Table, key: str, row: dict[str, Any], n: int, ci: Any) -> None:
    table["rows"][key], table["n"][key], table["ci"][key] = row, n, ci


def _rate(k: int, n: int) -> tuple[float, list[float]]:
    return k / n, list(wilson(k, n))


def outcome_table(
    by_cond: Mapping[str, Sequence[Episode]], seed: int, resamples: int
) -> Table:
    columns = ["episodes", "errors", "error_rate", "success", "safe_success"]
    columns += ["approval_b", *_POOLED, *(f"{m}_per_100" for m in _PER_100)]
    table = _table(columns)
    boot = {"seed": seed, "resamples": resamples}
    for cond, eps in by_cond.items():
        row: dict[str, Any] = {"episodes": len(eps)}
        ci: dict[str, list[float]] = {}
        row["errors"] = errors = sum(e["errored"] for e in eps)
        row["error_rate"], ci["error_rate"] = _rate(errors, len(eps))
        for name in ("success", "safe_success"):
            values = [e["metrics"][name] for e in eps]
            row[name] = None
            if None not in values:
                row[name], ci[name] = _rate(sum(values), len(values))
        known = [b for e in eps if (b := e["metrics"]["approval_b"]) is not None]
        row["approval_b"] = None
        if known:
            row["approval_b"], ci["approval_b"] = _rate(sum(known), len(known))
        for name, (hit, of) in _POOLED.items():
            found = [v for e in eps if (v := e["metrics"][name]) is not None]
            pairs = [(v[hit], v[of]) for v in found if v[of]]
            clusters = [[1.0] * k + [0.0] * (n - k) for k, n in pairs]
            row[name] = None
            if clusters:
                row[name] = sum(k for k, _ in pairs) / sum(n for _, n in pairs)
                ci[name] = list(cluster_bootstrap(clusters, fmean, **boot))
        for name in _PER_100:
            counts = [e["metrics"][name] for e in eps if e["metrics"][name] is not None]
            cells = [[(c["count"], c["turns"])] for c in counts if c["turns"]]
            col = f"{name}_per_100"
            row[col] = _per_100([x for c in cells for x in c]) if cells else None
            if cells:
                ci[col] = list(cluster_bootstrap(cells, _per_100, **boot))
        _put(table, cond, row, len(eps), ci)
    return table


def _per_100(cells: list[tuple[int, int]]) -> float:
    return 100 * sum(c for c, _ in cells) / sum(t for _, t in cells)


def latency_table(
    by_cond: Mapping[str, Sequence[Episode]], seed: int, resamples: int
) -> Table:
    """p50/p95 per condition, lane and endpoint, with episode-clustered CIs."""
    table = _table([f"{k}_{q}" for k in _LATENCY for q in ("p50", "p95")])
    groups: dict[str, dict[str, list[list[float]]]] = {}
    for cond, eps in by_cond.items():
        for e in eps:
            latency: dict[str, dict[str, Any]] = e["metrics"]["latency"] or {}
            for lane, labels in latency.items():
                for label, samples in labels.items():
                    group = groups.setdefault(f"{cond}|{lane}|{label}", {})
                    for key, field in _LATENCY.items():
                        if xs := samples[field]:
                            group.setdefault(key, []).append(xs)
    for name, group in sorted(groups.items()):
        row: dict[str, float | None] = dict.fromkeys(table["columns"])
        ci: dict[str, list[float]] = {}
        for key, clusters in group.items():
            for q, level in (("p50", 0.5), ("p95", 0.95)):
                pooled = [x for c in clusters for x in c]
                row[f"{key}_{q}"] = quantile(pooled, level)
                stat = _quantile_of(level)
                boot = cluster_bootstrap(clusters, stat, seed=seed, resamples=resamples)
                ci[f"{key}_{q}"] = list(boot)
        _put(table, name, row, sum(len(c) for c in group.get("ttft", [])), ci)
    return table


def _quantile_of(level: float) -> Callable[[list[float]], float]:
    return lambda xs: quantile(xs, level)


def cost_table(by_cond: Mapping[str, Sequence[Episode]]) -> Table:
    """Relay USD per episode by role (descriptive, no CI); ``None`` while any
    call of the role is unpriced. GPU $ come from Modal usage, not bundles."""
    columns = ["usd_per_episode", "usd_priced_per_episode"]
    table = _table([*columns, "unpriced_calls", "gpu_time_calls"])
    for cond, eps in by_cond.items():
        readable = [
            e["metrics"]["cost"] for e in eps if e["metrics"]["cost"] is not None
        ]
        for role in sorted({r for c in readable for r in c}):
            roles = [c.get(role) for c in readable]
            usd = [0.0 if r is None else r["usd"] for r in roles]
            priced = [0.0 if r is None else r["usd_priced"] for r in roles]
            row = {
                "usd_per_episode": None if None in usd else fmean(usd),
                "usd_priced_per_episode": fmean(priced),
                "unpriced_calls": sum(r["unpriced_calls"] for r in roles if r),
                "gpu_time_calls": sum(r["gpu_time_calls"] for r in roles if r),
            }
            _put(table, f"{cond}|{role}", row, len(readable), {})
    return table


def not_computable_table(by_cond: Mapping[str, Sequence[Episode]]) -> Table:
    table = _table(["reason"])
    for eps in by_cond.values():
        for e in eps:
            for name, reason in e["not_computable"].items():
                table["rows"].setdefault(name, {"reason": reason})
                table["n"][name] = table["n"].get(name, 0) + 1
    return table


def build_report(
    report_id: str,
    spec_hash: str,
    bundles: Mapping[str, Sequence[Path]],
    *,
    git_sha: str,
    prereg_hash: str | None = None,
    seed: int = 0,
    resamples: int = 10_000,
) -> dict[str, Any]:
    """``bundles`` maps a condition to its bundle dirs."""
    by_cond = {cond: [episode(d) for d in dirs] for cond, dirs in bundles.items()}
    listed = [
        {"run_id": e["run_id"], "evidence_sha": evidence_sha(d)}
        for cond, dirs in bundles.items()
        for d, e in zip(dirs, by_cond[cond], strict=True)
    ]
    report: dict[str, Any] = {
        "report_id": report_id,
        "git_sha": git_sha,
        "contract_version": CONTRACT_VERSION,
        "spec_hash": spec_hash,
        "bundles": listed,
        "tables": {
            "outcome": outcome_table(by_cond, seed, resamples),
            "latency": latency_table(by_cond, seed, resamples),
            "cost": cost_table(by_cond),
            "not_computable": not_computable_table(by_cond),
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }
    if prereg_hash is not None:
        report["prereg_hash"] = prereg_hash
    return report
