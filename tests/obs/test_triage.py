"""The triage CLI: the default output carries no content, --json is one
deterministic tagged row, and sealed, test-split and invalid bundles are
reported without a traceback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from tests.obs.bundles import Log, manifest, write
from tests.obs.triage_bundle import P, bundle

from proxyloop.contract.bundle import EVENTS, MANIFEST
from proxyloop.obs import detectors, triage


def test_the_row_names_what_ran(tmp_path: Path) -> None:
    report = triage.triage(bundle(tmp_path))
    row = {k: v for k, v in report.items() if k not in ("detectors", "timeline")}
    assert row == {
        "schema": "pl.triage/1",
        "advisory": detectors.BANNER,
        "run_id": "rT",
        "path": str((tmp_path / "rT").resolve()),
        "status": "ok",
        "started": "2026-09-27T01:00:00+00:00",
        "git_sha": "g",
        "slow_fp": None,  # before S1-SYS-43
        "task_ref": "cp-direct-discount@1",
        "split": "train",
        "mode": "live",  # the manifest's cfg.live
        "models": {},  # session.started names none in this fixture
        "slow_view": "transcript",
        "duration_ms": 3800,
        "relay_window_ms": 10_000,
    }


def test_the_default_timeline_has_codes_only(tmp_path: Path) -> None:
    rows = cast(list[P], triage.triage(bundle(tmp_path))["timeline"])
    by_seq = {r["seq"]: r for r in rows}
    assert by_seq[31] == {
        "seq": 31,
        "t_ms": 3100,
        "type": "slow.tool",
        "name": "act",
        "ok": True,
        "result_len": 11,
    }
    assert by_seq[32]["name"] == "unknown"  # not one of Slow's tools
    assert by_seq[22] == {
        "seq": 22,
        "t_ms": 2200,
        "type": "rep.policy",
        "from": "IDENTIFY",
        "to": "DISCOVER",
        "intent": "ok_hold",
    }
    assert by_seq[33]["reason"] == "guide_slot_not_public"
    assert by_seq[9]["msg_type"] == "USER_UPDATE"
    assert by_seq[9]["n_facts"] == 1
    assert by_seq[3] == {"seq": 3, "t_ms": 300, "type": "user.msg", "text_len": 18}


def test_default_output_has_no_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = bundle(tmp_path)
    for args in ([], ["--json"]):
        assert triage.main([str(run), *args]) == 0
        out = capsys.readouterr().out
        assert "PRIV" not in out
        assert detectors.BANNER in out
    assert triage.main([str(run), "--content", "--json"]) == 0
    content = capsys.readouterr().out
    for marker in ("PRIV-result", "PRIV-ask", "PRIV-f2s-text", "PRIV-msg-late"):
        assert marker in content
    assert "PRIV-error-text" not in content  # error text never, even here


def test_json_is_deterministic_and_tagged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = bundle(tmp_path)
    outs: list[str] = []
    for _ in range(2):
        assert triage.main([str(run), "--json"]) == 0
        outs.append(capsys.readouterr().out)
    assert outs[0] == outs[1]
    assert json.loads(outs[0])["schema"] == "pl.triage/1"


def test_refuses_sealed_and_test_split(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    test_split = bundle(tmp_path / "runs", split="test")
    sealed = bundle(tmp_path / "evidence" / "s4" / "test")
    for run in (test_split, sealed):
        assert triage.main([str(run)]) == 2
        assert "refused" in capsys.readouterr().err


def test_an_invalid_bundle_is_reported_not_raised(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = write(tmp_path / "bad", None, None)
    (run / MANIFEST).write_text("{", "utf-8")
    assert triage.main([str(run)]) == 1
    assert capsys.readouterr().err.startswith("unreadable: ")


def test_odd_event_files_are_unreadable_not_raised(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    partial = write(tmp_path / "a", None, None)  # incomplete: no manifest
    first = Log("a").events[0].model_dump_json()
    (partial / EVENTS).write_text(first, "utf-8")  # no trailing newline
    empty = write(tmp_path / "b", None, manifest("b"))
    (empty / EVENTS).write_text("", "utf-8")
    for run in (partial, empty):
        assert triage.main([str(run)]) == 1
        assert capsys.readouterr().err.startswith("unreadable: ")


def test_an_incomplete_bundle_is_read_unless_its_split_is_sealed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    train = write(tmp_path / "t", Log("t"), None)
    assert triage.main([str(train)]) == 0
    assert "status: incomplete" in capsys.readouterr().out
    held_out = write(tmp_path / "h", Log("h", split="test"), None)
    assert triage.main([str(held_out)]) == 2
    assert capsys.readouterr().err.startswith("refused: ")
