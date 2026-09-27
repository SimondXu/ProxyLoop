"""The S1-SYS-12 reviewer's attack cases, ported: each failed before its fix."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.contract.samples import GEMINI, QWEN, SONNET
from tests.obs.bundles import Log, manifest, write

from proxyloop.contract.llm import Usage
from proxyloop.obs import spend
from proxyloop.obs.runs import index

ONE = Usage(prompt_tokens=1, completion_tokens=1)


@pytest.fixture
def sealed_priced(tmp_path: Path) -> Path:
    """A readable, valid, priced bundle under evidence/s4/test (no chmod)."""
    h = Log("rH")
    h.call("slow", SONNET, Usage(prompt_tokens=5, completion_tokens=5), "tokens", 777)
    h.end("done")
    write(tmp_path / "evidence" / "s4" / "test" / "rH", h, manifest("rH"))
    return tmp_path


def test_case_bypass(sealed_priced: Path) -> None:
    if not (sealed_priced / "EVIDENCE").exists():
        pytest.skip("case-sensitive file system")
    assert index([sealed_priced / "Evidence"]) == []
    with pytest.raises(ValueError, match="rule 11"):
        index([sealed_priced / "evidence" / "S4" / "TEST"])


def test_file_symlink_bypass(sealed_priced: Path) -> None:
    z = sealed_priced / "runs" / "rZ"
    z.mkdir(parents=True)
    for name in ("manifest.json", "events.jsonl", "prompts.jsonl"):
        (z / name).symlink_to(sealed_priced / "evidence" / "s4" / "test" / "rH" / name)
    rows = [(r.run_id, r.status, r.priced_micro_usd) for r in index([z.parent])]
    assert rows == [("rZ", "sealed", None)]


def test_crashed_run_is_not_complete(tmp_path: Path) -> None:
    ok, crash = Log("rOK"), Log("rCRASH")
    ok.call("slow", SONNET, ONE, "tokens", 100)
    ok.end("done")
    crash.call("slow", SONNET, ONE, "tokens", 50000)
    write(tmp_path / "rOK", ok, manifest("rOK"))
    write(tmp_path / "rCRASH", crash, None)
    report = spend.report(index([tmp_path]), [], 10, {"gpu_usage": "gpu.json"})
    cumulative = report["cumulative"]
    assert (cumulative["complete"], cumulative["micro_usd"]) == (False, 100)
    assert cumulative["unindexed_priced_micro_usd"] == 50000
    assert report["bundles"]["not_counted"] == ["rCRASH"]


def test_unpriced_and_gpu_time_are_not_zero_dollars(tmp_path: Path) -> None:
    u = Log("rU")
    u.call("ear", GEMINI, Usage(prompt_tokens=9, completion_tokens=9), "unpriced")
    u.call("fast_cp", QWEN, ONE, "gpu_time")
    u.end("done")
    write(tmp_path / "rU", u, manifest("rU"))
    report = spend.report(index([tmp_path]), None, 10, {"gpu_usage": None})
    for row in report["live"]["models"]:
        assert (row["usd_per_episode"], row["lower_bound"]) == (None, True)
    for row in report["projection"]["by_model"]:
        assert (row["micro_usd"], row["usd"], row["lower_bound"]) == (None, None, True)
