"""The evaluation matrix (EVAL §5, §8.2, §9.2, §9.9).

``schedule`` lays cells out seed-major, in randomised blocks per
instance-repeat: every condition once per (seed, instance), in a seeded order.
``run_matrix`` calls ``run_session(cfg, task)`` once per cell (I1): a
condition is a ``SessionConfig``, the cell's seed a config value. An episode
error stays a failure in the bundle; nothing is retried or filtered. A dead
endpoint (``LLMUnavailable``), runaway spend or a changed served model aborts
the matrix; a re-run resumes it. ``integrity`` is the gate: at most 5 %
infra errors and no lane without a Fast turn, else the matrix is rerun whole.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proxyloop.contract.bundle import read_bundle
from proxyloop.contract.config import SessionConfig
from proxyloop.contract.llm import LLMCallRecord, LLMUnavailable
from proxyloop.env.tasks.schema import Task
from proxyloop.kernel.session import run_session
from proxyloop.llm.spend import RunawaySpend

MAX_ERROR_RATE = 0.05
# End reasons that abort the matrix, whatever run_session raised. On resume a
# cell is re-run only if no model output could be scored: the endpoint died,
# or the bundle is unended or unreadable. Budget and P3 stops are final
# (infra_error).
_ABORT = frozenset({"llm_unavailable", "budget", "p3_failed"})
_RERUN = frozenset({"llm_unavailable", "unended", "unreadable"})


@dataclass(frozen=True, slots=True)
class Cell:
    condition: str
    instance: str
    seed: int


@dataclass(frozen=True, slots=True)
class CellRun:
    cell: Cell
    path: Path  # the bundle dir (the cell folder if none was written)
    reason: str  # its session.ended reason, or unreadable/unended/no_bundle
    error: str | None = None  # the exception run_session raised, if any


@dataclass(frozen=True, slots=True)
class Gate:
    ok: bool
    n: int
    infra_errors: int  # gated
    model_failures: int  # reported, not gated
    reasons: tuple[str, ...]


class MatrixAborted(RuntimeError):
    pass


Seams = Callable[[Cell], Mapping[str, Any]]  # run_session's test keywords


def schedule(
    conditions: Sequence[str],
    instances: Sequence[str],
    seeds: Sequence[int],
    *,
    salt: int,
) -> list[Cell]:
    cells: list[Cell] = []
    for seed in seeds:
        for instance in instances:
            order = list(conditions)
            random.Random(f"{salt}:{seed}:{instance}").shuffle(order)
            cells += [Cell(c, instance, seed) for c in order]
    return cells


def check_echo(
    calls: Iterable[tuple[str, str, str]], seen: dict[tuple[str, str], str]
) -> None:
    """(role, requested model, echoed model): an echo must never change."""
    for role, requested, echo in calls:
        first = seen.setdefault((role, requested), echo)
        if echo != first:
            raise MatrixAborted(f"{role} {requested} served {echo}, earlier {first}")


def _ended(path: Path, seen: dict[tuple[str, str], str]) -> str:
    try:
        events = read_bundle(path).events
    except (OSError, ValueError):
        return "unreadable"
    calls = [
        LLMCallRecord.model_validate(e.payload) for e in events if e.type == "llm.call"
    ]
    echoes = [(c.role, c.requested_model, c.served_model_echo) for c in calls]
    check_echo([(r, m, e) for r, m, e in echoes if e is not None], seen)
    last = events[-1] if events else None
    ended = last is not None and last.type == "session.ended"
    return str(last.payload["reason"]) if last and ended else "unended"


def _bundles(folder: Path) -> set[Path]:
    return {d for d in folder.iterdir() if d.is_dir()} if folder.exists() else set()


_CELL_DIR = re.compile(r"\d{4}-(?P<condition>[^-]+)-(?P<instance>.+)-s(?P<seed>\d+)")


def cell_dir(runs_dir: Path, k: int, cell: Cell) -> Path:
    """The folder of the ``k``-th cell; a condition name holds no ``-``."""
    return runs_dir / f"{k:04d}-{cell.condition}-{cell.instance}-s{cell.seed}"


def read_cell_dir(folder: Path) -> Cell | None:
    """The cell a ``cell_dir`` folder holds; ``None`` for any other name."""
    if (m := _CELL_DIR.fullmatch(folder.name)) is None:
        return None
    return Cell(m["condition"], m["instance"], int(m["seed"]))


def kept(folder: Path, seen: dict[tuple[str, str], str]) -> tuple[Path, str] | None:
    """The bundle a resume keeps, with its end reason: the latest one not in
    ``_RERUN``; ``None`` if the cell must be (re-)run."""
    done = [
        (d, r) for d in sorted(_bundles(folder)) if (r := _ended(d, seen)) not in _RERUN
    ]
    return done[-1] if done else None


async def run_matrix(
    cells: Sequence[Cell],
    configs: Mapping[str, SessionConfig],
    tasks: Mapping[str, Task],
    runs_dir: Path,
    *,
    seams: Seams | None = None,
) -> list[CellRun]:
    """Resumable: a cell whose folder holds a bundle not in ``_RERUN`` is
    skipped (budget, timeout and abandoned included); otherwise it is re-run
    beside the old bundles, which are kept. A cell that leaves no bundle is an
    infra_error cell whose ``path`` is its folder."""
    runs: list[CellRun] = []
    seen: dict[tuple[str, str], str] = {}
    for k, cell in enumerate(cells):
        folder = cell_dir(runs_dir, k, cell)
        before = _bundles(folder)
        if done := kept(folder, seen):
            runs.append(CellRun(cell, *done))
            continue
        folder.mkdir(parents=True, exist_ok=True)
        base = configs[cell.condition].model_dump()
        cfg = SessionConfig.model_validate(base | {"seed": cell.seed})
        caught: Exception | None = None
        try:
            keywords: Mapping[str, Any] = seams(cell) if seams else {}
            await run_session(cfg, tasks[cell.instance], runs_dir=folder, **keywords)
        except Exception as err:  # the episode failed; its bundle says how
            caught = err
        new = sorted(_bundles(folder) - before)
        path = new[-1] if new else folder
        reason = _ended(path, seen) if new else "no_bundle"
        if isinstance(caught, (LLMUnavailable, RunawaySpend)):
            raise caught  # a dead endpoint or runaway spend aborts the matrix (I8)
        if reason in _ABORT:  # a dead endpoint at P3/attest closes llm_unavailable;
            # a P3 token mismatch closes p3_failed; both then raise other errors
            raise MatrixAborted(f"{cell} ended {reason}") from caught
        error = None if caught is None else f"{type(caught).__name__}: {caught}"
        runs.append(CellRun(cell, path, reason, error))
    return runs


def integrity(episodes: Sequence[Mapping[str, Any]]) -> Gate:
    """EVAL §9.9 on ``metrics`` records: invalid if more than 5 % are
    ``infra_error`` or any episode has zero Fast turns on a lane.
    ``model_failure`` episodes are reported, never gated: they are results."""
    n = len(episodes)
    infra = sum(e["outcome"] == "infra_error" for e in episodes)
    model = sum(e["outcome"] == "model_failure" for e in episodes)
    reasons: list[str] = []
    if not n:
        reasons.append("no episodes")
    elif infra / n > MAX_ERROR_RATE:
        reasons.append(f"{infra}/{n} infra errors (> 5 %): rerun the matrix whole")
    if silent := [e for e in episodes if min(e["fast_turns"].values()) == 0]:
        reasons.append(f"{len(silent)} episodes have a lane with zero Fast turns")
    return Gate(not reasons, n, infra, model, tuple(reasons))
