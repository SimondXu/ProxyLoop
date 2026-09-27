"""The spend report against a hand computation over the fixture corpus
(``conftest.py``). Every expected number is a literal, with its arithmetic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.contract.samples import SONNET
from tests.obs.bundles import Log, manifest, write

from proxyloop.contract.llm import Usage
from proxyloop.obs.spend import load_gpu, main

GPU = [
    {"job": "vllm-serve", "app_id": "ap-1", "usd": "1.234567", "source": "modal",
     "period": "2026-09"},
    {"job": "vllm-serve", "app_id": "ap-1", "usd": "0.5", "source": "modal",
     "period": None},
    {"job": "train", "app_id": None, "usd": "2", "source": "modal", "period": None},
]  # fmt: skip


def _report(corpus: tuple[Path, Path], tmp: Path, *extra: str) -> Any:
    runs, evidence = corpus
    out = tmp / "spend.json"
    args = ["--root", str(runs), "--root", str(evidence), "--out", str(out), *extra]
    assert main(args) == 0
    return json.loads(out.read_text("utf-8"))


def _row(section: Any, role: str) -> Any:
    rows = [r for r in section["models"] if r["role"] == role]
    assert len(rows) == 1
    return rows[0]


def test_hand_computation(corpus: tuple[Path, Path], tmp_path: Path) -> None:
    gpu = tmp_path / "gpu.json"
    gpu.write_text(json.dumps(GPU), "utf-8")
    report = _report(corpus, tmp_path, "--gpu-usage", str(gpu))
    assert report["schema"] == "pl.spend/1"
    # ok rows: rA rB rC(runs) rC(evidence) rD = 5; rC counted once -> 4 episodes
    assert report["bundles"] == {
        "ok": 5,
        "incomplete": 1,
        "invalid": 1,
        "sealed": 1,
        "duplicates_collapsed": 1,
        "episodes": 4,
        "not_counted": ["rE", "rF", "rG"],
    }
    live = report["live"]
    assert (live["episodes"], live["run_ids"]) == (3, ["rA", "rB", "rC"])
    # slow: rA 4500 + 1800, rB 3000, rC 600 = 9900; prompt 1000+100+1000+200;
    # completion 100+100+0+0; reasoning only rA's second call reports it (20);
    # rB's second slow call is unpriced and has no usage
    assert _row(live, "slow") == {
        "role": "slow",
        "endpoint": "relay",
        "model_id": "claude-sonnet-5",
        "calls_tokens": 4,
        "calls_gpu_time": 0,
        "calls_unpriced": 1,
        "priced_micro_usd": 9900,
        "prompt_tokens": 2300,
        "completion_tokens": 200,
        "reasoning_tokens": 20,
        "reasoning_unreported": 3,
        "usage_missing": 1,
        "charge_without_call": 0,
        "call_without_charge": 0,
        "episodes": 3,
        "usd_per_episode": None,  # rB's unpriced call: the exact $ is unknown
        # the priced calls only: 9900 / 3 = 3300 micro-USD, a floor
        "priced_lower_bound_micro_usd_per_episode": 3300,
        "priced_lower_bound_usd_per_episode": "0.00330000",
        "lower_bound": True,
    }
    # ear: rA 200/30/25, rB 100/20/-, rC 50/5/5
    ear = _row(live, "ear")
    assert (ear["calls_unpriced"], ear["prompt_tokens"], ear["completion_tokens"]) == (
        3,
        350,
        55,
    )
    assert (ear["reasoning_tokens"], ear["reasoning_unreported"]) == (30, 1)
    assert _row(live, "fast_cp")["calls_gpu_time"] == 1
    assert _row(live, "simuser")["usage_missing"] == 1  # never read as 0 tokens
    mouth = _row(live, "mouth")  # rC's charge without a call, rB's call without one
    assert (mouth["charge_without_call"], mouth["call_without_charge"]) == (1, 1)
    # per-key denominators: the live episodes each key ran in
    episodes = {r["role"]: r["episodes"] for r in live["models"]}
    assert episodes == {"slow": 3, "ear": 3, "fast_cp": 1, "simuser": 1, "mouth": 2}
    # any unpriced, gpu_time, usage-missing or uncharged call: $ unknown, not 0
    assert [r["usd_per_episode"] for r in live["models"]] == [None] * 5
    # every other key has no priced call: a floor of 0 / its episodes = 0
    floors = {
        r["role"]: r["priced_lower_bound_micro_usd_per_episode"] for r in live["models"]
    }
    assert floors == {"slow": 3300, "ear": 0, "fast_cp": 0, "simuser": 0, "mouth": 0}
    assert all(r["lower_bound"] for r in live["models"])
    non_live = report["non_live"]
    assert (non_live["episodes"], non_live["run_ids"]) == (1, ["rD"])
    assert _row(non_live, "slow")["priced_micro_usd"] == 9000
    # GPU: vllm-serve 1.234567 + 0.5 = 1734567; train 2000000
    assert report["gpu"] == {
        "input": str(gpu),
        "jobs": [
            {"job": "train", "entries": 1, "micro_usd": 2000000, "usd": "2.000000"},
            {"job": "vllm-serve", "entries": 2, "micro_usd": 1734567,
             "usd": "1.734567"},
        ],
        "micro_usd": 3734567,
    }  # fmt: skip
    # real_http priced only: 9900 (rD's 9000 is a recorded replay); + GPU 3734567
    assert report["cumulative"] == {
        "llm_priced_micro_usd": 9900,
        "gpu_micro_usd": 3734567,
        "micro_usd": 3744467,
        "usd": "3.744467",
        "calls_unpriced": 6,  # ear 3, simuser 1, mouth 1, slow 1
        "unpriced_prompt_tokens": 350,
        "unpriced_completion_tokens": 55,
        "usage_missing": 2,  # simuser 1, slow 1
        "mismatches": 2,
        "excluded_bundles": {"incomplete": 1, "invalid": 1, "sealed": 1},
        "unindexed_priced_micro_usd": 30000,  # rE's slow call, never in micro_usd
        "complete": False,
    }
    assert report["projection"] is None


def test_projection(corpus: tuple[Path, Path], tmp_path: Path) -> None:
    report = _report(corpus, tmp_path, "--project-episodes", "10")
    assert report["gpu"] == {"input": None, "note": "no Modal usage input"}
    cumulative = report["cumulative"]
    assert (cumulative["gpu_micro_usd"], cumulative["micro_usd"]) == (None, 9900)
    projection = report["projection"]
    assert projection["episodes"] == 10
    rows = {r["role"]: r for r in projection["by_model"]}
    # slow has an unpriced call: no exact $; the priced floor is
    # 10 x 9900 / 3 = 33000 micro-USD (rounded half-even to the micro-USD)
    slow = rows["slow"]
    assert (slow["micro_usd"], slow["usd"], slow["lower_bound"]) == (None, None, True)
    assert slow["priced_lower_bound_micro_usd"] == 33000
    assert slow["priced_lower_bound_usd"] == "0.033000"
    # ear unpriced tokens: 10 x 350 / 3 = 1166.67 -> 1167; 10 x 55 / 3 -> 183
    assert rows["ear"] == {
        "role": "ear",
        "endpoint": "teamrouter",
        "model_id": "gemini-3.8-flash",
        "episodes_basis": 3,
        "micro_usd": None,
        "usd": None,
        "priced_lower_bound_micro_usd": 0,
        "priced_lower_bound_usd": "0.000000",
        "lower_bound": True,
        "calls_unpriced": 3,
        "calls_gpu_time": 0,
        "usage_missing": 0,
        "unpriced_prompt_tokens": 1167,
        "unpriced_completion_tokens": 183,
    }
    # fast_cp ran in 1 live episode, on GPU time: its $ is Modal's, not 0
    assert (rows["fast_cp"]["episodes_basis"], rows["fast_cp"]["usd"]) == (1, None)
    assert projection["gpu"] is None and "Modal" in projection["gpu_note"]


def test_regeneration_is_byte_identical(
    corpus: tuple[Path, Path], tmp_path: Path
) -> None:
    first = json.dumps(_report(corpus, tmp_path))
    assert json.dumps(_report(corpus, tmp_path)) == first


@pytest.mark.parametrize(
    "entry",
    [
        {"usd": "1.2345678"},
        {"usd": "-1"},
        {"usd": 1.5},
        {"usd": "1e3"},
        {"extra": "x"},
    ],
)
def test_gpu_usage_is_strict(tmp_path: Path, entry: dict[str, object]) -> None:
    path = tmp_path / "gpu.json"
    path.write_text(json.dumps([GPU[2] | entry]), "utf-8")
    with pytest.raises(ValueError):
        load_gpu(path)


def test_complete_needs_every_bundle_counted(tmp_path: Path) -> None:
    """S1-SYS-12 review: a crashed run's real charge left ``complete`` true."""
    runs, gpu, out = tmp_path / "runs", tmp_path / "gpu.json", tmp_path / "s.json"
    gpu.write_text(json.dumps(GPU[2:]), "utf-8")
    log = Log("rP")
    log.call(
        "slow", SONNET, Usage(prompt_tokens=100, completion_tokens=0), "tokens", 300
    )
    write(runs / "rP", log, manifest("rP"))
    args = ["--root", str(runs), "--gpu-usage", str(gpu), "--out", str(out)]
    assert main(args) == 0
    clean = json.loads(out.read_text("utf-8"))
    assert clean["cumulative"]["complete"] is True
    [row] = clean["live"]["models"]  # 300 / 1 episode, every call priced: exact
    assert (row["usd_per_episode"], row["lower_bound"]) == ("0.00030000", False)
    crashed = Log("rQ")
    crashed.call(
        "slow", SONNET, Usage(prompt_tokens=1, completion_tokens=0), "tokens", 50000
    )
    write(runs / "rQ", crashed, None)
    assert main(args) == 0
    cumulative = json.loads(out.read_text("utf-8"))["cumulative"]
    assert cumulative["complete"] is False
    assert cumulative["excluded_bundles"] == {
        "incomplete": 1,
        "invalid": 0,
        "sealed": 0,
    }
    assert (cumulative["micro_usd"], cumulative["unindexed_priced_micro_usd"]) == (
        300 + 2000000,
        50000,
    )
