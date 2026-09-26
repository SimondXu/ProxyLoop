"""Load a family from ``tasks/families/<family>.yaml`` (EVAL §2)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from proxyloop.contract.base import canonical_json, sha256_text
from proxyloop.env.tasks.schema import Task

FAMILIES = Path(__file__).resolve().parents[4] / "tasks" / "families"


def load_task(family: str, root: Path = FAMILIES) -> Task:
    if not re.fullmatch(r"[a-z0-9-]+", family):
        raise ValueError(f"bad family id {family!r}")
    data: object = yaml.safe_load((root / f"{family}.yaml").read_text("utf-8"))
    task = Task.model_validate(data)
    if task.family != family:
        raise ValueError(f"{family}.yaml declares family {task.family!r}")
    return task


def instance_hash(task: Task) -> str:
    return sha256_text(canonical_json(task.model_dump(mode="json")))
