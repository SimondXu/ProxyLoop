"""A Slow tool's outcome: the text Slow reads and the ``guard`` effects to emit."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

Effect = tuple[str, Mapping[str, object]]


@dataclass(frozen=True)
class Result:
    ok: bool
    text: str
    effects: tuple[Effect, ...] = ()
    then: Callable[[], None] | None = None
    causes: tuple[str, ...] = ()  # cited by every effect, after the slow.tool


def no(text: str, *effects: Effect) -> Result:
    return Result(False, text, effects)
