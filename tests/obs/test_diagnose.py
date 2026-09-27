"""The cross-run table: ok runs only, one copy per run_id, grouped by git_sha
with the newest sha first."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.obs.bundles import Log, write
from tests.obs.triage_bundle import bare

from proxyloop.obs import detectors, diagnose


def test_groups_by_sha_newest_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runs, evidence = tmp_path / "runs", tmp_path / "evidence"
    bare(runs, "rOld", "old", hours=0)
    bare(runs, "rNew", "new", hours=2)
    bare(runs, "rOld2", "old", hours=1)
    bare(evidence / "s1", "rNew", "new", hours=2)  # an evidence copy
    write(runs / "rInc", Log("rInc"), None)  # incomplete: no manifest
    rows = diagnose.rows([runs, evidence])
    assert [(r["git_sha"], r["run_id"]) for r in rows] == [
        ("new", "rNew"),
        ("old", "rOld"),  # within a sha: task_ref, then start time
        ("old", "rOld2"),
    ]
    assert diagnose.main(["--root", str(runs), "--root", str(evidence)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"# {detectors.BANNER}"
    heads = [line for line in out if line.startswith("== ")]
    assert heads == ["== new  runs=1", "== old  runs=2"]
    # a bare run: no end and no step are unknown ("?"), counted per group
    assert "end_reason" not in out[2] and "end=None" in out[2]
    assert "slow_max_step_gap_ms:?x2" in out[-1]
