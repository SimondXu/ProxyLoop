"""``pl.report/1`` (DOCS §4.1), generated from bundles only (AGENTS rule 13):
``{report_id, git_sha, contract_version, spec_hash, prereg_hash?, bundles:
[{run_id, evidence_sha}], tables: {name: {columns, rows, n, ci}}, generated_at}``.

Rows are keyed by name (``/tables/outcome/rows/C2/model_failure_rate``); ``ci``
holds ``[lo, hi]`` per row and column. Failed episodes stay in every denominator
(I10); the model-failure rate leads the outcome table (the integrity gate counts
infra errors only, so this rate must never be hidden). ``budget_stops`` (runaway
spend: an infra_error outcome that a looping model may cause) are counted apart
and not in ``infra_errors``; the gate counts both. A rate with any unknown
episode value is ``None`` and the ``not_computable`` table says why. Latency
rows name their endpoint ("relay-measured" for hosted) and their turn counts.
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
    "relay_precision_value_only": ("correct", "facts"),
    "offer_capture": ("captured", "voiced"),
    "approval_c": ("complete", "cards"),
}
_PER_100 = ("unsupported_numbers", "directive_error")
_LATENCY = {"ttft": "ttft_ms", "ttfs": "ttfs_ms", "heard": "time_to_heard_ms"}
_COUNTS = ("turns", "untimed", "ttfs_missing", "heard_missing")


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
    columns = ["episodes", "model_failures", "model_failure_rate", "budget_stops"]
    columns += ["budget_rate", "infra_errors", "infra_error_rate", "success"]
    columns += ["safe_success", "approval_b", "accepts", "accepts_via_approval"]
    columns += ["accepts_via_mandate", *_POOLED, "offer_terms_unscored"]
    columns += [f"{m}_per_100" for m in _PER_100]
    table = _table(columns)
    boot = {"seed": seed, "resamples": resamples}
    for cond, eps in by_cond.items():
        row: dict[str, Any] = {"episodes": len(eps)}
        ci: dict[str, list[float]] = {}
        budget = [e["outcome"] == "infra_error" and e["ended"] == "budget" for e in eps]
        counts = {"budget_stop": sum(budget)}
        counts["model_failure"] = sum(e["outcome"] == "model_failure" for e in eps)
        counts["infra_error"] = sum(e["outcome"] == "infra_error" for e in eps)
        counts["infra_error"] -= counts["budget_stop"]
        for kind, k in counts.items():
            row[f"{kind}s"] = k
            rate = "budget_rate" if kind == "budget_stop" else f"{kind}_rate"
            row[rate], ci[rate] = _rate(k, len(eps))
        for name in ("success", "safe_success"):
            values = [e["metrics"][name] for e in eps]
            row[name] = None
            if None not in values:
                row[name], ci[name] = _rate(sum(values), len(values))
        known = [b for e in eps if (b := e["metrics"]["approval_b"]) is not None]
        row["approval_b"], row["accepts"] = None, sum(b["accepts"] for b in known)
        for via in ("approval", "mandate"):
            row[f"accepts_via_{via}"] = sum(b[f"via_{via}"] for b in known)
        if known:
            held = sum(b["held"] for b in known)
            row["approval_b"], ci["approval_b"] = _rate(held, len(known))
        offers = [o for e in eps if (o := e["metrics"]["offer_capture"]) is not None]
        row["offer_terms_unscored"] = sum(o["unscored"] for o in offers)
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
    columns = [f"{k}_{q}" for k in _LATENCY for q in ("p50", "p95")]
    table = _table([*_COUNTS, *columns])
    groups: dict[str, dict[str, list[list[float]]]] = {}
    counts: dict[str, dict[str, int]] = {}
    for cond, eps in by_cond.items():
        for e in eps:
            latency: dict[str, dict[str, Any]] = e["metrics"]["latency"] or {}
            for lane, labels in latency.items():
                for label, samples in labels.items():
                    name = f"{cond}|{lane}|{label}"
                    group = groups.setdefault(name, {})
                    tally = counts.setdefault(name, dict.fromkeys(_COUNTS, 0))
                    for c in _COUNTS:
                        tally[c] += samples[c]
                    for key, field in _LATENCY.items():
                        if xs := samples[field]:
                            group.setdefault(key, []).append(xs)
    for name, group in sorted(groups.items()):
        row: dict[str, float | None] = {**dict.fromkeys(columns), **counts[name]}
        ci: dict[str, list[float]] = {}
        for key, clusters in group.items():
            for q, level in (("p50", 0.5), ("p95", 0.95)):
                pooled = [x for c in clusters for x in c]
                row[f"{key}_{q}"] = quantile(pooled, level)
                stat = _quantile_of(level)
                boot = cluster_bootstrap(clusters, stat, seed=seed, resamples=resamples)
                ci[f"{key}_{q}"] = list(boot)
        _put(table, name, row, counts[name]["turns"], ci)
    return table


def _quantile_of(level: float) -> Callable[[list[float]], float]:
    return lambda xs: quantile(xs, level)


def cost_table(by_cond: Mapping[str, Sequence[Episode]]) -> Table:
    """Relay USD per episode by role (descriptive, no CI); ``None`` while any
    call of the role is unpriced or on GPU time, with ``usd_missing`` saying why."""
    columns = ["usd_per_episode", "usd_missing", "usd_priced_per_episode"]
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
                "usd_missing": "; ".join(
                    sorted({r["usd_missing"] for r in roles if r and r["usd_missing"]})
                )
                or None,
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
    allow_test: bool = False,
) -> dict[str, Any]:
    """``bundles`` maps a condition to its bundle dirs. A test-split bundle
    raises ``HeldOutRefused`` unless ``allow_test`` (after the unseal only)."""
    by_cond = {
        cond: [episode(d, allow_test=allow_test) for d in dirs]
        for cond, dirs in bundles.items()
    }
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
