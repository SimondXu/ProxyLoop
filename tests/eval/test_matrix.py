"""The matrix: seed-major interleaved blocks, one ``run_session`` per cell,
errors kept as failures, the integrity gate (EVAL §5, §8.2, §9.2, §9.9)."""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from tests.eval.test_kernel_bundle import FINISH, SCRIPTS
from tests.support.manual_clock import ScaledClock
from tests.support.sessions import clients, ear, fake_config, patient_task

from proxyloop.contract.llm import LLMUnavailable
from proxyloop.eval.matrix import Cell, MatrixAborted, integrity, run_matrix, schedule
from proxyloop.eval.metrics import episode


def test_schedule_is_seed_major_with_every_condition_once_per_block() -> None:
    cells = schedule(["C2", "T", "F"], ["i1", "i2"], [1, 2], salt=9)
    assert len(cells) == 12
    assert [c.seed for c in cells] == [1] * 6 + [2] * 6  # seed-major
    blocks = [cells[k : k + 3] for k in range(0, 12, 3)]
    for block in blocks:
        assert len({(c.instance, c.seed) for c in block}) == 1
        assert sorted(c.condition for c in block) == ["C2", "F", "T"]
    assert [b[0].instance for b in blocks] == ["i1", "i2", "i1", "i2"]


def test_schedule_orders_are_randomised_and_reproducible() -> None:
    a = schedule(["C2", "T", "F", "R", "C4"], ["i1", "i2", "i3"], [1, 2, 3], salt=9)
    assert a == schedule(
        ["C2", "T", "F", "R", "C4"], ["i1", "i2", "i3"], [1, 2, 3], salt=9
    )
    assert a != schedule(
        ["C2", "T", "F", "R", "C4"], ["i1", "i2", "i3"], [1, 2, 3], salt=8
    )
    orders = {tuple(c.condition for c in a[k : k + 5]) for k in range(0, 45, 5)}
    assert len(orders) > 1  # not one fixed order: blocks are randomised


def _gate(errored: list[bool], turns: list[int] | None = None) -> Any:
    eps = [
        {"errored": e, "fast_turns": {"user": 1, "cp": t}}
        for e, t in zip(errored, turns or [1] * len(errored), strict=True)
    ]
    return integrity(eps)


def test_the_integrity_gate_allows_at_most_5_percent_errors() -> None:
    assert _gate([True] + [False] * 19).ok  # 5 %
    gate = _gate([True, True] + [False] * 18)  # 10 %
    assert not gate.ok and gate.errors == 2 and gate.n == 20
    assert "error" in gate.reasons[0]


def test_the_integrity_gate_fails_on_an_episode_without_fast_turns() -> None:
    gate = integrity([{"errored": False, "fast_turns": {"user": 0, "cp": 0}}])
    assert not gate.ok and "zero Fast turns" in gate.reasons[0]


def test_an_empty_matrix_is_invalid() -> None:
    assert not integrity([]).ok


def _seams(cell: Cell) -> dict[str, Any]:
    clock = ScaledClock(100)
    until = {"slow": ("] cp_update", FINISH)}
    dead = ["fast_cp"] if cell.condition == "dead" else []
    scripts = SCRIPTS | (
        {"ear": [ear("no_such_act")]} if cell.condition == "bad" else {}
    )
    return {
        "clock": clock,
        "sleep": clock.sleep,
        "clients": clients(scripts, clock, dead, until),
    }


def _run(tmp_path: Path, cells: list[Cell]) -> list[Any]:
    configs = {c: fake_config() for c in ("C2", "dead", "bad")}
    coro = run_matrix(cells, configs, {"i1": patient_task()}, tmp_path, seams=_seams)
    return asyncio.run(asyncio.wait_for(coro, timeout=60))


def test_run_matrix_runs_each_cell_once_with_its_seed(tmp_path: Path) -> None:
    cells = schedule(["C2"], ["i1"], [3, 4], salt=0)
    runs = _run(tmp_path, cells)
    assert [r.cell for r in runs] == cells
    eps = [episode(r.path) for r in runs]
    assert [e["seed"] for e in eps] == [3, 4]  # the seed is a config value
    assert all(r.reason == "info_only" for r in runs)
    assert integrity(eps).ok
    assert Counter(p.parent for p in (r.path for r in runs)).most_common(1)[0][1] == 1


def test_an_errored_cell_is_kept_as_a_failure_and_the_matrix_goes_on(
    tmp_path: Path,
) -> None:
    cells = [Cell("bad", "i1", 1), Cell("C2", "i1", 1)]
    runs = _run(tmp_path, cells)
    assert [r.reason for r in runs] == ["world_error", "info_only"]
    eps = [episode(r.path) for r in runs]
    assert eps[0]["errored"] and eps[0]["metrics"]["success"] == 0
    assert not integrity(eps).ok  # 1 of 2 errored


def test_a_dead_endpoint_aborts_the_matrix_loudly(tmp_path: Path) -> None:
    cells = [Cell("C2", "i1", 1), Cell("dead", "i1", 1), Cell("C2", "i1", 2)]
    with pytest.raises(LLMUnavailable):
        _run(tmp_path, cells)
    ran = sorted(d.name for d in tmp_path.iterdir())
    assert len(ran) == 2  # the third cell never ran


def test_a_changed_served_model_aborts_the_matrix(tmp_path: Path) -> None:
    from proxyloop.eval.matrix import check_echo

    seen: dict[tuple[str, str], str] = {}
    check_echo([("fast_cp", "q", "q-2026")], seen)
    with pytest.raises(MatrixAborted):
        check_echo([("fast_cp", "q", "q-2027")], seen)
