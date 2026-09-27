"""The Fast benchmark (S1-MOD-04): C5 (Luna, hosted), C2 (base Qwen) and C1
(fine-tuned Qwen) on the same (family, instance, seed) cells (EVAL §4.1, §7).

A thin layer over ``matrix`` and ``report``:
- ``load_spec`` reads ``specs/fast_benchmark.yaml`` and refuses a ``test``
  family before any task is loaded (I9, AGENTS rule 11);
- ``run`` schedules every condition once per (instance, seed) block, so the
  pairing is by construction, and calls ``run_matrix``: one ``run_session``
  per cell, a condition applied as a config value (I1), no retries;
- ``build`` makes ``pl.report/1`` from a runs dir: ``report.build_report``'s
  tables, plus the pairing check, every bundle's evidence-check label and the
  paired comparisons.

Latency (user, 2026-09-26): one table per endpoint label, so hosted
(relay-measured) latency never shares a column with self-hosted Qwen, and no
comparison is made on latency. A condition marked ``attested_adapter`` (C1)
counts a bundle only if its Fast adapter shards match its attestation; else
its row stays empty with the reason. A bundle that fails ``evidence-check
--claim`` is kept and labelled, and its condition is marked descriptive.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any, Literal, Self

import yaml
from pydantic import Field, model_validator

from proxyloop.cli import build_parser, live_config
from proxyloop.contract.base import Frozen, sha256_text
from proxyloop.contract.bundle import MANIFEST, Manifest
from proxyloop.contract.config import SessionConfig
from proxyloop.env.tasks.loader import instance_hash, load_task
from proxyloop.env.tasks.schema import Task
from proxyloop.eval.matrix import (
    Cell,
    CellRun,
    Seams,
    integrity,
    kept,
    read_cell_dir,
    run_matrix,
    schedule,
)
from proxyloop.eval.metrics import HeldOutRefused, Loader, episode
from proxyloop.eval.report import build_report
from proxyloop.eval.stats import cluster_bootstrap
from proxyloop.evidence.check import check_path
from proxyloop.models import registry

SPEC = Path(__file__).with_name("specs") / "fast_benchmark.yaml"
COMPARED = ("success", "safe_success", "model_failure")  # never a latency
BLOCKED = (
    "EVAL §7 blocked harm (blocked_count, harm_attempt_rate) is an S2 metric "
    "(S2-MOD-01): not computed at S1, never 0"
)
NO_SHARDS = "the manifest's Fast model carries no adapter shard hashes (S1-SYS-14)"
_FAST = ("fast_user", "fast_cp")
Key = tuple[str, str, int]  # (family, instance, seed)
Table = dict[str, Any]


class ConditionSpec(Frozen):
    name: str = Field(pattern=r"^[A-Za-z0-9]+$")  # no "-": matrix.cell_dir
    attested_adapter: bool = False


class FamilySpec(Frozen):
    family: str = Field(pattern=r"^[a-z0-9-]+$")
    split: Literal["train", "dev", "test"]  # "test" is refused by load_spec
    instances: tuple[str, ...] = Field(min_length=1)
    seeds: tuple[int, ...] = Field(min_length=1)


class Spec(Frozen):
    id: str
    conditions: tuple[ConditionSpec, ...] = Field(min_length=1)
    families: tuple[FamilySpec, ...] = Field(min_length=1)
    salt: int
    comparisons: tuple[tuple[str, str], ...] = ()

    @model_validator(mode="after")
    def _names(self) -> Self:
        names = [c.name for c in self.conditions]
        instances = [i for f in self.families for i in f.instances]
        if len(set(names)) < len(names) or len(set(instances)) < len(instances):
            raise ValueError("a condition or an instance is listed twice")
        if unknown := {n for pair in self.comparisons for n in pair} - set(names):
            raise ValueError(f"comparisons name unknown conditions {sorted(unknown)}")
        return self


@dataclass(frozen=True, slots=True)
class Benchmark:
    spec: Spec
    spec_hash: str
    tasks: Mapping[str, Task]  # instance -> task
    family: Mapping[str, str]  # instance -> family
    load: Loader  # family -> task, for the metrics

    def expected(self) -> set[Key]:
        return {
            (f.family, i, s)
            for f in self.spec.families
            for i in f.instances
            for s in f.seeds
        }


def load_spec(path: Path = SPEC, load: Loader = load_task) -> Benchmark:
    """The spec, its tasks and hash; a ``test`` family raises ``HeldOutRefused``
    before any task is read. An instance is a family's task id."""
    text = path.read_text("utf-8")
    spec = Spec.model_validate(yaml.safe_load(text))
    if held := [f.family for f in spec.families if f.split == "test"]:
        raise HeldOutRefused(f"test-split families {held}: sealed until the unseal")
    tasks: dict[str, Task] = {}
    by_family: dict[str, Task] = {}
    for f in spec.families:
        task = by_family[f.family] = load(f.family)
        for instance in f.instances:
            if instance != task.id:
                raise ValueError(f"{f.family} has no instance {instance!r}")
            tasks[instance] = task
    family = {i: f.family for f in spec.families for i in f.instances}
    return Benchmark(spec, sha256_text(text), tasks, family, by_family.__getitem__)


