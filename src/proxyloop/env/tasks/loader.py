"""Load a family from ``tasks/families/<family>.yaml`` (EVAL §2).

A file's top level is its default mode. ``variants: {<mode>: {...}}`` holds
another mode as top-level keys that replace the default's (``cp-direct-discount``
is ``info_only`` by default, the S0 instance, and has a ``full`` variant).
``resolve`` loads the instance a task_ref names (``refs.py``); every loaded task
carries its canonical ref.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

import yaml

from proxyloop.contract.base import canonical_json, sha256_text
from proxyloop.env.tasks.instances import instance
from proxyloop.env.tasks.refs import TaskRef, format_task_ref, parse_task_ref
from proxyloop.env.tasks.schema import Task

FAMILIES = Path(__file__).resolve().parents[4] / "tasks" / "families"


def load_task(family: str, root: Path = FAMILIES, mode: str | None = None) -> Task:
    if not re.fullmatch(r"[a-z0-9-]+", family):
        raise ValueError(f"bad family id {family!r}")
    raw: object = yaml.safe_load((root / f"{family}.yaml").read_text("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{family}.yaml is not a mapping")
    data = cast(dict[str, object], raw)
    default = data.get("mode")
    variants = cast(dict[str, dict[str, object]], data.pop("variants", None) or {})
    if mode is not None and mode != data.get("mode"):
        if mode not in variants:
            raise ValueError(f"{family} has no {mode!r} mode")
        data |= variants[mode]
    task = Task.model_validate(data)
    if task.family != family:
        raise ValueError(f"{family}.yaml declares family {task.family!r}")
    if mode is not None and task.mode != mode:
        raise ValueError(f"the {mode!r} variant of {family} declares {task.mode!r}")
    shown = None if task.mode == default else task.mode
    ref = format_task_ref(TaskRef(family, task.version, shown, 0))
    return task.model_copy(update={"ref": ref})


def task_ref_of(
    family: str, version: int, mode: str | None, seed: int, root: Path = FAMILIES
) -> str:
    """The canonical ref: the family's default mode and seed 0 are left out."""

    shown = None if mode in (None, load_task(family, root).mode) else mode
    return format_task_ref(TaskRef(family, version, shown, seed))


def resolve(task_ref: str, root: Path = FAMILIES) -> Task:
    """The instance ``task_ref`` names; its version must be the file's."""

    ref = parse_task_ref(task_ref)
    task = load_task(ref.family, root, ref.mode)
    if task.version != ref.version:
        raise ValueError(f"{task_ref}: {ref.family}.yaml is version {task.version}")
    if (task := instance(task, ref.seed)).ref != task_ref:
        raise ValueError(f"{task_ref} is not canonical: write {task.ref}")
    return task


def instance_hash(task: Task) -> str:
    """``None`` fields and ``ref`` are left out: a field added later leaves old
    hashes."""

    data = task.model_dump(mode="json", exclude_none=True, exclude={"ref"})
    return sha256_text(canonical_json(data))
