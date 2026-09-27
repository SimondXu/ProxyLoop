"""Live runs sit one level deeper, at runs/live/<case_id>/<run_id>: listed and
replayed like any bundle, with the held-out barriers intact. Every other root
stays one level deep."""

from __future__ import annotations

import shutil
from pathlib import Path

from tests.serve.client import client, frames, get
from tests.serve.conftest import Bundles
from tests.serve.test_split import TEST, TRAIN

from proxyloop.contract.bundle import EVENTS


def _put(bundles: Bundles, dst: Path, run_id: str | None = None) -> Path:
    run = dst / (run_id or bundles.plain)
    shutil.copytree(bundles.root / bundles.plain, run)
    return run


def _listed(*roots: Path) -> list[str]:
    return [b["run_id"] for b in get(client(*roots), "/api/bundles").json()["bundles"]]


def test_a_live_run_is_listed_and_replayed(bundles: Bundles, tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run = _put(bundles, runs / "live" / "case-1")
    http = client(runs)
    (listed,) = get(http, "/api/bundles").json()["bundles"]
    assert (listed["run_id"], listed["root"]) == (bundles.plain, "runs")
    got = get(http, f"/api/replay/{bundles.plain}/events")
    assert (got.status_code, got.content) == (200, (run / EVENTS).read_bytes())
    assert frames(http, f"/ws/live/{bundles.plain}")[1] == 1000


def test_only_runs_live_is_one_level_deeper(bundles: Bundles, tmp_path: Path) -> None:
    runs, stage = tmp_path / "runs", tmp_path / "evidence" / "s1"
    _put(bundles, runs / "other" / "case-1")
    _put(bundles, runs / "live" / "case-1" / "deeper")
    _put(bundles, stage / "live" / "case-1")
    assert _listed(runs, stage) == []


def test_a_test_split_live_run_is_refused(bundles: Bundles, tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run = _put(bundles, runs / "live" / "case-1")
    first, rest = (run / EVENTS).read_bytes().split(b"\n", 1)
    (run / EVENTS).write_bytes(first.replace(TRAIN, TEST) + b"\n" + rest)
    for name in ("manifest.json", "prompts.jsonl"):
        (run / name).unlink()
    assert _listed(runs) == []
    assert get(client(runs), f"/api/replay/{bundles.plain}/events").status_code == 404
    assert frames(client(runs), f"/ws/live/{bundles.plain}") == ([], 4404)


def test_a_sealed_live_case_is_refused(bundles: Bundles, tmp_path: Path) -> None:
    runs, held = tmp_path / "runs", tmp_path / "evidence" / "s4" / "test" / "case-1"
    _put(bundles, held)
    (runs / "live").mkdir(parents=True)
    (runs / "live" / "case-1").symlink_to(held, target_is_directory=True)
    assert _listed(runs) == []
    assert frames(client(runs), f"/ws/live/{bundles.plain}") == ([], 4404)
