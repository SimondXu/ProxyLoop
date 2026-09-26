"""The evaluation matrix (EVAL §5, §8.2, §9.2, §9.9).

``schedule`` lays cells out seed-major, in randomised blocks per
instance-repeat: every condition once per (seed, instance), in a seeded order.
``run_matrix`` calls ``run_session(cfg, task)`` once per cell (I1): a
condition is a ``SessionConfig``, the cell's seed a config value. An episode
error stays a failure in the bundle; nothing is retried or filtered. A dead
endpoint (``LLMUnavailable``) or a changed served model aborts the matrix.
``integrity`` is the gate: at most 5 % errored episodes and none without a
Fast turn, else the matrix is rerun whole.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proxyloop.contract.bundle import read_bundle
from proxyloop.contract.config import SessionConfig
from proxyloop.contract.llm import LLMCallRecord, LLMUnavailable
from proxyloop.env.tasks.schema import Task
from proxyloop.kernel.session import run_session

MAX_ERROR_RATE = 0.05


@dataclass(frozen=True, slots=True)
class Cell:
    condition: str
    instance: str
    seed: int


@dataclass(frozen=True, slots=True)
class CellRun:
    cell: Cell
    path: Path  # the bundle dir
    reason: str  # its session.ended reason
    error: str | None = None  # the exception run_session raised, if any


@dataclass(frozen=True, slots=True)
class Gate:
    ok: bool
    n: int
    errors: int
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
    events = read_bundle(path).events
    calls = [
        LLMCallRecord.model_validate(e.payload) for e in events if e.type == "llm.call"
    ]
    echoes = [(c.role, c.requested_model, c.served_model_echo) for c in calls]
    check_echo([(r, m, e) for r, m, e in echoes if e is not None], seen)
    last = events[-1]
    return str(last.payload["reason"]) if last.type == "session.ended" else "unended"


async def run_matrix(
    cells: Sequence[Cell],
    configs: Mapping[str, SessionConfig],
    tasks: Mapping[str, Task],
    runs_dir: Path,
    *,
    seams: Seams | None = None,
) -> list[CellRun]:
    runs: list[CellRun] = []
    seen: dict[tuple[str, str], str] = {}
    for k, cell in enumerate(cells):
        base = configs[cell.condition].model_dump()
        cfg = SessionConfig.model_validate(base | {"seed": cell.seed})
        folder = runs_dir / f"{k:04d}-{cell.condition}-{cell.instance}-s{cell.seed}"
        folder.mkdir(parents=True)
        error: str | None = None
        try:
            keywords: Mapping[str, Any] = seams(cell) if seams else {}
            await run_session(cfg, tasks[cell.instance], runs_dir=folder, **keywords)
        except LLMUnavailable:
            raise  # a dead endpoint aborts the matrix (I8)
        except Exception as err:  # the episode failed; its bundle says how
            error = f"{type(err).__name__}: {err}"
        bundles = [d for d in folder.iterdir() if d.is_dir()]
        if not bundles:  # refused before any bundle: a setup error, not an episode
            raise MatrixAborted(f"{cell} left no bundle ({error})")
        runs.append(CellRun(cell, bundles[0], _ended(bundles[0], seen), error))
    return runs


def integrity(episodes: Sequence[Mapping[str, Any]]) -> Gate:
    """EVAL §9.9 on ``metrics`` records: invalid if more than 5 % errored or
    any episode has zero Fast turns."""
    n, errors = len(episodes), sum(bool(e["errored"]) for e in episodes)
    reasons: list[str] = []
    if not n:
        reasons.append("no episodes")
    elif errors / n > MAX_ERROR_RATE:
        reasons.append(f"{errors}/{n} episodes errored (> 5 %): rerun the matrix whole")
    if silent := [e for e in episodes if not sum(e["fast_turns"].values())]:
        reasons.append(f"{len(silent)} episodes have zero Fast turns")
    return Gate(not reasons, n, errors, tuple(reasons))
