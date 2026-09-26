from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from proxyloop.env.splits import stratified_split

V0 = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "v0" / "split.json").read_text(
        "utf-8"
    )
)


def _strata(run: dict[str, Any]) -> dict[str, str]:
    return {row["family_id"]: row["stratum"] for row in run["family_assignments"]}


@pytest.mark.parametrize("run", V0["runs"], ids=[r["salt"] for r in V0["runs"]])
def test_split_reproduces_v0_family_assignment(run: dict[str, Any]) -> None:
    expected = {row["family_id"]: row["split"] for row in run["family_assignments"]}
    assert stratified_split(_strata(run), salt=run["salt"]) == expected


def test_fixture_pins_the_v0_salt_and_salt_changes_the_draw() -> None:
    assert V0["runs"][0]["salt"] == "negotiation-split-v2"
    draws = [stratified_split(_strata(run), salt=run["salt"]) for run in V0["runs"]]
    assert any(draw != draws[0] for draw in draws[1:])