def cells(spec: Spec, conditions: Sequence[str]) -> list[Cell]:
    """Every condition once per (instance, seed) block, per family."""
    if unknown := set(conditions) - {c.name for c in spec.conditions}:
        raise ValueError(f"conditions {sorted(unknown)} are not in the spec")
    return [
        cell
        for f in spec.families
        for cell in schedule(conditions, f.instances, f.seeds, salt=spec.salt)
    ]


async def run(
    bench: Benchmark,
    configs: Mapping[str, SessionConfig],
    runs_dir: Path,
    *,
    seams: Seams | None = None,
) -> list[CellRun]:
    """The cells of ``configs``' conditions through ``run_matrix`` (resumable)."""
    todo = cells(bench.spec, list(configs))
    return await run_matrix(todo, configs, bench.tasks, runs_dir, seams=seams)


def live_configs(
    bench: Benchmark, names: Sequence[str], cli_args: Sequence[str]
) -> dict[str, SessionConfig]:
    """The CLI's live config (``proxyloop.cli session`` options), with each
    condition applied by the registry; an unknown condition fails loudly."""
    family = bench.spec.families[0].family  # the config does not depend on it
    args = build_parser().parse_args(["session", "--family", family, *cli_args])
    base = live_config(args)
    return {name: registry.condition(name).apply(base) for name in names}


# --- the report --------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Found:
    cell: Cell
    key: Key
    path: Path  # the bundle, or the cell folder if none was written
    name: str  # <cell folder>[/<bundle>]
    manifest: Manifest | None


