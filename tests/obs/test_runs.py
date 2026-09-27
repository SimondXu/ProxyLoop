"""The run index over the fixture corpus (``conftest.py``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    assert rows["runs/rE"].events == 3
    assert "JSON" in (rows["runs/rF"].error or "")


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
