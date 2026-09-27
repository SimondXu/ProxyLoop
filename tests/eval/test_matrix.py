"""The matrix: seed-major interleaved blocks, one ``run_session`` per cell,
errors kept as failures, the integrity gate (EVAL §5, §8.2, §9.2, §9.9)."""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from tests.eval.streams import Stream
from tests.eval.test_kernel_bundle import FINISH, SCRIPTS
from tests.support.manual_clock import ScaledClock
from tests.support.sessions import clients, ear, fake_config, patient_task

from proxyloop.contract.llm import LLMUnavailable
from proxyloop.env.tasks.schema import Task
from proxyloop.eval.matrix import (
    Cell,
    CellRun,
    MatrixAborted,
    Seams,
    check_echo,
    integrity,
    run_matrix,
    schedule,
)
from proxyloop.eval.metrics import episode
from proxyloop.llm.spend import Charge, RunawaySpend


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


def _gate(outcomes: list[str], cp_turns: list[int] | None = None) -> Any:
    eps = [
        {"outcome": o, "fast_turns": {"user": 1, "cp": t}}
        for o, t in zip(outcomes, cp_turns or [1] * len(outcomes), strict=True)
    ]
    return integrity(eps)


def test_the_integrity_gate_allows_at_most_5_percent_infra_errors() -> None:
    assert _gate(["infra_error"] + ["ok"] * 19).ok  # 5 %
    gate = _gate(["infra_error"] * 2 + ["ok"] * 18)  # 10 %
    assert not gate.ok and gate.infra_errors == 2 and gate.n == 20
    assert "infra errors" in gate.reasons[0]


def test_model_failures_are_reported_but_never_gated() -> None:
    gate = _gate(["model_failure"] * 5 + ["ok"] * 15)
    assert gate.ok and gate.model_failures == 5 and gate.infra_errors == 0


def test_the_integrity_gate_fails_on_a_lane_without_fast_turns() -> None:
    gate = _gate(["ok", "ok"], cp_turns=[1, 0])  # the user lane spoke, cp did not
    assert not gate.ok and "zero Fast turns" in gate.reasons[0]


def test_an_empty_matrix_is_invalid() -> None:
    assert not integrity([]).ok


def load(task_ref: str) -> Task:  # the matrix runs the patient variant
    return patient_task()


def _seams(alive: bool = False) -> Seams:
    def seams(cell: Cell) -> dict[str, Any]:
        clock = ScaledClock(100)
        until = {"slow": ("] cp_update", FINISH)}
        dead = ["fast_cp"] if cell.condition == "dead" and not alive else []
        bad = cell.condition == "bad"
        scripts = SCRIPTS | ({"ear": [ear("no_such_act")]} if bad else {})
        fakes = clients(scripts, clock, dead, until)
        return {"clock": clock, "sleep": clock.sleep, "clients": fakes}

    return seams


def _run(tmp_path: Path, cells: list[Cell], alive: bool = False) -> list[CellRun]:
    configs = {c: fake_config() for c in ("C2", "dead", "bad")}
    tasks = {"i1": patient_task()}
    coro = run_matrix(cells, configs, tasks, tmp_path, seams=_seams(alive))
    return asyncio.run(asyncio.wait_for(coro, timeout=60))


def test_run_matrix_runs_each_cell_once_with_its_seed(tmp_path: Path) -> None:
    cells = schedule(["C2"], ["i1"], [3, 4], salt=0)
    runs = _run(tmp_path, cells)
    assert [r.cell for r in runs] == cells
    eps = [episode(r.path, load) for r in runs]
    assert [e["seed"] for e in eps] == [3, 4]  # the seed is a config value
    assert all(r.reason == "info_only" for r in runs)
    assert integrity(eps).ok
    assert Counter(p.parent for p in (r.path for r in runs)).most_common(1)[0][1] == 1


def test_a_world_error_is_an_infra_error_cell_and_the_matrix_goes_on(
    tmp_path: Path,
) -> None:
    runs = _run(tmp_path, [Cell("bad", "i1", 1), Cell("C2", "i1", 1)])
    assert [r.reason for r in runs] == ["world_error", "info_only"]
    eps = [episode(r.path, load) for r in runs]
    assert eps[0]["outcome"] == "infra_error" and eps[0]["metrics"]["success"] == 0
    assert not integrity(eps).ok  # 1 of 2 are infra errors


