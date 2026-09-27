"""The run index over the fixture corpus (``conftest.py``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.obs.bundles import Log, manifest, write

from proxyloop.obs.runs import Run, index, main


def _by_path(runs: list[Run], base: Path) -> dict[str, Run]:
    return {str(Path(r.path).relative_to(base.resolve())): r for r in runs}


def test_one_row_per_bundle_with_status(corpus: tuple[Path, Path]) -> None:
    runs, evidence = corpus
    rows = _by_path(index([runs, evidence]), runs.parent)
    status = {path: row.status for path, row in rows.items()}
    assert status == {
        "runs/rA": "ok",
        "runs/live/case-1/rB": "ok",
        "runs/rC": "ok",
        "evidence/s1/rC": "ok",
        "runs/rD": "ok",
        "runs/rE": "incomplete",
        "runs/rF": "invalid",
        "runs/rG": "sealed",
    }
    a, b, c = rows["runs/rA"], rows["runs/live/case-1/rB"], rows["evidence/s1/rC"]
    assert (a.kind, b.kind, b.case_id, c.kind, c.stage) == (
        "runs",
        "live",
        "case-1",
        "evidence",
        "s1",
    )
    # rA: 1 start + 5 llm.call + 5 spend.charged + 1 end = 12 events, t_ms 1100
    assert (a.events, a.duration_ms, a.ended, a.started) == (
        12,
        1100,
        "done",
        "2026-09-27T01:00:00+00:00",
    )
    assert (a.priced_micro_usd, a.unpriced_calls, a.split) == (6300, 2, "train")
    assert a.models["slow"] == {"endpoint": "relay", "model_id": "claude-sonnet-5"}
    assert a.reality["fast_cp"] == "real_http"
    assert (b.uncharged_calls, rows["runs/rC"].unmatched_charges) == (1, 1)
    assert rows["runs/rE"].error == "no manifest.json"
    assert rows["runs/rE"].events == 5
    assert rows["runs/rF"].error == "json_invalid@"


def test_sealed_bundles_are_never_read(corpus: tuple[Path, Path]) -> None:
    runs, evidence = corpus
    rows = index([runs, evidence])
    assert not [r for r in rows if "s4" in Path(r.path).parts]
    sealed = next(r for r in rows if r.status == "sealed")
    assert (sealed.run_id, sealed.events, sealed.costs) == ("rG", None, ())
    with pytest.raises(ValueError, match="rule 11"):
        index([evidence / "s4" / "test"])


def test_cli_json(
    corpus: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    runs, evidence = corpus
    assert main(["--root", str(runs), "--root", str(evidence), "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 8 and "costs" not in rows[0]
    assert main(["--root", str(runs)]) == 0
    out = capsys.readouterr().out
    assert "rA" in out and "ok=4" in out and "sealed=1" in out


# Regressions from the S1-SYS-12 review, each from the reviewer's failing input.


def test_a_symlink_loop_ends(tmp_path: Path) -> None:
    (tmp_path / "runs" / "a").mkdir(parents=True)
    (tmp_path / "runs" / "a" / "back").symlink_to(tmp_path / "runs")
    assert index([tmp_path / "runs"]) == []


def test_differing_copies_of_a_run_id_are_invalid(tmp_path: Path) -> None:
    one, two = Log("rX"), Log("rX")
    one.end("done")
    two.end("abandoned")
    write(tmp_path / "runs" / "rX", one, manifest("rX"))
    write(tmp_path / "evidence" / "s1" / "rX", two, manifest("rX"))
    rows = index([tmp_path / "runs", tmp_path / "evidence"])
    assert [(r.status, r.error) for r in rows] == [("invalid", "run_id collision")] * 2


def test_errors_never_carry_input_values(tmp_path: Path) -> None:
    body = manifest("rS").model_dump(mode="json") | {"split": "SECRET-VALUE"}
    path = write(tmp_path / "runs" / "rS", Log("rS"), None)
    (path / "manifest.json").write_text(json.dumps(body), "utf-8")
    [row] = index([tmp_path / "runs"])
    assert (row.status, row.error) == ("invalid", "literal_error@split")


def test_kind_is_relative_to_the_root(tmp_path: Path) -> None:
    runs = tmp_path / "evidence" / "proj" / "runs"
    write(runs / "rA", Log("rA"), manifest("rA"))
    [row] = index([runs])
    assert (row.kind, row.stage) == ("runs", None)
    write(tmp_path / "evidence" / "s1" / "rB", Log("rB"), manifest("rB"))
    [row] = index([tmp_path / "evidence" / "s1"])
    assert (row.kind, row.stage) == ("evidence", "s1")


def test_a_drifted_charge_payload_is_invalid(tmp_path: Path) -> None:
    log = Log("rW")
    log.add(
        "spend.charged", "kernel", "ops", {"call_id": "c", "surprise": 1}, (log.start,)
    )
    write(tmp_path / "runs" / "rW", log, manifest("rW"))
    [row] = index([tmp_path / "runs"])
    assert row.status == "invalid" and "extra_forbidden@surprise" in (row.error or "")


def test_only_train_and_dev_splits_are_open(tmp_path: Path) -> None:
    for split in ("TEST", "", "holdout", "dev"):
        log = Log(f"r-{split}", split=split)
        log.end("done")
        write(tmp_path / f"r-{split}", log, None)
    status = {r.run_id: r.status for r in index([tmp_path])}
    assert status == {
        "r-TEST": "sealed",
        "r-": "sealed",
        "r-holdout": "sealed",
        "r-dev": "incomplete",  # open; no manifest
    }
