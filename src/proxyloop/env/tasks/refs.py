"""The task_ref grammar: ``family@version[:mode][#seed]``.

A ref names one instance of one family mode. The canonical ref leaves out the
family's default mode and seed 0, so the file itself is still ``family@version``
(every earlier bundle's ref). ``loader.task_ref_of`` and ``loader.resolve`` add
the family file's default mode; this module is the pure grammar.
"""

from __future__ import annotations

import re
from typing import NamedTuple

REF = re.compile(r"([a-z0-9-]+)@([1-9]\d*)(?::([a-z_]+))?(?:#([1-9]\d*))?")


class TaskRef(NamedTuple):
    family: str
    version: int
    mode: str | None  # None: the family's default mode
    seed: int


def parse_task_ref(ref: str) -> TaskRef:
    """Only the canonical spelling parses: ``#0`` is left out, never written."""

    if (m := REF.fullmatch(ref)) is None:
        raise ValueError(f"bad task_ref {ref!r}: want family@version[:mode][#seed]")
    return TaskRef(m[1], int(m[2]), m[3], int(m[4] or 0))


def format_task_ref(ref: TaskRef) -> str:
    if ref.seed < 0:
        raise ValueError(f"instance seed {ref.seed} < 0")
    mode = f":{ref.mode}" if ref.mode else ""
    return f"{ref.family}@{ref.version}{mode}" + (f"#{ref.seed}" if ref.seed else "")
