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


def _file() -> dict[str, Any]:
    return yaml.safe_load((FAMILIES / f"{FAMILY}.yaml").read_text("utf-8"))


def _raw() -> dict[str, Any]:  # the default (S0) mode
    raw = _file()
    raw.pop("variants")
    return raw


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


BAD_MONEY = ["68.0.0", "1e3", "-5", "68.001", "68.5", "NaN", "Infinity", "",
             " 68", "68 ", "68.00\n", "\u0666\u0668", "\uff16\uff18", "1,250",
             "$68"]  # fmt: skip


@pytest.mark.parametrize("value", BAD_MONEY)
@pytest.mark.parametrize(
    ("part", "field"),
    [("terms", "monthly_price"), ("hidden", "fee:activation"), ("terms", "credit:x")],
)
def test_a_money_term_is_a_plain_decimal(part: str, field: str, value: str) -> None:
    data = copy.deepcopy(_raw())  # #148 review: instances._usd never meets it
    data["counterparty"]["ladder"][0]["hidden"].pop("fee:activation")
    data["counterparty"]["ladder"][0][part][field] = "68.00"
    Task.model_validate(data)
    data["counterparty"]["ladder"][0][part][field] = value
    with pytest.raises(ValidationError, match="money"):
        Task.model_validate(data)


S0_HASH = "6a059e5760a1d2db94c46ccf464336ef2d38013717b6be1bf191e12f6151f2d9"


def test_the_s0_instance_keeps_the_hash_of_its_evidence_bundles() -> None:
    assert instance_hash(load_task(FAMILY)) == S0_HASH  # evidence/s0 manifests
    assert instance_hash(load_task(FAMILY, mode="info_only")) == S0_HASH


def test_the_full_variant_and_the_slice_families_load() -> None:
    full = load_task(FAMILY, mode="full")
    assert (full.id, full.mode, full.gold.check) == (
        "cp-direct-discount-full",
        "full",
        "ledger",
    )
    assert full.principal is not None and full.stop is None
    assert instance_hash(full) != S0_HASH
    for family in ("cp-hidden-fee-readback", "x-out-of-envelope-approval"):
        task = load_task(family)
        assert (task.mode, task.gold.check, task.stop) == ("full", "ledger", None)
    stop = load_task("x-user-mind-change")
    assert stop.stop is not None and stop.stop.trigger == "after_card"
    assert stop.gold.check == "no_commit_after_stop"
    names = sorted(p.stem for p in FAMILIES.glob("*.yaml"))
    assert names == sorted(
        {
            FAMILY,
            "cp-hidden-fee-readback",
            *("x-out-of-envelope-approval", "x-user-mind-change"),
        }
    )


def test_a_variant_must_exist_and_declare_its_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no 'portal' mode"):
        load_task(FAMILY, mode="portal")
    raw = _file()
    raw["variants"]["full"]["mode"] = "info_only"
    raw["variants"]["full"].pop("principal")
    raw["variants"]["other"] = raw["variants"].pop("full")
    (tmp_path / f"{FAMILY}.yaml").write_text(yaml.safe_dump(raw), "utf-8")
    with pytest.raises(ValueError, match="declares 'info_only'"):
        load_task(FAMILY, root=tmp_path, mode="other")
