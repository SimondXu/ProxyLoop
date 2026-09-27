"""The task_ref grammar ``family@version[:mode][#seed]`` and ``resolve``: the
file's default mode and seed 0 keep the S0 ref ``family@version``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from proxyloop import cli
from proxyloop.env.tasks.instances import instance
from proxyloop.env.tasks.loader import instance_hash, load_task, resolve, task_ref_of
from proxyloop.env.tasks.refs import TaskRef, format_task_ref, parse_task_ref
from proxyloop.env.tasks.schema import Task

S0 = sorted(Path(__file__).resolve().parents[2].glob("evidence/s0/*/manifest.json"))


@pytest.mark.parametrize(
    ("args", "ref"),
    [
        (("cp-direct-discount", 1, None, 0), "cp-direct-discount@1"),
        (("cp-direct-discount", 1, "info_only", 0), "cp-direct-discount@1"),
        (("cp-direct-discount", 1, "full", 7), "cp-direct-discount@1:full#7"),
        (("cp-direct-discount", 1, "full", 0), "cp-direct-discount@1:full"),
        (("cp-hidden-fee-readback", 1, None, 12), "cp-hidden-fee-readback@1#12"),
        (("cp-hidden-fee-readback", 1, "full", 12), "cp-hidden-fee-readback@1#12"),
    ],
)
def test_the_canonical_ref_leaves_out_the_default_mode_and_seed_0(
    args: tuple[str, int, str | None, int], ref: str
) -> None:
    assert task_ref_of(*args) == ref
    assert format_task_ref(parse_task_ref(ref)) == ref
    task = resolve(ref)
    assert task.ref == ref
    family, _, mode, seed = args
    assert task == instance(load_task(family, mode=mode), seed)


def test_the_grammar_parses_each_part() -> None:
    assert parse_task_ref("x-user-mind-change@3:full#12") == TaskRef(
        "x-user-mind-change", 3, "full", 12
    )
    assert parse_task_ref("cp-direct-discount@1") == TaskRef(
        "cp-direct-discount", 1, None, 0
    )


@pytest.mark.parametrize("path", S0, ids=[p.parent.name for p in S0])
def test_each_s0_bundle_resolves_to_its_instance(path: Path) -> None:
    manifest = json.loads(path.read_text("utf-8"))
    assert manifest["task_ref"] == "cp-direct-discount@1"
    assert instance_hash(resolve(manifest["task_ref"])) == manifest["instance_hash"]


def test_the_ref_is_not_part_of_the_instance_hash() -> None:
    task = load_task("cp-direct-discount", mode="full")
    other = task.model_copy(update={"ref": "cp-direct-discount@1:full#3"})
    assert instance_hash(other) == instance_hash(task)
    assert instance_hash(resolve("cp-direct-discount@1:full#3")) != instance_hash(task)


@pytest.mark.parametrize(
    ("ref", "why"),
    [
        ("cp-direct-discount@1:portal", "no 'portal' mode"),
        ("cp-direct-discount@2", "is version 1"),
        ("cp-direct-discount@1#-1", "bad task_ref"),
        ("cp-direct-discount@1#0", "bad task_ref"),
        ("cp-direct-discount@0", "bad task_ref"),
        ("cp-direct-discount", "bad task_ref"),
        ("../secrets@1", "bad task_ref"),
        ("cp-direct-discount@1:info_only", "not canonical: write cp-direct-discount@1"),
        ("cp-hidden-fee-readback@1:full#2", "not canonical"),
    ],
)
def test_a_bad_ref_raises(ref: str, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        resolve(ref)


def test_a_negative_seed_or_an_instance_of_an_instance_raises() -> None:
    with pytest.raises(ValueError, match="< 0"):
        task_ref_of("cp-direct-discount", 1, None, -1)
    task = load_task("cp-hidden-fee-readback")
    with pytest.raises(ValueError, match="< 0"):
        instance(task, -1)
    with pytest.raises(ValueError, match="already an instance"):
        instance(instance(task, 2), 3)


def test_a_task_without_a_ref_is_its_file_and_a_wrong_ref_is_rejected() -> None:
    data = load_task("cp-direct-discount").model_dump(mode="json")
    data.pop("ref")
    assert Task.model_validate(data).ref == "cp-direct-discount@1"
    for wrong in (
        "cp-hidden-fee-readback@1",
        "cp-direct-discount@2",
        "cp-direct-discount@1:full",
    ):
        with pytest.raises(ValidationError):
            Task.model_validate(data | {"ref": wrong})


def test_the_cli_picks_the_mode_and_the_instance() -> None:
    def task(*argv: str) -> Task:
        args = cli.build_parser().parse_args(["session", *argv])
        return cli.task_of(args)

    assert task("--family", "cp-direct-discount").ref == "cp-direct-discount@1"
    seeded = task("--family", "cp-direct-discount", "--mode", "full", "--instance", "7")
    assert seeded == resolve("cp-direct-discount@1:full#7")
    with pytest.raises(SystemExit):
        cli.main(["session", "--family", "cp-direct-discount", "--instance", "-1"])
