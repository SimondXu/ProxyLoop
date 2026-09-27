"""The cross-run table: ok runs only, one copy per run_id, grouped by git_sha
with the newest sha first; a bad bundle is skipped, a sealed root refused."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.obs.bundles import Log, manifest, write
from tests.obs.triage_bundle import bare, bundle

from proxyloop.contract.bundle import EVENTS
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
    rows, skipped = diagnose.rows([runs, evidence])
    assert skipped == []
    assert [(r["git_sha"], r["run_id"]) for r in rows] == [
        ("new", "rNew"),
        ("old", "rOld"),  # within a sha: task_ref, then start time
        ("old", "rOld2"),
    ]
    assert diagnose.main(["--root", str(runs), "--root", str(evidence)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"# {detectors.BANNER}"
    heads = [line for line in out if line.startswith("== ")]
    assert heads == ["== git_sha new  runs=1", "== git_sha old  runs=2"]
    # a bare run: no end and no step are unknown ("?"), counted per group
    assert "end_reason" not in out[2] and "end=None" in out[2]
    assert "slow_max_step_gap_ms:?x2" in out[-1]


def test_a_bad_bundle_is_skipped_not_fatal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle(tmp_path)  # rT: the one guide heard is 400 ms after it
    empty = write(tmp_path / "rE", None, manifest("rE"))
    (empty / EVENTS).write_text("", "utf-8")  # a manifest, no events: ok to index
    assert diagnose.main(["--root", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert "skipped: " in captured.err and "rE" in captured.err
    assert "skipped=1" in captured.err
    runs_lines = [line for line in captured.out.splitlines() if "rT " in line]
    assert len(runs_lines) == 1
    assert "guide_to_heard_ms=400" in runs_lines[0]  # the p50, not the count


def test_a_sealed_root_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sealed = tmp_path / "evidence" / "s4" / "test"
    sealed.mkdir(parents=True)
    assert diagnose.main(["--root", str(sealed)]) == 2
    assert capsys.readouterr().err.startswith("refused: ")


def test_groups_by_slow_fp_when_present(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bare(tmp_path, "rA", "s1", hours=0, slow_fp="fpA")
    bare(tmp_path, "rB", "s2", hours=1, slow_fp="fpA")  # same Slow, newer sha
    bare(tmp_path, "rC", "s1", hours=2)  # no slow_fp: its sha
    rows, _ = diagnose.rows([tmp_path])
    assert [(diagnose.group(r), r["run_id"]) for r in rows] == [
        ("git_sha:s1", "rC"),
        ("slow_fp:fpA", "rA"),
        ("slow_fp:fpA", "rB"),
    ]
    assert diagnose.main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert [x for x in out if x.startswith("== ")] == [
        "== git_sha s1  runs=1",
        "== slow_fp fpA  runs=2",
    ]
    totals = [x.split() for x in out if x.startswith("  sum")]
    assert totals and all("max" not in t for t in totals)  # bare runs: no maxima


def test_totals_label_sums_and_maxima(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle(tmp_path)
    assert diagnose.main(["--root", str(tmp_path)]) == 0
    total = capsys.readouterr().out.splitlines()[-1].split()
    sums, maxima = total[: total.index("max")], total[total.index("max") :]
    assert sums[0] == "sum" and "llm_calls=5" in sums
    assert "slow_max_step_gap_ms=2900" in maxima  # a max, not under "sum"
    assert not any(c.startswith("slow_max_step_gap_ms") for c in sums)


def test_unasked_offers_show_as_their_own_cell(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = Log("rO")
    slots = [{"field": "monthly_price", "value": "1", "status": "unknown"}]
    offer: dict[str, object] = {"offer_ref": "o1", "revision": 1, "slots": slots}
    offer["terms_hash"] = None
    log.add("offer.recorded", "guard", "agent", offer, (log.start,))
    write(tmp_path / "rO", log, manifest("rO"))
    assert diagnose.main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "offer.required_unconfirmed_after_readback.unasked_n=1" in out