def test_a_dead_endpoint_aborts_and_a_rerun_resumes(tmp_path: Path) -> None:
    cells = [Cell("C2", "i1", 1), Cell("dead", "i1", 1), Cell("C2", "i1", 2)]
    with pytest.raises(LLMUnavailable):
        _run(tmp_path, cells)
    folders = sorted(tmp_path.iterdir())
    assert len(folders) == 2  # the third cell never ran
    (first,) = [d for d in folders[0].iterdir() if d.is_dir()]
    runs = _run(tmp_path, cells, alive=True)  # the endpoint is back
    assert runs[0].path == first  # completed: skipped
    assert [r.reason for r in runs] == ["info_only"] * 3
    assert len([d for d in folders[1].iterdir() if d.is_dir()]) == 2  # old kept
    assert runs[1].path.parent == folders[1]


def _raising(err: Exception) -> Any:
    async def session(*args: Any, **kwargs: Any) -> None:
        raise err

    return session


def test_runaway_spend_aborts_the_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    charge = Charge(
        call_id="c",
        role="slow",
        attempt=0,
        endpoint="relay",
        model_id="m",
        basis="tokens",
    )
    runaway = RunawaySpend("runaway spend", charge)
    monkeypatch.setattr("proxyloop.eval.matrix.run_session", _raising(runaway))
    with pytest.raises(RunawaySpend):
        _run(tmp_path, [Cell("C2", "i1", 1), Cell("C2", "i1", 2)])
    assert len(list(tmp_path.iterdir())) == 1


def test_a_cell_that_leaves_no_bundle_is_an_infra_error_cell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # N7
    monkeypatch.setattr(
        "proxyloop.eval.matrix.run_session", _raising(ValueError("refused"))
    )
    (run,) = _run(tmp_path, [Cell("C2", "i1", 1)])
    assert run.reason == "no_bundle" and run.error == "ValueError: refused"
    assert episode(run.path, load)["outcome"] == "infra_error"


def test_an_llm_unavailable_bundle_aborts_whatever_was_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # D3: a dead endpoint at P3/attest closes llm_unavailable, then
    # the kernel raises the underlying error (for example a ConnectError)
    async def session(*args: Any, runs_dir: Path, **kwargs: Any) -> None:
        Stream().write(runs_dir / "run-p3", "llm_unavailable")
        raise RuntimeError("the endpoint did not answer /tokenize")

    monkeypatch.setattr("proxyloop.eval.matrix.run_session", session)
    with pytest.raises(MatrixAborted, match="llm_unavailable"):
        _run(tmp_path, [Cell("C2", "i1", 1), Cell("C2", "i1", 2)])
    assert len(list(tmp_path.iterdir())) == 1  # the second cell never ran


def test_a_p3_failed_cell_aborts_and_is_final_on_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []

    async def session(*args: Any, runs_dir: Path, **kwargs: Any) -> None:
        calls.append(args)
        Stream().write(runs_dir / "run-p3", "p3_failed")
        raise RuntimeError("P3: vLLM /tokenize != the pinned tokenizer")

    monkeypatch.setattr("proxyloop.eval.matrix.run_session", session)
    cells = [Cell("C2", "i1", 1), Cell("C2", "i1", 2)]
    with pytest.raises(MatrixAborted, match="p3_failed"):
        _run(tmp_path, cells)
    assert len(calls) == 1
    with pytest.raises(MatrixAborted):  # resume: cell 0 is final, cell 1 runs
        _run(tmp_path, cells)
    assert len(calls) == 2 and len(list(tmp_path.iterdir())) == 2
    (first,) = [d for d in sorted(tmp_path.iterdir())[0].iterdir() if d.is_dir()]
    assert episode(first)["outcome"] == "infra_error"


def test_resume_skips_timeout_abandoned_and_budget_cells(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # D4: a budget stop is final, never re-run
    cells = [Cell("C2", "i1", seed) for seed in (1, 2, 3)]
    ends = ("timeout", "abandoned", "budget")
    for k, (cell, end) in enumerate(zip(cells, ends, strict=True)):
        Stream().write(tmp_path / f"{k:04d}-C2-i1-s{cell.seed}" / "run-s", end)
    calls: list[object] = []

    async def session(*args: Any, **kwargs: Any) -> None:
        calls.append(args)

    monkeypatch.setattr("proxyloop.eval.matrix.run_session", session)
    runs = _run(tmp_path, cells)
    assert calls == [] and [r.reason for r in runs] == list(ends)
    eps = [episode(r.path) for r in runs]
    assert [e["outcome"] for e in eps] == [
        "model_failure",
        "model_failure",
        "infra_error",
    ]
    assert integrity(eps).infra_errors == 1  # the budget stop is counted


def test_a_changed_served_model_aborts_the_matrix() -> None:
    seen: dict[tuple[str, str], str] = {}
    check_echo([("fast_cp", "q", "q-2026")], seen)
    with pytest.raises(MatrixAborted):
        check_echo([("fast_cp", "q", "q-2027")], seen)
