"""The Fast benchmark (S1-MOD-04): C5 (Luna, hosted), C2 (base Qwen) and C1
(fine-tuned Qwen) on the same (family, instance, seed) cells (EVAL §4.1, §7).

A thin layer over ``matrix`` and ``report``:
- ``load_spec`` reads ``specs/fast_benchmark.yaml`` and refuses a ``test``
  family before any task is loaded (I9, AGENTS rule 11);
- ``run`` schedules every condition once per (instance, seed) block, so the
  pairing is by construction, and calls ``run_matrix``: one ``run_session``
  per cell, a condition applied as a config value (I1), no retries;
- ``build`` makes ``pl.report/1`` from runs dirs (one matrix each; C1 runs
  later as its own matrix): ``report.build_report``'s tables, plus every
  bundle's evidence-check label, the paired comparisons (``not interleaved``
  across matrices) and a gate (integrity, pairing, one shared config) that
  ``main report`` enforces unless ``--descriptive``.

Latency (user, 2026-09-26): one table per endpoint label, so hosted
(relay-measured) latency never shares a column with self-hosted Qwen, and no
comparison is made on latency. A condition marked ``attested_adapter`` (C1)
counts a bundle only if ``attestation_gap`` finds nothing; else its row stays
empty with the reason. A bundle that fails ``evidence-check
--claim`` is kept and labelled, and its condition is marked descriptive.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any, Literal, Self

import yaml
from pydantic import Field, model_validator

from proxyloop.cli import build_parser, live_config
from proxyloop.contract.base import Frozen, canonical_json, sha256_text
from proxyloop.contract.bundle import MANIFEST, Manifest
from proxyloop.contract.config import SessionConfig
from proxyloop.env.tasks.loader import instance_hash, load_task
from proxyloop.env.tasks.schema import Task
from proxyloop.eval.matrix import (
    Cell,
    CellRun,
    Seams,
    cell_dir,
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
ADAPTER = (
    "no attested adapter (attestation equality alone is insufficient: shards "
    "under adapters/<Fast model_id>/ and an evidence-check --claim pass): "
)
NOT_INTERLEAVED = "not interleaved: separate matrices, time-separated"
_FAST = ("fast_user", "fast_cp")
_NOT_SHARED = {"fast_user", "fast_cp", "teacher", "seed"}  # ablations: own only
Key = tuple[str, str, int]  # (family, instance, seed)
FamilyLoader = Callable[[str], Task]  # a spec family -> its task (the file's)
Table = dict[str, Any]


class ConditionSpec(Frozen):
    name: str = Field(pattern=r"^[A-Za-z0-9]+$")  # no "-": matrix.cell_dir
    attested_adapter: bool = False
    note: str | None = Field(default=None, min_length=1)  # on its conditions row


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
    load: Loader  # task_ref -> one of ``tasks``, for the metrics

    def expected(self) -> set[Key]:
        return {
            (f.family, i, s)
            for f in self.spec.families
            for i in f.instances
            for s in f.seeds
        }


def _by_ref(tasks: Iterable[Task]) -> Loader:
    """The metrics' loader: a bundle's task_ref -> the spec task of that ref."""
    known = {t.ref: t for t in tasks}

    def load(task_ref: str) -> Task:
        if task_ref not in known:
            raise ValueError(f"{task_ref} is not a task of this benchmark spec")
        return known[task_ref]

    return load


def load_spec(path: Path = SPEC, load: FamilyLoader = load_task) -> Benchmark:
    """The spec, its tasks and hash; a ``test`` family raises ``HeldOutRefused``
    before any task is read. An instance is a family's task id; a bundle's
    task_ref must be its task's ref (a ``#seed`` instance is not a cell)."""
    text = path.read_text("utf-8")
    spec = Spec.model_validate(yaml.safe_load(text))
    if held := [f.family for f in spec.families if f.split == "test"]:
        raise HeldOutRefused(f"test-split families {held}: sealed until the unseal")
    tasks: dict[str, Task] = {}
    for f in spec.families:
        task = load(f.family)
        for instance in f.instances:
            if instance != task.id:
                raise ValueError(f"{f.family} has no instance {instance!r}")
            tasks[instance] = task
    family = {i: f.family for f in spec.families for i in f.instances}
    return Benchmark(spec, sha256_text(text), tasks, family, _by_ref(tasks.values()))


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
    """The cells of ``configs``' conditions through ``run_matrix``. A runs dir
    holds one matrix: a folder outside this condition list's plan is refused
    before any session (the folder names carry the schedule index)."""
    todo = cells(bench.spec, list(configs))
    planned = {cell_dir(runs_dir, k, cell).name for k, cell in enumerate(todo)}
    folders = runs_dir.iterdir() if runs_dir.exists() else iter(())
    if stray := sorted(d.name for d in folders if d.is_dir() and d.name not in planned):
        raise ValueError(
            f"{runs_dir} holds folders outside this matrix ({', '.join(stray[:3])}"
            "...): use a fresh RUNS dir per condition set, or resume with the "
            "identical condition list"
        )
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
    matrix: int  # the runs dir it came from: one matrix each