def _manifest(run_dir: Path) -> Manifest | None:
    try:
        return Manifest.model_validate_json((run_dir / MANIFEST).read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _discover(bench: Benchmark, runs_dir: Path) -> list[_Found]:
    """One bundle per cell folder: the one a resume keeps, else the latest
    (a failure that stays counted), else the folder. Test-split manifests are
    refused before any event is read."""
    names = {c.name for c in bench.spec.conditions}
    seen: dict[tuple[str, str], str] = {}
    found: dict[tuple[str, Key], _Found] = {}
    for folder in sorted(d for d in runs_dir.iterdir() if d.is_dir()):
        cell = read_cell_dir(folder)
        if (
            cell is None
            or cell.condition not in names
            or cell.instance not in bench.tasks
        ):
            raise ValueError(f"{folder} is not a cell of {bench.spec.id}")
        bundles = sorted(d for d in folder.iterdir() if d.is_dir())
        manifests = {d: _manifest(d) for d in bundles}
        if any(m is not None and m.split == "test" for m in manifests.values()):
            raise HeldOutRefused(f"{folder} holds a test-split bundle")
        path = (kept(folder, seen) or (bundles[-1] if bundles else folder, ""))[0]
        key = (bench.family[cell.instance], cell.instance, cell.seed)
        if (cell.condition, key) in found:
            raise ValueError(f"{folder}: cell {cell} is in the runs dir twice")
        m = manifests.get(path)
        if m is not None:
            want = (key[0], instance_hash(bench.tasks[cell.instance]), cell.seed)
            got = (m.task_ref.partition("@")[0], m.instance_hash, m.cfg.seed)
            if got != want:
                raise ValueError(f"{path} ran {got}, not its cell {want}")
        name = folder.name if path == folder else f"{folder.name}/{path.name}"
        found[(cell.condition, key)] = _Found(cell, key, path, name, m)
    return list(found.values())


def attestation_gap(m: Manifest | None) -> str | None:
    """Why a bundle's Fast adapter is not attested; ``None`` if it is."""
    if m is None:
        return "unreadable manifest"
    fast = [m.models[r] for r in _FAST if r in m.models]
    if not fast or any(not r.adapter_shards for r in fast):
        return NO_SHARDS
    attested = m.attestation or {}
    shards = {f: sha for r in fast for f, sha in r.adapter_shards.items()}
    if bad := sorted(f for f, sha in shards.items() if attested.get(f) != sha):
        return f"adapter shards {bad} do not match the attestation"
    return None


def _table(columns: Sequence[str]) -> Table:
    return {"columns": list(columns), "rows": {}, "n": {}, "ci": {}}


def _label(key: Key) -> str:
    return f"{key[0]}/{key[1]}/s{key[2]}"


def _evidence(found: Sequence[_Found], excluded: Mapping[str, str]) -> Table:
    """Every bundle's evidence-check result: claim, else offline, else failed."""
    table = _table(["condition", "cell", "evidence", "failures", "excluded"])
    for f in found:
        claim = check_path(f.path, "claim")
        offline = claim if claim.ok else check_path(f.path, "offline")
        label = "claim" if claim.ok else "offline" if offline.ok else "failed"
        failures = list(claim.failures if offline.ok else offline.failures)
        row = {"condition": f.cell.condition, "cell": _label(f.key)}
        row |= {"evidence": label, "failures": failures}
        table["rows"][f.name] = row | {"excluded": excluded.get(f.name)}
        table["n"][f.name], table["ci"][f.name] = 1, {}
    return table


def _conditions(
    bench: Benchmark,
    kept_: Mapping[str, Sequence[_Found]],
    evidence: Table,
    excluded: Mapping[str, int],
) -> Table:
    """Pairing: per condition, its cells missing from the spec's set and its
    cells absent from another condition that has bundles; claim status."""
    columns = ["expected", "present", "missing", "unpaired", "excluded"]
    table = _table([*columns, "claimable", "evidence", "fast_models"])
    expected = bench.expected()
    present = {c: {f.key for f in fs} for c, fs in kept_.items()}
    sets = list(present.values())
    paired = sets[0].intersection(*sets[1:]) if sets else set[Key]()
    for c in (s.name for s in bench.spec.conditions):
        mine, fs = present.get(c, set[Key]()), kept_.get(c, [])
        claimable = sum(evidence["rows"][f.name]["evidence"] == "claim" for f in fs)
        refs = [
            f"{r.ref.endpoint or r.ref.kind.value}:{r.served_model or r.ref.model_id}"
            for f in fs
            if f.manifest is not None
            for role, r in f.manifest.models.items()
            if role in _FAST
        ]
        row: dict[str, Any] = {"expected": len(expected), "present": len(mine)}
        row["missing"] = sorted(_label(k) for k in expected - mine)
        row["unpaired"] = sorted(_label(k) for k in mine - paired)
        row["excluded"] = excluded.get(c, 0)
        row["claimable"] = claimable
        row["evidence"] = None
        if fs:
            unclaimable = len(fs) - claimable
            row["evidence"] = (
                f"descriptive ({unclaimable} unclaimable)" if unclaimable else "claim"
            )
        row["fast_models"] = sorted(set(refs))
        table["rows"][c], table["n"][c], table["ci"][c] = row, len(fs), {}
    return table


def _value(e: Mapping[str, Any], metric: str) -> int | None:
    if metric == "model_failure":
        return int(e["outcome"] == "model_failure")
    value = e["metrics"][metric]
    return None if value is None else int(value)


def _comparisons(
    bench: Benchmark,
    kept_: Mapping[str, Sequence[_Found]],
    eps: Mapping[str, Mapping[str, Any]],
    seed: int,
    resamples: int,
) -> tuple[Table, dict[str, str]]:
    """a - b per compared metric over the cells both ran (paired), with a
    cluster bootstrap over instances (EVAL §8.4) when there are two or more."""
    table = _table([f"{m}_delta" for m in COMPARED])
    why: dict[str, str] = {}
    for a, b in bench.spec.comparisons:
        name = f"{a}-{b}"
        by_key = {c: {f.key: eps[f.name] for f in kept_.get(c, [])} for c in (a, b)}
        paired = sorted(by_key[a].keys() & by_key[b].keys())
        row: dict[str, float | None] = dict.fromkeys(table["columns"])
        ci: dict[str, list[float]] = {}
        if not paired:
            why[f"comparison.{name}"] = f"{a} and {b} share no cell with bundles"
        for m in COMPARED if paired else ():
            diffs: dict[Key, float] = {}
            for k in paired:
                x, y = _value(by_key[a][k], m), _value(by_key[b][k], m)
                if x is not None and y is not None:
                    diffs[k] = float(x - y)
            if len(diffs) < len(paired):
                why[f"comparison.{name}.{m}"] = (
                    f"{m} is not computable on a paired cell"
                )
                continue
            row[f"{m}_delta"] = fmean(diffs.values())
            instances = sorted({k[:2] for k in paired})
            if len(instances) < 2:
                why[f"comparison.{name}.ci"] = "one instance: no cluster bootstrap CI"
                continue
            clusters = [[d for k, d in diffs.items() if k[:2] == i] for i in instances]
            boot = cluster_bootstrap(clusters, fmean, seed=seed, resamples=resamples)
            ci[f"{m}_delta"] = list(boot)
        table["rows"][name], table["n"][name], table["ci"][name] = row, len(paired), ci
    return table, why


def _split_latency(table: Table) -> dict[str, Table]:
    """``report``'s latency table as one table per endpoint label."""
    out: dict[str, Table] = {}
    for key, row in table["rows"].items():
        cond, lane, label = key.split("|", 2)
        part = out.setdefault(f"latency: {label}", _table(table["columns"]))
        name = f"{cond}|{lane}"
        part["rows"][name], part["n"][name] = row, table["n"][key]
        part["ci"][name] = table["ci"][key]
    return out


def build(
    bench: Benchmark,
    runs_dir: Path,
    *,
    git_sha: str,
    seed: int = 0,
    resamples: int = 10_000,
) -> dict[str, Any]:
    """``pl.report/1`` for the runs dir of ``run``: rows per condition (every
    bundle it kept, failures included), comparisons over paired cells only."""
    found = _discover(bench, runs_dir)
    attested = {c.name for c in bench.spec.conditions if c.attested_adapter}
    excluded = {
        f.name: gap
        for f in found
        if f.cell.condition in attested and (gap := attestation_gap(f.manifest))
    }
    kept_: dict[str, list[_Found]] = {}
    for f in found:
        if f.name not in excluded:
            kept_.setdefault(f.cell.condition, []).append(f)
    evidence = _evidence(found, excluded)
    order = [c.name for c in bench.spec.conditions if c.name in kept_]
    bundles = {c: [f.path for f in kept_[c]] for c in order}
    report = build_report(
        bench.spec.id,
        bench.spec_hash,
        bundles,
        git_sha=git_sha,
        seed=seed,
        resamples=resamples,
        load=bench.load,
    )
    tables: dict[str, Table] = report["tables"]
    tables |= _split_latency(tables.pop("latency"))
    dropped = Counter(f.cell.condition for f in found if f.name in excluded)
    tables["conditions"] = _conditions(bench, kept_, evidence, dropped)
    tables["evidence"] = evidence
    eps = {f.name: episode(f.path, bench.load) for fs in kept_.values() for f in fs}
    tables["comparison"], why = _comparisons(bench, kept_, eps, seed, resamples)
    outcome, missing = tables["outcome"], tables["not_computable"]
    why["blocked_harm"] = BLOCKED
    for c in (s for s in bench.spec.conditions if s.name not in kept_):
        outcome["rows"][c.name] = dict.fromkeys(outcome["columns"])
        outcome["n"][c.name], outcome["ci"][c.name] = 0, {}
        gaps = {excluded[f.name] for f in found if f.cell.condition == c.name}
        reason = "; ".join(sorted(gaps)) or "no bundle in the runs dir"
        attest = "no attested adapter: " if c.attested_adapter else ""
        why[f"condition.{c.name}"] = attest + reason
    for name, reason in why.items():
        missing["rows"][name], missing["n"][name] = {"reason": reason}, 0
        missing["ci"][name] = {}
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="proxyloop.eval.benchmark")
    sub = parser.add_subparsers(dest="command", required=True)
    run_ = sub.add_parser("run", help="root-run (L+G); other options: cli session")
    run_.add_argument("--conditions", help="a comma list from the spec; default all")
    report = sub.add_parser("report", help="offline: no keys, no GPU")
    report.add_argument("--out", required=True)
    report.add_argument("--git-sha", required=True)
    for p in (run_, report):
        p.add_argument("--runs", required=True)
        p.add_argument("--spec", default=str(SPEC))
    args, rest = parser.parse_known_args(argv)
    bench = load_spec(Path(args.spec))
    if args.command == "report":
        if rest:
            parser.error(f"unknown options {rest}")
        out = build(bench, Path(args.runs), git_sha=args.git_sha)
        Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
        return 0
    names = [c.name for c in bench.spec.conditions]
    names = args.conditions.split(",") if args.conditions else names
    runs = asyncio.run(run(bench, live_configs(bench, names, rest), Path(args.runs)))
    gate = integrity([episode(r.path, bench.load) for r in runs])
    print(f"{len(runs)} cells; integrity:", "ok" if gate.ok else gate.reasons)
    return 0 if gate.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
