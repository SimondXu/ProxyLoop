"""Task schema and loader (EVAL §2) against the family YAML."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from proxyloop.env.tasks.loader import FAMILIES, instance_hash, load_task
from proxyloop.env.tasks.schema import Task

FAMILY = "cp-direct-discount"
Mutate = Callable[[dict[str, Any]], object]


def _raw() -> dict[str, Any]:
    return yaml.safe_load((FAMILIES / f"{FAMILY}.yaml").read_text("utf-8"))


def test_the_family_loads_as_information_only() -> None:
    task = load_task(FAMILY)
    assert (task.family, task.mode, task.stratum) == (FAMILY, "info_only", "cp_success")
    assert set(task.channels) == {"user", "cp"}
    cp = task.counterparty
    assert [o.offer_ref for o in cp.ladder] == ["loyal-1", "loyal-2"]
    assert all(o.hidden for o in cp.ladder)  # a term only a read-back reveals
    assert set(cp.identity) <= task.profile.facts.keys()
    assert task.user.reply_delay_s.range == (2, 20)


def test_instance_hash_is_stable_and_content_bound() -> None:
    task = load_task(FAMILY)
    assert instance_hash(task) == instance_hash(load_task(FAMILY))
    other = task.model_copy(update={"version": 2})
    assert instance_hash(other) != instance_hash(task)


def test_the_loader_rejects_bad_ids_and_a_mismatched_family(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="bad family id"):
        load_task("../secrets")
    (tmp_path / "other.yaml").write_text(yaml.safe_dump(_raw()), "utf-8")
    with pytest.raises(ValueError, match="declares family"):
        load_task("other", root=tmp_path)


def _mutations() -> list[tuple[str, Mutate]]:
    def offer(d: dict[str, Any]) -> dict[str, Any]:
        return d["counterparty"]["ladder"][0]

    return [
        ("said and hidden", lambda d: offer(d)["hidden"].update(monthly_price="1")),
        ("no term_months", lambda d: offer(d)["terms"].pop("term_months")),
        ("bad term field", lambda d: offer(d)["terms"].update(price="1")),
        ("unknown identity", lambda d: d["counterparty"].update(identity=["pin"])),
        ("unknown shareable", lambda d: d["disclosure"].update(shareable=["x"])),
        ("reversed delay", lambda d: d["user"].update(reply_delay_s={"range": [9, 2]})),
        ("dup offer", lambda d: d["counterparty"]["ladder"].append(offer(d))),
        ("bad fact key", lambda d: d["profile"]["facts"].update({"Bad Key": "1"})),
        ("hold too short", lambda d: d["counterparty"]["patience"].update(hold_s=5)),
        ("unknown field", lambda d: d.update(patience=3)),
    ]


@pytest.mark.parametrize(
    ("name", "mutate"), _mutations(), ids=[n for n, _ in _mutations()]
)
def test_the_schema_rejects(name: str, mutate: Mutate) -> None:
    data = copy.deepcopy(_raw())
    Task.model_validate(data)
    mutate(data)
    with pytest.raises(ValidationError):
        Task.model_validate(data)
