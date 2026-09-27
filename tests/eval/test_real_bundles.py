"""Metrics on the committed real S0 bundles equal hand-derived expectations
(S1-MOD-02 acceptance 1).

Each ``expectations/s0/<run_id>.json`` maps a metric to ``expected`` (or
``null`` plus a ``not_computable`` reason class) and a ``derivation`` naming the
events it rests on. The expectations were derived from the bundle files alone,
not from ``proxyloop.eval``. This test only reads ``evidence/s0``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import pytest

from proxyloop.eval.metrics import episode

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "evidence" / "s0"
EXPECTED = Path(__file__).parent / "expectations" / "s0"
RUNS = sorted(p.stem for p in EXPECTED.glob("*.json"))
TOL = 1e-12
# relay_recall.undelivered counts undelivered *values*; the code reports
# undelivered user.sim *events* (compared as undelivered_reveals). The unit is
# not fixed by the #135 definition, so the value count is documentation only.
HAND_ONLY = {"relay_recall": {"undelivered"}}


def reason_class(reason: str) -> str:
    """Coarse class of a not-computable reason: the bundle lacks a field, or
    the episode has nothing to score."""
    if re.search(r"\b[a-z_]+\.[a-z_]+ has no [a-z_]+", reason):
        return "missing_field"
    if reason.startswith("no "):
        return "empty_denominator"
    return f"other: {reason}"


def ratio(num: int, den: int) -> float:
    return num / den


def code_value(record: dict[str, Any], metric: str) -> tuple[Any, str | None]:
    """The code's value for an expectation key, in the expectation's shape,
    and its not-computable reason (None when computed)."""
    values, missing = record["metrics"], record["not_computable"]
    if metric == "outcome":
        return record["outcome"], missing.get("outcome")
    if metric.startswith("latency."):
        _, lane, label = metric.split(".", 2)
        return values["latency"][lane][label], None
    if metric.startswith("cost."):
        c = values["cost"][metric.removeprefix("cost.")]
        calls = {
            basis: c[f"{basis}_calls"]
            for basis in ("priced", "unpriced", "gpu_time")
            if c[f"{basis}_calls"]
        }
        return {
            "usd": c["usd"],
            "reason": c["usd_missing"],
            "calls_by_basis": calls,
        }, None
    name = metric.removesuffix("_cp")
    v = values[name]
    if v is None:
        return None, missing[name]
    if name == "relay_recall":
        return {
            "value": ratio(v["recalled"], v["revealed"]),
            "recalled": v["recalled"],
            "scored": v["revealed"],
            "undelivered_reveals": v["undelivered_reveals"],
        }, None
    if name == "relay_precision_value_only":
        return {"value": ratio(v["correct"], v["facts"]), **v}, None
    if name == "directive_error":
        return {"issues": v["count"], "turns": v["turns"]}, None
    return v, None


def assert_equal(got: Any, want: Any, where: str) -> None:
    if isinstance(want, float):
        assert got == pytest.approx(want, rel=TOL, abs=TOL), where
    elif isinstance(want, dict):
        assert isinstance(got, dict), where
        for key, sub in cast(dict[str, Any], want).items():
            assert key in got, f"{where}.{key} missing from the code's output"
            assert_equal(got[key], sub, f"{where}.{key}")
    else:
        assert got == want and type(got) is type(want), f"{where}: {got!r} != {want!r}"


@pytest.fixture(scope="module")
def records() -> dict[str, dict[str, Any]]:
    return {run: episode(EVIDENCE / run) for run in RUNS}


def test_every_committed_s0_bundle_has_expectations() -> None:
    assert sorted(d.name for d in EVIDENCE.iterdir() if d.is_dir()) == RUNS


@pytest.mark.parametrize("run", RUNS)
def test_metrics_equal_hand_derivation(run: str, records: dict[str, Any]) -> None:
    record = records[run]
    expected: dict[str, dict[str, Any]] = json.loads(
        (EXPECTED / f"{run}.json").read_text()
    )
    for metric, exp in expected.items():
        assert exp["derivation"], f"{run} {metric}: no derivation"
        got, reason = code_value(record, metric)
        want = exp["expected"]
        if isinstance(want, dict):
            skip = HAND_ONLY.get(metric, set())
            want = {
                k: v for k, v in cast(dict[str, Any], want).items() if k not in skip
            }
        where = f"{run} {metric}"
        nc = exp.get("not_computable")
        if isinstance(nc, str):  # the whole metric is not computable
            assert got is None and reason is not None, f"{where}: computed {got!r}"
            assert reason_class(reason) == nc, f"{where}: {reason!r}"
            if "unscored_terms" in exp:  # offer_capture lists what it skipped
                n = re.search(r"\((\d+) unscored\)", reason)
                assert n and int(n.group(1)) == len(exp["unscored_terms"]), where
            continue
        assert reason is None, f"{where}: not computable ({reason})"
        assert_equal(got, want, where)
        for part, cls in cast(
            dict[str, str], nc or {}
        ).items():  # a not-computable part of a row
            lane = metric.split(".")[1]
            assert (
                reason_class(record["not_computable"][f"latency.{lane}.{part}"]) == cls
            )
        if metric.startswith("cost.") and want["usd"] is None:
            assert record["not_computable"][f"{metric}.usd"] == want["reason"], where


@pytest.mark.parametrize("run", RUNS)
def test_no_role_or_lane_outside_the_expectations(
    run: str, records: dict[str, Any]
) -> None:
    expected = json.loads((EXPECTED / f"{run}.json").read_text())
    values = records[run]["metrics"]
    if not any(k.startswith("cost.") for k in expected):
        pytest.skip("outcome-only case (dead endpoint)")
    assert {f"cost.{r}" for r in values["cost"]} == {
        k for k in expected if k.startswith("cost.")
    }
    lanes = {
        f"latency.{lane}.{label}"
        for lane, row in values["latency"].items()
        for label in row
    }
    assert lanes == {k for k in expected if k.startswith("latency.")}