def _manifest(run_dir: Path) -> Manifest | None:
    try:
        return Manifest.model_validate_json((run_dir / MANIFEST).read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _discover(bench: Benchmark, runs_dirs: Sequence[Path]) -> list[_Found]:
    """One bundle per cell folder: the one a resume keeps, else the latest
    (a failure that stays counted), else the folder. Test-split manifests are
    refused before any event is read."""
    names = {c.name for c in bench.spec.conditions}
    seen: dict[tuple[str, str], str] = {}
    found: dict[tuple[str, Key], _Found] = {}
    folders = [(n, d) for n, r in enumerate(runs_dirs) for d in sorted(r.iterdir())]
    for matrix, folder in ((n, d) for n, d in folders if d.is_dir()):
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
            raise ValueError(f"{folder}: cell {cell} is in the runs dirs twice")
        m = manifests.get(path)
        if m is not None:
            task = bench.tasks[cell.instance]
            want = (task.ref, instance_hash(task), cell.seed)
            got = (m.task_ref, m.instance_hash, m.cfg.seed)
            if got != want:
                raise ValueError(f"{path} ran {got}, not its cell {want}")
        name = folder.name if path == folder else f"{folder.name}/{path.name}"
        found[(cell.condition, key)] = _Found(cell, key, path, name, m, matrix)
    return list(found.values())


def _check(path: Path) -> tuple[str, list[str]]:
    """The evidence-check label (claim, else offline, else failed), and why."""
    claim = check_path(path, "claim")
    if claim.ok:
        return "claim", []
    offline = check_path(path, "offline")
    return (
        ("offline", list(claim.failures))
        if offline.ok
        else (
            "failed",
            list(offline.failures),
        )
    )


def attestation_gap(m: Manifest | None, label: str) -> str | None:
    """Why an ``attested_adapter`` bundle does not count; ``None`` if it does:
    shards under ``adapters/<its Fast model_id>/`` that match the attestation,
    and an evidence-check ``claim`` label (with S1-SYS-14: the training card)."""
    if m is None:
        return "unreadable manifest"
    fast = [m.models[r] for r in _FAST if r in m.models]
    if not fast or any(not r.adapter_shards for r in fast):
        return NO_SHARDS
    for r in fast:
        slot = f"adapters/{r.ref.model_id}/"
        if stray := sorted(f for f in r.adapter_shards if not f.startswith(slot)):
            return f"adapter shards {stray} are not under {slot}"
    attested = m.attestation or {}
    shards = {f: sha for r in fast for f, sha in r.adapter_shards.items()}
    if bad := sorted(f for f, sha in shards.items() if attested.get(f) != sha):
        return f"adapter shards {bad} do not match the attestation"
    return None if label == "claim" else f"evidence-check --claim fails ({label})"


def _trained_prefix() -> str:
    from serving import config  # lazily, as models.registry resolves C1

    prefix = getattr(config, "TRAINED_PREFIX", None)
    if not isinstance(prefix, str):
        raise LookupError("serving.config has no TRAINED_PREFIX: C1 is uncheckable")
    return prefix


def _own(c: ConditionSpec) -> tuple[str, ...]:
    """The ablations the condition itself sets (C1 sets none)."""
    return () if c.attested_adapter else registry.condition(c.name).ablations


def _ref_gap(c: ConditionSpec, m: Manifest) -> str | None:
    """Why the bundle's Fast refs are not its folder's condition's."""
    refs = (m.cfg.fast_user, m.cfg.fast_cp)
    ids = [f"{r.endpoint}:{r.model_id}" for r in refs]
    if c.attested_adapter:
        prefix = _trained_prefix()
        if all(r.endpoint == "vllm" and r.model_id.startswith(prefix) for r in refs):
            return None
        return f"Fast {ids} is not a vllm {prefix}* slot"
    want = registry.condition(c.name)
    return None if refs == (want.fast_user, want.fast_cp) else f"Fast {ids}"


def _config_gap(
    specs: Mapping[str, ConditionSpec], kept_: Sequence[_Found]
) -> list[str]:
    """Everything but the Fast lanes, teacher, own ablations and seed must be one
    value across all kept bundles; else the distinct values by run_id."""
    groups: dict[str, list[str]] = {}
    for f, m in ((f, f.manifest) for f in kept_):
        if m is None:  # an unreadable bundle: an infra_error, no config
            continue
        data = m.cfg.model_dump(mode="json", exclude=_NOT_SHARED)
        own = _own(specs[f.cell.condition])
        data["ablations"] = [a for a in data["ablations"] if a not in own]
        groups.setdefault(canonical_json(data), []).append(m.run_id)
    if len(groups) < 2:
        return []
    return [f"cfg differs: {v} for run_ids {sorted(ids)}" for v, ids in groups.items()]


def _table(columns: Sequence[str]) -> Table:
    return {"columns": list(columns), "rows": {}, "n": {}, "ci": {}}


def _put(table: Table, name: str, row: dict[str, Any], n: int) -> None:
    table["rows"][name], table["n"][name], table["ci"][name] = row, n, {}


def _label(key: Key) -> str:
    return f"{key[0]}/{key[1]}/s{key[2]}"


def _conditions(
    bench: Benchmark,
    kept_: Mapping[str, Sequence[_Found]],
    labels: Mapping[str, str],
    excluded: Mapping[str, int],
) -> Table:
    """Pairing: per condition, its cells missing from the spec's set and its
    cells absent from another condition that has bundles; claim status."""
    columns = ["expected", "present", "missing", "unpaired", "excluded"]
    table = _table([*columns, "claimable", "evidence", "fast_models", "note"])
    expected = bench.expected()
    present = {c: {f.key for f in fs} for c, fs in kept_.items()}
    sets = list(present.values())
    paired = sets[0].intersection(*sets[1:]) if sets else set[Key]()
    for c, note in ((s.name, s.note) for s in bench.spec.conditions):
        mine, fs = present.get(c, set[Key]()), kept_.get(c, [])
        claimable = sum(labels[f.name] == "claim" for f in fs)
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
        row["note"] = note
        _put(table, c, row, len(fs))
    return table


def _value(e: Mapping[str, Any], metric: str) -> int | None:
    if e["outcome"] == "infra_error":  # budget stops included: never scored 0
        return None
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
    cluster bootstrap over instances (EVAL §8.4) when there are two or more.
    Cells from different matrices (runs dirs) are time-separated: marked."""
    table = _table([f"{m}_delta" for m in COMPARED] + ["interleaving"])
    why: dict[str, str] = {}
    for a, b in bench.spec.comparisons:
        name = f"{a}-{b}"
        by_key = {c: {f.key: f for f in kept_.get(c, [])} for c in (a, b)}
        paired = sorted(by_key[a].keys() & by_key[b].keys())
        row: dict[str, Any] = dict.fromkeys(table["columns"])
        ci: dict[str, list[float]] = {}
        if not paired:
            why[f"comparison.{name}"] = f"{a} and {b} share no cell with bundles"
        else:
            same = all(by_key[a][k].matrix == by_key[b][k].matrix for k in paired)
            row["interleaving"] = "interleaved" if same else NOT_INTERLEAVED
        cells_ = [(eps[by_key[a][k].name], eps[by_key[b][k].name]) for k in paired]
        infra = sum("infra_error" in (x["outcome"], y["outcome"]) for x, y in cells_)
        for m in COMPARED if paired else ():
            diffs: dict[Key, float] = {}
            for k, (x, y) in zip(paired, cells_, strict=True):
                vx, vy = _value(x, m), _value(y, m)
                if vx is not None and vy is not None:
                    diffs[k] = float(vx - vy)
            if len(diffs) < len(paired):
                why[f"comparison.{name}.{m}"] = (
                    f"infra_error (budget stops included) on {infra} paired cells: "
                    "not scored"
                    if infra
                    else f"{m} is not computable on a paired cell"
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
        _put(table, name, row, len(paired))
        table["ci"][name] = ci
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


def refusals(report: Mapping[str, Any]) -> list[str]:
    """The gate's reasons; the report is claimable only when there are none."""
    return [
        r for row in report["tables"]["gate"]["rows"].values() for r in row["reasons"]
    ]


def build(
    bench: Benchmark,
    runs_dirs: Sequence[Path],
    *,
    git_sha: str,
    seed: int = 0,
    resamples: int = 10_000,
) -> dict[str, Any]:
    """``pl.report/1`` for the runs dirs of ``run`` (one matrix each): rows per
    condition (every bundle it kept, failures included), comparisons over
    paired cells only, and the gate (integrity, pairing, one shared config).
    A bundle whose Fast refs are not its folder's condition's is refused."""
    specs = {c.name: c for c in bench.spec.conditions}
    found = _discover(bench, runs_dirs)
    checked = {f.name: _check(f.path) for f in found}
    excluded = {
        f.name: gap
        for f in found
        if specs[f.cell.condition].attested_adapter
        and (gap := attestation_gap(f.manifest, checked[f.name][0]))
    }
    kept_: dict[str, list[_Found]] = {}
    for f in (f for f in found if f.name not in excluded):
        m = f.manifest
        if m is not None and (gap := _ref_gap(specs[f.cell.condition], m)):
            raise ValueError(f"{f.path} is not a {f.cell.condition} bundle: {gap}")
        kept_.setdefault(f.cell.condition, []).append(f)
    order = [c.name for c in bench.spec.conditions if c.name in kept_]
    report = build_report(
        bench.spec.id,
        bench.spec_hash,
        {c: [f.path for f in kept_[c]] for c in order},
        git_sha=git_sha,
        seed=seed,
        resamples=resamples,
        load=bench.load,
    )
    tables: dict[str, Table] = report["tables"]
    tables |= _split_latency(tables.pop("latency"))
    dropped = Counter(f.cell.condition for f in found if f.name in excluded)
    labels = {name: label for name, (label, _) in checked.items()}
    conditions = tables["conditions"] = _conditions(bench, kept_, labels, dropped)
    evidence = tables["evidence"] = _table(
        ["condition", "cell", "evidence", "failures", "excluded"]
    )
    for f in found:
        label, failures = checked[f.name]
        row = {"condition": f.cell.condition, "cell": _label(f.key)}
        row |= {"evidence": label, "failures": failures}
        _put(evidence, f.name, row | {"excluded": excluded.get(f.name)}, 1)
    eps = {f.name: episode(f.path, bench.load) for fs in kept_.values() for f in fs}
    tables["comparison"], why = _comparisons(bench, kept_, eps, seed, resamples)
    gate = tables["gate"] = _table(["ok", "reasons"])
    matrix = integrity(list(eps.values()))
    pairing = [
        f"{c}: {k} cells {', '.join(row[k])}"
        for c, row in conditions["rows"].items()
        for k in ("missing", "unpaired")
        if row[k] and conditions["n"][c]  # a condition with bundles
    ]
    for name, reasons in (
        ("integrity", list(matrix.reasons)),
        ("pairing", pairing),
        ("config", _config_gap(specs, [f for fs in kept_.values() for f in fs])),
    ):
        _put(gate, name, {"ok": not reasons, "reasons": reasons}, matrix.n)
    outcome, missing = tables["outcome"], tables["not_computable"]
    why["blocked_harm"] = BLOCKED
    for c in (s for s in bench.spec.conditions if s.name not in kept_):
        _put(outcome, c.name, dict.fromkeys(outcome["columns"]), 0)
        gaps = {excluded[f.name] for f in found if f.cell.condition == c.name}
        reason = "; ".join(sorted(gaps)) or "no bundle in the runs dirs"
        why[f"condition.{c.name}"] = (ADAPTER if c.attested_adapter else "") + reason
    for name, reason in why.items():
        _put(missing, name, {"reason": reason}, 0)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="proxyloop.eval.benchmark")
    sub = parser.add_subparsers(dest="command", required=True)
    run_ = sub.add_parser("run", help="root-run (L+G); other options: cli session")
    run_.add_argument("--conditions", help="a comma list from the spec; default all")
    run_.add_argument("--runs", required=True)
    report = sub.add_parser("report", help="offline: no keys, no GPU")
    report.add_argument("--runs", required=True, action="append", help="per matrix")
    report.add_argument("--out", required=True)
    report.add_argument("--git-sha", required=True)
    report.add_argument("--descriptive", action="store_true", help="write if gated")
    for p in (run_, report):
        p.add_argument("--spec", default=str(SPEC))
    args, rest = parser.parse_known_args(argv)
    bench = load_spec(Path(args.spec))
    if args.command == "report":
        if rest:
            parser.error(f"unknown options {rest}")
        out = build(bench, [Path(r) for r in args.runs], git_sha=args.git_sha)
        if reasons := refusals(out):
            print("gate:", *reasons, sep="\n  ", file=sys.stderr)
            if not args.descriptive:
                print("nothing written (--descriptive writes it)", file=sys.stderr)
                return 1
            out |= {"descriptive": True, "refusals": reasons}
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
