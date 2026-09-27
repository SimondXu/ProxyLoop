"""Load a family from ``tasks/families/<family>.yaml`` (EVAL §2).

A file's top level is its default mode. ``variants: {<mode>: {...}}`` holds
another mode as top-level keys that replace the default's (``cp-direct-discount``
is ``info_only`` by default, the S0 instance, and has a ``full`` variant).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

import yaml

from proxyloop.contract.base import canonical_json, sha256_text
from proxyloop.env.tasks.schema import Task

FAMILIES = Path(__file__).resolve().parents[4] / "tasks" / "families"


def load_task(family: str, root: Path = FAMILIES, mode: str | None = None) -> Task:
    if not re.fullmatch(r"[a-z0-9-]+", family):
        raise ValueError(f"bad family id {family!r}")
    raw: object = yaml.safe_load((root / f"{family}.yaml").read_text("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{family}.yaml is not a mapping")
    data = cast(dict[str, object], raw)
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
    return task


def instance_hash(task: Task) -> str:
    """``None`` fields are left out: a field added later leaves old hashes."""

    return sha256_text(canonical_json(task.model_dump(mode="json", exclude_none=True)))
