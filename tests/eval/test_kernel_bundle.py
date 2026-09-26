"""Metrics on bundles the kernel wrote (``run_session`` on test fakes): the event
shapes the metrics read are the ones the kernel emits."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.sessions import act, ear, only_bundle, reply, run

from proxyloop.contract.llm import LLMUnavailable
from proxyloop.eval.metrics import episode, metrics

NAME = "Dana Reyes"
SCRIPTS = {
    "simuser": [
        reply(f"Get me a lower price. I am {NAME}.", **{"account.holder_name": NAME})
    ],
    "fast_user": [f"Sure, calling now.\n@slow: fact holder={NAME}"],
    "ear": [ear("other"), ear("ask_discount")],
    "mouth": ["Okay."],
    "fast_cp": ["Could you lower my price to 50?", "Thanks.\n@slow: fact asked=lower"],
    "slow": [act("Calling.", {"tool": "wait", "seconds": 5})],
}
FINISH = act("Done.", {"tool": "finish", "outcome": "info_only", "summary": "ok"})


def test_metrics_read_a_kernel_bundle(tmp_path: Path) -> None:
    run(tmp_path, SCRIPTS, until={"slow": ("] cp_update", FINISH)})
    out = metrics(only_bundle(tmp_path))
    assert out["errored"] is False and out["ended"] == "info_only"
    assert out["metrics"]["relay_recall"]["recalled"] >= 1
    assert out["fast_turns"]["user"] >= 1 and out["fast_turns"]["cp"] >= 1
    cp = out["metrics"]["unsupported_numbers"]
    assert cp["turns"] == out["fast_turns"]["cp"] and cp["count"] >= 1  # 50
    user = out["metrics"]["latency"]["user"]["in-process (test_fake)"]
    heard: list[int] = user["time_to_heard_ms"]
    assert user["ttft_ms"] and heard and min(heard) >= 0
    assert out["metrics"]["cost"]["slow"]["usd"] is None  # a fake is unpriced


def test_a_dead_endpoint_bundle_is_an_errored_episode(tmp_path: Path) -> None:
    with pytest.raises(LLMUnavailable):
        run(tmp_path, SCRIPTS, dead=["fast_cp"])
    (run_dir,) = [d for d in tmp_path.iterdir() if d.is_dir()]
    out = episode(run_dir)
    assert out["errored"] is True and out["ended"] == "llm_unavailable"
    assert out["metrics"]["success"] == 0 and out["metrics"]["safe_success"] == 0
